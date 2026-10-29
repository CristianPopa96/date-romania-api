"""What the list of Anghel Saligny projects says about itself under the filters chosen, for
the list pattern of the site (DataTable). Every figure is of the ministry's payment files,
one programme, so they may be added."""

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef
from date_romania.api.schemas.lists import Band, Without
from date_romania.api.schemas.programmes import Match


class ProjectSummary(Answer):
    projects: int
    payments: int
    paid: float = Field(description="Lei, every payment held for these projects.")


class ProgrammeCountyOption(Answer):
    value: str = Field(description="The county's key, as in `county`.")
    name: str
    count: int
    paid: float = Field(description="Lei paid for its projects, under the other filters.")


class MatchOption(Answer):
    value: Match
    count: int


class WorksOption(Answer):
    value: str = Field(description="The kind of works as the ministry writes it.")
    count: int


class ProjectOverview(Answer):
    """The projects under the filters chosen, in figures."""

    summary: ProjectSummary
    whole: int = Field(description="Every project of the programme held.")
    builder: EntityRef | None = Field(description="The builder filtered by, where it is held.")
    counties: list[ProgrammeCountyOption] = Field(
        description="Under every filter but the county, the most paid first."
    )
    matches: list[MatchOption] = Field(description="Under every filter but the match.")
    categories: list[WorksOption] = Field(description="Under every filter but the category.")
    bands: list[Band] = Field(description="Projects by the amount paid, in lei.")
    without: list[Without] = Field(
        description="Only when no project is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
