"""Who sold and who bought the most."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Day, Db, Limit, in_period, list_source, top
from date_romania.api.schemas import Ranking, RankingRow
from date_romania.models import DirectPurchase

router = APIRouter(tags=["rankings"])


def _ranking(
    session: Session, side: ColumnElement, date_from: date | None, date_to: date | None, limit: int
) -> Ranking:
    rows = top(session, side, in_period(date_from, date_to), limit)
    return Ranking(
        date_from=date_from,
        date_to=date_to,
        items=[RankingRow(rank=n, **row.model_dump()) for n, row in enumerate(rows, 1)],
        source=list_source(session),
    )


@router.get("/rankings/suppliers")
def ranking_suppliers(
    session: Db, date_from: Day = None, date_to: Day = None, limit: Limit = 20
) -> Ranking:
    """Suppliers by the value of their accepted direct purchases."""
    return _ranking(session, DirectPurchase.supplier_cui, date_from, date_to, limit)


@router.get("/rankings/institutions")
def ranking_institutions(
    session: Db, date_from: Day = None, date_to: Day = None, limit: Limit = 20
) -> Ranking:
    """Institutions by the value of the direct purchases they accepted."""
    return _ranking(session, DirectPurchase.buyer_cui, date_from, date_to, limit)
