"""Reading the lists of contracted projects, whatever their layout.

Every programme has its own: the header sits on one row or on six, the values come in
groups ('Valoarea eligibilă / Finanțare acordată / Fonduri UE'), the SMIS code can be in
three columns, a workbook can hold working sheets next to the list, and a list can come
as an xlsx, an xls, a zip or a 7z. So a column is found by the words of its header, never
by its place, and the sheet by the projects it holds.
"""

import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import py7zr
import py7zr.exceptions

from date_romania.collectors.sheets import is_workbook, workbook_sheets
from date_romania.cui import parse_cui
from date_romania.entities import kind_of
from date_romania.text import plain

PARSER_VERSION = 1

_SEVEN_ZIP = b"7z\xbc\xaf\x27\x1c"
_SMIS = re.compile(r"\d{4,7}")
_MONTHS = {
    "IANUARIE": 1,
    "FEBRUARIE": 2,
    "MARTIE": 3,
    "APRILIE": 4,
    "MAI": 5,
    "IUNIE": 6,
    "IULIE": 7,
    "AUGUST": 8,
    "SEPTEMBRIE": 9,
    "OCTOMBRIE": 10,
    "NOIEMBRIE": 11,
    "DECEMBRIE": 12,
}
_ERRORS = (ArithmeticError, AttributeError, KeyError, TypeError, ValueError)


@dataclass
class Parsed:
    projects: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    rejected: list[tuple[object, str]] = field(default_factory=list)
    invalid_cuis: int = 0
    # False when no sheet of the file is a list of projects or of payments.
    found: bool = False
    # Cells that could not be read, by field: the project is kept with that field empty.
    # Two rates in one cell ('85% (RMPD) 80% (RMD)'), a day written as text.
    unread: Counter = field(default_factory=Counter)


def last_day(label: str | None) -> date | None:
    """The last day a title names: 'la 31 august 2025', 'la data de 30.06.2026',
    '1 septembrie - 30 septembrie 2026'."""
    words = plain(label)
    found: list[date] = []
    for day, month, year in re.findall(r"\b(\d{1,2}) ([A-Z]+) (\d{4})\b", words):
        if month in _MONTHS:
            found.append(date(int(year), _MONTHS[month], int(day)))
    for day, month, year in re.findall(r"\b(\d{1,2}) (\d{1,2}) (\d{4})\b", words):
        try:
            found.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return max(found) if found else None


def workbooks(content: bytes) -> list[tuple[str, bytes]]:
    """The workbooks in a file: itself, or each one inside a zip or a 7z archive. An xlsx is
    a zip too: it is told apart by its own content list."""
    try:
        if content[:6] == _SEVEN_ZIP:
            with py7zr.SevenZipFile(io.BytesIO(content)) as archive:
                files = archive.readall()
            return sorted(
                (name, data.read()) for name, data in files.items() if is_workbook(data.getvalue())
            )
        if content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if "[Content_Types].xml" not in names:
                    inner = [(name, archive.read(name)) for name in sorted(names)]
                    return [(name, data) for name, data in inner if is_workbook(data)]
    except (zipfile.BadZipFile, py7zr.exceptions.ArchiveError, EOFError, OSError) as exc:
        # A cut or broken archive is that file's failure, never the run's.
        raise ValueError(f"unreadable archive: {exc!r}") from exc
    return [("", content)] if is_workbook(content) else []


def _cell(value) -> str:
    return plain(value) if value not in (None, "") else ""


@dataclass
class Columns:
    """Where each field is in one sheet; `None` when the sheet does not give it."""

    smis: list[int]
    first_row: int
    title: int | None = None
    name: int | None = None
    cui: int | None = None
    partners: int | None = None
    summary: int | None = None
    starts: int | None = None
    ends: int | None = None
    rate: int | None = None
    region: int | None = None
    county: int | None = None
    locality: int | None = None
    kind: int | None = None
    status: int | None = None
    total: int | None = None
    eu: int | None = None
    paid: list[int] = field(default_factory=list)
    # The payments of the Health programme.
    amount: int | None = None
    paid_on: int | None = None
    payment_kind: int | None = None
    request_kind: int | None = None
    request_number: int | None = None
    order_number: int | None = None
    funding: int | None = None


def _labels(rows: list[list], top: int, first: int) -> list[tuple[str, str]]:
    """(head, whole) for each column: its own header, with a group title carried over the
    columns it spans, and every header row joined. Cut at the last header that says
    something: some sheets declare thousands of empty columns."""
    header = rows[top:first]
    width = 1 + max((i for r in header for i, c in enumerate(r) if _cell(c)), default=0)
    parts: list[list[str]] = [[] for _ in range(width)]
    for n, row in enumerate(header):
        carried = ""
        for i in range(width):
            cell = _cell(row[i]) if i < len(row) else ""
            if cell:
                carried = cell
            elif n < len(header) - 1:
                cell = carried
            if cell and (not parts[i] or parts[i][-1] != cell):
                parts[i].append(cell)
    return [(p[0] if p else "", " / ".join(p)) for p in parts]


