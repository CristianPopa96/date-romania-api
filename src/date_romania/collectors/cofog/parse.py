"""Reading Eurostat's JSON-stat answer for `gov_10a_exp` into one row per year, sector and
COFOG code."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import product

PARSER_VERSION = 1

TABLE = "gov_10a_exp"
# All of public administration, then central, local and social security.
SECTORS = ("S13", "S1311", "S1313", "S1314")
FIRST_YEAR = 2015
URL = (
    f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{TABLE}"
    "?format=JSON&lang=EN&geo=RO&unit=MIO_NAC&na_item=TE"
    + "".join(f"&sector={sector}" for sector in SECTORS)
    + f"&sinceTimePeriod={FIRST_YEAR}"
)


class CofogError(ValueError):
    pass


@dataclass
class Parsed:
    rows: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)
    updated_at: datetime | None = None


def _categories(dataset: dict, dimension: str) -> list[tuple[str, str]]:
    """The codes of one dimension in their index order, with their labels."""
    category = dataset["dimension"][dimension]["category"]
    index = category["index"]
    codes = sorted(index, key=index.get) if isinstance(index, dict) else list(index)
    labels = category.get("label") or {}
    return [(code, labels.get(code, code)) for code in codes]


def parse(content: bytes) -> Parsed:
    """Every value of the answer. JSON-stat keeps the values in one flat list, by the
    position of each code in the dimensions named by `id`, the last one moving fastest; a
    value Eurostat does not have is left out of the list (and so of the rows)."""
    try:
        dataset = json.loads(content)
        ids, sizes, values = dataset["id"], dataset["size"], dataset["value"]
    except (ValueError, KeyError, TypeError) as exc:
        raise CofogError(f"not a JSON-stat answer: {content[:200]!r}") from exc
    for needed in ("sector", "cofog99", "time"):
        if needed not in ids:
            raise CofogError(f"the answer has no {needed} dimension: {ids}")
    for dimension, size in zip(ids, sizes, strict=True):
        if dimension not in ("sector", "cofog99", "time") and size != 1:
            raise CofogError(f"{dimension} has {size} values, expected one")
    parsed = Parsed(updated_at=datetime.fromisoformat(dataset["updated"]))
    axes = [_categories(dataset, dimension) for dimension in ids]
    if isinstance(values, list):
        values = {str(i): value for i, value in enumerate(values) if value is not None}
    for position, coordinates in enumerate(product(*axes)):
        value = values.get(str(position))
        if value is None:
            continue
        named = dict(zip(ids, coordinates, strict=True))
        sector, (cofog, label), year = named["sector"][0], named["cofog99"], named["time"][0]
        row = {"year": year, "sector": sector, "cofog": cofog, "value": value}
        try:
            amount = Decimal(str(value))
            year_no = int(year)
        except (ArithmeticError, ValueError):
            parsed.rejected.append((row, "not a number"))
            continue
        parsed.rows.append(
            {
                "year": year_no,
                "sector": sector,
                "cofog": cofog,
                "label": label,
                "amount": amount,
                "updated_at": parsed.updated_at,
            }
        )
    return parsed
