"""Reading the yearly budget workbook and the population workbooks."""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from date_romania.collectors.sheets import workbook_sheets
from date_romania.text import plain

PARSER_VERSION = 1

BUDGET, POPULATION = "budget", "population"
REVENUE, SPENDING, CHAPTER = "revenue", "spending", "chapter"


@dataclass
class Parsed:
    rows: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def file_kind(title: str | None) -> tuple[str, int] | None:
    """What a file of the dataset holds, from the publisher's title: ('budget', 2024)
    for 'Situația veniturilor și cheltuielilor - 2024', ('population', 2024) for
    'Populația definitivă a României la 1 ianuarie 2024'; None for anything else."""
    text = plain(title)
    year = re.search(r"\b(20\d\d)\b", text)
    if not year:
        return None
    if "VENITURILOR" in text and "CHELTUIELILOR" in text:
        return BUDGET, int(year.group(1))
    if text.startswith("POPULATIA"):
        return POPULATION, int(year.group(1))
    return None


def _number(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _int(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number == number.to_integral() else None


def _title(*parts: object) -> str:
    """A column's title from its header rows, without the sums and the 'of which'."""
    text = " ".join(" ".join(str(part).split()) for part in parts if str(part).strip())
    text = re.sub(r"\(col\.[^)]*\)", "", text)
    text = re.sub(r"d ?i ?n +c ?a ?r ?e ?:", "", text)
    text = re.sub(r"pe (titluri|parti si capitole) de cheltuieli", "", text, flags=re.I)
    return " ".join(text.split())


def _code(value: object) -> str:
    """A budget code as printed; a code typed as a number ('20.0') loses its '.0'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _columns(header: list[list]) -> list[tuple[int, int, str, str | None, str]]:
    """(position, column number, section, code, title) of every figure column.

    The column number is what the sheets agree on: codes and titles are typed by hand on
    each county's sheet, and sheets 2 to 42 shift the codes of the first two columns.

    `header` holds the sheet's rows from the titles down to the row of column numbers;
    the codes are in the row above the numbers. Revenue comes first; the spending total
    opens the titles, and a second spending total opens the chapters.
    """
    numbers, codes = header[-1], header[-2]
    found, section, totals = [], REVENUE, 0
    for at, value in enumerate(numbers):
        number = _int(value)
        if number is None:
            continue
        title = _title(*(row[at] if at < len(row) else "" for row in header[:-2]))
        if "CHELTUIELI TOTALE" in plain(title):
            totals += 1
            section = SPENDING
        elif "CAPITOLE" in plain(" ".join(str(row[at]) for row in header[:-2] if at < len(row))):
            section = CHAPTER
        code = _code(codes[at] if at < len(codes) else "")
        found.append((at, number, section, code or None, title or code))
    return found


def parse_budget(content: bytes, year: int) -> Parsed:
    """The figures of every UAT (by SIRUTA) and county council (by ('county', its
    county's name)) in the county sheets `1` to `42`."""
    parsed = Parsed()
    for name, rows in workbook_sheets(content):
        if not name.strip().isdigit():
            continue
        rows = list(rows)
        starts = [i for i, row in enumerate(rows) if plain(row[0]).startswith("DENUMIREA")]
        ends = [i for i, row in enumerate(rows) if plain(row[0]) == "A"]
        if not starts or not ends:
            parsed.rejected.append((name, "sheet without its header"))
            continue
        columns = _columns(rows[starts[0] : ends[0] + 1])
        county = next(
            (
                plain(cell).removeprefix("JUDETUL").strip()
                for row in rows[: starts[0]]
                for cell in row
                if plain(cell).startswith("JUDETUL")
            ),
            None,
        )
        for row in rows[ends[0] + 1 :]:
            label = plain(row[0])
            if label.startswith("A CONSILIUL"):
                key: object = ("county", county)
            else:
                siruta = _int(row[1]) if len(row) > 1 else None
                if siruta is None:
                    continue
                key = siruta
            figures = [
                (column, _number(row[column[0]]) if column[0] < len(row) else None)
                for column in columns
            ]
            if not any(amount for _, amount in figures):
                continue
            for (_, number, section, code, title), amount in figures:
                if amount is None:
                    continue
                parsed.rows.append(
                    {
                        "place": key,
                        "year": year,
                        "column_no": number,
                        "section": section,
                        "code": code,
                        "title": title,
                        "amount": amount,
                    }
                )
    return parsed


_PLACE = re.compile(r"^\s*(\d+)\s+\S")


def _uat_rows(rows: list[list]) -> list[tuple[object, object]]:
    """(place, people) for each UAT row of a sheet, in either layout: a 'siruta' column
    and a 'total' or 'populatia...' one (2021 to 2023), or '1017 MUNICIPIUL ALBA IULIA'
    with the number in the last cell (2024). A place is its SIRUTA code, or ('uat',
    county, name) where the file gives only the name."""
    for at, row in enumerate(rows):
        header = [plain(cell) for cell in row]
        counts = [i for i, name in enumerate(header) if name == "TOTAL" or "POPULATIA" in name]
        if "SIRUTA" in header and counts:
            code, people = header.index("SIRUTA"), counts[0]
            return [
                (siruta, row[people] if people < len(row) else None)
                for row in rows[at + 1 :]
                if (siruta := _int(row[code] if code < len(row) else None))
            ]
    found: list[tuple[object, object]] = []
    for row in rows:
        cells = [cell for cell in row if str(cell).strip()]
        if len(cells) < 2:
            continue
        match = next(filter(None, (_PLACE.match(str(cell)) for cell in cells)), None)
        first = plain(cells[0])
        if match:
            found.append((int(match.group(1)), cells[-1]))
        # Bucharest's sheet names its sectors. Its total is theirs added up, and is left
        # out, as the other years leave it.
        elif first.startswith("SECTORUL"):
            found.append((("uat", "BUCURESTI", first), cells[-1]))
    return found


def parse_population(content: bytes, year: int) -> Parsed:
    """People per UAT at 1 January of `year`, from every sheet that lists UATs."""
    parsed = Parsed()
    on = date(year, 1, 1)
    for _, rows in workbook_sheets(content):
        for siruta, value in _uat_rows(list(rows)):
            people = _int(value)
            if people is None:
                parsed.rejected.append(((siruta, value), "no number of people"))
                continue
            parsed.rows.append({"place": siruta, "on": on, "people": people})
    return parsed
