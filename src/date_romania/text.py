"""Text as it is compared: one form for headers, names and places read from many sources."""

import re
import unicodedata


def plain(value: object) -> str:
    """A header or a name as it is compared: upper case, no diacritics, single spaces."""
    text = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    text = text.encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()
