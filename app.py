from datetime import datetime
from pathlib import Path
from typing import Generator, List

import pandas as pd
from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import FileResponse, RedirectResponse

from database.db import SessionLocal, init_db
from database.models import Report, ReceivableRow
from output.export_excel import export_all
from output.export_pdf import export_pdf
from parser.pdf_reader import read_pdf
from parser.pipeline import run_full_pipeline
from utils.logger import get_logger
from utils.static_dashboard import dashboard_html


logger = get_logger(__name__)

init_db()

app = FastAPI(title="PDF Receivable Parser")


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _extract_header_and_range(raw_text: str) -> tuple[str | None, str | None]:
    """
    Extract the company header line and the date range like '1-Apr-25 to 18-Feb-26'.
    """
    header = None
    date_range = None

    for line in raw_text.splitlines():
        if "PURPLE PATCH FARMS INTERNATIONAL PVT.LTD -FARM" in line:
            header = line.strip()
        if "to" in line and any(month in line for month in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]):
            date_range = line.strip()
        if header and date_range:
            break

    return header, date_range


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html = """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Receivables Dashboard – Upload</title>
        <script src="https://cdn.tailwindcss.com"></script>
      </head>
      <body class="bg-slate-50">
        <div class="min-h-screen flex items-center justify-center px-4">
          <div class="max-w-xl w-full bg-white shadow-sm border border-slate-200 rounded-xl p-8">
            <h1 class="text-2xl font-semibold text-slate-900">Upload receivable report</h1>
            <p class="mt-2 text-sm text-slate-600">
              Upload a financial outstanding report PDF (including scanned PDFs). We will parse all customer receivable rows,
              detect regions like <span class="font-medium">Calicut Customers</span>,
              and open an interactive dashboard where you can review and adjust buckets.
            </p>
            <form class="mt-6 space-y-4" action="/upload" method="post" enctype="multipart/form-data">
              <div>
                <label class="block text-sm font-medium text-slate-700 mb-1">Choose PDF file</label>
                <input
                  type="file"
                  name="file"
                  accept="application/pdf"
                  required
                  class="block w-full text-sm text-slate-900
                         file:mr-4 file:py-2 file:px-4
                         file:rounded-md file:border-0
                         file:text-sm file:font-semibold
                         file:bg-slate-900 file:text-white
                         hover:file:bg-slate-800"
                />
              </div>
              <div class="flex items-center justify-between text-xs text-slate-500">
                <span>Supports multi-page PDFs and scanned documents (via OCR fallback).</span>
                <span>Typical 10-page report &lt; 5s on CPU.</span>
              </div>
              <button
                type="submit"
                class="inline-flex items-center justify-center px-4 py-2 rounded-md bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 w-full mt-2"
              >
                Upload &amp; open dashboard
              </button>
            </form>
          </div>
        </div>
      </body>
    </html>
    """
    return html


@app.get("/dashboard/{report_id}", response_class=HTMLResponse)
async def dashboard(report_id: int) -> str:
    return dashboard_html()


@app.get("/reports/{report_id}")
async def get_report(report_id: int, db=Depends(get_db)):
    rpt = db.query(Report).filter(Report.id == report_id).first()
    if not rpt:
        return JSONResponse({"error": "Report not found"}, status_code=404)
    return {
        "id": rpt.id,
        "filename": rpt.filename,
        "header": rpt.header,
        "date_range": rpt.date_range,
        "created_at": rpt.created_at.isoformat(),
    }


@app.get("/reports/{report_id}/rows")
async def get_rows(report_id: int, db=Depends(get_db)):
    rows = (
        db.query(ReceivableRow)
        .filter(ReceivableRow.report_id == report_id)
        .order_by(ReceivableRow.region.asc(), ReceivableRow.customer_name.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "report_id": r.report_id,
            "region": r.region,
            "customer_name": r.customer_name,
            "payment_status": r.payment_status,
            "safe": r.safe,
            "warning": r.warning,
            "danger": r.danger,
            "doubtful": r.doubtful,
            "total": r.total,
        }
        for r in rows
    ]


