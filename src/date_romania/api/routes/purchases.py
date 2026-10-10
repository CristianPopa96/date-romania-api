"""Direct purchases: the list with its filters, and one purchase."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from date_romania import money
from date_romania.api.routes.common import Day, Db, Limit, in_period, ref
from date_romania.api.schemas import Purchase, PurchasePage, Source
from date_romania.models import DirectPurchase, Entity, SourceDocument
from date_romania.sources import SEAP_DIRECT

router = APIRouter(tags=["direct purchases"])

Buyer, Supplier = aliased(Entity), aliased(Entity)


def _purchases() -> Select:
    return (
        select(DirectPurchase, Buyer, Supplier, SourceDocument.fetched_at)
        .outerjoin(Buyer, DirectPurchase.buyer_cui == Buyer.cui)
        .outerjoin(Supplier, DirectPurchase.supplier_cui == Supplier.cui)
        .join(SourceDocument, DirectPurchase.source_document_id == SourceDocument.id)
    )


def _purchase(row) -> Purchase:
    purchase, buyer, supplier, fetched_at = row
    value = purchase.closing_value
    return Purchase(
        id=purchase.id,
        code=purchase.code,
        name=purchase.name,
        state_id=purchase.state_id,
        state=purchase.state,
        cpv_code=purchase.cpv_code,
        cpv_name=purchase.cpv_name,
        buyer=ref(buyer),
        buyer_text=purchase.buyer_text,
        supplier=ref(supplier),
        supplier_text=purchase.supplier_text,
        published_at=purchase.published_at,
        finalized_at=purchase.finalized_at,
        estimated_value=purchase.estimated_value_ron,
        value=value,
        above_limit=money.is_above_limit(purchase.state_id, value),
        source=Source(
            publisher=SEAP_DIRECT.publisher,
            record=purchase.code,
            url=SEAP_DIRECT.record_url.format(id=purchase.id),
            fetched_at=fetched_at,
            document_id=purchase.source_document_id,
        ),
    )


@router.get("/direct-purchases")
def direct_purchases(
    session: Db,
    buyer: Annotated[int | None, Query(description="CUI of the buying institution.")] = None,
    supplier: Annotated[int | None, Query(description="CUI of the supplier.")] = None,
    cpv: Annotated[
        str | None, Query(max_length=10, description="Start of a CPV code, e.g. 4523.")
    ] = None,
    state: Annotated[int | None, Query(description="SEAP state id; 7 is accepted.")] = None,
    date_from: Day = None,
    date_to: Day = None,
    sort: Literal["newest", "value"] = "newest",
    limit: Limit = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PurchasePage:
    """Direct purchases by finalization day, newest or largest first."""
    filters = in_period(date_from, date_to)
    if buyer is not None:
        filters.append(DirectPurchase.buyer_cui == buyer)
    if supplier is not None:
        filters.append(DirectPurchase.supplier_cui == supplier)
    if cpv:
        filters.append(DirectPurchase.cpv_code.startswith(cpv, autoescape=True))
    if state is not None:
        filters.append(DirectPurchase.state_id == state)
    order = (
        [DirectPurchase.closing_value.desc().nulls_last()]
        if sort == "value"
        else [DirectPurchase.finalized_at.desc().nulls_last()]
    )
    total = session.scalar(select(func.count()).select_from(DirectPurchase).where(*filters))
    rows = session.execute(
        _purchases()
        .where(*filters)
        .order_by(*order, DirectPurchase.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return PurchasePage(total=total, items=[_purchase(row) for row in rows])


@router.get("/direct-purchases/{purchase_id}")
def direct_purchase(session: Db, purchase_id: int) -> Purchase:
    """One direct purchase, by SEAP's own id."""
    row = session.execute(_purchases().where(DirectPurchase.id == purchase_id)).one_or_none()
    if row is None:
        raise HTTPException(404, f"No direct purchase with id {purchase_id}")
    return _purchase(row)
