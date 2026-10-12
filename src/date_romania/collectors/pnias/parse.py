"""Turning a payment file of the Anghel Saligny programme into rows."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from date_romania.collectors.sheets import plain, workbook_sheets
from date_romania.cui import parse_cui
from date_romania.personal_id import mask_cnp

PARSER_VERSION = 1

INFRA, GAS = "infra", "gas"

# 'ASA4-25421 / 02.03.2026 ora 10:12': the ministry's number for a request, and its day.
_ANNEX = re.compile(r"\s*ASA4-(\d+)\s*/\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")

_MONTHS = [
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
]
# '27 august 2026.xlsx': the publisher's title of a file.
_FILE_DAY = re.compile(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})")

# Our name for a column, and how its header starts once `plain()` has cleaned it. The
# headers change from file to file ('Dată Anexă 4 Beneficiar', 'Data Anexa 4 Beneficiar').
_COLUMNS = {
    "county": "JUDET",
    "town_hall": "UAT",
    "state": "STARE",
    "request_no": "NUMAR ANEXA 4 BENEFICIAR",
    "requested_on": "DATA ANEXA 4 BENEFICIAR",
    "annex": "NR DATA ANEXA 4 MDLPA",
    "investment": "DENUMIREA OBIECTIVULUI",
    "category": "CATEGORIE INVESTITII",
    "project_id": "ID PROIECT",
    "ministry_contract_no": "NR CONTRACT MDLPA",
    "ministry_contract_date": "DATA CONTRACT MDLPA",
    "poim": "POIM",
    "total_value": "VALOAREA TOTALA",
    "state_budget_value": "VALOAREA DE LA BUGETUL",
    "amount": "VALOAREA SOLICITATA",
    "progress": "PROGRES",
    "designer_cui": "CUI PROIECTANT",
    "designer_text": "PROIECTANT",
    "builder_cui": "CUI EXECUTANT",
    "builder_text": "EXECUTANT",
    "estimated_end": "DATA ESTIMATA FINALIZARE",
}

_ERRORS = (AttributeError, KeyError, TypeError, ValueError, InvalidOperation)


@dataclass
class Parsed:
    payments: list[dict] = field(default_factory=list)
    # (row, reason) for rows that could not be read at all
    rejected: list[tuple[object, str]] = field(default_factory=list)
    invalid_cuis: int = 0


def file_day(title: str | None) -> date | None:
    """The day a file is named after: '27 august 2026.xlsx' is 27 August 2026."""
    found = _FILE_DAY.search((title or "").lower())
    if not found or found.group(2) not in _MONTHS:
        return None
    return date(int(found.group(3)), _MONTHS.index(found.group(2)) + 1, int(found.group(1)))


def _text(value: object) -> str | None:
    """A cell as text. A whole number read as 644.0 is written 644."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value if value is not None else "").strip()
    return text or None


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _money(value: object) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _columns(header: list) -> dict[str, int] | None:
    """Where each of our columns is, or None if this row is not the header of a payment
    sheet.
    """
    cleaned = [plain(cell) for cell in header]
    if "UAT" not in cleaned or "ID PROIECT" not in cleaned:
        return None
    found = {}
    for name, start in _COLUMNS.items():
        index = next((i for i, cell in enumerate(cleaned) if cell.startswith(start)), None)
        if index is not None:
            found[name] = index
    return found


def _party(cells: dict, role: str, parsed: Parsed) -> tuple[int | None, str | None]:
    """The builder or the designer: a valid tax ID or none, and the name as published."""
    raw = _text(cells.get(f"{role}_cui"))
    cui = parse_cui(raw) if raw else None
    if raw and cui is None:
        parsed.invalid_cuis += 1
    return cui, mask_cnp(_text(cells.get(f"{role}_text")))


def _payment(cells: dict, network: str, published_on: date | None, parsed: Parsed) -> dict:
    annex = _ANNEX.match(str(cells["annex"]))
    if not annex:
        raise ValueError(f"no request number in {cells['annex']!r}")
    number, day, month, year = (int(part) for part in annex.groups())
    builder_cui, builder_text = _party(cells, "builder", parsed)
    designer_cui, designer_text = _party(cells, "designer", parsed)
    poim = _text(cells.get("poim"))
    return {
        "id": number,
        "registered_on": date(year, month, day),
        "request_no": _text(cells.get("request_no")),
        "requested_on": _day(cells.get("requested_on")),
        "published_on": published_on,
        "network": network,
        "county": plain(cells["county"]),
        "town_hall": _text(cells["town_hall"]),
        "project_id": int(cells["project_id"]),
        "investment": mask_cnp(_text(cells.get("investment")), checked=True),
        "category": _text(cells.get("category")),
        "ministry_contract_no": _text(cells.get("ministry_contract_no")),
        "ministry_contract_date": _day(cells.get("ministry_contract_date")),
        "total_value": _money(cells.get("total_value")),
        "state_budget_value": _money(cells.get("state_budget_value")),
        "amount": Decimal(str(cells["amount"])),
        "state": _text(cells.get("state")),
        "progress": _text(cells.get("progress")),
        "poim": None if "poim" not in cells else poim == "1",
        "builder_cui": builder_cui,
        "builder_text": builder_text,
        "designer_cui": designer_cui,
        "designer_text": designer_text,
        "estimated_end": _day(cells.get("estimated_end")),
    }


def parse_payments(content: bytes, published_on: date | None = None) -> Parsed:
    """Turn one payment file into rows, one per request.

    Sheets without the payment header (pivot tables) are passed over, and so are total
    rows. A request listed twice in a file is one payment: the copies are merged, since
    one sheet can name the builder's tax ID and the other not.
    """
    parsed = Parsed()
    by_id: dict[int, dict] = {}
    for name, rows in workbook_sheets(content):
        columns = None
        for row in rows:
            if columns is None:
                columns = _columns(row)
                continue
            cells = {key: row[index] for key, index in columns.items() if index < len(row)}
            if not _text(cells.get("town_hall")) and not _text(cells.get("annex")):
                continue  # an empty row, or the totals under the table
            try:
                network = GAS if "GAZ" in plain(name) else INFRA
                payment = _payment(cells, network, published_on, parsed)
            except _ERRORS as error:
                parsed.rejected.append((row, repr(error)))
                continue
            earlier = by_id.get(payment["id"], {})
            by_id[payment["id"]] = {
                key: earlier.get(key) if earlier.get(key) is not None else value
                for key, value in payment.items()
            }
    parsed.payments = list(by_id.values())
    return parsed