def _find(labels, test, last: bool = False) -> int | None:
    found = [i for i, (head, whole) in enumerate(labels) if test(head, whole)]
    return (found[-1] if last else found[0]) if found else None


def columns(rows: list[list]) -> Columns | None:
    """The columns of a sheet, or None if it is not a list of projects or payments."""
    top = next((i for i, row in enumerate(rows[:40]) if any("SMIS" in _cell(c) for c in row)), None)
    if top is None:
        return None
    candidates = [i for i, c in enumerate(rows[top]) if "SMIS" in _cell(c)]
    first = next(
        (
            n
            for n in range(top + 1, min(len(rows), top + 20))
            if any(_smis(rows[n], [i]) for i in candidates)
        ),
        None,
    )
    if first is None:
        return None
    labels = _labels(rows, top, first)
    # The SMIS column that holds codes most often: some lists repeat it, one with blanks.
    smis = sorted(
        candidates,
        key=lambda i: -sum(1 for row in rows[first:] if _smis(row, [i])),
    )
    eu = [
        i
        for i, (head, whole) in enumerate(labels)
        if "ELIGIBIL" in head
        and any(word in whole for word in ("FONDURI UE", "FEDR", "FSE"))
        and "EURO" not in whole
    ]
    # Where a list splits the EU money by fund, the group of both funds is the total.
    eu_both = [i for i in eu if " SI " in labels[i][1]]
    return Columns(
        smis=smis,
        first_row=first,
        title=_find(labels, lambda h, w: h.startswith("TITLU PROIECT")),
        name=_find(
            labels,
            lambda h, w: h.startswith(("DENUMIRE BENEFICIAR", "NUME BENEFICIAR")) or h == "LIDER",
        ),
        cui=_find(labels, lambda h, w: h.startswith("CUI")),
        partners=_find(labels, lambda h, w: "PARTENERI" in h),
        summary=_find(
            labels, lambda h, w: h.startswith(("REZUMAT", "SCOP PROIECT", "OBIECTIVE PROIECT"))
        ),
        starts=_find(labels, lambda h, w: "INCEPERE" in h),
        ends=_find(labels, lambda h, w: "FINALIZARE" in h),
        rate=_find(labels, lambda h, w: h.startswith("RATA")),
        region=_find(labels, lambda h, w: h.startswith("REGIUNE")),
        county=_find(labels, lambda h, w: "JUDET" in h),
        locality=_find(labels, lambda h, w: h.startswith(("LOCALITATE", "LOCALIZARE"))),
        kind=_find(labels, lambda h, w: h.startswith(("TIP BENEFICIAR", "TIP ORGANIZATIE"))),
        status=_find(labels, lambda h, w: h.startswith(("STADIU", "STARE"))),
        total=_find(
            labels,
            lambda h, w: (
                h.startswith(("TOTAL VALOARE PROIECT", "VALOARE TOTALA PROIECT"))
                and "EURO" not in w
            ),
            last=True,
        ),
        eu=(eu_both or eu or [None])[0],
        paid=[
            i
            for i, (head, whole) in enumerate(labels)
            if head.startswith("PLATI") and "EURO" not in whole
        ],
        amount=_find(labels, lambda h, w: h == "SUMA"),
        paid_on=_find(labels, lambda h, w: h.startswith("DATA PLATII")),
        payment_kind=_find(labels, lambda h, w: h.startswith("TIP PLATA")),
        request_kind=_find(labels, lambda h, w: h.startswith("TIP CERERE")),
        request_number=_find(labels, lambda h, w: h.startswith("NR CERERE")),
        order_number=_find(labels, lambda h, w: h.startswith("NR OP")),
        funding=_find(labels, lambda h, w: h.startswith("SURSA DE FINANTARE")),
    )


def _at(row: list, i: int | None):
    return row[i] if i is not None and i < len(row) else None


def _smis(row: list, candidates: list[int]) -> int | None:
    for i in candidates:
        value = _at(row, i)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = str(value or "").strip()
        if _SMIS.fullmatch(text):
            return int(text)
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip() or None


