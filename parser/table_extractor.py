from pathlib import Path
from typing import List, Dict, Any

import camelot
import pandas as pd

from utils.logger import get_logger


logger = get_logger(__name__)


def extract_tables(path: str) -> List[pd.DataFrame]:
    """
    Use Camelot to extract tables from all pages.
    On failure, return empty list and let text parser handle everything.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        tables = camelot.read_pdf(str(pdf_path), pages="all", flavor="lattice")
        if not tables:
            logger.info("No tables detected with lattice; retrying with stream flavor.")
            tables = camelot.read_pdf(str(pdf_path), pages="all", flavor="stream")
    except Exception as exc:
        logger.warning("Camelot failed to read tables: %s", exc)
        return []

    dfs: List[pd.DataFrame] = []
    for t in tables:
        df = t.df
        dfs.append(df)
    logger.info("Camelot extracted %s tables.", len(dfs))
    return dfs

