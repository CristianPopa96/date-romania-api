"""Personal numeric codes (CNP): finding and hiding them before a row is stored (GDPR)."""

import re

_CNP = re.compile(r"\b[1-9]\d{12}\b")
_KEY = "279146358279"


def is_cnp(digits: str) -> bool:
    """True for 13 digits with a possible birth date and the right control digit."""
    if not (1 <= int(digits[3:5]) <= 12 and 1 <= int(digits[5:7]) <= 31):
        return False
    control = sum(int(d) * int(k) for d, k in zip(digits, _KEY, strict=False)) % 11
    return (1 if control == 10 else control) == int(digits[12])


def mask_cnp(text: str | None, checked: bool = False) -> str | None:
    """Hide personal numeric codes; the name of a sole trader stays.

    Where a party is named, any 13-digit number is hidden. In free text most such numbers
    are barcodes and permit numbers, so `checked` hides only those that are valid codes.
    """
    if not text:
        return text
    return _CNP.sub(
        lambda found: "[CNP]" if not checked or is_cnp(found.group()) else found.group(), text
    )
