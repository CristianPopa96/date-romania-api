"""An institution's budget: the executed budget of a town hall or county council, and the
Anghel Saligny payments to it. Each figure names its own period; none is added to
another."""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef, Source

RevenueLine = Literal[
    "state_subsidies",
    "income_tax",
    "vat",
    "own_revenue",
    "eu_funds",
    "other_administrations",
    "other",
]
Chapter = Literal[
    "general_services",
    "defence_order",
    "education",
    "health",
    "culture",
    "social",
    "housing",
    "environment",
    "economic_affairs",
    "energy",
    "agriculture",
    "transport",
    "other_economic",
]
PlaceKind = Literal["county", "municipality", "town", "commune", "sector"]


class PlaceRef(Answer):
    siruta: int
    name: str = Field(description="As the national list of places writes it.")
    kind: PlaceKind


class RevenueAmount(Answer):
    line: RevenueLine
    amount: float


class ChapterAmount(Answer):
    chapter: Chapter
    amount: float


class LocalBudgetOut(Answer):
    """A year of a town hall's or county council's budget, executed to 31 December."""

    year: int
    executed_on: date = Field(description="The day the figures run to: 31 December.")
    revenue: float = Field(description="Total revenue; the lines add up to it exactly.")
    revenue_lines: list[RevenueAmount] = Field(description="In the order the site shows them.")
    spending: float
    capital: float = Field(description="Capital spending (investments), part of `spending`.")
    chapters: list[ChapterAmount] = Field(
        description="Spending by what it was for, largest first; they add up to `spending`."
    )
    source: Source


class ProgrammePayments(Answer):
    """The Anghel Saligny payments to this town hall or county council, from the
    ministry's files. Never added to the budget's state subsidies: the periods differ,
    and the budget file does not say which programme a subsidy came from."""

    county: str = Field(description="As the files write it, the key of the programme's counties.")
    town_hall: str = Field(description="As the files write it, to find its projects.")
    amount: float
    payments: int
    projects: int
    first_published: date | None = Field(description="Day of the first file that lists one.")
    last_published: date | None
    source: Source


class InstitutionBudget(Answer):
    """`place` is the UAT or county the institution governs, when it is a town hall or
    a county council; every other institution has none, and no budget held."""

    place: PlaceRef | None
    funder: EntityRef | None = Field(
        description="The institution that funds it (its main credit holder), when held."
    )
    budget: LocalBudgetOut | None
    programme_payments: ProgrammePayments | None
