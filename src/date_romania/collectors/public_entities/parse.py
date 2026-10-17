"""Reading the list of public entities: one row per entity."""

from dataclasses import dataclass, field

from date_romania.collectors.sheets import workbook_sheets
from date_romania.cui import parse_cui
from date_romania.text import plain

PARSER_VERSION = 1

# Headers in `plain` form; the two funder columns end in '(1)' and '(2)'.
_CUI = "CIF ENTITATE PUBLICA"
_NAME = "DENUMIRE ENTITATE PUBLICA"
_COUNTY = "JUDET"
_UAT = "DENUMIRE UAT PE RAZA CAREIA ISI DESFASOARA ACTIVITATEA"
_FUNDERS = (
    ("CIF ORDONATOR PRINCIPAL DE CREDITE 1", "DENUMIRE ORDONATOR PRINCIPAL DE CREDITE 1"),
    ("CIF ORDONATOR PRINCIPAL DE CREDITE 2", "DENUMIRE ORDONATOR PRINCIPAL DE CREDITE 2"),
)


@dataclass
class Parsed:
    entities: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def _text(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def _cui(value: object) -> int | None:
    text = _text(value).removesuffix(".0")
    return parse_cui(text) if text else None


def parse_entities(content: bytes) -> Parsed:
    """The entities of the first sheet. A row with no valid tax ID is rejected; a funder
    whose tax ID is not valid is left out of its row."""
    parsed = Parsed()
    _, rows = next(workbook_sheets(content))
    rows = iter(rows)
    header = [plain(cell) for cell in next(rows, [])]
    wanted = [_CUI, _NAME, _COUNTY, _UAT, *(name for pair in _FUNDERS for name in pair)]
    missing = [name for name in wanted if name not in header]
    if missing:
        raise ValueError(f"list of public entities without {', '.join(missing)}")
    at = {name: header.index(name) for name in wanted}
    seen: set[int] = set()
    for row in rows:
        if not any(_text(cell) for cell in row):
            continue

        def cell(name: str, row: list = row) -> object:
            return row[at[name]] if at[name] < len(row) else None

        cui = _cui(cell(_CUI))
        if cui is None:
            parsed.rejected.append((row, "no valid tax ID"))
            continue
        if cui in seen:
            parsed.rejected.append((row, "tax ID listed twice"))
            continue
        seen.add(cui)
        funders = [(_cui(cell(code)), _text(cell(name)) or None) for code, name in _FUNDERS]
        parsed.entities.append(
            {
                "cui": cui,
                "name": _text(cell(_NAME)),
                "county": _text(cell(_COUNTY)),
                "uat": _text(cell(_UAT)),
                "funder_cui": funders[0][0],
                "funder_name": funders[0][1] if funders[0][0] else None,
                "second_funder_cui": funders[1][0],
                "second_funder_name": funders[1][1] if funders[1][0] else None,
            }
        )
    return parsed
