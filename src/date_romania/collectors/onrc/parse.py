"""Reading one edition of the trade register, line by line: the companies file (700 MB), the
file of their states, and the list that names each state.

The files are UTF-8 with a byte-order mark, fields separated by '^', never quoted. A tax
ID can be on several rows: a company that moved to another county was registered again
there, and its old registration is struck off ('radiată'). The loader keeps one row per
tax ID.

Natural persons acting commercially (PF, PFA, II, IF, AF) are listed with their home
address: their rows are skipped unread, and a row the parser cannot read is logged by its
registration number alone, never its name.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from date_romania.cui import parse_cui
from date_romania.eu_links import name_key
from date_romania.places import PlaceIndex

PARSER_VERSION = 1

# The legal persons kept, by `FORMA_JURIDICA`. Any other form is rejected, so a new form of
# natural person is never read by mistake. 'N/A' and 'ALT' are branches of foreign companies.
LEGAL_FORMS = frozenset(
    {
        "SRL",
        "SA",
        "SNC",
        "SCS",
        "SCA",
        "SE",
        "SCE",
        "RA",
        "INCD",
        "GIE",
        "GEIE",
        "CA",
        "SC",
        "OC",
        "OCR",
        "OCC",
        "OCM",
        *(f"OC{n}" for n in range(1, 8)),
        "N/A",
        "ALT",
    }
)
# Natural persons; the empty form is an older sole trader.
PERSONS = frozenset({"PF", "PFA", "II", "IF", "AF", ""})
# The state 'radiată': struck off the register.
DELETED = 1084

_SEPARATOR = "^"


@dataclass
class Read:
    """What a file gave: its rows are yielded as they are read, the rest is counted here."""

    rejected: list[tuple[object, str]] = field(default_factory=list)
    persons: int = 0


def _lines(path: Path) -> Iterator[list[str]]:
    """The rows of a file, its header first."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        for line in file:
            yield line.rstrip("\r\n").split(_SEPARATOR)


def _header(rows: Iterator[list[str]], needed: tuple[str, ...]) -> dict[str, int]:
    header = next(rows, [])
    columns = {name.strip(): n for n, name in enumerate(header)}
    missing = [name for name in needed if name not in columns]
    if missing:
        raise ValueError(f"columns not found: {missing}; header: {header[:30]}")
    return columns


def _date(text: str) -> date | None:
    """'14/03/1991', or with the time for newer ones: '14/08/2026 09:23:04'."""
    text = text.strip()[:10]
    return datetime.strptime(text, "%d/%m/%Y").date() if text else None


_SPACES = re.compile(r"\s+")


def _text(value: str) -> str | None:
    return _SPACES.sub(" ", value).strip() or None


_COMPANY_COLUMNS = (
    "DENUMIRE",
    "CUI",
    "COD_INMATRICULARE",
    "DATA_INMATRICULARE",
    "FORMA_JURIDICA",
    "ADR_JUDET",
    "ADR_LOCALITATE",
)


def companies(path: Path, index: PlaceIndex, read: Read) -> Iterator[tuple]:
    """The legal persons of `OD_FIRME.CSV` with a valid tax ID, as (cui, name, name_key,
    legal_form, registration, registered_on, county, siruta)."""
    rows = _lines(path)
    column = _header(rows, _COMPANY_COLUMNS)
    width = len(column)
    places: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for row in rows:
        if len(row) != width:
            # Its fields cannot be told apart, so not even its registration is logged: the
            # row may be a natural person's.
            read.rejected.append((None, f"{len(row)} fields, not {width}"))
            continue
        form = row[column["FORMA_JURIDICA"]].strip()
        if form in PERSONS:
            read.persons += 1
            continue
        registration = row[column["COD_INMATRICULARE"]].strip()
        if form not in LEGAL_FORMS:
            read.rejected.append((registration, f"legal form not known: {form!r}"))
            continue
        written = row[column["CUI"]].strip()
        if written in ("", "0"):
            # Old companies struck off before tax IDs were kept: nothing to tie them by.
            continue
        cui = parse_cui(written)
        if cui is None:
            read.rejected.append((registration, f"tax ID fails its check: {written!r}"))
            continue
        name = _text(row[column["DENUMIRE"]])
        if name is None:
            read.rejected.append((registration, "no name"))
            continue
        try:
            registered_on = _date(row[column["DATA_INMATRICULARE"]])
        except ValueError:
            read.rejected.append((registration, "registration date not read"))
            continue
        where = (row[column["ADR_JUDET"]], row[column["ADR_LOCALITATE"]])
        if where not in places:
            places[where] = (index.county(where[0]), index.uat(*where))
        county, siruta = places[where]
        yield (
            cui,
            name,
            name_key(name),
            form,
            registration,
            registered_on,
            county,
            siruta,
        )


def states(path: Path, read: Read) -> Iterator[tuple[str, int]]:
    """The rows of `OD_STARE_FIRMA.CSV`, as (registration, state code). A registration can
    have several states ('funcțiune' and an expired office)."""
    rows = _lines(path)
    column = _header(rows, ("COD_INMATRICULARE", "COD"))
    for row in rows:
        try:
            yield row[column["COD_INMATRICULARE"]].strip(), int(row[column["COD"]])
        except (IndexError, ValueError):
            read.rejected.append((row[0] if row else None, "state not read"))


def state_names(path: Path, read: Read) -> dict[int, str]:
    """`N_STARE_FIRMA.CSV`: each state's name by its code ('1084' 'radiată')."""
    rows = _lines(path)
    column = _header(rows, ("COD", "DENUMIRE"))
    names = {}
    for row in rows:
        try:
            names[int(row[column["COD"]])] = row[column["DENUMIRE"]].strip()
        except (IndexError, ValueError):
            read.rejected.append((row, "state name not read"))
    return names
