"""Direct purchases: the list with its filters, and one purchase."""

from collections.abc import Iterable
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import aliased

from date_romania import money
from date_romania.api.routes.common import (
    Db,
    Format,
    Limit,
    Offset,
    cell,
    csv_file,
    record_source,
    ref,
    summary,
)
from date_romania.api.routes.list_common import ordered
from date_romania.api.routes.purchase_list import Filters
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


def purchases_query() -> Select:
    return (
        select(DirectPurchase, Buyer, Supplier, SourceDocument.fetched_at, SourceDocument.sha256)
        .outerjoin(Buyer, DirectPurchase.buyer_cui == Buyer.cui)
        .outerjoin(Supplier, DirectPurchase.supplier_cui == Supplier.cui)
        .join(SourceDocument, DirectPurchase.source_document_id == SourceDocument.id)
    )


def purchase_row(row) -> Purchase:
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
    filters: Filters,
    sort: Annotated[
        Literal["date", "value", "supplier", "buyer", "newest"],
        Query(
            description="The finalization day, the closing value or a party's name; "
            "`newest` is the day, as before."
        ),
    ] = "date",
    order: Literal["desc", "asc"] = "desc",
    limit: Limit = 20,
    offset: Offset = 0,
    format: Format = "json",
) -> PurchasePage:
    """Direct purchases under the filters given, by finalization day, value or party.

    As csv, the whole list in the same order; a file needs a buyer or a supplier."""
    conditions = filters.all()
    column = {
        "value": DirectPurchase.closing_value,
        "supplier": func.lower(func.coalesce(Supplier.name, DirectPurchase.supplier_text)),
        "buyer": func.lower(func.coalesce(Buyer.name, DirectPurchase.buyer_text)),
    }.get(sort, DirectPurchase.finalized_at)
    query = ordered(purchases_query().where(*conditions), column, order, DirectPurchase.id)
    if format == "csv":
        if not {"buyer", "supplier"} & filters.named.keys():
            raise HTTPException(400, "A file of direct purchases needs a buyer or a supplier.")
        return purchases_csv(purchase_row(row) for row in session.execute(query))
    total = session.scalar(select(func.count()).select_from(DirectPurchase).where(*conditions))
    rows = session.execute(query.limit(limit).offset(offset))
    return PurchasePage(total=total, items=[purchase_row(row) for row in rows])


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


def purchases_csv(purchases: Iterable[Purchase]) -> Response:
    """The list as a file; every row names where it was read."""
    header = [
        "code",
        "finalized_at",
        "name",
        "state",
        "contract_type",
        "cpv_code",
        "buyer_cui",
        "buyer",
        "supplier_cui",
        "supplier",
        "value_ron_without_vat",
        "above_limit",
        "source_url",
        "fetched_at",
    ]
    rows = (
        [
            cell(p.code),
            p.finalized_at and p.finalized_at.isoformat(),
            cell(p.name),
            cell(p.state),
            p.contract_type_id,
            p.cpv_code,
            p.buyer and p.buyer.cui,
            cell(p.buyer.name if p.buyer else p.buyer_text),
            p.supplier and p.supplier.cui,
            cell(p.supplier.name if p.supplier else p.supplier_text),
            p.value,
            p.above_limit,
            p.source.url,
            p.source.fetched_at and p.source.fetched_at.isoformat(),
        ]
        for p in purchases
    )
    return csv_file(header, rows, "achizitii-directe.csv")


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
    # What was bought: the lines the supplier did not turn down.
    values = [item.value for item in items if not item.rejected]
    return PurchaseDetail(
        payment_condition=detail.payment_condition,
        delivery_condition=detail.delivery_condition,
        items=items,
        items_value=None if not values or None in values else round(sum(values), 2),
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
    row = session.execute(purchases_query().where(DirectPurchase.id == purchase_id)).one_or_none()
    if row is None:
        raise HTTPException(404, f"No direct purchase with id {purchase_id}")
    purchase = purchase_row(row)
    return PurchaseWithDetail(**dict(purchase), detail=_detail(session, purchase))
