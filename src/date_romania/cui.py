"""Romanian tax ID (CUI / CIF) parsing and checksum validation."""

import re

_KEY = "753217532"


def parse_cui(raw: str | int) -> int | None:
    """Return the CUI as an int from strings like ' 23517392', 'RO 8955860', or None if invalid."""
    digits = re.sub(r"\D", "", str(raw))
    if not 2 <= len(digits) <= 10:
        return None
    return int(digits) if is_valid_cui(digits) else None


def is_valid_cui(digits: str) -> bool:
    body, control = digits[:-1].zfill(9), int(digits[-1])
    total = sum(int(d) * int(k) for d, k in zip(body, _KEY, strict=True))
    expected = total * 10 % 11
    return (0 if expected == 10 else expected) == control
