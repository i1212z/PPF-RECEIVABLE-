from pathlib import Path
from typing import List

import cv2
import numpy as np
import pdf2image
import pytesseract

from utils.logger import get_logger


logger = get_logger(__name__)


def pdf_to_ocr_text(path: str) -> List[str]:
    """
    Convert each PDF page to an image and run OCR to extract text lines.
    This is used as a fallback when pdfplumber returns little/no text.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found for OCR: {pdf_path}")

    logger.info("Starting OCR fallback for PDF: %s", pdf_path)
    pages = pdf2image.convert_from_path(str(pdf_path))
    all_lines: List[str] = []

    for idx, pil_img in enumerate(pages, start=1):
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
        # basic preprocessing: threshold + denoise
        _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        denoised = cv2.medianBlur(thresh, 3)

        text = pytesseract.image_to_string(denoised)
        page_lines = [ln for ln in text.splitlines() if ln.strip()]
        logger.info("OCR page %s produced %s lines", idx, len(page_lines))
        all_lines.extend(page_lines)

    logger.info("Completed OCR. Total OCR lines: %s", len(all_lines))
    return all_lines

