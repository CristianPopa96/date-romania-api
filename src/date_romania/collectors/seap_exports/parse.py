"""Turning a quarterly contract export into rows, for the suppliers asked for."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from date_romania.collectors.sheets import csv_rows, is_workbook, plain, workbook_sheets
from date_romania.counties import COUNTIES
from date_romania.cui import parse_cui
from date_romania.personal_id import mask_cnp

PARSER_VERSION = 1

# Every layout has this column, under this name; the row that holds it is the header.
_KEY = "NUMAR ANUNT ATRIBUIRE"

# The narrowest layout has 19 columns.
_FEWEST = 10

# Day 0 of a spreadsheet's calendar: one export gives its dates as bare day numbers.
_DAY_ZERO = date(1899, 12, 30)

# 'mm/dd/yyyy', with or without leading zeros and a time after it. Checked over every
# export from 2021 to 2026: the month always comes first.
_US_DAY = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})")
# '1,293,617.50': commas between thousands.
_THOUSANDS = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?")

_ERRORS = (AttributeError, IndexError, KeyError, TypeError, ValueError, InvalidOperation)


@dataclass
class Parsed:
    contracts: list[dict] = field(default_factory=list)
    # (row, reason) for rows of the suppliers asked for that could not be read
    rejected: list[tuple[object, str]] = field(default_factory=list)
    # Every contract row of the file, whoever won it.
    seen: int = 0
    # Every buyer of the file: cui -> (name, county where the layout gives one).
    buyers: dict[int, tuple[str, str | None]] = field(default_factory=dict)


def _named(header: list[str], test) -> int | None:
    return next((index for index, name in enumerate(header) if test(name)), None)


def _columns(row: list) -> dict[str, int] | None:
    """Where each of our columns is, or None if this row is not a header.

    Six layouts in six years name the same things differently ('CASTIGATOR_CUI',
    'CUI_OFERTANT', 'CUI_OF', 'CUI ofertant castigator'), so a column is found by what
    its name says, not by the name itself.
    """
    header = [plain(cell) for cell in row]
    # The last export ends with a sheet of notes that names the columns one per row.
    if _KEY not in header or sum(1 for name in header if name) < _FEWEST:
        return None

    def winner(name: str) -> bool:
        return any(word in name for word in ("CASTIG", "CATIG", "OFERTANT"))

    def party(name: str) -> bool:
        return not any(word in name for word in ("CUI", "TARA", "LOCALITATE", "ADRESA", "ORAS"))

    notice = header.index(_KEY)
    found = {
        "notice_no": notice,
        # The 2024 to 2026 layouts have two columns named 'Data publicare'; the one after
        # the notice number is the notice's.
        "notice_date": notice + 1 if header[notice + 1].startswith("DATA") else None,
        "supplier_cui": _named(
            header, lambda name: "CUI" in name and (winner(name) or name == "CUI OF")
        ),
        "supplier_text": _named(header, lambda name: winner(name) and party(name)),
        "buyer_cui": _named(
            header, lambda name: "AUTORITATE" in name and "CUI" in name or name in ("CUI AC", "CUI")
        ),
        "buyer_text": _named(
            header, lambda name: name in ("AUTORITATE CONTRACTANTA", "DENUMIRE AC")
        ),
        # Only the layout of 2022 T1 says where the buyer is.
        "buyer_county": _named(header, lambda name: name == "DENUMIRE NUTS"),
        "contract_no": _named(header, lambda name: name == "NUMAR CONTRACT"),
        "contract_date": _named(
            header, lambda name: name.startswith("DATA") and name.endswith("CONTRACT")
        ),
        "title": _named(header, lambda name: name in ("TITLU CONTRACT", "DENUMIRE CONTRACT")),
        "value_ron": _named(
            header, lambda name: name.startswith(("VALOARE CONTRACT", "VALOARE ATRIBUITA"))
        ),
        "procedure_type": _named(header, lambda name: name == "TIP PROCEDURA"),
        "contract_type": _named(header, lambda name: name == "TIP CONTRACT"),
        "closing": _named(header, lambda name: name.startswith("TIP INCH")),
        "cpv_code": _named(header, lambda name: name in ("CPV CODE", "COD CPV")),
        "cpv_name": _named(header, lambda name: name == "DENUMIRE CPV"),
        "lot": _named(header, lambda name: name == "NUMAR LOT"),
    }
    for needed in ("supplier_cui", "buyer_text", "contract_date", "value_ron"):
        if found[needed] is None:
            raise ValueError(f"no {needed} column in {header}")
    return {name: index for name, index in found.items() if index is not None}


def _text(value: object) -> str | None:
    """A cell as text. A whole number read as 898.0 is written 898."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value if value is not None else "").strip()
    return text or None


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return _DAY_ZERO + timedelta(days=int(value))
    text = _text(value)
    if not text:
        return None
    found = _US_DAY.match(text)
    if found:
        month, day, year = (int(part) for part in found.groups())
        return date(year, month, day)
    return date.fromisoformat(text[:10])


