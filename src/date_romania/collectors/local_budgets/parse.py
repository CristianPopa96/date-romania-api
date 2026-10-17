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


def _number_row(rows: list[list]) -> int | None:
    """Where the row of column numbers is: the first row that counts 1, 2, 3."""
    for at, row in enumerate(rows):
        numbers = [_int(cell) for cell in row]
        if [n for n in numbers if n][:3] == [1, 2, 3]:
            return at
    return None


def _columns(
    header: list[list], codes: dict[int, str]
) -> list[tuple[int, int, str, str | None, str]]:
    """(position, column number, section, code, title) of every figure column.

    `header` holds the sheet's rows from the titles down to the row of column numbers.
    The column number is what the sheets agree on: codes and titles are typed by hand on
    each county's sheet, and sheets 2 to 42 shift the codes of the first two columns, so
    a code is taken from the country's sheet (`codes`) when it has one. Revenue comes
    first; the spending total opens the titles, and the chapters follow.
    """
    numbers, printed = header[-1], header[-2]
    found, section = [], REVENUE
    for at, value in enumerate(numbers):
        number = _int(value)
        if number is None:
            continue
        above = [row[at] if at < len(row) else "" for row in header[:-2]]
        title = _title(*above)
        if "CHELTUIELI TOTALE" in plain(title):
            section = SPENDING
        elif "CAPITOLE" in plain(" ".join(str(cell) for cell in above)):
            section = CHAPTER
        code = codes.get(number) or _code(printed[at] if at < len(printed) else "")
        found.append((at, number, section, code or None, title or code))
    return found


def _country_codes(rows: list[list]) -> dict[int, str]:
    """Column number -> budget code, from the country's sheet."""
    at = _number_row(rows)
    if not at:
        return {}
    numbers, printed = rows[at], rows[at - 1]
    return {
        number: code
        for i, value in enumerate(numbers)
        if (number := _int(value)) and i < len(printed) and (code := _code(printed[i]))
    }


def _heading_problem(rows: list[list], year: int) -> str | None:
    """Why a sheet's heading does not hold one year in lei, or None. A sheet must name
    the period 31.12 of `year` (a quarter would overwrite the year's figures), and
    must not name a unit other than lei (a year in thousands would be stored a
    thousand times too small). Suceava's sheet names no unit; the file's others do."""
    cells = [plain(cell) for row in rows for cell in row if str(cell).strip()]
    periods = [cell for cell in cells if cell.startswith("PERIOADA")]
    if periods != [f"PERIOADA 31 12 {year}"]:
        return f"period {periods or 'not named'}, not 31.12.{year}"
    units = [cell for cell in cells if cell.endswith("LEI") and len(cell) < 12]
    if any(unit != "LEI" for unit in units):
        return f"unit {units}, not lei"
    return None


def parse_budget(content: bytes, year: int) -> Parsed:
    """The figures of every UAT (by SIRUTA) and county council (by ('county', its
    county's name)) in the county sheets `1` to `42`. A sheet whose heading is not the
    whole year in lei is rejected whole; a cell that is not a number is rejected alone.
    """
    parsed = Parsed()
    sheets = [(name, list(rows)) for name, rows in workbook_sheets(content)]
    cells = [plain(cell) for _, rows in sheets for row in rows[:12] for cell in row]
    if "LEI" not in cells:
        raise ValueError("budget file that never names its unit")
    codes = next((_country_codes(rows) for name, rows in sheets if "TARA" in plain(name)), {})
    for name, rows in sheets:
        if not name.strip().isdigit():
            continue
        end = _number_row(rows)
        starts = [i for i, row in enumerate(rows) if plain(row[0]).startswith("DENUMIREA")]
        if end is None or not starts:
            parsed.rejected.append((name, "sheet without its header"))
            continue
        problem = _heading_problem(rows[: starts[0]], year)
        if problem:
            parsed.rejected.append((name, problem))
            continue
        columns = _columns(rows[starts[0] : end + 1], codes)
        county = next(
            (
                plain(cell).removeprefix("JUDETUL").strip()
                for row in rows[: starts[0]]
                for cell in row
                if plain(cell).startswith("JUDETUL")
            ),
            None,
        )
        for row in rows[end + 1 :]:
            _read_row(parsed, row, columns, county, year)
    return parsed


def _read_row(parsed: Parsed, row: list, columns: list, county: str | None, year: int) -> None:
    label = plain(row[0])
    if label.startswith("A CONSILIUL"):
        key: object = ("county", county)
    else:
        siruta = _int(row[1]) if len(row) > 1 else None
        if siruta is None:
            # Totals and the empty numbered rows that pad each block have no name.
            if _int(row[0]) and len(row) > 2 and str(row[2]).strip():
                parsed.rejected.append((row[:3], "UAT without its SIRUTA code"))
            return
        key = siruta
    figures = []
    for at, number, section, code, title in columns:
        cell = row[at] if at < len(row) else None
        amount = _number(cell)
        if amount is None and str(cell or "").strip():
            parsed.rejected.append(((key, number, cell), "figure that is not a number"))
        figures.append((number, section, code, title, amount))
    if not any(amount for *_, amount in figures):
        return
    for number, section, code, title, amount in figures:
        if amount is not None:
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
