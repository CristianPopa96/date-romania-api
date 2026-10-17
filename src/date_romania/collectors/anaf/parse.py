"""Reading ANAF's answer to one batch of tax IDs."""

import json
from dataclasses import dataclass, field
from datetime import date

PARSER_VERSION = 1


@dataclass
class Parsed:
    records: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def _text(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def _caen(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def is_answer(content: bytes) -> bool:
    """True for ANAF's JSON answer: an object with the lists `found` and `notFound`.
    ANAF can answer HTTP 200 with an HTML page instead."""
    try:
        answer = json.loads(content)
    except ValueError:
        return False
    return (
        isinstance(answer, dict)
        and isinstance(answer.get("found"), list)
        and isinstance(answer.get("notFound"), list)
    )


def parse_answer(content: bytes, asked_on: date) -> Parsed:
    """A record for every tax ID of the answer, found or not. Only the county and the
    locality of the registered office are read: never the street."""
    parsed = Parsed()
    answer = json.loads(content)
    for item in answer.get("found") or []:
        general = item.get("date_generale") or {}
        office = item.get("adresa_sediu_social") or {}
        try:
            cui = int(general["cui"])
        except (KeyError, TypeError, ValueError):
            parsed.rejected.append((general, "no tax ID"))
            continue
        parsed.records.append(
            {
                "cui": cui,
                "asked_on": asked_on,
                "found": True,
                "name": _text(general.get("denumire")),
                "county": _text(office.get("sdenumire_Judet")),
                "county_code": _text(office.get("scod_JudetAuto")),
                "locality": _text(office.get("sdenumire_Localitate")),
                "caen": _caen(general.get("cod_CAEN")),
                "registration": _text(general.get("stare_inregistrare")),
                "inactive": (item.get("stare_inactiv") or {}).get("statusInactivi"),
                "vat_payer": (item.get("inregistrare_scop_Tva") or {}).get("scpTVA"),
            }
        )
    for cui in answer.get("notFound") or []:
        try:
            parsed.records.append(
                {"cui": int(cui), "asked_on": asked_on, "found": False}
                | dict.fromkeys(
                    (
                        "name",
                        "county",
                        "county_code",
                        "locality",
                        "caen",
                        "registration",
                        "inactive",
                        "vat_payer",
                    )
                )
            )
        except (TypeError, ValueError):
            parsed.rejected.append((cui, "not a tax ID"))
    return parsed
