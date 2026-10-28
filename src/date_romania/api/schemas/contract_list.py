"""What a list of award contracts says about itself under the filters chosen: the figures,
the charts and the options of each filter, for the list pattern of the site (DataTable)."""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.awards import ContractTotals, Period, Won
from date_romania.api.schemas.common import Answer, EntityRef
from date_romania.api.schemas.lists import Band, Option, Others, Point, Without


class ContractSummary(Answer):
    contracts: int
    value: float = Field(description="Lei without VAT; a contract with no value adds nothing.")
    without_value: int = Field(description="Contracts SEAP gives no value in lei for.")
    first_day: date | None = Field(description="The first day a contract found was signed.")
    last_day: date | None


class ContractParty(EntityRef):
    contracts: int
    value: float


class WonOption(Answer):
    value: Won
    count: int


class ContractOverview(Answer):
    """The contracts of an institution or a company under the filters chosen, in figures.

    The list holds only what totals may count: contracts signed in the period held, of a
    counted kind (never a framework agreement), in a notice still in force. It is never
    complete: SEAP publishes many contracts weeks after they are signed.
    """

    summary: ContractSummary
    whole: int = Field(
        description="Contracts of the same institution, or of the same company won the same "
        "way, with no other filter."
    )
    period: Period
    step: Literal["month", "day"] = Field(
        description="Months, or days when the contracts found span under two months."
    )
    points: list[Point] = Field(description="Contracts signed, and their value, per step.")
    party: Literal["supplier", "buyer"] = Field(
        description="The side `parties` lists: the other side of the buyer or supplier asked."
    )
    parties: list[ContractParty] = Field(
        description="The largest by value, at most five. Winners are ranked by the contracts "
        "they won alone: a contract won by an association is never given to one member."
    )
    others: Others
    associations: ContractTotals | None = Field(
        description="For the winners of a buyer's contracts: those won by associations, kept "
        "out of `parties` and `others`. Null for the buyers of a company's contracts."
    )
    won: list[WonOption] = Field(description="Contracts won alone, and by associations.")
    kinds: list[Option] = Field(description="1 ordinary contracts, 3 subsequent contracts.")
    eu_funded: list[Option] = Field(
        description="1: notices with a lot paid from EU funds; 0: notices that say no lot is. "
        "Notices that do not say are in neither."
    )
    bands: list[Band] = Field(description="Contracts by value in lei.")
    without: list[Without] = Field(
        description="Only when no contract is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
