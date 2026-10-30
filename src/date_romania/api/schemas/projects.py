"""Every project of every programme held, as one list (design D22): what each row says, and
what the list says about itself under the filters chosen.

Programmes publish their figures each at its own day and in its own way, so no sum is
given across them: a value total only once one programme is chosen.
"""

from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef, Source
from date_romania.api.schemas.lists import Band, Without

ProjectKind = Literal["anghel_saligny", "pnrr", "cohesion"]
ProjectStatus = Literal["in_progress", "finished", "terminated"]
Reach = Literal["beneficiary", "payments", "purchases", "companies"]


class CountyRef(Answer):
    code: str = Field(description="The two-letter code: 'CJ', 'B'.")
    name: str


class ProjectItem(Answer):
    kind: ProjectKind
    key: int = Field(
        description="The programme's own key: the ministry's project id (Anghel Saligny), the "
        "commitment id (PNRR, `id_angajament`), the SMIS code (cohesion)."
    )
    programme: str = Field(description="'AS', 'PNRR', or the cohesion programme's code.")
    programme_name: str
    period: str | None = Field(description="A cohesion programme's period: '2014-2020'.")
    title: str | None
    number: str | None = Field(description="The financing contract's number, where given.")
    beneficiary_name: str | None = Field(description="As the programme writes it.")
    beneficiary: EntityRef | None = Field(description="The beneficiary's entity, where tied.")
    counties: list[CountyRef] = Field(description="None for a national project.")
    value: float | None = Field(description="Lei, as the programme gives it.")
    status: ProjectStatus | None = Field(description="Ours, where the programme's words map.")
    status_written: str | None = Field(description="As the programme writes it.")
    reach: Reach = Field(description="The last step of the money's road followed.")
    gap: Literal["payments"] | None = Field(
        description="A step we cannot follow: the payments, when they are on a measure the "
        "beneficiary has several contracts on, or not published while a later step is."
    )


class ProjectList(Answer):
    total: int
    items: list[ProjectItem]


class ProjectsSummary(Answer):
    projects: int = Field(description="Natural persons' projects left out.")
    companies: int = Field(description="Of them, followed to the companies that delivered.")
    natural_persons: int = Field(
        description="Projects of natural persons under the filters, never listed by name."
    )
    value: float | None = Field(
        description="Lei: only when a programme is chosen and every project filtered is of "
        "that one programme (cohesion is several, each at its own cut-off), since programmes "
        "are never added together."
    )


class KindOption(Answer):
    value: ProjectKind
    count: int


class ProgrammeOption(Answer):
    value: str = Field(description="As in `programme`.")
    kind: ProjectKind
    name: str
    period: str | None
    count: int


class ProjectCountyOption(Answer):
    value: str = Field(description="The county's code, as in `county`.")
    name: str
    count: int


class ProjectStatusOption(Answer):
    value: ProjectStatus
    count: int


class ReachOption(Answer):
    value: Reach
    count: int


class ProjectsOverview(Answer):
    """The projects under the filters chosen, in figures; each option counted under every
    filter but its own."""

    summary: ProjectsSummary
    whole: int = Field(description="Every project held, natural persons' left out.")
    beneficiary: EntityRef | None = Field(description="The beneficiary filtered by.")
    kinds: list[KindOption]
    programmes: list[ProgrammeOption]
    counties: list[ProjectCountyOption]
    statuses: list[ProjectStatusOption]
    reaches: list[ReachOption] = Field(description="How far the road is followed.")
    bands: list[Band] = Field(description="Projects by value, in lei.")
    without: list[Without] = Field(
        description="Only when no project is found: what each filter given would leave out "
        "if it alone were removed, in the order of the parameters."
    )
    sources: list[Source] = Field(description="One per programme's source.")
