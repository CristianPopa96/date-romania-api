"""Who sold and who bought the most, and the CPV divisions the rankings can be filtered by."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, Row, Select, and_, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes.common import (
    Cpv,
    Day,
    Db,
    Limit,
    Offset,
    containing,
    in_period,
    list_source,
)
from date_romania.api.routes.list_common import Order
from date_romania.api.schemas import CpvDivision, Ranking, RankingRow
from date_romania.models import AwardNotice, DirectPurchase, Entity, search_text

router = APIRouter(tags=["rankings"])


@dataclass
class Page:
    """Which page of a ranking, in which order, and the party searched for."""

    sort: Literal["value", "count"]
    order: Order
    limit: int
    offset: int
    q: str | None


def ranking_page(
    sort: Annotated[
        Literal["value", "count"],
        Query(description="The value added up, or how many rows it is added up from."),
    ] = "value",
    order: Order = "desc",
    q: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=100,
            description="Words of the party's name, or its CUI: the parties found keep their "
            "place in the ranking.",
        ),
    ] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page:
    return Page(sort, order, limit, offset, q)


RankingPage = Annotated[Page, Depends(ranking_page)]


def ranked(
    session: Session, query: Select, column: ColumnElement, page: Page
) -> tuple[int, list[Row]]:
    """A page of a ranking: `query` gives a party's CUI, name and kind and its figures, one
    row per party; `column` is the figure it is ranked by. Each row carries its `place` in
    the whole ranking, in the order asked for, ties in the order of their CUI; a search
    keeps it."""
    place = func.row_number().over(
        order_by=[column.asc() if page.order == "asc" else column.desc(), Entity.cui]
    )
    parties = query.add_columns(place.label("place")).subquery()
    found = []
    if page.q:
        words = and_(*(search_text(parties.c.name).like(containing(w)) for w in page.q.split()))
        code = page.q.strip()
        found.append(or_(words, parties.c.cui == int(code)) if code.isdecimal() else words)
    total = session.scalar(select(func.count()).select_from(parties).where(*found))
    rows = session.execute(
        select(parties)
        .where(*found)
        .order_by(parties.c.place)
        .limit(page.limit)
        .offset(page.offset)
    ).all()
    return total, rows


def _ranking(
    session: Session,
    side: ColumnElement,
    date_from: date | None,
    date_to: date | None,
    cpv: str | None,
    page: Page,
) -> Ranking:
    filters = in_period(date_from, date_to)
    if cpv:
        filters.append(DirectPurchase.cpv_code.startswith(cpv, autoescape=True))
    accepted = func.count()
    query = (
        select(Entity.cui, Entity.name, Entity.kind)
        .add_columns(accepted.label("accepted"), money.value.label("value"))
        .join(Entity, Entity.cui == side)
        .where(money.counted, *filters)
        .group_by(Entity.cui)
    )
    column = accepted if page.sort == "count" else money.value
    total, rows = ranked(session, query, column, page)
    return Ranking(
        date_from=date_from,
        date_to=date_to,
        total=total,
        items=[
            RankingRow(
                rank=row.place,
                cui=row.cui,
                name=row.name,
                kind=row.kind,
                accepted=row.accepted,
                value=row.value,
            )
            for row in rows
        ],
        source=list_source(session, money.counted, *filters),
    )


@router.get("/rankings/suppliers")
def ranking_suppliers(
    session: Db,
    page: RankingPage,
    date_from: Day = None,
    date_to: Day = None,
    cpv: Cpv = None,
) -> Ranking:
    """Suppliers by the value of their accepted direct purchases, or by how many."""
    return _ranking(session, DirectPurchase.supplier_cui, date_from, date_to, cpv, page)


@router.get("/rankings/institutions")
def ranking_institutions(
    session: Db,
    page: RankingPage,
    date_from: Day = None,
    date_to: Day = None,
    cpv: Cpv = None,
) -> Ranking:
    """Institutions by the value of the direct purchases they accepted, or by how many."""
    return _ranking(session, DirectPurchase.buyer_cui, date_from, date_to, cpv, page)


@router.get("/cpv-divisions")
def cpv_divisions(session: Db) -> list[CpvDivision]:
    """The CPV divisions (first two digits of a code) found in the purchases and notices held.

    The name is SEAP's own for the division's code (45000000 for 45), where a row carries
    it; it is never translated.
    """
    codes = union_all(
        select(DirectPurchase.cpv_code.label("code"), DirectPurchase.cpv_name.label("name")),
        select(AwardNotice.cpv_code, AwardNotice.cpv_name),
    ).subquery()
    division = func.left(codes.c.code, 2)
    root = func.substr(codes.c.code, 3, 6) == literal("000000")
    rows = session.execute(
        select(division, func.min(codes.c.name).filter(root))
        .where(codes.c.code.regexp_match(r"^\d{8}"))
        .group_by(division)
        .order_by(division)
    )
    return [CpvDivision(code=code, name=name) for code, name in rows]
