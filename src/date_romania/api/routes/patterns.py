"""Patterns: measured facts worth asking documents for, never a finding of wrongdoing."""

from decimal import ROUND_FLOOR, Decimal

from fastapi import APIRouter, Response
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import aliased

from date_romania import money
from date_romania.api.routes.common import Cpv, Db, Format, Limit, cell, csv_file, list_source, ref
from date_romania.api.schemas import (
    NearLimitPair,
    NearLimitPattern,
    NearLimitPurchase,
    NearLimitRule,
)
from date_romania.models import DirectPurchase, Entity, SourceDocument
from date_romania.sources import SEAP_DIRECT

router = APIRouter(tags=["patterns"])

Buyer, Supplier = aliased(Entity), aliased(Entity)


@router.get("/patterns/near-limit")
def near_limit(
    session: Db, cpv: Cpv = None, limit: Limit = 50, format: Format = "json"
) -> NearLimitPattern:
    """Pairs of a buyer and a supplier with repeated accepted direct purchases just under the
    legal limit of their contract type, most purchases first.

    A purchase is near the limit from `rule.share` of it to just under it. A purchase whose type is
    not known cannot be checked: `checked` of `accepted_total` were, and `first_day` and
    `last_day` bound those. As csv: every pair, one line per purchase.
    """
    filters = [
        money.near_limit,
        DirectPurchase.buyer_cui.is_not(None),
        DirectPurchase.supplier_cui.is_not(None),
    ]
    if cpv:
        filters.append(DirectPurchase.cpv_code.startswith(cpv, autoescape=True))
    pair = (DirectPurchase.buyer_cui, DirectPurchase.supplier_cui, DirectPurchase.contract_type_id)
    value = func.sum(DirectPurchase.closing_value)
    grouped = (
        select(*pair, func.count().label("purchases"), value.label("value"))
        .where(*filters)
        .group_by(*pair)
        .having(func.count() >= money.NEAR_LIMIT_REPEATS)
    )
    pairs = session.scalar(select(func.count()).select_from(grouped.subquery()))
    ordered = grouped.order_by(func.count().desc(), value.desc(), *pair)
    found = session.execute(ordered if format == "csv" else ordered.limit(limit)).all()

    rows: dict[tuple, list[NearLimitPurchase]] = {}
    fetched: dict[int, object] = {}
    if found:
        purchases = session.execute(
            select(DirectPurchase, SourceDocument.fetched_at)
            .join(SourceDocument, DirectPurchase.source_document_id == SourceDocument.id)
            .where(*filters, tuple_(*pair).in_([tuple(row[:3]) for row in found]))
            .order_by(DirectPurchase.finalized_at, DirectPurchase.id)
        )
        for purchase, fetched_at in purchases:
            fetched[purchase.id] = fetched_at
            key = (purchase.buyer_cui, purchase.supplier_cui, purchase.contract_type_id)
            rows.setdefault(key, []).append(
                NearLimitPurchase(
                    id=purchase.id,
                    code=purchase.code,
                    name=purchase.name,
                    finalized_at=purchase.finalized_at,
                    value=purchase.closing_value,
                )
            )
    entities = {
        entity.cui: entity
        for entity in session.scalars(
            select(Entity).where(Entity.cui.in_({cui for row in found for cui in row[:2]}))
        )
    }
    if format == "csv":
        return _csv(found, rows, entities, fetched)
    # What could be checked: accepted purchases of a known type, under the same filters. The
    # type is known only where SEAP's list was asked by type, so quiet days stay unchecked;
    # the period is the one of the purchases checked, not of all the data.
    scope = [money.accepted]
    if cpv:
        scope.append(DirectPurchase.cpv_code.startswith(cpv, autoescape=True))
    typed = DirectPurchase.contract_type_id.is_not(None)
    checked, accepted_total, first_day, last_day = session.execute(
        select(
            func.count().filter(typed),
            func.count(),
            func.min(money.day).filter(typed),
            func.max(money.day).filter(typed),
        ).where(*scope)
    ).one()
    return NearLimitPattern(
        rule=NearLimitRule(
            share=money.NEAR_LIMIT_SHARE,
            repeats=money.NEAR_LIMIT_REPEATS,
            limits=money.LIMIT_BY_CONTRACT_TYPE,
        ),
        first_day=first_day,
        last_day=last_day,
        pairs=pairs,
        items=[
            NearLimitPair(
                buyer=ref(entities[buyer]),
                supplier=ref(entities[supplier]),
                contract_type=kind,
                limit=money.LIMIT_BY_CONTRACT_TYPE[kind],
                purchases=count,
                value=total,
                items=rows[(buyer, supplier, kind)],
            )
            for buyer, supplier, kind, count, total in found
        ],
        checked=checked,
        accepted_total=accepted_total,
        unknown_type=accepted_total - checked,
        source=list_source(session, *filters),
    )


def _share(value: float, limit: Decimal) -> float:
    """The share of its limit a purchase reaches, rounded down as the site does: a value
    under the limit never reads 1.0."""
    return float((Decimal(str(value)) / limit).quantize(Decimal("0.0001"), ROUND_FLOOR))


def _csv(found: list, rows: dict, entities: dict, fetched: dict) -> Response:
    """One line per purchase, each naming its pair (by its place in the list), the two
    parties, the limit of its type and where it was read. A pattern, not a finding."""
    header = [
        "pair",
        "buyer_cui",
        "buyer",
        "supplier_cui",
        "supplier",
        "contract_type",
        "limit_ron",
        "pair_purchases",
        "pair_value_ron",
        "purchase_code",
        "purchase",
        "finalized_at",
        "value_ron_without_vat",
        "share_of_limit",
        "source_url",
        "fetched_at",
    ]
    lines = []
    for place, (buyer, supplier, kind, count, total) in enumerate(found, start=1):
        limit = money.LIMIT_BY_CONTRACT_TYPE[kind]
        for purchase in rows[(buyer, supplier, kind)]:
            at = fetched[purchase.id]
            lines.append(
                [
                    place,
                    buyer,
                    cell(entities[buyer].name),
                    supplier,
                    cell(entities[supplier].name),
                    kind,
                    float(limit),
                    count,
                    float(total),
                    cell(purchase.code),
                    cell(purchase.name),
                    purchase.finalized_at and purchase.finalized_at.isoformat(),
                    purchase.value,
                    _share(purchase.value, limit),
                    SEAP_DIRECT.record_url.format(id=purchase.id),
                    at and at.isoformat(),
                ]
            )
    return csv_file(header, lines, "tipare-sub-plafon.csv")
