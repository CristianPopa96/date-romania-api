"""What the database holds."""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.api.routes.common import Db, list_source, summary
from date_romania.api.schemas import Dataset, Datasets, Stats
from date_romania.dates import BUCHAREST
from date_romania.models import (
    AwardContract,
    AwardNotice,
    DirectPurchase,
    JobRun,
    SourceDocument,
)
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


def _days(session: Session, job: str) -> tuple[int, int]:
    """How many days a collector read in full, and how many only in part.

    A day read again counts once, by its best run: in full if any run got all of it.
    """
    runs = session.execute(
        select(JobRun.period_start, JobRun.status)
        .where(JobRun.job == job, JobRun.status.in_(("succeeded", "partial")))
        .distinct()
    )
    full, partial = set(), set()
    for start, status in runs:
        (full if status == "succeeded" else partial).add(start.astimezone(BUCHAREST).date())
    return len(full), len(partial - full)


@router.get("/datasets")
def datasets(session: Db) -> Datasets:
    """What the site is built on: each source, the days we hold and how many records."""
    documents = {
        source: (fetched, count)
        for source, fetched, count in session.execute(
            select(
                SourceDocument.source, func.max(SourceDocument.fetched_at), func.count()
            ).group_by(SourceDocument.source)
        )
    }
    fetched = {source: at for source, (at, _) in documents.items()}
    stored = {source: count for source, (_, count) in documents.items()}
    direct = summary(session)
    period = money.contracts_period(session)
    contracts = session.scalar(
        select(func.count())
        .select_from(AwardContract)
        .where(money.contract_counted, money.contract_in_force, *money.signed_in(period))
    )
    notices = session.scalar(select(func.count()).select_from(AwardNotice))
    held = session.scalar(select(func.count()).select_from(AwardContract))
    direct_days, awards_days = _days(session, SEAP_DIRECT.key), _days(session, SEAP_AWARDS.key)
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
                days_collected=direct_days[0],
                days_partial=direct_days[1],
                documents=stored.get(SEAP_DIRECT.key, 0),
                counts={
                    "purchases": direct.purchases,
                    "accepted": direct.accepted,
                    "above_limit": direct.above_limit,
                },
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
                days_collected=awards_days[0],
                days_partial=awards_days[1],
                documents=stored.get(SEAP_AWARDS.key, 0),
                # Notices carry contracts signed years before the days read; only the
                # ones signed inside those days are counted.
                counts={"notices": notices, "contracts": held, "counted_contracts": contracts},
            ),
        ]
    )
