import re
from typing import Iterable, List


WHITESPACE_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def clean_lines(lines: Iterable[str]) -> List[str]:
    return [normalize_whitespace(l) for l in lines if l is not None and l.strip()]


NON_DATA_KEYWORDS = [
    "Grand Total",
    "Particulars",
    "SAFE",
    "WARNING",
    "DANGER",
    "DOUBTFUL",
    "Note",
    "Legend",
    "Status as on",
]


def is_non_data_line(line: str) -> bool:
    upper = line.upper()
    for kw in NON_DATA_KEYWORDS:
        if kw.upper() in upper:
            return True
    return False

