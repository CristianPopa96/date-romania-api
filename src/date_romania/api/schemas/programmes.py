"""The Anghel Saligny programme: its figures, its projects and the trace of one."""

from datetime import date
from typing import Literal

from pydantic import ConfigDict, Field

from date_romania.api.schemas.common import Answer, EntityRef, Source

# Whether a contract was found for a payment or a project, and how sure a tie is.
Match = Literal["one", "several", "none", "unnamed"]
Confidence = Literal["probable", "possible"]


class MatchCount(Answer):
    count: int = 0
    amount: float = 0


class ProgrammeMatch(Answer):
    """Payments or projects by whether a SEAP contract was found for them."""

    one: MatchCount = Field(MatchCount(), description="Tied to the contracts of one notice.")
    several: MatchCount = Field(
        MatchCount(), description="Tied to more than one notice; the files do not say which."
    )
    none: MatchCount = Field(
        MatchCount(), description="The builder is named by tax ID and no contract was found."
    )
    unnamed: MatchCount = Field(
        MatchCount(),
        description="The file names the builder by name only, so nothing can be tied.",
    )


class ProgrammeGroup(Answer):
    key: str
    name: str
    payments: int
    amount: float
    projects: int


class ProgrammeFile(Answer):
    """One payment file. The files give no payment day; the day in their name stands for it."""

    published_on: date | None
    payments: int
    amount: float
    with_tax_id: int = Field(description="Payments that name the builder by tax ID.")


class Programme(Answer):
    """The Anghel Saligny programme, from the ministry's payment files."""

    payments: int = Field(description="Settlement requests the ministry paid.")
    amount: float
    projects: int
    town_halls: int = Field(description="Town halls and county councils that were paid.")
    builders: int = Field(description="Builders named by tax ID.")
    first_day: date | None = Field(description="The day of the first payment file held.")
    last_day: date | None
    networks: list[ProgrammeGroup] = Field(description="`infra` (roads, water, sewage), `gas`.")
    counties: list[ProgrammeGroup]
    files: list[ProgrammeFile]
    payments_match: ProgrammeMatch
    projects_match: ProgrammeMatch
    payments_possible: ProgrammeMatch = Field(
        description="Of the payments tied (`one` or `several`), those whose links are all "
        "only possible: other buyers carry the town hall's name, and nothing says which "
        "county the contract's buyer is in. The rest are probable. No link is sure."
    )
    contracts_first_day: date | None = Field(
        description="The contracts searched were published in SEAP between these two days."
    )
    contracts_last_day: date | None
    source: Source
    contracts_source: Source


class ProjectRow(Answer):
    id: int = Field(description="The ministry's id of the project.")
    investment: str | None
    county: str
    county_name: str
    town_hall: str = Field(description="The beneficiary as the ministry names it.")
    network: str
    category: str | None
    total_value: float | None
    state_budget_value: float | None
    paid: float = Field(description="The payments held for this project, added up.")
    payments: int
    match: Match = Field(description="one, several, none or unnamed")


class ProjectPage(Answer):
    total: int
    items: list[ProjectRow]


class ProjectPayment(Answer):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="The ministry's number for the request: ASA4-<id>.")
    published_on: date | None = Field(description="The day of the file that lists it.")
    registered_on: date | None
    requested_on: date | None
    amount: float
    progress: str | None = Field(description="As written in the file.")
    builder_text: str | None


class TraceParty(Answer):
    cui: int | None = Field(description="Null when the files give only the name.")
    name: str | None
    entity: EntityRef | None = Field(description="Set when the company has a page.")


class TraceContract(Answer):
    """A contract from SEAP's exports that a payment could be tied to."""

    notice_no: str | None
    notice_id: int | None = Field(
        description="Our id of the award notice, when we also collected it from SEAP."
    )
    notice_date: date | None
    contract_no: str | None
    contract_date: date | None
    title: str | None = Field(description="Only the 2021 and 2022 exports carry one.")
    lot: str | None
    value_ron: float | None
    procedure_type: str | None
    contract_type: str | None
    is_framework: bool | None
    buyer: EntityRef | None
    buyer_text: str | None
    confidence: Confidence = Field(
        description="probable: an export puts the buyer in the project's county, or no "
        "other buyer carries that name. possible: other buyers do."
    )
    method: str = Field(description="What the link rests on.")
    partners: list[TraceParty] = Field(
        description="The other winners, when the contract was won by an association. "
        "The value is the whole contract's, never split."
    )
    ratio: float | None = Field(description="Contract value over the project's total value.")


class TraceBuilder(TraceParty):
    payments: int = Field(description="The payments of the project that name this builder.")
    amount: float
    match: Match = Field(description="one, several, none or unnamed")
    contracts: list[TraceContract]


class Project(ProjectRow):
    town_hall_entity: EntityRef | None = Field(
        description="The buyer of the tied contracts: the town hall as SEAP holds it."
    )
    ministry_contract_no: str | None
    ministry_contract_date: date | None
    poim: bool | None
    progress: str | None = Field(description="From the latest payment that gives one.")
    estimated_end: date | None
    items: list[ProjectPayment]
    builders: list[TraceBuilder]
    designers: list[TraceParty]
    confidence: Confidence | None = Field(
        description="The weakest link among the contracts shown; null when there are none."
    )
    source: Source
    contracts_source: Source
