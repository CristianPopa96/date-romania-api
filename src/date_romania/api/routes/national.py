"""The country's budget, and what our data shows of it: the home page (design round 18)."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import budget_law, local_money
from date_romania import national as rules
from date_romania.api.routes.common import Db
from date_romania.api.routes.national_common import (
    anghel_saligny,
    cofog,
    cofog_source,
    contracts,
    direct_purchases,
    domains,
    execution_lines,
    execution_source,
    latest_execution,
    lei,
    not_collected,
    total,
)
from date_romania.api.routes.programmes import source as programme_source
from date_romania.api.schemas.common import Source
from date_romania.api.schemas.national import (
    Budget,
    Category,
    Check,
    CheckPart,
    Executed,
    Figure,
    National,
    Ours,
    Planned,
    Segment,
)
from date_romania.models import LocalBudget, PnrrContract, PnrrEdition
from date_romania.sources import LOCAL_BUDGETS, PNRR

router = APIRouter(tags=["overview"])


def _planned(year: int, figure: str) -> Planned | None:
    row = budget_law.planned(year, figure)
    return row and Planned(
        amount=lei(row.amount),
        document=row.document.title,
        act=row.document.act,
        published_on=row.document.published_on,
        page=row.page,
        url=row.document.url,
    )


def _ours(session: Session, year: int) -> list[Ours]:
    return [
        contracts(session, year),
        direct_purchases(session, year),
        anghel_saligny(session, year),
        # Named per institution, payments do not name the supplier: not held.
        Ours(key="institution_payments", collected=False),
    ]


def _budget(session: Session) -> Budget | None:
    period_end = latest_execution(session)
    if period_end is None:
        # The law's plan is ours to give before any month of the execution is held.
        year = budget_law.latest_year(budget_law.SPENDING)
        if year is None:
            return None
        return Budget(
            year=year,
            planned=_planned(year, budget_law.SPENDING),
            planned_revenue=_planned(year, budget_law.REVENUE),
            executed=None,
            executed_share=None,
            categories=[],
            band=[],
            ours=_ours(session, year),
        )
    year = period_end.year
    spent = execution_lines(session, period_end, rules.CONSOLIDATED, "spending")
    earned = execution_lines(session, period_end, rules.CONSOLIDATED, "revenue")
    spending = spent["total"]
    named = [
        Category(key=key, amount=lei(total(spent, lines)))
        for key, lines in rules.CATEGORIES.items()
    ]
    other = spending - sum((total(spent, lines) for lines in rules.CATEGORIES.values()), Decimal(0))
    band = [total(spent, rules.BAND[key]) for key in (rules.NOT_PROCUREMENT, rules.PROCUREMENT)]
    band.append(spending - sum(band, Decimal(0)))
    planned = _planned(year, budget_law.SPENDING)
    return Budget(
        year=year,
        planned=planned,
        planned_revenue=_planned(year, budget_law.REVENUE),
        executed=Executed(
            period_start=date(year, 1, 1),
            period_end=period_end,
            months=period_end.month,
            spending=lei(spending),
            revenue=lei(earned["total"]),
            source=execution_source(session, period_end),
        ),
        executed_share=planned and lei(spending) / planned.amount,
        categories=[
            *sorted(named, key=lambda category: category.amount, reverse=True),
            Category(key=rules.OTHER, amount=lei(other)),
        ],
        band=[
            Segment(key=key, amount=lei(amount), share=share, lines=list(rules.BAND.get(key, ())))
            for key, amount, share in zip(
                (rules.NOT_PROCUREMENT, rules.PROCUREMENT, rules.REST),
                band,
                rules.whole_shares(band),
                strict=True,
            )
        ],
        ours=_ours(session, year),
    )


def _compared(key: str, official: Figure, ours: Figure, reason: str, **extra) -> Check:
    """A check both sides of which measure the same thing over the same period."""
    if official.amount is None or ours.amount is None:
        return Check(key=key, official=official, ours=ours, state=rules.NOT_YET, reason=reason)
    difference = ours.amount - official.amount
    return Check(
        key=key,
        official=official,
        ours=ours,
        state=rules.COMPARABLE,
        difference=difference,
        difference_share=difference / official.amount if official.amount else None,
        reason=reason,
        **extra,
    )


def _local_year(session: Session) -> int | None:
    return session.scalar(select(func.max(LocalBudget.year)))


def _local_ours(session: Session, year: int) -> tuple[Figure, dict[int, Decimal]]:
    """Every place's executed budget for the year, added up, and each column's sum."""
    rows = session.execute(
        select(LocalBudget.column_no, func.sum(LocalBudget.amount))
        .where(LocalBudget.year == year)
        .group_by(LocalBudget.column_no)
    ).all()
    places, documents = session.execute(
        select(
            func.count(LocalBudget.siruta.distinct()),
            func.count(LocalBudget.source_document_id.distinct()),
        ).where(LocalBudget.year == year)
    ).one()
    columns = dict(rows)
    figure = Figure(
        amount=float(columns.get(local_money.SPENDING_TOTAL, 0)),
        count=places,
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        source=programme_source(session, LOCAL_BUDGETS, documents),
    )
    return figure, columns


def _local_checks(session: Session) -> list[Check]:
    year = _local_year(session)
    if year is None:
        return []
    ours, columns = _local_ours(session, year)
    december = date(year, 12, 31)
    lines = execution_lines(session, december, rules.LOCAL, "spending")
    official = (
        Figure(
            amount=lei(lines["total"]),
            period_start=date(year, 1, 1),
            period_end=december,
            source=execution_source(session, december),
        )
        if "total" in lines
        else not_collected(period_start=date(year, 1, 1), period_end=december)
    )
    checks = [_compared(rules.LOCAL_BUDGETS, official, ours, rules.REASON_LOCAL_SCOPE)]

    local = cofog(session, year, rules.LOCAL_GOVERNMENT)
    chapters = {
        key: columns.get(number, Decimal(0)) for key, number in local_money.CHAPTERS.items()
    }
    parts = [
        CheckPart(
            key=key,
            divisions=list(divisions),
            official=lei(total(local, divisions)),
            ours=float(total(chapters, ours_keys)),
        )
        for key, (ours_keys, divisions) in rules.CHAPTER_DIVISIONS.items()
    ]
    official_domains = (
        Figure(
            amount=lei(total(local, rules.DIVISIONS)),
            count=len(rules.DIVISIONS),
            period_start=date(year, 1, 1),
            period_end=december,
            source=cofog_source(session),
        )
        if local
        else not_collected(period_start=date(year, 1, 1), period_end=december)
    )
    by_chapter = ours.model_copy(update={"amount": float(sum(chapters.values(), Decimal(0)))})
    # COFOG counts what was owed in the year, our budgets what was paid: two measures.
    checks.append(
        Check(
            key=rules.LOCAL_DOMAINS,
            official=official_domains,
            ours=by_chapter,
            state=rules.DIFFERENT_MEASURES if local else rules.NOT_YET,
            reason=rules.REASON_ACCRUAL_NOT_CASH,
            parts=parts if local else [],
        )
    )
    return checks


def _year_checks(session: Session, budget: Budget | None) -> list[Check]:
    if budget is None or budget.executed is None:
        return []
    executed = budget.executed
    spent = execution_lines(session, executed.period_end, rules.CONSOLIDATED, "spending")
    period = {"period_start": executed.period_start, "period_end": executed.period_end}

    def official(lines: tuple[str, ...]) -> Figure:
        return Figure(amount=lei(total(spent, lines)), source=executed.source, **period)

    checks = []
    credits = _planned(budget.year, budget_law.ANGHEL_SALIGNY)
    paid = next(figure for figure in budget.ours if figure.key == "anghel_saligny")
    if credits and paid.collected:
        planned = Figure(
            amount=credits.amount,
            period_start=date(budget.year, 1, 1),
            period_end=date(budget.year, 12, 31),
            source=Source(publisher=credits.act, record=credits.document, url=credits.url),
        )
        ours = Figure(**paid.model_dump(exclude={"key"}))
        checks.append(
            Check(
                key=rules.ANGHEL_SALIGNY,
                official=planned,
                ours=ours,
                state=rules.COMPARABLE,
                paid_share=ours.amount / planned.amount,
                reason=rules.REASON_CREDITS_YEAR,
            )
        )
    pnrr_contracts, edition = session.execute(
        select(func.count(PnrrContract.id), select(func.max(PnrrEdition.day)).scalar_subquery())
    ).one()
    checks.append(
        Check(
            key=rules.PNRR,
            official=official(rules.PNRR_PROJECT_LINES),
            ours=Figure(
                count=pnrr_contracts,
                unit="contracts",
                period_end=edition,
                collected=pnrr_contracts > 0,
                source=Source(publisher=PNRR.publisher, record=PNRR.dataset, url=PNRR.list_url),
            ),
            state=rules.NOT_YET,
            reason=rules.REASON_CONTRACTS_NOT_PAYMENTS,
        )
    )
    checks.append(
        Check(
            key=rules.EU_FUNDS,
            official=official(rules.EU_PROJECT_LINES),
            ours=not_collected(),
            state=rules.NOT_YET,
            reason=rules.REASON_PAYMENTS_UNDATED,
        )
    )
    return checks


def _ordered(checks: list[Check]) -> list[Check]:
    """By state (comparable, different measures, not yet), each the largest official
    figure first."""
    return sorted(
        checks,
        key=lambda check: (rules.STATES.index(check.state), -(check.official.amount or 0)),
    )


@router.get("/national")
def national(session: Db) -> National:
    """The country's budget against what our data shows. Official figures and ours each
    keep their own source and period; a difference is given only where both measure the
    same thing over the same period (`state`), and every check says why they differ.
    Amounts are lei: official ones as the ministry gives them (cash, with VAT where paid),
    ours without VAT."""
    budget = _budget(session)
    return National(
        budget=budget,
        checks=_ordered([*_local_checks(session), *_year_checks(session, budget)]),
        domains=domains(session),
    )
