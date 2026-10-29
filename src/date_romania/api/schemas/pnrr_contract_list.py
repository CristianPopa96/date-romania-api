"""What a list of PNRR financing contracts says about itself under the filters chosen, for
the list pattern of the site (DataTable)."""

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef
from date_romania.api.schemas.lists import Band, Others, Without
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


class CountyOption(Answer):
    value: str = Field(description="The county as the dashboard writes it.")
    count: int


class PnrrBeneficiaryBar(Answer):
    """One of the beneficiaries with the largest value under the filters: never a natural
    person."""

    name: str | None = Field(description="As the dashboard writes it.")
    entity: EntityRef | None = Field(description="The entity of its CUI, where it is held.")
    contracts: int
    value: float = Field(description="Lei, every measure of each contract added up.")


class PnrrStatusOption(Answer):
    value: PnrrStatus
    count: int = Field(description="Contracts whose measures all give this status.")


class PnrrContractOverview(Answer):
    """The contracts under the filters chosen, in figures."""

    summary: PnrrContractSummary
    whole: int = Field(
        description="Contracts of the list's own beneficiary or measure (`scope`), with no "
        "other filter; with no scope, every contract listed."
    )
    measures: list[MeasureOption] = Field(description="Under every filter but the measure.")
    counties: list[CountyOption] = Field(description="Under every filter but the county.")
    statuses: list[PnrrStatusOption]
    measures_differ: int = Field(
        description="Contracts whose measures give different statuses: under no status."
    )
    bands: list[Band] = Field(description="Contracts by value in lei.")
    progress: list[Band] = Field(
        description="Contracts by physical progress, 0 to 1, where their measures agree on it; "
        "the last band is 1, finished."
    )
    beneficiaries: list[PnrrBeneficiaryBar] = Field(
        description="The beneficiaries with the largest value under every filter but the "
        "beneficiary, told apart by CUI or by name."
    )
    others: Others = Field(description="The beneficiaries after those, and their value.")
    without: list[Without] = Field(
        description="Only when no contract is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
