"""Read-only endpoints over the collected data. Every answer names its source."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import ColumnElement, Date, Select, String, and_, cast, func, or_, select
from sqlalchemy.orm import Session, aliased

from date_romania.api.schemas import (
    EntityOut,
    EntityPage,
    EntityRef,
    Partner,
    Purchase,
    PurchasePage,
    Ranking,
    RankingRow,
    SearchResults,
    Source,
    Stats,
    Summary,
)
from date_romania.collectors.jobs import day_bounds
from date_romania.db import get_session
from date_romania.models import (
    DIRECT_PURCHASE_ACCEPTED,
    DIRECT_PURCHASE_LIMIT_RON,
    DirectPurchase,
    Entity,
    SourceDocument,
    search_text,
)

router = APIRouter(prefix="/v1")

Db = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Day = Annotated[date | None, Query(description="A day in Romanian time, YYYY-MM-DD.")]

SEAP = "SEAP"
SEAP_SOURCE = "seap-direct"
SEAP_LIST_URL = "https://e-licitatie.ro/pub/direct-acquisitions/list/1"
SEAP_VIEW_URL = "https://e-licitatie.ro/pub/direct-acquisition/view/{id}"

Buyer, Supplier = aliased(Entity), aliased(Entity)

_LIKE_ESCAPES = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})

_accepted = DirectPurchase.state_id == DIRECT_PURCHASE_ACCEPTED
_counted = and_(_accepted, DirectPurchase.closing_value <= DIRECT_PURCHASE_LIMIT_RON)
_above = and_(_accepted, DirectPurchase.closing_value > DIRECT_PURCHASE_LIMIT_RON)
_day = cast(func.timezone("Europe/Bucharest", DirectPurchase.finalized_at), Date)
_value = func.coalesce(func.sum(DirectPurchase.closing_value).filter(_counted), 0)

_SUMMARY = (
    func.count().label("purchases"),
    func.count().filter(_accepted).label("accepted"),
    _value.label("value"),
    func.count().filter(_above).label("above_limit"),
    func.coalesce(func.sum(DirectPurchase.closing_value).filter(_above), 0).label(
        "above_limit_value"
    ),
    func.min(_day).label("first_day"),
    func.max(_day).label("last_day"),
)


def _in_period(date_from: date | None, date_to: date | None) -> list[ColumnElement[bool]]:
    """Filters for purchases finalized from `date_from` to `date_to`, both included."""
    filters = []
    if date_from:
        filters.append(DirectPurchase.finalized_at >= day_bounds(date_from)[0])
    if date_to:
        filters.append(DirectPurchase.finalized_at < day_bounds(date_to)[1])
    return filters


def _summary(session: Session, *filters: ColumnElement[bool]) -> Summary:
    row = session.execute(select(*_SUMMARY).where(*filters)).one()
    return Summary.model_validate(row._mapping)


def _list_source(session: Session) -> Source:
    """The source of a figure added up from many purchases: the SEAP list as last fetched."""
    fetched = session.scalar(
        select(func.max(SourceDocument.fetched_at)).where(SourceDocument.source == SEAP_SOURCE)
    )
    return Source(publisher=SEAP, url=SEAP_LIST_URL, fetched_at=fetched)


def _ref(entity: Entity | None) -> EntityRef | None:
    return entity and EntityRef(cui=entity.cui, name=entity.name, kind=entity.kind)


def _entity_out(entity: Entity) -> EntityOut:
    return EntityOut(
        cui=entity.cui,
        name=entity.name,
        kind=entity.kind,
        county=entity.county,
        locality=entity.locality,
    )


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
        buyer=_ref(buyer),
        buyer_text=purchase.buyer_text,
        supplier=_ref(supplier),
        supplier_text=purchase.supplier_text,
        published_at=purchase.published_at,
        finalized_at=purchase.finalized_at,
        estimated_value=purchase.estimated_value_ron,
        value=value,
        # As in the totals: only an accepted purchase can be "above the limit". A refused
        # offer is left out because it was refused, whatever value it carries.
        above_limit=(
            purchase.state_id == DIRECT_PURCHASE_ACCEPTED
            and value is not None
            and value > DIRECT_PURCHASE_LIMIT_RON
        ),
        source=Source(
            publisher=SEAP,
            record=purchase.code,
            url=SEAP_VIEW_URL.format(id=purchase.id),
            fetched_at=fetched_at,
            document_id=purchase.source_document_id,
        ),
    )


def _top(
    session: Session,
    group_by: ColumnElement,
    filters: list[ColumnElement[bool]],
    limit: int,
) -> list[Partner]:
    """Entities on one side of the accepted purchases, by value, largest first."""
    rows = session.execute(
        select(Entity, func.count().label("accepted"), _value.label("value"))
        .join(Entity, Entity.cui == group_by)
        .where(_counted, *filters)
        .group_by(Entity.cui)
        .order_by(_value.desc(), Entity.cui)
        .limit(limit)
    )
    return [
        Partner(cui=entity.cui, name=entity.name, kind=entity.kind, accepted=accepted, value=value)
        for entity, accepted, value in rows
    ]


@router.get("/stats", tags=["overview"])
def stats(session: Db) -> Stats:
    """What the database holds: how many direct purchases, for how much, over which days."""
    institutions, suppliers = session.execute(
        select(
            func.count(DirectPurchase.buyer_cui.distinct()),
            func.count(DirectPurchase.supplier_cui.distinct()),
        )
    ).one()
    return Stats(
        direct_purchases=_summary(session),
        institutions=institutions,
        suppliers=suppliers,
        limit=DIRECT_PURCHASE_LIMIT_RON,
        source=_list_source(session),
    )


@router.get("/search", tags=["overview"])
def search(
    session: Db,
    q: Annotated[str, Query(min_length=2, max_length=100, description="A name or a CUI.")],
    kind: Literal["authority", "company"] | None = None,
    limit: Limit = 20,
) -> SearchResults:
    """Find institutions and companies by name (diacritics and small typos forgiven) or CUI."""
    query = select(Entity)
    if kind:
        query = query.where(Entity.kind == kind)
    digits = q.upper().removeprefix("RO").replace(" ", "")
    if digits.isdigit():
        query = query.where(cast(Entity.cui, String).startswith(digits)).order_by(Entity.cui)
    else:
        name, term = search_text(Entity.name), search_text(q.strip())
        # Best: every word of the query is in the name. Otherwise a close spelling will do.
        every_word = and_(
            *(
                name.like(search_text("%" + word.translate(_LIKE_ESCAPES) + "%"))
                for word in q.split()
            )
        )
        query = query.where(or_(every_word, term.op("<%")(name))).order_by(
            every_word.desc(),
            func.word_similarity(term, name).desc(),
            func.length(Entity.name),
            Entity.cui,
        )
    return SearchResults(items=[_entity_out(e) for e in session.scalars(query.limit(limit))])


def _entity_page(
    session: Session, cui: int, own: ColumnElement, other: ColumnElement, partners: int
) -> EntityPage:
    entity = session.get(Entity, cui)
    if entity is None:
        raise HTTPException(404, f"No institution or company with CUI {cui}")
    return EntityPage(
        entity=_entity_out(entity),
        direct_purchases=_summary(session, own == cui),
        partners=_top(session, other, [own == cui], partners),
        source=_list_source(session),
    )


@router.get("/institutions/{cui}", tags=["entities"])
def institution(session: Db, cui: int, partners: Limit = 10) -> EntityPage:
    """An institution as a buyer: what it bought directly and from whom."""
    return _entity_page(
        session, cui, DirectPurchase.buyer_cui, DirectPurchase.supplier_cui, partners
    )


@router.get("/suppliers/{cui}", tags=["entities"])
def supplier(session: Db, cui: int, partners: Limit = 10) -> EntityPage:
    """A company as a supplier: what it sold directly and to whom."""
    return _entity_page(
        session, cui, DirectPurchase.supplier_cui, DirectPurchase.buyer_cui, partners
    )


@router.get("/direct-purchases", tags=["direct purchases"])
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
    filters = _in_period(date_from, date_to)
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


@router.get("/direct-purchases/{purchase_id}", tags=["direct purchases"])
def direct_purchase(session: Db, purchase_id: int) -> Purchase:
    """One direct purchase, by SEAP's own id."""
    row = session.execute(_purchases().where(DirectPurchase.id == purchase_id)).one_or_none()
    if row is None:
        raise HTTPException(404, f"No direct purchase with id {purchase_id}")
    return _purchase(row)


def _ranking(
    session: Session, side: ColumnElement, date_from: date | None, date_to: date | None, limit: int
) -> Ranking:
    top = _top(session, side, _in_period(date_from, date_to), limit)
    return Ranking(
        date_from=date_from,
        date_to=date_to,
        items=[RankingRow(rank=n, **row.model_dump()) for n, row in enumerate(top, 1)],
        source=_list_source(session),
    )


@router.get("/rankings/suppliers", tags=["rankings"])
def ranking_suppliers(
    session: Db, date_from: Day = None, date_to: Day = None, limit: Limit = 20
) -> Ranking:
    """Suppliers by the value of their accepted direct purchases."""
    return _ranking(session, DirectPurchase.supplier_cui, date_from, date_to, limit)


@router.get("/rankings/institutions", tags=["rankings"])
def ranking_institutions(
    session: Db, date_from: Day = None, date_to: Day = None, limit: Limit = 20
) -> Ranking:
    """Institutions by the value of the direct purchases they accepted."""
    return _ranking(session, DirectPurchase.buyer_cui, date_from, date_to, limit)
