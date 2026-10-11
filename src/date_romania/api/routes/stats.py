"""What the database holds."""

from fastapi import APIRouter
from sqlalchemy import func, select

from date_romania import money
from date_romania.api.routes.common import Db, list_source, summary
from date_romania.api.schemas import Dataset, Datasets, Stats
from date_romania.models import AwardContract, DirectPurchase, SourceDocument
from date_romania.sources import SEAP_AWARDS, SEAP_DIRECT

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


@router.get("/datasets")
def datasets(session: Db) -> Datasets:
    """What the site is built on: each source, the days we hold and how many records."""
    fetched = dict(
        session.execute(
            select(SourceDocument.source, func.max(SourceDocument.fetched_at)).group_by(
                SourceDocument.source
            )
        ).all()
    )
    direct = summary(session)
    period = money.contracts_period(session)
    contracts = session.scalar(
        select(func.count())
        .select_from(AwardContract)
        .where(money.contract_counted, money.contract_in_force, *money.signed_in(period))
    )
    return Datasets(
        items=[
            Dataset(
                key=SEAP_DIRECT.key,
                publisher=SEAP_DIRECT.publisher,
                first_day=direct.first_day,
                last_day=direct.last_day,
                records=direct.purchases,
                complete=True,
                fetched_at=fetched.get(SEAP_DIRECT.key),
            ),
            Dataset(
                key=SEAP_AWARDS.key,
                publisher=SEAP_AWARDS.publisher,
                first_day=period and period[0],
                last_day=period and period[1],
                # The contracts signed in the period, the ones the totals count.
                records=contracts,
                complete=False,
                fetched_at=fetched.get(SEAP_AWARDS.key),
            ),
        ]
    )
