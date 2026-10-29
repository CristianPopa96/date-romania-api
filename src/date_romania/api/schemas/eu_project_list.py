"""What a list of EU cohesion projects says about itself under the filters chosen, for the
list pattern of the site (DataTable). A programme's figures are never added to another's."""

from datetime import date

from pydantic import Field

from date_romania.api.schemas.common import Answer
from date_romania.api.schemas.eu_projects import EuStatus
from date_romania.api.schemas.lists import Band, Without


class EuProjectSummary(Answer):
    projects: int
    first_start: date | None = Field(description="The earliest start of a project found.")
    last_start: date | None


class ProgrammeOption(Answer):
    """One programme of the list under the other filters, with its own figures."""

    value: str = Field(description="The programme's code, e.g. 'POR'.")
    count: int
    total: float | None = Field(description="Lei; never add it to another programme's.")
    paid: float | None
    cut_off: date | None = Field(description="The day its list counts `paid` up to.")


class StatusOption(Answer):
    value: EuStatus
    count: int


class EuProjectOverview(Answer):
    """The projects under the filters chosen, in figures."""

    summary: EuProjectSummary
    whole: int = Field(description="Projects of the same beneficiary, with no other filter.")
    programmes: list[ProgrammeOption] = Field(
        description="Under every filter but the programme: the options of that filter, and "
        "each programme's value and amount paid, most projects first."
    )
    statuses: list[StatusOption]
    other_statuses: int = Field(
        description="Projects whose status the lists write in words of their own."
    )
    bands: list[Band] = Field(description="Projects by total value in lei.")
    without: list[Without] = Field(
        description="Only when no project is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
