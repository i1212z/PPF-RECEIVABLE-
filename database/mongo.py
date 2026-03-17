from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import MongoClient
from pymongo import UpdateOne


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MongoStore:
    def __init__(self) -> None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")

        db_name = os.getenv("MONGODB_DB", "ppf_receivable")
        self._client = MongoClient(uri)
        self._db = self._client[db_name]
        self.reports = self._db["reports"]
        self.rows = self._db["rows"]

        # Helpful indexes (safe to call repeatedly)
        self.reports.create_index("created_at")
        self.rows.create_index("report_id")
        self.rows.create_index([("report_id", 1), ("region", 1), ("customer_name", 1)])

    @staticmethod
    def _oid(id_str: str) -> ObjectId:
        try:
            return ObjectId(id_str)
        except Exception as exc:
            raise ValueError("Invalid id") from exc

    def create_report(self, *, filename: str, header: Optional[str], date_range: Optional[str]) -> str:
        doc = {
            "filename": filename,
            "header": header,
            "date_range": date_range,
            "created_at": _utcnow(),
        }
        res = self.reports.insert_one(doc)
        return str(res.inserted_id)

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        doc = self.reports.find_one({"_id": self._oid(report_id)})
        if not doc:
            return None
        return {
            "id": str(doc["_id"]),
            "filename": doc.get("filename"),
            "header": doc.get("header"),
            "date_range": doc.get("date_range"),
            "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        }

    def insert_rows(self, report_id: str, rows: List[Dict[str, Any]]) -> None:
        rid = self._oid(report_id)
        docs: List[Dict[str, Any]] = []
        for r in rows:
            safe = float(r.get("safe") or 0.0)
            warning = float(r.get("warning") or 0.0)
            danger = float(r.get("danger") or 0.0)
            doubtful = float(r.get("doubtful") or 0.0)
            total = float(r.get("total") or (safe + warning + danger + doubtful))

            docs.append(
                {
                    "report_id": rid,
                    "region": str(r.get("region") or "Unknown"),
                    "customer_name": str(r.get("customer_name") or "").strip(),
                    "payment_status": r.get("payment_status") or "Unpaid",
                    "safe": safe,
                    "warning": warning,
                    "danger": danger,
                    "doubtful": doubtful,
                    "total": total,
                    "original_safe": safe,
                    "original_warning": warning,
                    "original_danger": danger,
                    "original_doubtful": doubtful,
                    "original_total": total,
                    "created_at": _utcnow(),
                }
            )
        if docs:
            self.rows.insert_many(docs)

    def list_rows(self, report_id: str) -> List[Dict[str, Any]]:
        rid = self._oid(report_id)
        cur = self.rows.find({"report_id": rid}).sort([("region", 1), ("customer_name", 1)])
        out: List[Dict[str, Any]] = []
        for d in cur:
            out.append(
                {
                    "id": str(d["_id"]),
                    "report_id": str(d["report_id"]),
                    "region": d.get("region"),
                    "customer_name": d.get("customer_name"),
                    "payment_status": d.get("payment_status"),
                    "safe": float(d.get("safe") or 0.0),
                    "warning": float(d.get("warning") or 0.0),
                    "danger": float(d.get("danger") or 0.0),
                    "doubtful": float(d.get("doubtful") or 0.0),
                    "total": float(d.get("total") or 0.0),
                }
            )
        return out

    def move_amount(self, row_id: str, *, from_bucket: str, to_bucket: str, amount: float) -> bool:
        if from_bucket not in {"safe", "warning", "danger", "doubtful"}:
            raise ValueError("Invalid from_bucket")
        if to_bucket not in {"safe", "warning", "danger", "doubtful"}:
            raise ValueError("Invalid to_bucket")

        oid = self._oid(row_id)
        row = self.rows.find_one({"_id": oid})
        if not row:
            return False

        current_from = float(row.get(from_bucket) or 0.0)
        amt = max(0.0, min(float(amount or 0.0), current_from))
        if amt <= 0:
            return True

        updated = {
            from_bucket: current_from - amt,
            to_bucket: float(row.get(to_bucket) or 0.0) + amt,
        }
        total = float(updated.get("safe", row.get("safe") or 0.0)) + float(updated.get("warning", row.get("warning") or 0.0)) + float(
            updated.get("danger", row.get("danger") or 0.0)
        ) + float(updated.get("doubtful", row.get("doubtful") or 0.0))
        updated["total"] = total

        self.rows.update_one({"_id": oid}, {"$set": updated})
        return True

    def set_payment_status(self, row_id: str, *, status: str) -> bool:
        oid = self._oid(row_id)
        res = self.rows.update_one({"_id": oid}, {"$set": {"payment_status": status}})
        return res.matched_count > 0

    def set_row(self, row_id: str, payload: Dict[str, Any]) -> bool:
        oid = self._oid(row_id)
        row = self.rows.find_one({"_id": oid})
        if not row:
            return False

        updated: Dict[str, Any] = {}
        for key in ["safe", "warning", "danger", "doubtful"]:
            if key in payload:
                updated[key] = float(payload.get(key) or 0.0)
        if "payment_status" in payload:
            updated["payment_status"] = payload.get("payment_status") or "Unpaid"

        safe = float(updated.get("safe", row.get("safe") or 0.0))
        warning = float(updated.get("warning", row.get("warning") or 0.0))
        danger = float(updated.get("danger", row.get("danger") or 0.0))
        doubtful = float(updated.get("doubtful", row.get("doubtful") or 0.0))
        updated["total"] = safe + warning + danger + doubtful

        self.rows.update_one({"_id": oid}, {"$set": updated})
        return True

    def reset_report(self, report_id: str) -> bool:
        rid = self._oid(report_id)
        cur = self.rows.find({"report_id": rid}, {"original_safe": 1, "original_warning": 1, "original_danger": 1, "original_doubtful": 1, "original_total": 1})
        ops: List[UpdateOne] = []
        for d in cur:
            ops.append(
                UpdateOne(
                    {"_id": d["_id"]},
                    {
                        "$set": {
                            "safe": float(d.get("original_safe") or 0.0),
                            "warning": float(d.get("original_warning") or 0.0),
                            "danger": float(d.get("original_danger") or 0.0),
                            "doubtful": float(d.get("original_doubtful") or 0.0),
                            "total": float(d.get("original_total") or 0.0),
                            "payment_status": "Unpaid",
                        }
                    },
                )
            )

        if not ops:
            return False
        self.rows.bulk_write(ops, ordered=False)
        return True

