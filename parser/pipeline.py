from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from output.export_excel import export_all
from parser.pdf_reader import read_pdf
from parser.region_detector import detect_region
from parser.row_parser import ReceivableRow, parse_receivable_lines, rows_to_dataframe
from parser.table_extractor import extract_tables
from utils.logger import get_logger
from utils.validators import almost_equal_sum, is_numeric_token, parse_numeric
from vision.qwen_validator import validate_with_qwen


logger = get_logger(__name__)

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _rows_from_camelot_tables(
    dfs: List[pd.DataFrame],
    raw_text: str,
) -> List[ReceivableRow]:
    """
    Convert Camelot dataframes into ReceivableRow objects using region headers
    detected from the surrounding raw text.
    """
    regions_by_order: List[Tuple[str, int]] = []
    for i, line in enumerate(raw_text.splitlines()):
        reg = detect_region(line)
        if reg:
            regions_by_order.append((reg, i))

    def region_for_line_index(idx: int) -> str | None:
        current = None
        for reg, pos in regions_by_order:
            if idx >= pos:
                current = reg
            else:
                break
        return current

    rows: List[ReceivableRow] = []
    line_index = 0

    for df in dfs:
        for _, row in df.iterrows():
            # Heuristic: each row with >= 5 numeric-looking cells is a candidate
            tokens = [str(v).strip() for v in row.tolist()]
            numeric_cells = [t for t in tokens if is_numeric_token(t)]
            if len(numeric_cells) < 5:
                continue

            # last 5 numeric cells map to safe, warning, danger, doubtful, total
            safe_s, warn_s, danger_s, doubtful_s, total_s = numeric_cells[-5:]
            customer = " ".join(tokens[: len(tokens) - 5]).strip()
            if not customer:
                continue

            region = region_for_line_index(line_index) or "Unknown"

            safe_v = parse_numeric(safe_s)
            warning_v = parse_numeric(warn_s)
            danger_v = parse_numeric(danger_s)
            doubtful_v = parse_numeric(doubtful_s)
            total_v = parse_numeric(total_s)

            rows.append(
                ReceivableRow(
                    region=region,
                    customer_name=customer,
                    safe=safe_v,
                    warning=warning_v,
                    danger=danger_v,
                    doubtful=doubtful_v,
                    total=total_v,
                )
            )
            line_index += 1

    logger.info("Built %s rows from Camelot tables.", len(rows))
    return rows


def _attempt_column_shift_correction(row: ReceivableRow) -> ReceivableRow:
    """
    If the financial validation fails, try simple column shift corrections
    (e.g., when DOUBTFUL and TOTAL are swapped).
    """
    combos = []
    vals = [row.safe, row.warning, row.danger, row.doubtful, row.total]

    # original
    combos.append(vals)
    # shift total left (sometimes last two swapped)
    combos.append([row.safe, row.warning, row.danger, row.total, row.doubtful])

    for safe_v, warning_v, danger_v, doubtful_v, total_v in combos:
        if almost_equal_sum(safe_v, warning_v, danger_v, doubtful_v, total_v):
            return ReceivableRow(
                region=row.region,
                customer_name=row.customer_name,
                safe=safe_v,
                warning=warning_v,
                danger=danger_v,
                doubtful=doubtful_v,
                total=total_v,
            )

    return row


def _apply_financial_validation(rows: List[ReceivableRow]) -> List[ReceivableRow]:
    corrected: List[ReceivableRow] = []
    for r in rows:
        if not almost_equal_sum(r.safe, r.warning, r.danger, r.doubtful, r.total):
            new_r = _attempt_column_shift_correction(r)
            if new_r is not r:
                logger.info(
                    "Corrected financial mismatch for '%s' in region '%s'",
                    r.customer_name,
                    r.region,
                )
                corrected.append(new_r)
            else:
                corrected.append(r)
        else:
            corrected.append(r)
    return corrected


def _validation_pass_rate(rows: List[ReceivableRow]) -> float:
    if not rows:
        return 0.0
    ok = 0
    for r in rows:
        if almost_equal_sum(r.safe, r.warning, r.danger, r.doubtful, r.total):
            ok += 1
    return ok / max(len(rows), 1)


