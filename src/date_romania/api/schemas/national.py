"""The country's budget against what our data shows (the home page, design round 18)."""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, Source


class Planned(Answer):
    """A figure of the planned year, entered by hand from its document."""

    amount: float = Field(description="Lei.")
    document: str = Field(description="The document's title.")
    act: str = Field(description="The act it goes with, as the site names it.")
    published_on: date
    page: int = Field(description="The page of the PDF the figure is printed on.")
    url: str


class Executed(Answer):
    """The execution of the consolidated general budget from 1 January, cash."""

    period_start: date
    period_end: date
    months: int = Field(description="How many months of the year the execution covers.")
    spending: float = Field(description="Lei.")
    revenue: float = Field(description="Lei.")
    source: Source


class Category(Answer):
    key: str = Field(description="A group of spending lines; `other` holds the lines not named.")
    amount: float


class Segment(Answer):
    key: Literal["not_procurement", "procurement", "rest"]
    amount: float
    share: int = Field(description="Whole percent of the total; the three add up to 100.")
    lines: list[str] = Field(description="The execution's lines it holds; empty for `rest`.")


class Figure(Answer):
    """One figure with its own period and source; our figures are without VAT."""

    amount: float | None = Field(None, description="Lei.")
    count: int | None = Field(None, description="Records behind the figure.")
    unit: Literal["lei", "contracts"] = "lei"
    period_start: date | None = None
    period_end: date | None = None
    collected: bool = Field(True, description="False while we do not hold this figure.")
    source: Source | None = None


class Ours(Figure):
    key: str


class Budget(Answer):
    """Block 1 ("Bugetul țării") and block 2 ("Ce parte din acești bani putem urmări")."""

    year: int
    planned: Planned | None = Field(description="Total spending planned; null if not entered.")
    planned_revenue: Planned | None
    executed: Executed | None = Field(description="Null until the year's execution is held.")
    executed_share: float | None = Field(
        description="Executed spending over planned, 0 to 1: the same measure for one year."
    )
    categories: list[Category] = Field(description="Largest first, `other` last.")
    band: list[Segment] = Field(description="In this order: not_procurement, procurement, rest.")
    ours: list[Ours] = Field(
        description="Our figures for the year, beside the band: never subtracted from it."
    )


class CheckPart(Answer):
    key: str = Field(description="Our chapter, by `local_money.CHAPTERS`.")
    divisions: list[str] = Field(description="The COFOG divisions it is set against.")
    official: float
    ours: float


class Check(Answer):
    """An official figure against ours. `difference` only when `comparable`."""

    key: str
    official: Figure
    ours: Figure
    comparable: bool
    difference: float | None = Field(None, description="Ours minus official, in lei.")
    difference_share: float | None = Field(
        None, description="`difference` over the official figure."
    )
    paid_share: float | None = Field(
        None, description="For a plan against its payments: paid over planned, 0 to 1."
    )
    reason: str = Field(description="Why they differ or do not compare; always given.")
    parts: list[CheckPart] = Field(default_factory=list)


class Division(Answer):
    cofog: str
    label: str = Field(description="Eurostat's English label; the site words it.")
    total: float = Field(description="All of public administration, lei.")
    local: float = Field(description="Local government, lei.")
    local_share: float = Field(description="Local over total, 0 to 1, both from COFOG.")


class Domains(Answer):
    """Block 4 ("Pe domenii"): COFOG by division, largest first."""

    year: int
    total: float
    updated_on: date = Field(description="When Eurostat last updated the table, its own day.")
    divisions: list[Division]
    source: Source


class National(Answer):
    budget: Budget | None = Field(description="Null until the budget execution is held.")
    checks: list[Check] = Field(
        description="Comparable checks first, largest official figure first; then the rest."
    )
    domains: Domains | None = Field(description="Null until COFOG is held.")
