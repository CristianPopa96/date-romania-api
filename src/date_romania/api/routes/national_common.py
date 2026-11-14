"""What `/v1/national` reads: the budget execution and COFOG as held, and our own figures
for a year, from the same helpers as every other page."""

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from date_romania import money, national
from date_romania.api.routes.award_common import in_period
from date_romania.api.routes.common import last_fetched, list_source, summary
from date_romania.api.routes.programmes import source as programme_source
from date_romania.api.schemas.common import Source
from date_romania.api.schemas.national import Division, Domains, Figure, Ours
from date_romania.models import (
    AwardContract,
    AwardNotice,
    BudgetExecution,
    CofogSpending,
    PniasPayment,
    SourceDocument,
)
from date_romania.national import MILLION
from date_romania.sources import BUDGET_EXECUTION, EUROSTAT_COFOG, PNIAS_PAYMENTS, SEAP_AWARDS

EUROSTAT_ZONE = ZoneInfo("Europe/Luxembourg")


def lei(million: Decimal) -> float:
    return float(million * MILLION)


def total(lines: dict[str, Decimal], names: tuple[str, ...]) -> Decimal:
    return sum((lines.get(name, Decimal(0)) for name in names), Decimal(0))


def latest_execution(session: Session, year: int | None = None) -> date | None:
    """The newest month held, of `year` when given."""
    query = select(func.max(BudgetExecution.period_end))
    if year is not None:
        query = query.where(extract("year", BudgetExecution.period_end) == year)
    return session.scalar(query)


def execution_lines(session: Session, period_end: date, budget: str, section: str) -> dict:
    """One column of one month: each line's amount, million lei."""
    rows = session.execute(
        select(BudgetExecution.line, BudgetExecution.amount).where(
            BudgetExecution.period_end == period_end,
            BudgetExecution.budget == budget,
            BudgetExecution.section == section,
        )
    )
    return dict(rows.all())


def execution_source(session: Session, period_end: date) -> Source:
    """The workbook of one month: a single stored file."""
    doc = session.scalar(
        select(SourceDocument)
        .join(BudgetExecution, BudgetExecution.source_document_id == SourceDocument.id)
        .where(BudgetExecution.period_end == period_end)
        .limit(1)
    )
    parser = session.scalar(
        select(BudgetExecution.parser_version).where(BudgetExecution.period_end == period_end)
    )
    return Source(
        publisher=BUDGET_EXECUTION.publisher,
        # The ministry's own name for the file: "bgc30092026.xlsx".
        record=doc.url.rsplit("/", 1)[-1],
        url=doc.url,
        fetched_at=doc.fetched_at,
        document_id=doc.id,
        sha256=doc.sha256,
        parser_version=parser,
    )


def cofog(session: Session, year: int, sector: str) -> dict[str, Decimal]:
    rows = session.execute(
        select(CofogSpending.cofog, CofogSpending.amount).where(
            CofogSpending.year == year, CofogSpending.sector == sector
        )
    )
    return dict(rows.all())


def cofog_source(session: Session) -> Source:
    return Source(
        publisher=EUROSTAT_COFOG.publisher,
        record=EUROSTAT_COFOG.dataset,
        url=EUROSTAT_COFOG.list_url,
        fetched_at=last_fetched(session, EUROSTAT_COFOG),
        documents=session.scalar(select(func.count(CofogSpending.source_document_id.distinct()))),
    )