@app.post("/rows/{row_id}/move")
async def move_amount(row_id: int, payload: dict, db=Depends(get_db)):
    row = db.query(ReceivableRow).filter(ReceivableRow.id == row_id).first()
    if not row:
        return JSONResponse({"error": "Row not found"}, status_code=404)

    from_bucket = payload.get("from_bucket")
    to_bucket = payload.get("to_bucket")
    amount = float(payload.get("amount", 0) or 0)
    if from_bucket not in {"safe", "warning", "danger", "doubtful"}:
        return JSONResponse({"error": "Invalid from_bucket"}, status_code=400)
    if to_bucket not in {"safe", "warning", "danger", "doubtful"}:
        return JSONResponse({"error": "Invalid to_bucket"}, status_code=400)
    if amount <= 0:
        return JSONResponse({"error": "Amount must be > 0"}, status_code=400)

    current_from = float(getattr(row, from_bucket) or 0.0)
    amt = min(amount, current_from)
    setattr(row, from_bucket, current_from - amt)
    setattr(row, to_bucket, float(getattr(row, to_bucket) or 0.0) + amt)
    row.total = float(row.safe or 0) + float(row.warning or 0) + float(row.danger or 0) + float(row.doubtful or 0)
    db.commit()
    return {"ok": True, "row_id": row_id}


@app.patch("/rows/{row_id}/payment-status")
async def set_payment_status(row_id: int, payload: dict, db=Depends(get_db)):
    row = db.query(ReceivableRow).filter(ReceivableRow.id == row_id).first()
    if not row:
        return JSONResponse({"error": "Row not found"}, status_code=404)
    status = payload.get("payment_status")
    if status not in {"Paid", "Unpaid", "Partially Paid"}:
        return JSONResponse({"error": "Invalid payment_status"}, status_code=400)
    row.payment_status = status
    db.commit()
    return {"ok": True}


@app.post("/rows/{row_id}/set")
async def set_row(row_id: int, payload: dict, db=Depends(get_db)):
    row = db.query(ReceivableRow).filter(ReceivableRow.id == row_id).first()
    if not row:
        return JSONResponse({"error": "Row not found"}, status_code=404)
    for key in ["safe", "warning", "danger", "doubtful"]:
        if key in payload:
            setattr(row, key, float(payload[key] or 0.0))
    if "payment_status" in payload:
        row.payment_status = payload["payment_status"] or "Unpaid"
    row.total = float(row.safe or 0) + float(row.warning or 0) + float(row.danger or 0) + float(row.doubtful or 0)
    db.commit()
    return {"ok": True}


@app.post("/reports/{report_id}/reset")
async def reset_report(report_id: int, db=Depends(get_db)):
    rows = db.query(ReceivableRow).filter(ReceivableRow.report_id == report_id).all()
    if not rows:
        return JSONResponse({"error": "Report not found or has no rows"}, status_code=404)
    for r in rows:
        r.safe = r.original_safe
        r.warning = r.original_warning
        r.danger = r.original_danger
        r.doubtful = r.original_doubtful
        r.total = r.original_total
        r.payment_status = "Unpaid"
    db.commit()
    return {"ok": True}


