"""What the database holds."""

from datetime import date

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania import places as places_
from date_romania.api.routes.common import Db, list_source, summary
from date_romania.api.schemas import Dataset, Datasets, Stats
from date_romania.models import (
    SUCCEEDED,
    AnafRecord,
    AwardContract,
    AwardNotice,
    DirectPurchase,
    ExportContract,
    JobRun,
    LocalBudget,
    Place,
    PniasPayment,
    PublicEntity,
    SourceDocument,
    done_days,
)
from date_romania.models import Population as PopulationRow
from date_romania.sources import (
    ANAF,
    LOCAL_BUDGETS,
    PNIAS_PAYMENTS,
    PUBLIC_ENTITIES,
    SEAP_AWARDS,
    SEAP_DIRECT,
    SEAP_EXPORTS,
    SIRUTA,
)

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
        limit_goods_services=money.DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON,
        source=list_source(session),
    )


def _days(session: Session, job: str, first: date | None, last: date | None) -> tuple[int, int]:
    """How many days of the period a collector read in full, and how many only in part.

    A day read again counts once, by its best run: in full if any run got all of it. A day
    read outside the period is not counted: the figure is shown next to the period, and
    must never be larger than it.
    """
    if not (first and last):
        return 0, 0
    days = [whole for day, whole in done_days(session, job).items() if first <= day <= last]
    return days.count(True), days.count(False)


def _last_run_whole(session: Session, job: str) -> bool:
    """False when the latest run of a file collector left a file unread."""
    status = session.scalar(
        select(JobRun.status).where(JobRun.job == job).order_by(JobRun.id.desc()).limit(1)
    )
    return status in (None, SUCCEEDED)


def _count(session: Session, *columns) -> tuple:
    return session.execute(select(*columns)).one()


def _place_datasets(session: Session) -> list[tuple]:
    """The place sources (release 3), as (source, first day, last day, records, counts).
    SIRUTA and the list of public entities are lists, with no period of their own."""
    places, uats = _count(session, func.count(), func.count().filter(Place.kind.in_(places_.UATS)))
    entities, placed = _count(
        session, func.count(PublicEntity.cui), func.count(PublicEntity.siruta)
    )
    budgets, figures, first_year, last_year = _count(
        session,
        func.count(LocalBudget.siruta.distinct()),
        func.count(),
        func.min(LocalBudget.year),
        func.max(LocalBudget.year),
    )
    people = session.scalar(select(func.count()).select_from(PopulationRow))
    asked, found, first_asked, last_asked = _count(
        session,
        func.count(AnafRecord.cui),
        func.count().filter(AnafRecord.found),
        func.min(AnafRecord.asked_on),
        func.max(AnafRecord.asked_on),
    )
    return [
        (SIRUTA, None, None, places, {"uats": uats}),
        (PUBLIC_ENTITIES, None, None, entities, {"placed": placed}),
        (
            LOCAL_BUDGETS,
            first_year and date(first_year, 1, 1),
            last_year and date(last_year, 12, 31),
            budgets,
            {"figures": figures, "population": people},
        ),
        (ANAF, first_asked, last_asked, asked, {"found": found}),
    ]


def _file_datasets(session: Session, fetched: dict, stored: dict, rejected: dict) -> list[Dataset]:
    """The sources that come as files, not as days: listed once we hold a file of theirs.

    Their period is what the files cover, and no day of it is read or missed.
    """
    payments, projects, first_file, last_file = session.execute(
        select(
            func.count(),
            func.count(PniasPayment.project_id.distinct()),
            func.min(PniasPayment.published_on),
            func.max(PniasPayment.published_on),
        )
    ).one()
    winners, first_notice, last_notice = session.execute(
        select(
            func.count(),
            func.min(ExportContract.notice_date),
            func.max(ExportContract.notice_date),
        )
    ).one()
    held = (
        (PNIAS_PAYMENTS, first_file, last_file, payments, {"projects": projects}),
        # A contract has a row for each winner and for each export it is in.
        (SEAP_EXPORTS, first_notice, last_notice, winners, {}),
        *_place_datasets(session),
    )
    return [
        Dataset(
            key=source.key,
            publisher=source.publisher,
            first_day=first,
            last_day=last,
            records=records,
            complete=_last_run_whole(session, source.key),
            fetched_at=fetched[source.key],
            days_collected=0,
            days_partial=0,
            documents=stored[source.key],
            rejected_rows=rejected[source.key],
            counts={"files": stored[source.key], "rows": records, **counts},
        )
        for source, first, last, records, counts in held
        if source.key in stored
    ]


@router.get("/datasets")
def datasets(session: Db) -> Datasets:
    """What the site is built on: each source, the days we hold and how many records."""
    documents = {
        source: (fetched, count, counted, rejected)
        for source, fetched, count, counted, rejected in session.execute(
            select(
                SourceDocument.source,
                func.max(SourceDocument.fetched_at),
                func.count(),
                func.count(SourceDocument.parser_version),
                func.coalesce(func.sum(SourceDocument.rejected_rows), 0),
            ).group_by(SourceDocument.source)
        )
    }
    fetched = {source: at for source, (at, *_) in documents.items()}
    stored = {source: count for source, (_, count, *_) in documents.items()}
    # Known only once every document of the source was seen by a parser that counts: read,
    # or set aside unread. Until a reparse after the count began, a few new documents would
    # otherwise read as the whole source.
    rejected = {
        source: int(total) if counted == count else None
        for source, (_, count, counted, total) in documents.items()
    }
    direct = summary(session)
    period = money.contracts_period(session)
    contracts = session.scalar(
        select(func.count())
        .select_from(AwardContract)
        .where(money.contract_counted, money.contract_in_force, *money.signed_in(period))
    )
    notices = session.scalar(select(func.count()).select_from(AwardNotice))
    held = session.scalar(select(func.count()).select_from(AwardContract))
    direct_days = _days(session, SEAP_DIRECT.key, direct.first_day, direct.last_day)
    awards_days = _days(session, SEAP_AWARDS.key, *(period or (None, None)))
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
                rejected_rows=rejected.get(SEAP_DIRECT.key),
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
                rejected_rows=rejected.get(SEAP_AWARDS.key),
                # Notices carry contracts signed years before the days read; only the
                # ones signed inside those days are counted.
                counts={"notices": notices, "contracts": held, "counted_contracts": contracts},
            ),
            *_file_datasets(session, fetched, stored, rejected),
        ]
    )
