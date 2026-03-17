from typing import Optional


def almost_equal_sum(
    safe: float,
    warning: float,
    danger: float,
    doubtful: float,
    total: float,
    tolerance: float = 0.05,
) -> bool:
    """
    Check that safe+warning+danger+doubtful ~= total within tolerance.
    """
    computed = (safe or 0.0) + (warning or 0.0) + (danger or 0.0) + (doubtful or 0.0)
    return abs(computed - (total or 0.0)) <= tolerance


def parse_numeric(value: str) -> float:
    """
    Convert strings like '1,660.00', '-', '' to float, treating '-' or empty as 0.
    """
    if value is None:
        return 0.0
    v = value.strip()
    if not v or v == "-":
        return 0.0
    v = v.replace(",", "")
    return float(v)


def is_numeric_token(token: str) -> bool:
    """
    Decide whether a token looks like a numeric field (possibly '-').
    """
    if not token:
        return False
    t = token.strip()
    if t == "-":
        return True
    # remove thousand separators
    t = t.replace(",", "")
    try:
        float(t)
        return True
    except ValueError:
        return False