@app.get("/reports/{report_id}/export/{fmt}")
async def export_report(report_id: int, fmt: str, db=Depends(get_db)):
    rpt = db.query(Report).filter(Report.id == report_id).first()
    if not rpt:
        return JSONResponse({"error": "Report not found"}, status_code=404)

    rows = (
        db.query(ReceivableRow)
        .filter(ReceivableRow.report_id == report_id)
        .order_by(ReceivableRow.region.asc(), ReceivableRow.customer_name.asc())
        .all()
    )
    df = pd.DataFrame(
        [
            {
                "region": r.region,
                "customer_name": r.customer_name,
                "payment_status": r.payment_status,
                "safe": r.safe,
                "warning": r.warning,
                "danger": r.danger,
                "doubtful": r.doubtful,
                "total": r.total,
            }
            for r in rows
        ]
    )

    export_dir = Path("exports") / f"report_{report_id}"
    export_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        p = export_dir / "receivables.csv"
        df.to_csv(p, index=False)
        return FileResponse(p)
    if fmt == "json":
        p = export_dir / "receivables.json"
        df.to_json(p, orient="records", indent=2)
        return FileResponse(p)
    if fmt == "xlsx":
        p = export_dir / "receivables.xlsx"
        df.to_excel(p, index=False)
        return FileResponse(p)
    if fmt == "pdf":
        p = export_dir / "receivables.pdf"
        export_pdf(df, p, title=rpt.header or "Receivables", subtitle=rpt.date_range)
        return FileResponse(p, media_type="application/pdf", filename=p.name)

    return JSONResponse({"error": "Unsupported format"}, status_code=400)


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    if file.content_type != "application/pdf":
        return HTMLResponse(
            content="<h3>Only PDF files are supported.</h3>", status_code=400
        )

    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    pdf_path = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"

    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    logger.info("Uploaded PDF saved to %s", pdf_path)

    # Derive heading and date range from the raw text of the uploaded PDF
    parsed_for_header = read_pdf(str(pdf_path))
    raw_text = parsed_for_header["raw_text"]
    header_line, date_range_line = _extract_header_and_range(raw_text)

    df, summary = run_full_pipeline(str(pdf_path), export_dir="exports")

    report = Report(
        filename=file.filename,
        header=header_line or "PURPLE PATCH FARMS INTERNATIONAL PVT.LTD -FARM",
        date_range=date_range_line,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    db_rows: List[ReceivableRow] = []
    for _, r in df.iterrows():
        safe = float(r.get("safe", 0.0) or 0.0)
        warning = float(r.get("warning", 0.0) or 0.0)
        danger = float(r.get("danger", 0.0) or 0.0)
        doubtful = float(r.get("doubtful", 0.0) or 0.0)
        total = float(r.get("total", safe + warning + danger + doubtful) or 0.0)
        db_rows.append(
            ReceivableRow(
                report_id=report.id,
                region=str(r.get("region") or "Unknown"),
                customer_name=str(r.get("customer_name") or "").strip(),
                payment_status="Unpaid",
                safe=safe,
                warning=warning,
                danger=danger,
                doubtful=doubtful,
                total=total,
                original_safe=safe,
                original_warning=warning,
                original_danger=danger,
                original_doubtful=doubtful,
                original_total=total,
            )
        )
    db.add_all(db_rows)
    db.commit()

    return RedirectResponse(url=f"/dashboard/{report.id}", status_code=303)


@app.post("/upload-json")
async def upload_json(
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    if file.content_type != "application/pdf":
        return JSONResponse(
            content={"error": "Only PDF files are supported."}, status_code=400
        )

    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    pdf_path = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}"

    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Extract heading and date range for API clients as well
    parsed_for_header = read_pdf(str(pdf_path))
    raw_text = parsed_for_header["raw_text"]
    header_line, date_range_line = _extract_header_and_range(raw_text)

    df, summary = run_full_pipeline(str(pdf_path), export_dir=None)

    report = Report(
        filename=file.filename,
        header=header_line or "PURPLE PATCH FARMS INTERNATIONAL PVT.LTD -FARM",
        date_range=date_range_line,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    db_rows: List[ReceivableRow] = []
    for _, r in df.iterrows():
        safe = float(r.get("safe", 0.0) or 0.0)
        warning = float(r.get("warning", 0.0) or 0.0)
        danger = float(r.get("danger", 0.0) or 0.0)
        doubtful = float(r.get("doubtful", 0.0) or 0.0)
        total = float(r.get("total", safe + warning + danger + doubtful) or 0.0)
        db_rows.append(
            ReceivableRow(
                report_id=report.id,
                region=str(r.get("region") or "Unknown"),
                customer_name=str(r.get("customer_name") or "").strip(),
                payment_status="Unpaid",
                safe=safe,
                warning=warning,
                danger=danger,
                doubtful=doubtful,
                total=total,
                original_safe=safe,
                original_warning=warning,
                original_danger=danger,
                original_doubtful=doubtful,
                original_total=total,
            )
        )
    db.add_all(db_rows)
    db.commit()

    return {
        "report_id": report.id,
        "rows_extracted": summary["rows_extracted"],
        "regions_detected": summary["regions_detected"],
        "total_value": summary["total_value"],
        "header": report.header,
        "date_range": report.date_range,
    }

