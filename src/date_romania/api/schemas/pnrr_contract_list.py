"""What a list of PNRR financing contracts says about itself under the filters chosen, for
the list pattern of the site (DataTable)."""

from pydantic import Field

from date_romania.api.schemas.common import Answer
from date_romania.api.schemas.lists import Band, Without
from date_romania.api.schemas.pnrr import PnrrStatus


class PnrrContractSummary(Answer):
    contracts: int = Field(description="Contracts listed: never a natural person's.")
    value: float | None = Field(description="Lei, every measure of each contract added up.")
    natural_persons: int = Field(
        description="Natural persons' contracts the filters also give: counted, never named."
    )


class MeasureOption(Answer):
    value: str = Field(description="The measure's code, e.g. 'C10.I3'.")
    count: int


class PnrrStatusOption(Answer):
    value: PnrrStatus
    count: int = Field(description="Contracts whose measures all give this status.")


class PnrrContractOverview(Answer):
    """The contracts under the filters chosen, in figures."""

    summary: PnrrContractSummary
    whole: int = Field(description="Contracts of the same beneficiary, with no other filter.")
    measures: list[MeasureOption] = Field(description="Under every filter but the measure.")
    statuses: list[PnrrStatusOption]
    measures_differ: int = Field(
        description="Contracts whose measures give different statuses: under no status."
    )
    bands: list[Band] = Field(description="Contracts by value in lei.")
    progress: list[Band] = Field(
        description="Contracts by physical progress, 0 to 1, where their measures agree on it; "
        "the last band is 1, finished."
    )
    without: list[Without] = Field(
        description="Only when no contract is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
