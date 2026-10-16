"""Who sold and who bought the most, and the CPV divisions the rankings can be filtered by."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import ColumnElement, func, literal, select, union_all
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes.common import Cpv, Day, Db, Limit, in_period, list_source, top
from date_romania.api.schemas import CpvDivision, Ranking, RankingRow
from date_romania.models import AwardNotice, DirectPurchase

router = APIRouter(tags=["rankings"])


def _ranking(
    session: Session,
    side: ColumnElement,
    date_from: date | None,
    date_to: date | None,
    cpv: str | None,
    limit: int,
) -> Ranking:
    filters = in_period(date_from, date_to)
    if cpv:
        filters.append(DirectPurchase.cpv_code.startswith(cpv, autoescape=True))
    rows = top(session, side, filters, limit)
    return Ranking(
        date_from=date_from,
        date_to=date_to,
        items=[RankingRow(rank=n, **row.model_dump()) for n, row in enumerate(rows, 1)],
        source=list_source(session, money.counted, *filters),
    )


@router.get("/rankings/suppliers")
def ranking_suppliers(
    session: Db, date_from: Day = None, date_to: Day = None, cpv: Cpv = None, limit: Limit = 20
) -> Ranking:
    """Suppliers by the value of their accepted direct purchases."""
    return _ranking(session, DirectPurchase.supplier_cui, date_from, date_to, cpv, limit)


@router.get("/rankings/institutions")
def ranking_institutions(
    session: Db, date_from: Day = None, date_to: Day = None, cpv: Cpv = None, limit: Limit = 20
) -> Ranking:
    """Institutions by the value of the direct purchases they accepted."""
    return _ranking(session, DirectPurchase.buyer_cui, date_from, date_to, cpv, limit)


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
