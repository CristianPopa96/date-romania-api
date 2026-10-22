"""Turning the files of one edition of MIPE's PNRR dashboard into rows."""

import gzip
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from date_romania.cui import parse_cui
from date_romania.dates import BUCHAREST
from date_romania.text import plain

PARSER_VERSION = 1

# What an edition is made of, as `contains.json` names them: `<yyyymmdd>-<endpoint>.json.gz`.
CONTRACTS = "progres_tehnic_proiecte"
PAYMENTS = "plati_pnrr"
MEASURES = "masuri"
# The largest recipients: a short preview with grants and loans apart, and the full list.
TOP = "top_beneficiari"
TOP_DAYS = "persons"
TOTALS = "indicatori_total"
ENDPOINTS = (CONTRACTS, PAYMENTS, MEASURES, TOP, TOP_DAYS, TOTALS)

_ERRORS = (AttributeError, KeyError, TypeError, ValueError, InvalidOperation)

# How the ministries write a natural person's type, compared in `plain()` form.
_NATURAL_PERSON = {"PF", "P F", "PERSOANA FIZICA"}
# Words that make a beneficiary public, or a company, in the ministries' free text.
_PUBLIC = (
    "UAT",
    "INSTITUTI",
    "INVATAMANT",
    "UNIVERSITAT",
    "SPITAL",
    "SANATORIU",
    "AUTORITATE",
    "ADMINISTRATI",
    "MINISTER",
    "DIRECTIE",
    "INSTITUT",
    "GRADINITA",
    "AUTORITATI",
)
_PUBLIC_EXACT = {"DSP", "SAJ", "CJ", "INCD", "IP", "ASSMB", "MS", "MAI", "CNAS", "SRI", "CCD"}
_COMPANY = (
    "IMM",
    "INTREPRINDERE",
    "SOCIETATE",
    "COMPANIE",
    "COOPERATIVA",
    "MEDIC FAMILIE",
)
_COMPANY_EXACT = {
    "SRL",
    "S R L",
    "SA",
    "S A",
    "SC",
    "S C",
    "PFA",
    "P F A",
    "II",
    "I I",
    "I F",
    "RA",
    "R A",
    "CMI",
    "PJ",
    "MICROINTREPRINDERE",
}


@dataclass
class Parsed:
    measures: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    top: list[dict] = field(default_factory=list)
    totals: list[dict] = field(default_factory=list)
    # cui -> (name, kind), for the entity table.
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    rejected: list[tuple[object, str]] = field(default_factory=list)
    # Tax IDs given that fail the checksum: the row is kept, without a CUI.
    invalid_cuis: int = 0


