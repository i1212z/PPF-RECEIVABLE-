from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from paddleocr import PaddleOCR
import pdf2image

from utils.logger import get_logger


logger = get_logger(__name__)


_ocr = PaddleOCR(use_angle_cls=True, lang="en")


def pdf_to_ocr_boxes(path: str) -> List[Tuple[int, List[Tuple[str, List[Tuple[float, float]]]]]]:
    """
    Convert each PDF page to an image and run PaddleOCR.

    Returns list of:
      (page_index, [(text, box_coords), ...])
    where box_coords is a list of 4 (x, y) points for the text box.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found for OCR: {pdf_path}")

    logger.info("Starting PaddleOCR fallback for PDF: %s", pdf_path)
    pages = pdf2image.convert_from_path(str(pdf_path))
    results: List[Tuple[int, List[Tuple[str, List[Tuple[float, float]]]]]] = []

    for idx, pil_img in enumerate(pages, start=1):
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        ocr_result = _ocr.ocr(img, cls=True)
        page_items: List[Tuple[str, List[Tuple[float, float]]]] = []
        for line in ocr_result:
            for box, (txt, conf) in line:
                if not txt.strip():
                    continue
                # box: 4 points
                coords = [(float(x), float(y)) for x, y in box]
                page_items.append((txt, coords))
        logger.info("PaddleOCR page %s produced %s text boxes", idx, len(page_items))
        results.append((idx, page_items))

    logger.info("Completed PaddleOCR on %s pages.", len(results))
    return results

