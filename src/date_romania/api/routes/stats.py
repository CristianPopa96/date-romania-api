"""What the database holds."""

from fastapi import APIRouter
from sqlalchemy import func, select

from date_romania import money
from date_romania.api.routes.common import Db, list_source, summary
from date_romania.api.schemas import Stats
from date_romania.models import DirectPurchase

router = APIRouter(tags=["overview"])


@router.get("/stats")
def stats(session: Db) -> Stats:
    """What the database holds: how many direct purchases, for how much, over which days."""
    institutions, suppliers = session.execute(
        select(
            func.count(DirectPurchase.buyer_cui.distinct()),
            func.count(DirectPurchase.supplier_cui.distinct()),
        )
    ).one()
    return Stats(
        direct_purchases=summary(session),
        institutions=institutions,
        suppliers=suppliers,
        limit=money.DIRECT_PURCHASE_LIMIT_RON,
        source=list_source(session),
    )
