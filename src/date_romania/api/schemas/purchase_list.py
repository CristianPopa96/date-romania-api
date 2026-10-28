"""What a list of direct purchases says about itself under the filters chosen: the figures,
the charts and the options of each filter, for the list pattern of the site (DataTable)."""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef
from date_romania.api.schemas.purchases import Partner, Summary


class Option(Answer):
    """One option of a choice filter, with the purchases it leaves under the other filters."""

    value: int
    purchases: int


class Band(Answer):
    """Purchases whose closing value is from `start` up to `end` (excluded; null: no end)."""

    start: float
    end: float | None
    purchases: int


class Point(Answer):
    """Accepted purchases counted in totals, in one month or one day."""

    start: date = Field(description="The first day of the month, or the day.")
    accepted: int
    value: float


class Others(Answer):
    """The rest of the accepted purchases after the largest parties."""

    parties: int = Field(description="How many other parties, told apart by CUI or by text.")
    value: float


class Without(Answer):
    """How many purchases one filter alone keeps out, for a list it leaves empty."""

    param: str
    purchases: int


class PurchaseOverview(Answer):
    """The list of direct purchases under the filters chosen, in figures.

    Every figure counts the rows the filters give; `value` and the charts only the accepted
    purchases at or under their legal limit, as every total does.
    """

    summary: Summary
    whole: int = Field(description="Purchases of the same buyer or supplier, with no filter.")
    last_day_held: date | None = Field(
        description="The newest day collected: a month or day after it is not over yet."
    )
    step: Literal["month", "day"] = Field(
        description="Months, or days when the purchases found span under two months."
    )
    points: list[Point]
    party: Literal["supplier", "buyer"] = Field(
        description="The side `parties` lists: the other side of the buyer or supplier asked."
    )
    parties: list[Partner] = Field(description="The largest by value, at most five.")
    others: Others
    states: list[Option] = Field(description="SEAP's states, most purchases first.")
    contract_types: list[Option] = Field(
        description="1 goods, 2 services, 3 works, 0 for a purchase whose type is not known."
    )
    bands: list[Band] = Field(description="Purchases by closing value, whatever their state.")
    without: list[Without] = Field(
        description="Only when no purchase is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )


class PartyOption(EntityRef):
    purchases: int


class CpvOption(Answer):
    code: str
    name: str | None
    purchases: int
