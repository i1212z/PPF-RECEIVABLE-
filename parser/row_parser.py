import regex as re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import pandas as pd

from parser.cleaner import clean_lines, is_non_data_line
from parser.region_detector import detect_region
from utils.logger import get_logger
from utils.validators import is_numeric_token, parse_numeric, almost_equal_sum


logger = get_logger(__name__)


NUMERIC_GROUP_RE = re.compile(r"(\s+[-\d,\.]+){5}$")


@dataclass
class ReceivableRow:
    region: str
    customer_name: str
    safe: float
    warning: float
    danger: float
    doubtful: float
    total: float


def _join_multiline_rows(lines: Iterable[str]) -> List[str]:
    """
    Join lines where customer names wrap to the next line.
    A valid data line must end with 5 numeric-like tokens.
    """
    joined: List[str] = []
    buffer: Optional[str] = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Skip obvious non-data header/footer lines
        if is_non_data_line(line):
            if buffer:
                joined.append(buffer)
                buffer = None
            continue

        tokens = line.split()
        numeric_count = sum(1 for t in tokens if is_numeric_token(t))

        # Treat lines with >=3 numeric fields as data rows (even if missing columns).
        # This prevents mistakenly gluing partial rows like "Latin Street - - 4,771.00 4,771.00"
        # to the next customer row.
        if numeric_count >= 3:
            if buffer:
                joined.append(buffer)
                buffer = None
            joined.append(line)
            continue

        # Otherwise, likely a wrapped customer name line
        if buffer:
            buffer = f"{buffer} {line}"
        else:
            buffer = line

    if buffer:
        joined.append(buffer)

    return joined


MONEY_RE = re.compile(r"^-?$|^\d{1,3}(?:,\d{3})*(?:\.\d+)?$")

LEADING_COMMA_RE = re.compile(r"^,\d")


def _merge_money_tokens(tokens: List[str]) -> List[str]:
    """
    Some PDFs split amounts like '600.00' into ['6', '00.00'].
    This routine walks tokens left->right and merges adjacent numeric tokens
    when their concatenation looks like a money value.
    """
    if not tokens:
        return []

    merged: List[str] = []
    i = 0
    while i < len(tokens):
        cur = tokens[i]

        # Fix split thousands separators like ['7', ',773.00'] -> '7,773.00'
        if i + 1 < len(tokens) and cur.isdigit() and LEADING_COMMA_RE.match(tokens[i + 1]):
            merged.append(cur + tokens[i + 1])
            i += 2
            continue

        # Fix split like ['1', '7,831.00'] -> '17,831.00'
        if (
            i + 1 < len(tokens)
            and cur.isdigit()
            and re.match(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$", tokens[i + 1])
        ):
            candidate = cur + tokens[i + 1]
            if MONEY_RE.match(candidate):
                merged.append(candidate)
                i += 2
                continue

        # Try to merge with next if both numeric-like and combined looks like money
        if i + 1 < len(tokens) and is_numeric_token(cur) and is_numeric_token(tokens[i + 1]):
            candidate = cur + tokens[i + 1]
            if MONEY_RE.match(candidate.replace(" ", "")):
                merged.append(candidate)
                i += 2
                continue
        merged.append(cur)
        i += 1
    return merged


def _split_numeric_columns(line: str) -> Optional[Tuple[str, List[str]]]:
    """
    Split the last 5 numeric-looking tokens from a line.
    Returns (customer_name, [safe, warning, danger, doubtful, total]) or None.
    """
    # Repair spacing artifacts inside amounts: "7 ,773.00" -> "7,773.00"
    line = re.sub(r"(\d)\s*,\s*(\d{3}\.\d+)", r"\1,\2", line)
    # Repair artifacts like "1 7,831.00" -> "17,831.00"
    line = re.sub(r"\b(\d)\s+(\d{1,3}(?:,\d{3})+\.\d+)\b", r"\1\2", line)

    raw_tokens = line.split()
    tokens = _merge_money_tokens(raw_tokens)

    numeric_tokens: List[str] = []
    for tok in reversed(tokens):
        if is_numeric_token(tok) and len(numeric_tokens) < 5:
            numeric_tokens.append(tok)
        elif len(numeric_tokens) == 5:
            break

    if len(numeric_tokens) < 3:
        return None

    numeric_tokens = list(reversed(numeric_tokens))
    name_len = len(tokens) - len(numeric_tokens)
    customer_name = " ".join(tokens[:name_len]).strip()

    # Normalize to exactly 5 columns by inserting missing '-' where common patterns appear.
    # Common case in this PDF: '- - 4,771.00 4,771.00' meaning DANGER=4771, TOTAL=4771.
    if len(numeric_tokens) == 4:
        if (
            numeric_tokens[0] == "-"
            and numeric_tokens[1] == "-"
            and numeric_tokens[2] == numeric_tokens[3]
        ):
            numeric_tokens = ["-", "-", numeric_tokens[2], "-", numeric_tokens[3]]
        else:
            numeric_tokens = [numeric_tokens[0], numeric_tokens[1], numeric_tokens[2], "-", numeric_tokens[3]]
    elif len(numeric_tokens) == 3:
        numeric_tokens = [numeric_tokens[0], numeric_tokens[1], "-", "-", numeric_tokens[2]]

    if len(numeric_tokens) != 5:
        return None

    return customer_name, numeric_tokens


def parse_receivable_lines(lines: Iterable[str]) -> List[ReceivableRow]:
    """
    Parse cleaned text lines into structured receivable rows with region detection.
    """
    cleaned = clean_lines(lines)
    joined = _join_multiline_rows(cleaned)

    rows: List[ReceivableRow] = []
    current_region: Optional[str] = None

    for line in joined:
        reg = detect_region(line)
        if reg:
            current_region = reg
            logger.info("Detected region header: %s", current_region)
            continue

        if current_region is None:
            # ignore lines before first region header
            continue

        # ignore any remaining non-data lines
        if is_non_data_line(line):
            continue

        res = _split_numeric_columns(line)
        if not res:
            continue

        customer_name, numeric_tokens = res
        if not customer_name:
            continue

        safe_v = parse_numeric(numeric_tokens[0])
        warning_v = parse_numeric(numeric_tokens[1])
        danger_v = parse_numeric(numeric_tokens[2])
        doubtful_v = parse_numeric(numeric_tokens[3])
        total_v = parse_numeric(numeric_tokens[4])

        if not almost_equal_sum(safe_v, warning_v, danger_v, doubtful_v, total_v):
            logger.warning(
                "Validation mismatch for '%s' in region '%s': "
                "safe=%s warning=%s danger=%s doubtful=%s total=%s",
                customer_name,
                current_region,
                safe_v,
                warning_v,
                danger_v,
                doubtful_v,
                total_v,
            )

        row = ReceivableRow(
            region=current_region,
            customer_name=customer_name,
            safe=safe_v,
            warning=warning_v,
            danger=danger_v,
            doubtful=doubtful_v,
            total=total_v,
        )
        rows.append(row)

    logger.info("Parsed %s receivable rows from text.", len(rows))
    return rows


def rows_to_dataframe(rows: List[ReceivableRow]) -> pd.DataFrame:
    data = [
        {
            "region": r.region,
            "customer_name": r.customer_name,
            "safe": r.safe,
            "warning": r.warning,
            "danger": r.danger,
            "doubtful": r.doubtful,
            "total": r.total,
        }
        for r in rows
    ]
    return pd.DataFrame(data)