def _amount(value) -> Decimal | None:
    """Lei as a number, or as text in either convention ('1.234.567,89' or '1234567.89')."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or text in "-.,":
        return None
    if "," in text and "." in text:
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else text.replace(",", "")
        )
    elif "," in text:
        text = text.replace(",", ".") if len(text.rsplit(",", 1)[1]) <= 2 else text.replace(",", "")
    elif "." in text and (text.count(".") > 1 or len(text.rsplit(".", 1)[1]) == 3):
        # Lei have two decimals: '12.500' and '1.250.000' group thousands.
        text = text.replace(".", "")
    return Decimal(text).quantize(Decimal("0.01"))


def _day(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    # Day first, as Romania writes it; a US day ('12/31/2029') only when that fails.
    for pattern in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    raise ValueError(f"not a day: {text!r}")


def _rate(value) -> Decimal | None:
    """The EU share from 0 to 1, written as 0.85, as 85 or as '85%'."""
    if value is None or value == "":
        return None
    text = str(value).replace("%", "").replace(",", ".").strip()
    if not text:
        return None
    rate = Decimal(text)
    return (rate / 100 if rate > 1 else rate).quantize(Decimal("0.0001"))


def _sheets(content: bytes) -> list[tuple[str, list[list], Columns]]:
    found = []
    for book, data in workbooks(content):
        try:
            sheets = [(name, [list(row) for row in rows]) for name, rows in workbook_sheets(data)]
        except Exception as exc:  # calamine's own errors: a broken workbook
            raise ValueError(f"unreadable workbook {book!r}: {exc!r}") from exc
        for name, rows in sheets:
            where = columns(rows)
            if where is not None:
                found.append((f"{book}:{name}", rows, where))
    return found


def parse_projects(content: bytes, programme: str, period: str, cut_off: date | None) -> Parsed:
    """The projects of a list. In each workbook, the sheet with a title column and the most
    projects is the list; the others are working sheets. A SMIS code met twice keeps its
    first row."""
    parsed = Parsed()
    by_book: dict[str, tuple[int, list[list], Columns]] = {}
    for where, rows, cols in _sheets(content):
        if cols.title is None:
            continue
        book = where.rsplit(":", 1)[0]
        parsed.found = True
        held = sum(1 for row in rows[cols.first_row :] if _smis(row, cols.smis))
        if book not in by_book or held > by_book[book][0]:
            by_book[book] = (held, rows, cols)
    seen: set[int] = set()
    for _, rows, cols in by_book.values():
        for row in rows[cols.first_row :]:
            smis = _smis(row, cols.smis)
            if smis is None:
                continue
            if smis in seen:
                parsed.rejected.append((row, f"SMIS {smis} is listed twice"))
                continue
            try:
                parsed.projects.append(
                    _project(parsed, row, cols, smis, programme, period, cut_off)
                )
            except _ERRORS as exc:
                parsed.rejected.append((row, repr(exc)))
                continue
            seen.add(smis)
    return parsed


def _read(parsed: Parsed, name: str, read, value):
    """A field read from its cell, or None, counted, when the cell cannot be read."""
    try:
        return read(value)
    except _ERRORS:
        parsed.unread[name] += 1
        return None


def _project(parsed, row, cols: Columns, smis, programme, period, cut_off) -> dict:
    cui = None
    written = _text(_at(row, cols.cui))
    if written:
        cui = parse_cui(written)
        parsed.invalid_cuis += cui is None
    name = _text(_at(row, cols.name))
    kind = _text(_at(row, cols.kind))
    if cui is not None:
        parsed.entities.setdefault(cui, (name or f"CUI {cui}", kind_of(kind)))
    paid = [_read(parsed, "paid", _amount, _at(row, i)) for i in cols.paid]
    return {
        "smis": smis,
        "programme": programme,
        "period": period,
        "title": _text(_at(row, cols.title)),
        "beneficiary_cui": cui,
        "beneficiary_name": name,
        "beneficiary_type": kind,
        "partners": _text(_at(row, cols.partners)),
        "summary": _text(_at(row, cols.summary)),
        "starts_on": _read(parsed, "starts_on", _day, _at(row, cols.starts)),
        "ends_on": _read(parsed, "ends_on", _day, _at(row, cols.ends)),
        "cofinancing_rate": _read(parsed, "cofinancing_rate", _rate, _at(row, cols.rate)),
        "region": _text(_at(row, cols.region)),
        "county": _text(_at(row, cols.county)),
        "locality": _text(_at(row, cols.locality)),
        "eu_value": _read(parsed, "eu_value", _amount, _at(row, cols.eu)),
        "total_value": _read(parsed, "total_value", _amount, _at(row, cols.total)),
        "paid": sum((p for p in paid if p is not None), Decimal(0))
        if any(p is not None for p in paid)
        else None,
        "status": _text(_at(row, cols.status)),
        "cut_off": cut_off,
    }


def parse_payments(content: bytes, programme: str) -> Parsed:
    """The payments of one month, as the Health programme publishes them."""
    parsed = Parsed()
    position = 0
    for _, rows, cols in _sheets(content):
        if cols.amount is None:
            continue
        parsed.found = True
        for row in rows[cols.first_row :]:
            smis = _smis(row, cols.smis)
            if smis is None:
                continue
            try:
                amount = _read(parsed, "amount", _amount, _at(row, cols.amount))
                if amount is None:
                    raise ValueError("no amount")
                position += 1
                parsed.payments.append(
                    {
                        "position": position,
                        "smis": smis,
                        "programme": programme,
                        "beneficiary_name": _text(_at(row, cols.name)),
                        "kind": _text(_at(row, cols.payment_kind)),
                        "request_kind": _text(_at(row, cols.request_kind)),
                        "request_number": _text(_at(row, cols.request_number)),
                        "order_number": _text(_at(row, cols.order_number)),
                        "amount": amount,
                        "paid_on": _read(parsed, "paid_on", _day, _at(row, cols.paid_on)),
                        "funding": _text(_at(row, cols.funding)),
                    }
                )
            except _ERRORS as exc:
                parsed.rejected.append((row, repr(exc)))
    return parsed
