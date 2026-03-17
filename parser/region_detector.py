import re
from typing import Optional


REGION_PATTERNS = {
    "Calicut": re.compile(r"\bCalicut Customers\b", re.IGNORECASE),
    "Kochi & Kottayam": re.compile(
        r"\bKochi\s*&\s*Kottayam Customers\b", re.IGNORECASE
    ),
    "Tamilnadu": re.compile(r"\bTamilnadu Customers\b", re.IGNORECASE),
    "Karnataka": re.compile(r"\bKarnataka Customers\b", re.IGNORECASE),
}


def detect_region(line: str) -> Optional[str]:
    for region, pattern in REGION_PATTERNS.items():
        if pattern.search(line):
            return region
    return None

