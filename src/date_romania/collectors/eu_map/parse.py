"""Reading one edition of the map: a list of counties, each with its projects in
`extras.rows`, their keys as the map writes them (diacritics lost: `OPERAIUNE`).

A project is listed once per fund it draws on (FEDR and FSE+, in PoIDS): its rows are
parts of one project, and their amounts are added. A project in several counties is listed
once, its counties together ('B,IF'), in the edition of 27.10.2026; a second row of the
same fund is rejected, never added, so the amounts stay right if that ever changes.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from date_romania.cui import parse_cui
from date_romania.entities import kind_of
from date_romania.eu_programmes import BY_MAP_NAME
from date_romania.text import plain

PARSER_VERSION = 2

# The amounts of a project, added over its fund rows.
_AMOUNTS = {
    "eu_value": "BUGET_TOTAL_UE",
    "total_value": "VALOARE_TOTAL_PROIECT",
    "paid": "TOTAL_PLI_VALIDATE",
}


@dataclass
class Parsed:
    projects: dict[int, dict] = field(default_factory=dict)
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def _text(value) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", str(value)).strip() or None


def _amount(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    return Decimal(str(value).strip())


def _date(value) -> date | None:
    """'27.10.2023 00:00:00'."""
    text = _text(value)
    return datetime.strptime(text[:10], "%d.%m.%Y").date() if text else None


def _siruta(value) -> int | None:
    """The UAT, when the map names one alone ('1017'); none for several ('1017,1696')."""
    text = _text(value)
    return int(text) if text and text.isdigit() else None


def _project(row: dict, cut_off: date) -> dict:
    programme = BY_MAP_NAME.get(plain(row["PROGRAMUL"]))
    if programme is None:
        raise ValueError(f"programme not known: {row['PROGRAMUL']!r}")
    return {
        "smis": int(row["COD_SMIS"]),
        "programme": programme.code,
        "period": programme.period,
        "title": _text(row.get("TITLU_PROIECT")),
        # The map's tax ID is kept apart from a list's (`map_cui`).
        "beneficiary_cui": None,
        "map_cui": parse_cui(str(row.get("CUI_LIDER") or "")),
        "beneficiary_name": _text(row.get("LIDER")),
        "beneficiary_type": _text(row.get("TIP_ORGANIZAIE")),
        "partners": None,
        "summary": _text(row.get("SCOP_PROIECT")),
        "starts_on": _date(row.get("DATA_NCEPERE_PROIECT")),
        "ends_on": _date(row.get("DATA_FINALIZARE_PROIECT")),
        "cofinancing_rate": None,
        "region": _text(row.get("REGIUNE_PROIECT_IMPLEMENTARE")),
        "county": _text(row.get("JUDEE_PROIECT_IMPLEMENTARE")),
        "locality": _text(row.get("LOCALIZARE_LOCALITATE")),
        "siruta": _siruta(row.get("COD_SIRUTA_LOCALITATE")),
        **{name: _amount(row.get(key)) for name, key in _AMOUNTS.items()},
        "status": _text(row.get("STATUS")),
        "cut_off": cut_off,
    }


def parse(content: bytes, cut_off: date) -> Parsed:
    """The projects of one edition, by SMIS code; `cut_off` is the edition's day."""
    parsed = Parsed()
    funds: set[tuple[int, str | None]] = set()
    for county in json.loads(content):
        for row in (county.get("extras") or {}).get("rows") or ():
            try:
                project = _project(row, cut_off)
            except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
                parsed.rejected.append((row.get("COD_SMIS"), repr(exc)))
                continue
            fund = (project["smis"], _text(row.get("FOND")))
            if fund in funds:
                parsed.rejected.append((row.get("COD_SMIS"), f"fund listed again: {fund[1]!r}"))
                continue
            funds.add(fund)
            held = parsed.projects.get(project["smis"])
            if held is None:
                parsed.projects[project["smis"]] = project
            else:
                # Another fund's part of the same project.
                for name in _AMOUNTS:
                    if project[name] is not None:
                        held[name] = (held[name] or 0) + project[name]
            cui = project["map_cui"]
            if cui is not None:
                parsed.entities.setdefault(
                    cui,
                    (
                        project["beneficiary_name"] or f"CUI {cui}",
                        kind_of(project["beneficiary_type"]),
                    ),
                )
    return parsed
