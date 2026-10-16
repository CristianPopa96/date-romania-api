"""Patterns: measured facts worth asking documents for, never a finding of wrongdoing."""

from fastapi import APIRouter
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import aliased

from date_romania import money
from date_romania.api.routes.common import Cpv, Db, Limit, list_source, ref
from date_romania.api.schemas import (
    NearLimitPair,
    NearLimitPattern,
    NearLimitPurchase,
    NearLimitRule,
)
from date_romania.models import DirectPurchase, Entity

router = APIRouter(tags=["patterns"])

Buyer, Supplier = aliased(Entity), aliased(Entity)


@router.get("/patterns/near-limit")
def near_limit(session: Db, cpv: Cpv = None, limit: Limit = 50) -> NearLimitPattern:
    """Pairs of a buyer and a supplier with repeated accepted direct purchases just under the
    legal limit of their contract type, most purchases first.

    A purchase is near the limit from `rule.share` of it to just under it. A purchase whose type is
    not known cannot be checked: `checked` of `accepted_total` were, and `first_day` and
    `last_day` bound those.
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
    found = session.execute(
        grouped.order_by(func.count().desc(), value.desc(), *pair).limit(limit)
    ).all()

    rows: dict[tuple, list[NearLimitPurchase]] = {}
    if found:
        purchases = session.scalars(
            select(DirectPurchase)
            .where(*filters, tuple_(*pair).in_([tuple(row[:3]) for row in found]))
            .order_by(DirectPurchase.finalized_at, DirectPurchase.id)
        )
        for purchase in purchases:
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
        source=list_source(session),
    )
