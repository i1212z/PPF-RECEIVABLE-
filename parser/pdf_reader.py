from pathlib import Path
from typing import Dict, List, Any

import pdfplumber

from utils.logger import get_logger


logger = get_logger(__name__)


def read_pdf(path: str) -> Dict[str, Any]:
    """
    Read all pages with pdfplumber, preserving line order and basic metadata.

    Returns:
        {
            "pages": [
                {
                    "page_number": int,
                    "text_lines": [str, ...],
                },
                ...
            ],
            "raw_text": "concatenated text",
        }
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("Reading PDF with pdfplumber: %s", pdf_path)

    pages: List[Dict[str, Any]] = []
    raw_text_parts: List[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = text.splitlines()
            pages.append(
                {
                    "page_number": idx,
                    "text_lines": lines,
                }
            )
            raw_text_parts.append(text)
            logger.info("Processed page %s with %s lines", idx, len(lines))

    raw_text = "\n".join(raw_text_parts)
    logger.info("Completed reading PDF. Total pages: %s", len(pages))

    return {"pages": pages, "raw_text": raw_text}

