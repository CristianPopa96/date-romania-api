"""Reading spreadsheets from public sources: the rows of a file, whatever its format."""

import csv
import io
import re
import unicodedata
from collections.abc import Iterator

from python_calamine import CalamineWorkbook

_ZIP = b"PK"  # xlsx and ods
_OLE = b"\xd0\xcf\x11\xe0"  # xls


def plain(value: object) -> str:
    """A header or a name as it is compared: upper case, no diacritics, single spaces."""
    text = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    text = text.encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def is_workbook(content: bytes) -> bool:
    """True for xls, xlsx and ods. The signature decides, never the label on the file."""
    return content[:2] == _ZIP or content[:4] == _OLE


def workbook_sheets(content: bytes) -> Iterator[tuple[str, list[list]]]:
    """Each sheet of a workbook as (name, rows)."""
    workbook = CalamineWorkbook.from_filelike(io.BytesIO(content))
    for name in workbook.sheet_names:
        yield name, workbook.get_sheet_by_name(name).to_python(skip_empty_area=False)


def csv_rows(content: bytes) -> Iterator[list[str]]:
    """The rows of a delimited text file, with the delimiter and the encoding found out.

    The exports use `^`, `|`, `;` or `,` between values, and one of them wraps every value
    in `|` with commas between.
    """
    head = content[:200_000]
    try:
        head.decode("utf-8")
        encoding = "utf-8-sig"
    except UnicodeDecodeError as error:
        # A character cut in two by the end of the sample is not a wrong encoding.
        encoding = "utf-8-sig" if error.start >= len(head) - 8 else "cp1250"
    first = head.decode(encoding, errors="replace").split("\n", 1)[0].lstrip("﻿")
    delimiter, quote = max("^;,|\t", key=first.count), '"'
    if first.startswith("|"):
        delimiter, quote = ",", "|"
    text = io.TextIOWrapper(io.BytesIO(content), encoding=encoding, errors="replace", newline="")
    csv.field_size_limit(1 << 30)
    yield from csv.reader(text, delimiter=delimiter, quotechar=quote)