def _money(value: object) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    if _THOUSANDS.fullmatch(text):
        text = text.replace(",", "")
    return Decimal(text.replace(",", "."))


def _cui(value: object) -> int | None:
    text = _text(value)
    return parse_cui(text) if text else None


def _contract(cells: dict, supplier_cui: int | None) -> dict:
    closing = plain(cells.get("closing"))
    return {
        "notice_no": _text(cells.get("notice_no")),
        "notice_date": _day(cells.get("notice_date")),
        "contract_no": _text(cells.get("contract_no")),
        "contract_date": _day(cells.get("contract_date")),
        "title": mask_cnp(_text(cells.get("title")), checked=True),
        "lot": _text(cells.get("lot")),
        "buyer_cui": _cui(cells.get("buyer_cui")),
        "buyer_text": mask_cnp(_text(cells["buyer_text"])),
        "supplier_cui": supplier_cui,
        "supplier_text": mask_cnp(_text(cells.get("supplier_text"))),
        "value_ron": _money(cells.get("value_ron")),
        "procedure_type": _text(cells.get("procedure_type")),
        "contract_type": _text(cells.get("contract_type")),
        # A framework agreement is a ceiling, as in the award notices.
        "is_framework": "ACORD CADRU" in closing if closing else None,
        "cpv_code": _text(cells.get("cpv_code")),
        "cpv_name": _text(cells.get("cpv_name")),
    }


def _sheets(content: bytes) -> Iterator[Iterable[list]]:
    if is_workbook(content):
        for _, rows in workbook_sheets(content):
            yield rows
    else:
        yield csv_rows(content)


def _rows(content: bytes) -> Iterator[tuple[dict[str, int], list]]:
    """Every contract row of an export, with where its columns are. A workbook repeats
    its header on every sheet, and may end with a sheet of notes."""
    for rows in _sheets(content):
        columns = None
        for row in rows:
            if columns is None:
                columns = _columns(row)
            elif len(row) > max(columns.values()):
                yield columns, row


def _contract_key(columns: dict[str, int], row: list) -> tuple:
    """What tells one contract of an export from another: its notice and its number."""
    return _text(row[columns["notice_no"]]), _text(row[columns.get("contract_no", 0)])


def _note_buyer(buyers: dict, columns: dict[str, int], row: list) -> None:
    """Remember a buyer and, where the layout names a county, which one. The column
    also holds regions ('Nord-Est'), which are not counties and are left out."""
    cui = _cui(row[columns["buyer_cui"]]) if "buyer_cui" in columns else None
    name = _text(row[columns["buyer_text"]])
    if cui is None or name is None:
        return
    county = plain(row[columns["buyer_county"]]) if "buyer_county" in columns else None
    known = buyers.get(cui, (name, None))[1]
    buyers[cui] = (mask_cnp(name), county if county in COUNTIES else known)


def parse_contracts(content: bytes, suppliers: set[int]) -> Parsed:
    """The contracts in one export won by any of `suppliers`.

    An export has hundreds of thousands of rows; only the ones asked for are kept. A
    contract won by an association has one row per member, with the same value on each:
    all of them are kept, so the contract can be shown as won together. The file is read
    twice, since a partner can come before the supplier asked for. Every buyer of the
    file is noted on the way (`Parsed.buyers`).
    """
    parsed = Parsed()
    wanted = set()
    for columns, row in _rows(content):
        if _cui(row[columns["supplier_cui"]]) in suppliers:
            wanted.add(_contract_key(columns, row))
        _note_buyer(parsed.buyers, columns, row)
    for columns, row in _rows(content):
        parsed.seen += 1
        if _contract_key(columns, row) not in wanted:
            continue
        try:
            cells = {name: row[index] for name, index in columns.items()}
            parsed.contracts.append(_contract(cells, _cui(cells["supplier_cui"])))
        except _ERRORS as error:
            parsed.rejected.append((row, repr(error)))
    return parsed