def read(content: bytes) -> object:
    """A file of the dashboard: gzipped JSON, told by its signature."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return json.loads(content)


def _rows(data: object) -> list:
    """The list of a file: the whole file, or its `items` (the ORDS answers)."""
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        raise ValueError(f"no rows in {str(data)[:200]!r}")
    return data


def measure_code(component, measure, submeasure) -> str:
    """'C10.I3', or 'C10.I3.a' for a sub-measure."""
    parts = [str(part).strip() for part in (component, measure, submeasure) if part]
    if len(parts) < 2:
        raise ValueError(f"no measure in {(component, measure, submeasure)!r}")
    return ".".join(parts)


def _money(value) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


def _day(value: str | None) -> date | None:
    """A day as Romania counts it. The files write midnight in Bucharest as UTC
    ('2023-01-25T22:00:00Z' is 26 January); the top 100 writes '2026.09.25'."""
    if not value:
        return None
    if "T" not in value:
        return datetime.strptime(value.replace(".", "-"), "%Y-%m-%d").date()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(BUCHAREST).date()


def _text(value) -> str | None:
    return str(value).strip() or None if value is not None else None


def is_natural_person(beneficiary_type: str | None) -> bool:
    return plain(beneficiary_type) in _NATURAL_PERSON


def kind_of(beneficiary_type: str | None) -> str:
    """The entity kind the ministry's own word suggests: 'authority' only when it is
    clearly public, 'company' when clearly a business, else 'other'."""
    words = plain(beneficiary_type)
    if words in _PUBLIC_EXACT or any(word in words for word in _PUBLIC):
        return "authority"
    if words in _COMPANY_EXACT or any(word in words for word in _COMPANY):
        return "company"
    return "other"


def _cui(parsed: Parsed, value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    cui = parse_cui(str(value))
    parsed.invalid_cuis += cui is None
    return cui


def parse_measures(data: object) -> Parsed:
    parsed = Parsed()
    for item in _rows(data):
        try:
            parsed.measures.append(
                {
                    "code": measure_code(
                        item["componenta_cod"], item["masura_cod"], item.get("submasura_cod")
                    ),
                    "component": str(item["componenta_cod"]).strip(),
                    "measure": str(item["masura_cod"]).strip(),
                    "submeasure": _text(item.get("submasura_cod")),
                    "name": _text(item.get("masura_denumire")),
                    "ministry": _text(item.get("cri_acronim")),
                    "ministry_name": _text(item.get("cri_denumire")),
                    "funding": _text(item.get("sursa_finantare")),
                    "allocated_eur": _money(item.get("alocare_financiare_eur")),
                    # Spelled so in the file.
                    "contracted_eu_ron": _money(item.get("contractare_anhajata_total_fe_ron")),
                    "paid_ron": _money(item.get("valoare_plata_total_fe_ron")),
                    "paid_eur": _money(item.get("valoare_plata_total_fe_eur")),
                }
            )
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    return parsed


def parse_contracts(data: object) -> Parsed:
    """One `pnrr_contract` per `id_angajament`, from its first row, and one line per row."""
    parsed = Parsed()
    contracts: dict[int, dict] = {}
    positions: dict[int, int] = defaultdict(int)
    for item in _rows(data):
        try:
            contract_id = int(item["id_angajament"])
            line = {
                "contract_id": contract_id,
                "measure_code": measure_code(
                    item["cod_componenta"], item["cod_masura"], item.get("cod_submasura")
                ),
                "funding": _text(item.get("sursa_finantare")),
                "total": _money(item.get("valoare_total")),
                "eu": _money(item.get("valoare_fe")),
                "national": _money(item.get("valoare_fpn")),
                "vat": _money(item.get("valoare_tva")),
                "ineligible": _money(item.get("valoare_neeligibil")),
                "status": _text(item.get("stadiu")),
                "ends_on": _day(item.get("data_finalizare")),
                "physical_progress": _money(item.get("progres_fizic")),
                "financial_progress": _money(item.get("progres_financiar")),
            }
            if contract_id not in contracts:
                kind = _text(item.get("tip_beneficiar"))
                natural = is_natural_person(kind)
                cui = None if natural else _cui(parsed, item.get("cui"))
                contracts[contract_id] = {
                    "id": contract_id,
                    "number": _text(item.get("nr_contract")),
                    "title": _text(item.get("titlu_contract")),
                    "beneficiary_cui": cui,
                    "beneficiary_name": _text(item.get("denumire_beneficiar")),
                    "beneficiary_type": kind,
                    "natural_person": natural,
                    "ministry": _text(item.get("cri")),
                    "signed_on": _day(item.get("data_angajament")),
                    "starts_on": _day(item.get("data_inceput")),
                    "impact": _text(item.get("impact")),
                    "county": _text(item.get("judet_implementare")),
                    "locality": _text(item.get("localitate_implementare")),
                }
                if cui is not None:
                    name = contracts[contract_id]["beneficiary_name"] or f"CUI {cui}"
                    parsed.entities.setdefault(cui, (name, kind_of(kind)))
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
            continue
        positions[contract_id] += 1
        parsed.lines.append({**line, "position": positions[contract_id]})
    parsed.contracts = list(contracts.values())
    return parsed


def parse_payments(data: object) -> Parsed:
    """Every payment in the file's order; alike rows are all kept, as published."""
    parsed = Parsed()
    for position, item in enumerate(_rows(data), 1):
        try:
            cui = _cui(parsed, item.get("cui_beneficiar_final"))
            name = _text(item.get("nume_beneficiar"))
            parsed.payments.append(
                {
                    "position": position,
                    "measure_code": measure_code(
                        item["cod_componenta"], item["cod_masura"], item.get("cod_submasura")
                    ),
                    "funding": _text(item.get("sursa_finantare")),
                    "amount": Decimal(str(item["valoare_plata_fe"])),
                    "amount_eur": _money(item.get("valoare_plata_fe_euro")),
                    "paid_on": _day(item.get("data_plata")),
                    "reported_on": _day(item.get("data_raportarii")),
                    "beneficiary_cui": cui,
                    "beneficiary_name": name,
                    "natural_person": cui is None,
                    "county": _text(item.get("judet_beneficiar")),
                    "locality": _text(item.get("localitate_beneficiar")),
                    "caen_division": _text(item.get("cod_diviziune_caen")),
                }
            )
            if cui is not None:
                parsed.entities.setdefault(cui, (name or f"CUI {cui}", "other"))
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    return parsed


