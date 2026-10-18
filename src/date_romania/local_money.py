"""What the Ministry of Development's budget file says, read once: the lines of revenue
and spending the site shows, by the file's own column numbers.

The file's total revenue (column 1) is own revenue (2) plus columns 8 to 21, less 15:
the income tax shares (3 to 7) and the sale of goods (15) are inside own revenue. The
lines below split it so they add up to the total exactly, with nothing counted twice
(checked for all 3,228 places of 2024). Spending (22) adds up both by title (23 to 37)
and by chapter (38 to 50).
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.models import LocalBudget

REVENUE_TOTAL, OWN_REVENUE, SPENDING_TOTAL, CAPITAL = 1, 2, 22, 35
INCOME_TAX = (3, 4, 5, 6, 7)

# Revenue lines in the order the site shows them (design round 8).
REVENUE_LINES: dict[str, tuple[int, ...]] = {
    "state_subsidies": (16,),
    "income_tax": INCOME_TAX,
    "vat": (8, 9, 10, 11, 12, 13),
    # Own revenue less the income tax shares inside it.
    "own_revenue": (OWN_REVENUE,),
    "eu_funds": (18, 19, 20),
    "other_administrations": (17,),
    "other": (14, 21),
}

# Spending by chapter (what it was spent on), by the file's column number.
CHAPTERS: dict[str, int] = {
    "general_services": 38,
    "defence_order": 39,
    "education": 40,
    "health": 41,
    "culture": 42,
    "social": 43,
    "housing": 44,
    "environment": 45,
    "economic_affairs": 46,
    "energy": 47,
    "agriculture": 48,
    "transport": 49,
    "other_economic": 50,
}


@dataclass(frozen=True)
class Budget:
    """One place's executed budget for one year, in lei."""

    year: int
    revenue: Decimal
    revenue_lines: dict[str, Decimal]
    spending: Decimal
    capital: Decimal
    chapters: dict[str, Decimal]
    document_id: int


def latest_year(session: Session, siruta: int) -> int | None:
    return session.scalar(select(func.max(LocalBudget.year)).where(LocalBudget.siruta == siruta))


def budget(session: Session, siruta: int) -> Budget | None:
    """The latest year held for a UAT or a county (its council), or None."""
    year = latest_year(session, siruta)
    if year is None:
        return None
    rows = session.scalars(
        select(LocalBudget).where(LocalBudget.siruta == siruta, LocalBudget.year == year)
    ).all()
    column = {row.column_no: row.amount for row in rows}

    def total(numbers: tuple[int, ...]) -> Decimal:
        return sum((column.get(number, Decimal(0)) for number in numbers), Decimal(0))

    lines = {key: total(numbers) for key, numbers in REVENUE_LINES.items()}
    lines["own_revenue"] -= total(INCOME_TAX)
    return Budget(
        year=year,
        revenue=column.get(REVENUE_TOTAL, Decimal(0)),
        revenue_lines=lines,
        spending=column.get(SPENDING_TOTAL, Decimal(0)),
        capital=column.get(CAPITAL, Decimal(0)),
        chapters={key: column.get(number, Decimal(0)) for key, number in CHAPTERS.items()},
        document_id=rows[0].source_document_id,
    )