def _year(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def contracts(session: Session, year: int) -> Ours:
    """Contracts signed in the year, as every contract total counts them: of a counted
    kind, in a notice in force, signed inside the days of award notices held."""
    held = money.contracts_period(session)
    first, last = _year(year)
    period = held and (max(held[0], first), min(held[1], last))
    if period is None or period[0] > period[1]:
        return Ours(key="contracts", amount=0, count=0, source=_awards_source(session, 0))
    filters = [*in_period(session), *money.signed_in(period)]
    count, value, documents = session.execute(
        select(
            func.count(),
            money.contract_value,
            func.count(AwardNotice.source_document_id.distinct()),
        )
        .select_from(AwardContract)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .where(*filters)
    ).one()
    return Ours(
        key="contracts",
        amount=float(value),
        count=count,
        period_start=period[0],
        period_end=period[1],
        source=_awards_source(session, documents),
    )


def _awards_source(session: Session, documents: int) -> Source:
    return Source(
        publisher=SEAP_AWARDS.publisher,
        url=SEAP_AWARDS.list_url,
        fetched_at=last_fetched(session, SEAP_AWARDS),
        documents=documents,
    )


def direct_purchases(session: Session, year: int) -> Ours:
    """Accepted direct purchases finalized in the year, as every total counts them."""
    first, last = _year(year)
    filters = [money.day >= first, money.day <= last]
    found = summary(session, *filters)
    return Ours(
        key="direct_purchases",
        amount=found.value,
        count=found.accepted,
        period_start=found.first_day,
        period_end=found.last_day,
        source=list_source(session, *filters),
    )


def anghel_saligny(session: Session, year: int) -> Ours:
    """The ministry's payments in the files published in the year. A payment has no day
    of its own: the period is the files' days."""
    count, amount, first, last, documents = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PniasPayment.amount), 0),
            func.min(PniasPayment.published_on),
            func.max(PniasPayment.published_on),
            func.count(PniasPayment.source_document_id.distinct()),
        ).where(extract("year", PniasPayment.published_on) == year)
    ).one()
    return Ours(
        key="anghel_saligny",
        amount=float(amount),
        count=count,
        period_start=first,
        period_end=last,
        collected=count > 0,
        source=programme_source(session, PNIAS_PAYMENTS, documents),
    )


def _one(session: Session, *columns) -> tuple:
    return session.execute(select(*columns)).one()


def datasets(session: Session) -> list[tuple]:
    """The country's official totals, as (source, first day, last day, records, counts): the
    budget execution from 1 January of its first year to its newest month, COFOG over the
    years it holds figures for."""
    figures, months, first_month, last_month = _one(
        session,
        func.count(),
        func.count(BudgetExecution.period_end.distinct()),
        func.min(BudgetExecution.period_end),
        func.max(BudgetExecution.period_end),
    )
    cofog, first_year, last_year = _one(
        session, func.count(), func.min(CofogSpending.year), func.max(CofogSpending.year)
    )
    return [
        (
            BUDGET_EXECUTION,
            first_month and date(first_month.year, 1, 1),
            last_month,
            figures,
            {"months": months},
        ),
        (
            EUROSTAT_COFOG,
            first_year and date(first_year, 1, 1),
            last_year and date(last_year, 12, 31),
            cofog,
            {"years": last_year - first_year + 1 if first_year else 0},
        ),
    ]


def domains(session: Session) -> Domains | None:
    year = session.scalar(
        select(func.max(CofogSpending.year)).where(
            CofogSpending.sector == national.ALL_GOVERNMENT,
            CofogSpending.cofog == national.COFOG_TOTAL,
        )
    )
    if year is None:
        return None
    labels = dict(
        session.execute(
            select(CofogSpending.cofog, CofogSpending.label).where(
                CofogSpending.year == year, CofogSpending.sector == national.ALL_GOVERNMENT
            )
        ).all()
    )
    everyone = cofog(session, year, national.ALL_GOVERNMENT)
    local = cofog(session, year, national.LOCAL_GOVERNMENT)
    divisions = [
        Division(
            cofog=code,
            label=labels.get(code, code),
            total=lei(everyone[code]),
            local=lei(local.get(code, Decimal(0))),
            local_share=float(local.get(code, Decimal(0)) / everyone[code])
            if everyone[code]
            else 0,
        )
        for code in national.DIVISIONS
        if code in everyone
    ]
    updated = session.scalar(select(func.max(CofogSpending.updated_at)))
    return Domains(
        year=year,
        total=lei(everyone[national.COFOG_TOTAL]),
        # The day as Eurostat gives it: its time stamps are Luxembourg time, and 23:00
        # there is already the next day in Bucharest.
        updated_on=updated.astimezone(EUROSTAT_ZONE).date(),
        divisions=sorted(divisions, key=lambda division: division.total, reverse=True),
        source=cofog_source(session),
    )


def not_collected(**fields) -> Figure:
    return Figure(collected=False, **fields)