def parse_top(top: object, persons: object) -> Parsed:
    """The largest recipients (`persons`: about a hundred, with what each received and when
    last); the split into grants and loans only for the few the dashboard's preview
    (`top_beneficiari`) gives it."""
    parsed = Parsed()
    split: dict[int, dict] = {}
    for item in _rows(top):
        try:
            split[int(item["cui"])] = item
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    for item in _rows(persons):
        try:
            cui = int(item["tax identification number"])
            parts = split.get(cui, {})
            parsed.top.append(
                {
                    "cui": cui,
                    "name": _text(item.get("full legal name")),
                    "grant": _money(parts.get("nerambursabil")),
                    "loan": _money(parts.get("rambursabil")),
                    "total": _money(item.get("received amount in lei")),
                    "total_eur": _money(parts.get("total_euro")),
                    "last_received_on": _day(item.get("last date funding received")),
                }
            )
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    return parsed


def parse_totals(data: object, day: date) -> Parsed:
    parsed = Parsed()
    for item in _rows(data)[:1]:
        try:
            parsed.totals.append(
                {
                    "day": day,
                    "allocated_eur": _money(item.get("alocat_eur")),
                    "paid_eur": _money(item.get("platit_eur")),
                    "received_eur": _money(item.get("incasat_eur")),
                    "prefinancing_eur": _money(item.get("prefinantare_eur")),
                    "suspended_eur": _money(item.get("suspendat_eur")),
                    "revoked_eur": _money(item.get("revocat_eur")),
                    "beneficiaries_contracted": item.get("nr_beneficiari_contracte"),
                    "beneficiaries_paid": item.get("nr_beneficiari_plati"),
                    "contracts": item.get("nr_proiecte"),
                }
            )
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    return parsed


def tie(payments: list[dict], contracts: list[dict], lines: list[dict]) -> None:
    """Give each payment the number of contracts its beneficiary has on its measure, and
    the contract when there is exactly one. A payment never names its contract."""
    beneficiary = {each["id"]: each["beneficiary_cui"] for each in contracts}
    on_measure: dict[tuple[int, str], set[int]] = defaultdict(set)
    for line in lines:
        cui = beneficiary.get(line["contract_id"])
        if cui is not None:
            on_measure[(cui, line["measure_code"])].add(line["contract_id"])
    for payment in payments:
        found = on_measure.get((payment["beneficiary_cui"], payment["measure_code"]), set())
        payment["contracts_on_measure"] = len(found)
        payment["contract_id"] = next(iter(found)) if len(found) == 1 else None
