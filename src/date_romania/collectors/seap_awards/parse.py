"""Turning SEAP's notice list and contract list responses into rows."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from date_romania.cui import parse_cui
from date_romania.personal_id import mask_cnp

PARSER_VERSION = 1

# The list names a buyer as 'CUI - NAME', sometimes with RO in front of the number.
_BUYER = re.compile(r"\s*(?:RO)?\s*(\d{2,10})\s*-\s*(.*)", re.IGNORECASE | re.DOTALL)
# A Romanian tax ID as winners carry it: '15148952', 'RO 15425816', 'RO17789473'.
_TAX_ID = re.compile(r"\s*(?:RO)?\s*(\d{2,10})\s*", re.IGNORECASE)

_ERRORS = (AttributeError, KeyError, TypeError, ValueError, InvalidOperation)


def split_buyer(text: str | None) -> tuple[int | None, str | None]:
    """Split '4364349 - ADMINISTRATIA ...' or 'RO 2684940 - APA CANAL SIBIU SA'."""
    text = (text or "").strip()
    match = _BUYER.fullmatch(text)
    if not match:
        return None, text or None
    return parse_cui(match.group(1)), match.group(2).strip() or None


def winner_cui(fiscal_number: str | None, country_code: str | None) -> int | None:
    """The CUI of a winner, or None for a foreign company or a number that is not a CUI.

    A foreign tax number made only of digits could pass the checksum by chance, so a
    winner with an address outside Romania never gets a CUI.
    """
    if country_code not in (None, "", "RO"):
        return None
    match = _TAX_ID.fullmatch(fiscal_number or "")
    return parse_cui(match.group(1)) if match else None


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _money(value: float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _item(value: dict | None) -> tuple[int | None, str | None]:
    """SEAP's {id, text} pair for a classified value."""
    value = value or {}
    return value.get("id"), value.get("text")


@dataclass
class Parsed:
    notices: list[dict] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)
    winners: list[dict] = field(default_factory=list)
    # cui -> (name, kind)
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    # (item, reason) for rows that could not be read at all
    rejected: list[tuple[object, str]] = field(default_factory=list)
    invalid_cuis: int = 0


def parse_notices(data: dict) -> Parsed:
    """Turn one list response into notice rows; a later copy of a notice replaces an earlier."""
    parsed = Parsed()
    by_id: dict[int, dict] = {}
    for item in data.get("items", []):
        try:
            buyer_cui, buyer_name = split_buyer(item.get("contractingAuthorityNameAndFN"))
            cpv_code, _, cpv_name = (item.get("cpvCodeAndName") or "").partition(" - ")
            contract_type_id, contract_type = _item(item.get("sysAcquisitionContractType"))
            procedure_type_id, procedure_type = _item(item.get("sysProcedureType"))
            procedure_state_id, procedure_state = _item(item.get("sysProcedureState"))
            assignment_type_id, assignment_type = _item(item.get("sysContractAssigmentType"))
            row = {
                "id": int(item["caNoticeId"]),
                "notice_no": item.get("noticeNo"),
                "notice_type_id": item.get("sysNoticeTypeId"),
                "procedure_id": item.get("procedureId"),
                "title": mask_cnp(item.get("contractTitle"), checked=True),
                "buyer_cui": buyer_cui,
                "buyer_text": mask_cnp(item.get("contractingAuthorityNameAndFN")),
                "cpv_code": cpv_code.strip() or None,
                "cpv_name": cpv_name.strip() or None,
                "contract_type_id": contract_type_id,
                "contract_type": contract_type,
                "procedure_type_id": procedure_type_id,
                "procedure_type": procedure_type,
                "procedure_state_id": procedure_state_id,
                "procedure_state": procedure_state,
                "assignment_type_id": assignment_type_id,
                "assignment_type": assignment_type,
                "value_ron": _money(item.get("ronContractValue")),
                "is_utility": item.get("isUtility"),
                "has_subsequent_contracts": item.get("hasSubsequentContracts"),
                "published_at": _when(item.get("noticeStateDate")),
            }
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
            continue
        by_id[row["id"]] = row
        parsed.invalid_cuis += buyer_cui is None
        if buyer_cui is not None:
            parsed.entities[buyer_cui] = (buyer_name or f"CUI {buyer_cui}", "authority")
    parsed.notices = list(by_id.values())
    return parsed


def parse_contracts(data: dict) -> Parsed:
    """Turn one contracts response into contract rows and one row per winner."""
    parsed = Parsed()
    by_id: dict[int, tuple[dict, list[dict]]] = {}
    for item in data.get("items", []):
        try:
            row = {
                "id": int(item["caNoticeContractId"]),
                "notice_id": int(item["caNoticeId"]),
                "contract_no": mask_cnp(item.get("contractNo"), checked=True),
                "contract_date": _when(item.get("contractDate")),
                "title": mask_cnp(item.get("contractTitle"), checked=True),
                "kind": item.get("contractType"),
                "lots": item.get("lotsNoCaption") or None,
                "value": _money(item.get("contractValue")),
                "currency": (item.get("currency") or {}).get("text"),
                "value_ron": _money(item.get("defaultCurrencyContractValue")),
                "min_offer_ron": _money(item.get("defaultCurrencyContractValueMinOffer")),
                "max_offer_ron": _money(item.get("defaultCurrencyContractValueMaxOffer")),
                "modified_count": item.get("modifiedCount"),
            }
            winners, entities = [], {}
            for position, winner in enumerate(item.get("winners") or []):
                country = (winner.get("address") or {}).get("countryItem") or {}
                cui = winner_cui(winner.get("fiscalNumber"), country.get("localeKey"))
                name = (winner.get("name") or "").strip()
                text = f"{winner.get('fiscalNumber') or ''} {name}".strip()
                winners.append(
                    {
                        "contract_id": row["id"],
                        "position": position,
                        "supplier_cui": cui,
                        "supplier_text": mask_cnp(text) or None,
                        "country": country.get("text"),
                    }
                )
                if cui is not None:
                    entities[cui] = (name or f"CUI {cui}", "company")
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
            continue
        by_id[row["id"]] = (row, winners)
        for cui, entity in entities.items():
            parsed.entities.setdefault(cui, entity)
    for row, winners in by_id.values():
        parsed.contracts.append(row)
        parsed.winners.extend(winners)
        parsed.invalid_cuis += sum(winner["supplier_cui"] is None for winner in winners)
    return parsed
