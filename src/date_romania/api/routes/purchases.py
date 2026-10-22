"""Direct purchases: the list with its filters, and one purchase."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from date_romania import money
from date_romania.api.routes.common import (
    Day,
    Db,
    Limit,
    Offset,
    in_period,
    record_source,
    ref,
    summary,
)
from date_romania.api.schemas import (
    Purchase,
    PurchaseDetail,
    PurchaseItem,
    PurchasePage,
    PurchaseWithDetail,
    Summary,
)
from date_romania.models import DirectPurchase, DirectPurchaseDetail, Entity, SourceDocument
from date_romania.sources import SEAP_DIRECT

router = APIRouter(tags=["direct purchases"])

Buyer, Supplier = aliased(Entity), aliased(Entity)


def _purchases() -> Select:
    return (
        select(DirectPurchase, Buyer, Supplier, SourceDocument.fetched_at, SourceDocument.sha256)
        .outerjoin(Buyer, DirectPurchase.buyer_cui == Buyer.cui)
        .outerjoin(Supplier, DirectPurchase.supplier_cui == Supplier.cui)
        .join(SourceDocument, DirectPurchase.source_document_id == SourceDocument.id)
    )


def _purchase(row) -> Purchase:
    purchase, buyer, supplier, fetched_at, sha256 = row
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
        contract_type_id=purchase.contract_type_id,
        limit=money.limit_of(purchase.contract_type_id, purchase.cpv_code),
        above_limit=money.is_above_limit(
            purchase.state_id, value, purchase.contract_type_id, purchase.cpv_code
        ),
        source=record_source(
            SEAP_DIRECT,
            purchase,
            record=purchase.code,
            url=SEAP_DIRECT.record_url.format(id=purchase.id),
            fetched_at=fetched_at,
            sha256=sha256,
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
    offset: Offset = 0,
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


@router.get("/direct-purchases/summary")
def direct_purchases_summary(
    session: Db,
    buyer: Annotated[int | None, Query(description="CUI of the buying institution.")] = None,
    supplier: Annotated[int | None, Query(description="CUI of the supplier.")] = None,
) -> Summary:
    """The totals of the direct purchases of a buyer, a supplier, or the two together."""
    filters = []
    if buyer is not None:
        filters.append(DirectPurchase.buyer_cui == buyer)
    if supplier is not None:
        filters.append(DirectPurchase.supplier_cui == supplier)
    return summary(session, *filters)


def _detail(session: Db, purchase: Purchase) -> PurchaseDetail | None:
    row = session.execute(
        select(DirectPurchaseDetail, SourceDocument.fetched_at, SourceDocument.sha256)
        .join(SourceDocument, DirectPurchaseDetail.source_document_id == SourceDocument.id)
        .where(DirectPurchaseDetail.purchase_id == purchase.id)
    ).one_or_none()
    if row is None:
        return None
    detail, fetched_at, sha256 = row
    items = [
        PurchaseItem(
            name=item.name,
            cpv_code=item.cpv_code,
            quantity=item.quantity,
            unit=item.unit,
            unit_price=item.unit_price,
            value=(
                None
                if item.unit_price is None or item.quantity is None
                else round(item.unit_price * item.quantity, 2)
            ),
            rejected=item.rejected,
        )
        for item in detail.items
    ]
    values = [item.value for item in items]
    return PurchaseDetail(
        payment_condition=detail.payment_condition,
        delivery_condition=detail.delivery_condition,
        items=items,
        items_value=None if None in values else round(sum(values), 2),
        source=record_source(
            SEAP_DIRECT,
            detail,
            record=purchase.code,
            url=SEAP_DIRECT.record_url.format(id=purchase.id),
            fetched_at=fetched_at,
            sha256=sha256,
        ),
    )


@router.get("/direct-purchases/{purchase_id}")
def direct_purchase(session: Db, purchase_id: int) -> PurchaseWithDetail:
    """One direct purchase, by SEAP's own id, with its lines and conditions once collected."""
    row = session.execute(_purchases().where(DirectPurchase.id == purchase_id)).one_or_none()
    if row is None:
        raise HTTPException(404, f"No direct purchase with id {purchase_id}")
    purchase = _purchase(row)
    return PurchaseWithDetail(**dict(purchase), detail=_detail(session, purchase))
