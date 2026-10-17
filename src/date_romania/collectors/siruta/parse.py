"""Reading a SIRUTA CSV: one row per place."""

from dataclasses import dataclass, field

from date_romania import places
from date_romania.collectors.sheets import csv_rows
from date_romania.text import plain

PARSER_VERSION = 1

# INS's type of place (`TIP`), from the legend published with the file.
_KINDS = {
    "40": places.COUNTY,
    "1": places.MUNICIPALITY,  # county seat, and Bucharest
    "4": places.MUNICIPALITY,
    "2": places.TOWN,
    "5": places.TOWN,  # county seat
    "3": places.COMMUNE,
    "6": places.SECTOR,
}
_COUNTRY = 1  # `SIRSUP` of a county
_COLUMNS = ("SIRUTA", "DENLOC", "JUD", "SIRSUP", "TIP", "NIV", "MED")


@dataclass
class Parsed:
    places: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def _kind(tip: str, level: str) -> str:
    # Bucharest is level 2 with the type of a component locality (9).
    if level == "2" and tip == "9":
        return places.MUNICIPALITY
    return _KINDS.get(tip, places.VILLAGE)


def parse_places(content: bytes) -> Parsed:
    """Every place of the file, counties first, then UATs, then villages, so a place
    comes after the one it belongs to."""
    parsed = Parsed()
    rows = csv_rows(content)
    header = [plain(name) for name in next(rows, [])]
    missing = [name for name in _COLUMNS if name not in header]
    if missing:
        raise ValueError(f"SIRUTA file without {', '.join(missing)}")
    at = {name: header.index(name) for name in _COLUMNS}
    read = []
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue
        try:
            value = {name: row[at[name]].strip() for name in _COLUMNS}
            read.append({**value, "code": int(value["SIRUTA"]), "up": int(value["SIRSUP"])})
        except (IndexError, ValueError):
            parsed.rejected.append((row, "no SIRUTA code"))
    counties = {row["JUD"]: row["code"] for row in read if row["TIP"] == "40"}
    for row in read:
        county = counties.get(row["JUD"])
        if county is None:
            parsed.rejected.append((row, f"county {row['JUD']} not in the file"))
            continue
        parsed.places.append(
            {
                "siruta": row["code"],
                "name": row["DENLOC"],
                "kind": _kind(row["TIP"], row["NIV"]),
                "parent": None if row["up"] == _COUNTRY else row["up"],
                "county": county,
                "urban": row["MED"] == "1",
                "level": int(row["NIV"] or 9),
            }
        )
    parsed.places.sort(key=lambda place: (place["level"], place["siruta"]))
    for place in parsed.places:
        del place["level"]
    return parsed
