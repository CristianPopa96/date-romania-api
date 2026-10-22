"""Turning one SEAP list response into rows."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from date_romania.collectors.seap_direct.slices import STATES_WITHOUT_CA_DEADLINE
from date_romania.cui import parse_cui
from date_romania.personal_id import mask_cnp

# 3: the contract type, from the query that returned the row.
PARSER_VERSION = 3

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
    details: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    # The purchase whose lines `items` replaces, when a detail was read.
    items_of: int | None = None


def parse_page(data: dict, contract_type: int | None = None) -> Parsed:
    """Turn one list response into rows; a later copy of the same purchase replaces an earlier.

    `contract_type` is the type the query filtered by, if it did: every row it returned is
    of that type.
    """
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
                "contract_type_id": contract_type,
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


# The detail of one purchase has its own parser version: a list page and a detail answer
# are told apart by address, and change apart.
DETAIL_PARSER_VERSION = 1

_ERRORS = (AttributeError, KeyError, TypeError, ValueError, InvalidOperation)


def _text(value: str | None) -> str | None:
    """Free text as it is, with valid personal codes hidden; blank is none."""
    return mask_cnp((value or "").strip(), checked=True) or None


def _cpv(value: dict | None) -> str | None:
    """The code of SEAP's CPV object, e.g. '16700000-2'."""
    return ((value or {}).get("localeKey") or "").strip() or None


def _fund(value: dict | None) -> str | None:
    """A fund's name, or the end of its key when SEAP leaves the name empty ('PEO')."""
    value = value or {}
    return (value.get("text") or "").strip() or (
        (value.get("localeKey") or "").rpartition(".")[2] or None
    )


def parse_detail(data: dict, purchase_id: int | None = None) -> Parsed:
    """Turn the detail of one purchase into its `direct_purchase_detail` row and its lines.

    `purchase_id` is the purchase that was asked for: an answer about another is rejected.
    The names and emails of the officials in the answer are never read.
    """
    parsed = Parsed()
    try:
        found = int(data["directAcquisitionID"])
        if purchase_id is not None and found != purchase_id:
            raise ValueError(f"asked for purchase {purchase_id}, got {found}")
        parsed.details.append(
            {
                "purchase_id": found,
                "description": _text(data.get("directAcquisitionDescription")),
                "payment_condition": _text(data.get("paymentCondition")),
                "delivery_condition": _text(data.get("deliveryCondition")),
                "eu_funded": data.get("financingType"),
                "eu_fund": _fund(data.get("sysEuropeanFund")),
            }
        )
        lines = data.get("directAcquisitionItems") or []
    except _ERRORS as exc:
        parsed.rejected.append((data, repr(exc)))
        return parsed
    parsed.items_of = found
    for position, item in enumerate(lines, 1):
        try:
            parsed.items.append(
                {
                    "purchase_id": found,
                    "position": position,
                    "name": _text(item.get("catalogItemName")),
                    "description": _text(item.get("catalogItemDescription")),
                    "cpv_code": _cpv(item.get("cpvCode")),
                    "quantity": _money(item.get("itemQuantity")),
                    "unit": _text(item.get("itemMeasureUnit")),
                    "unit_price": _money(item.get("itemClosingPrice")),
                    "rejected": item.get("isRejectedBySupplier"),
                }
            )
        except _ERRORS as exc:
            parsed.rejected.append((item, repr(exc)))
    return parsed
