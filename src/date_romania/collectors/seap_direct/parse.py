"""Turning one SEAP list response into rows."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from date_romania.collectors.seap_direct.slices import STATES_WITHOUT_CA_DEADLINE
from date_romania.cui import parse_cui
from date_romania.personal_id import mask_cnp

PARSER_VERSION = 2

_PARTY = re.compile(r"\s*(?:RO?)?\s*(\d{2,10})\s+(.*)", re.IGNORECASE | re.DOTALL)


def split_party(text: str | None) -> tuple[int | None, str | None]:
    """Split SEAP's 'CUI NAME' text, e.g. 'RO 8574866 ALMERA INTERNATIONAL' or 'R 361684 BNR'."""
    text = (text or "").strip()
    match = _PARTY.fullmatch(text)
    if not match:
        return None, text or None
    return parse_cui(match.group(1)), match.group(2).strip() or None


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _money(value: float | int | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


@dataclass
class Parsed:
    purchases: list[dict] = field(default_factory=list)
    # cui -> (name, kind)
    entities: dict[int, tuple[str, str]] = field(default_factory=dict)
    # (item, reason) for rows that could not be read at all
    rejected: list[tuple[object, str]] = field(default_factory=list)
    invalid_cuis: int = 0
    # Rows without a deadline where one is expected: a slice split by deadline would miss them.
    missing_deadlines: int = 0


def parse_page(data: dict) -> Parsed:
    """Turn one list response into rows; a later copy of the same purchase replaces an earlier."""
    parsed = Parsed()
    by_id: dict[int, dict] = {}
    for item in data.get("items", []):
        try:
            state = item.get("sysDirectAcquisitionState") or {}
            cpv_code, _, cpv_name = (item.get("cpvCode") or "").partition(" - ")
            buyer_cui, buyer_name = split_party(item.get("contractingAuthority"))
            supplier_cui, supplier_name = split_party(item.get("supplier"))
            row = {
                "id": int(item["directAcquisitionId"]),
                "code": item.get("uniqueIdentificationCode"),
                "name": mask_cnp(item.get("directAcquisitionName"), checked=True),
                "state_id": state.get("id"),
                "state": state.get("text"),
                "cpv_code": cpv_code.strip() or None,
                "cpv_name": cpv_name.strip() or None,
                "buyer_cui": buyer_cui,
                "buyer_text": mask_cnp(item.get("contractingAuthority")),
                "supplier_cui": supplier_cui,
                "supplier_text": mask_cnp(item.get("supplier")),
                "published_at": _when(item.get("publicationDate")),
                "finalized_at": _when(item.get("finalizationDate")),
                "estimated_value_ron": _money(item.get("estimatedValueRon")),
                "closing_value": _money(item.get("closingValue")),
            }
        except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
            parsed.rejected.append((item, repr(exc)))
            continue
        by_id[row["id"]] = row
        parsed.invalid_cuis += (buyer_cui is None) + (supplier_cui is None)
        parsed.missing_deadlines += item.get("supplierDecisionDeadline") is None or (
            item.get("caDecisionDeadline") is None
            and row["state_id"] not in STATES_WITHOUT_CA_DEADLINE
        )
        if supplier_cui is not None and supplier_cui not in parsed.entities:
            parsed.entities[supplier_cui] = (supplier_name or f"CUI {supplier_cui}", "company")
        if buyer_cui is not None:
            # Whoever buys with public money is listed as an authority, even if it also sells.
            parsed.entities[buyer_cui] = (buyer_name or f"CUI {buyer_cui}", "authority")
    parsed.purchases = list(by_id.values())
    return parsed
