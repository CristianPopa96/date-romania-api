"""Reading spreadsheets from public sources: the rows of a file, whatever its format."""

import codecs
import csv
import io
from collections.abc import Iterable, Iterator

from python_calamine import CalamineWorkbook

_ZIP = b"PK"  # xlsx and ods
_OLE = b"\xd0\xcf\x11\xe0"  # xls
_PIECE = 1 << 20


def is_workbook(content: bytes) -> bool:
    """True for xls, xlsx and ods. The signature decides, never the label on the file."""
    return content[:2] == _ZIP or content[:4] == _OLE


def workbook_sheets(content: bytes) -> Iterator[tuple[str, Iterable[list]]]:
    """Each sheet of a workbook as (name, rows). Rows come one at a time: a sheet of an
    export has 65,000 of them."""
    workbook = CalamineWorkbook.from_filelike(io.BytesIO(content))
    for name in workbook.sheet_names:
        yield name, workbook.get_sheet_by_name(name).iter_rows()


def _encoding(content: bytes) -> str:
    """UTF-8 if the whole file reads as UTF-8, else the Windows encoding of Romanian.
    Checked piece by piece: an export is up to 280 MB."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        for start in range(0, len(content), _PIECE):
            decoder.decode(content[start : start + _PIECE])
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return "cp1250"
    return "utf-8-sig"


def csv_rows(content: bytes) -> Iterator[list[str]]:
    """The rows of a delimited text file, with the delimiter and the encoding found out.

    The exports use `^`, `|`, `;` or `,` between values, and one of them wraps every value
    in `|` with commas between.
    """
    encoding = _encoding(content)
    first = content[:200_000].decode(encoding, errors="replace").split("\n", 1)[0]
    first = first.lstrip("﻿")
    delimiter, quote = max("^;,|\t", key=first.count), '"'
    if first.startswith("|"):
        delimiter, quote = ",", "|"
    text = io.TextIOWrapper(io.BytesIO(content), encoding=encoding, errors="replace", newline="")
    csv.field_size_limit(1 << 30)
    yield from csv.reader(text, delimiter=delimiter, quotechar=quote)