def run_full_pipeline(pdf_path: str, export_dir: str | Path | None = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Run the complete parsing pipeline on a single PDF:
      1. pdfplumber text extraction
      2. Camelot table extraction
      3. Coordinate-aware reconstruction (simplified to table/text reconciliation)
      4. OCR fallback with PaddleOCR when needed
      5. Vision validation hook with Qwen2.5-VL
      6. Financial consistency validation and column-shift correction
      7. Structured data export (optional)
    """
    pdf_path = str(Path(pdf_path))
    logger.info("Starting full parsing pipeline for %s", pdf_path)

    parsed = read_pdf(pdf_path)
    raw_text = parsed["raw_text"]
    all_lines: List[str] = []
    for page in parsed["pages"]:
        all_lines.extend(page["text_lines"])

    # 1) Text parser (baseline)
    text_rows = parse_receivable_lines(all_lines)
    text_pass_rate = _validation_pass_rate(text_rows)
    text_regions = sorted({r.region for r in text_rows if r.region and r.region != "Unknown"})

    # Fast-path: if text parser extracted enough rows with decent financial consistency,
    # skip Camelot and OCR entirely for performance.
    if len(text_rows) >= 20 and text_pass_rate >= 0.85 and len(text_regions) >= 1:
        logger.info(
            "Fast-path using text parser only (rows=%s, pass_rate=%.2f, regions=%s).",
            len(text_rows),
            text_pass_rate,
            len(text_regions),
        )
        candidate_rows = text_rows
    else:
        # 2) Camelot tables (only when text quality looks weak)
        camelot_dfs = extract_tables(pdf_path)
        table_rows: List[ReceivableRow] = []
        if camelot_dfs:
            table_rows = _rows_from_camelot_tables(camelot_dfs, raw_text)

        # Prefer whichever produces more plausible rows
        if len(table_rows) > len(text_rows):
            logger.info(
                "Using Camelot-based rows (%s) over text rows (%s)",
                len(table_rows),
                len(text_rows),
            )
            candidate_rows = table_rows
        else:
            candidate_rows = text_rows

    # 3) If we have very few rows, trigger OCR+PaddleOCR as a fallback (lazy import)
    if len(candidate_rows) < 5:
        logger.info(
            "Low row count (%s) from text/Camelot; triggering PaddleOCR fallback.",
            len(candidate_rows),
        )
        try:
            from ocr.paddle_ocr_reader import pdf_to_ocr_boxes

            ocr_boxes = pdf_to_ocr_boxes(pdf_path)
            # For now, we only reuse text from OCR (concatenated lines)
            ocr_lines: List[str] = []
            for _, items in ocr_boxes:
                for txt, _ in items:
                    ocr_lines.append(txt)
            ocr_rows = parse_receivable_lines(ocr_lines)
            if len(ocr_rows) > len(candidate_rows):
                logger.info(
                    "Using PaddleOCR-derived rows (%s) over previous (%s).",
                    len(ocr_rows),
                    len(candidate_rows),
                )
                candidate_rows = ocr_rows
        except Exception as exc:  # noqa: BLE001
            logger.info("PaddleOCR not available; skipping OCR fallback (%s).", exc)

    # 4) Vision validation hook – no-op placeholder, but structured for production
    #    You would pass per-page images and rows to Qwen2.5-VL here.
    candidate_dicts = [asdict(r) for r in candidate_rows]
    # For now, we just call a stub that returns these unchanged.
    dummy_image_path = Path(pdf_path)  # in real use, pass page images
    validated_dicts = validate_with_qwen(dummy_image_path, candidate_dicts)
    validated_rows = [
        ReceivableRow(
            region=d["region"],
            customer_name=d["customer_name"],
            safe=float(d["safe"]),
            warning=float(d["warning"]),
            danger=float(d["danger"]),
            doubtful=float(d["doubtful"]),
            total=float(d["total"]),
        )
        for d in validated_dicts
    ]

    # 5) Financial validation and correction
    final_rows = _apply_financial_validation(validated_rows)

    df = rows_to_dataframe(final_rows)

    summary = {
        "rows_extracted": int(len(df)),
        "regions_detected": sorted(df["region"].dropna().unique().tolist()),
        "total_value": float(df["total"].sum()),
    }

    if export_dir is not None:
        export_all(df, export_dir)

    logger.info(
        "Completed full pipeline: rows=%s, regions=%s, total=%.2f",
        summary["rows_extracted"],
        len(summary["regions_detected"]),
        summary["total_value"],
    )
    return df, summary

