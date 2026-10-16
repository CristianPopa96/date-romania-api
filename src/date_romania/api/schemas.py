"""Shapes of the API answers. Amounts are in lei, without VAT, as SEAP publishes them."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from date_romania.money import (
    DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON,
    DIRECT_PURCHASE_LIMIT_RON,
)

# The legal limits as the descriptions print them, e.g. "900,400 lei".
_LIMIT = f"{DIRECT_PURCHASE_LIMIT_RON:,.0f} lei"
_LIMIT_GOODS_SERVICES = f"{DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON:,.0f} lei"


class Source(BaseModel):
    """Where a figure comes from, so the site can show it next to the figure."""

    publisher: str
    record: str | None = Field(None, description="The publisher's own number for the record.")
    url: str | None = None
    fetched_at: datetime | None = Field(None, description="When we last fetched it.")
    document_id: int | None = Field(None, description="Our id of the stored raw response.")
    # Only for one record: a figure added up from many responses has no single file.
    sha256: str | None = Field(
        None, description="SHA-256 of the stored raw response, as it was received."
    )
    parser_version: int | None = Field(
        None, description="Version of the parser that read the record from it."
    )


class EntityRef(BaseModel):
    # Filled straight from an `Entity` row.
    model_config = ConfigDict(from_attributes=True)

    cui: int
    name: str
    kind: str = Field(description="authority, company or other")


class EntityOut(EntityRef):
    county: str | None
    locality: str | None


class SearchResults(BaseModel):
    items: list[EntityOut]


class Summary(BaseModel):
    """Direct purchases in a period. `value` counts accepted purchases only."""

    purchases: int = Field(description="All finished purchases, whatever their outcome.")
    accepted: int = Field(description="Purchases where the offer was accepted.")
    value: float = Field(description="Sum of the accepted purchases at or under `limit`.")
    above_limit: int = Field(
        description=f"Accepted purchases published with a value above {_LIMIT}, the highest "
        "legal limit for a direct purchase (the one for works). They are not counted in "
        "`value` and are listed separately. A goods or services purchase between its own "
        f"limit of {_LIMIT_GOODS_SERVICES} and this one is not marked."
    )
    above_limit_value: float
    first_day: date | None = Field(description="First day we have data for.")
    last_day: date | None


class Purchase(BaseModel):
    id: int
    code: str | None
    name: str | None
    state_id: int | None
    state: str | None
    cpv_code: str | None
    cpv_name: str | None
    buyer: EntityRef | None = Field(description="Null when SEAP gives no valid CUI.")
    buyer_text: str | None = Field(description="The buyer as SEAP writes it.")
    supplier: EntityRef | None
    supplier_text: str | None
    published_at: datetime | None
    finalized_at: datetime | None
    estimated_value: float | None
    value: float | None = Field(description="The closing value.")
    above_limit: bool = Field(
        description=f"The purchase was accepted with a value above {_LIMIT}, the highest "
        "legal limit for a direct purchase. Always false for a purchase that was not accepted."
    )
    source: Source


class PurchasePage(BaseModel):
    total: int
    items: list[Purchase]


class Partner(EntityRef):
    accepted: int
    value: float


class EntityPage(BaseModel):
    entity: EntityOut
    direct_purchases: Summary
    partners: list[Partner] = Field(
        description="The suppliers of an institution, or the institutions a supplier sold to, "
        "by value of accepted purchases."
    )
    source: Source


class RankingRow(Partner):
    rank: int


class Ranking(BaseModel):
    date_from: date | None
    date_to: date | None
    items: list[RankingRow]
    source: Source


class CpvDivision(BaseModel):
    code: str = Field(description="The first two digits of a CPV code, e.g. 45.")
    name: str | None = Field(description="SEAP's name for the division, where a row gives it.")


class NearLimitPurchase(BaseModel):
    id: int
    code: str | None
    name: str | None
    finalized_at: datetime | None
    value: float = Field(description="Closing value in lei without VAT.")


class NearLimitPair(BaseModel):
    """One buyer and one supplier with repeated accepted purchases just under a limit."""

    buyer: EntityRef
    supplier: EntityRef
    contract_type: int = Field(description="1 goods, 2 services, 3 works.")
    limit: float = Field(description="The legal limit for that type, in lei without VAT.")
    purchases: int
    value: float
    items: list[NearLimitPurchase] = Field(description="The purchases, oldest first.")


class NearLimitRule(BaseModel):
    share: float = Field(description="A value from this share of the limit up to it is near it.")
    repeats: int = Field(description="Purchases a pair needs to be listed.")
    limits: dict[int, float] = Field(description="The limit of each contract type.")


class NearLimitPattern(BaseModel):
    rule: NearLimitRule
    first_day: date | None = Field(description="The first day of a purchase checked.")
    last_day: date | None = Field(description="The last day of a purchase checked.")
    pairs: int = Field(description="Every pair that matches, beyond the ones listed.")
    items: list[NearLimitPair]
    checked: int = Field(
        description="Accepted purchases of known contract type: the ones that were checked."
    )
    accepted_total: int = Field(description="Accepted purchases, checked or not.")
    unknown_type: int = Field(
        description="Accepted purchases of unknown contract type, which cannot be checked."
    )
    source: Source


class Stats(BaseModel):
    direct_purchases: Summary
    institutions: int = Field(description="Institutions with at least one purchase.")
    suppliers: int
    limit: float = Field(
        description="The limit used for `above_limit`: the legal one for works, the highest a "
        "direct purchase may have, in lei without VAT."
    )
    source: Source


class Period(BaseModel):
    """The days we hold. Contract totals count the contracts signed inside them."""

    first_day: date | None
    last_day: date | None


class Winner(BaseModel):
    supplier: EntityRef | None = Field(description="Null for a foreign company or an invalid CUI.")
    text: str | None = Field(description="The winner as SEAP writes it.")
    country: str | None


class Contract(BaseModel):
    """One contract of an award notice. `value` is in lei without VAT."""

    id: int
    notice_id: int
    notice_no: str | None
    notice_title: str | None
    contract_no: str | None
    title: str | None
    signed_at: datetime | None
    kind: int | None = Field(description="1 ordinary, 2 framework agreement, 3 subsequent.")
    counted: bool = Field(
        description="False for a framework agreement: its value is a ceiling, not money "
        "committed, and is never added to a total."
    )
    lots: str | None
    value: float | None
    original_value: float | None = Field(description="In `currency`, when not in lei.")
    currency: str | None
    buyer: EntityRef | None
    buyer_text: str | None
    procedure_type: str | None
    cpv_code: str | None
    winners: list[Winner] = Field(
        description="In SEAP's order. More than one is an association: one value for all of "
        "them, never split, and SEAP does not say who leads."
    )
    source: Source


class ContractPage(BaseModel):
    total: int
    period: Period | None = Field(description="Null for the contracts of one notice.")
    items: list[Contract]


class NoticeDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    call_notice_no: str | None = Field(description="The notice that opened the procedure.")
    call_published_at: datetime | None
    ted_notice_no: str | None
    lots: int
    eu_funded: bool | None = Field(description="Null when SEAP does not say.")
    financing_types: list[str]
    eu_funds: list[str]
    eu_project: str | None


class AwardNoticeOut(BaseModel):
    id: int
    notice_no: str | None
    notice_type_id: int | None
    title: str | None
    buyer: EntityRef | None
    buyer_text: str | None
    cpv_code: str | None
    cpv_name: str | None
    contract_type: str | None
    procedure_type: str | None
    published_at: datetime | None = Field(description="Of the version we hold, the latest.")
    first_published_at: datetime | None = Field(
        description="The earliest publication SEAP lists. Null until the versions are collected."
    )
    versions: int | None = Field(description="Null until the versions are collected.")
    detail: NoticeDetail | None = Field(description="Null until the detail is collected.")
    contracts: int
    ordinary: int
    frameworks: int
    subsequent: int
    total: float = Field(
        description="Ordinary and subsequent contracts of this notice, whatever their date."
    )
    source: Source


class ContractTotals(BaseModel):
    contracts: int
    value: float


class InstitutionContracts(ContractTotals):
    period: Period
    source: Source


class SupplierContracts(BaseModel):
    period: Period
    alone: ContractTotals
    association: ContractTotals = Field(
        description="The whole value of the contracts won with others; never add it to `alone`."
    )
    source: Source


class ContractRankingRow(EntityRef):
    rank: int
    contracts: int
    value: float


class ContractRanking(BaseModel):
    period: Period
    won: str | None = Field(description="alone or association, for a ranking of winners.")
    items: list[ContractRankingRow]
    source: Source


class Dataset(BaseModel):
    """One source as we hold it, for the table that says what the site is built on."""

    key: str
    publisher: str
    first_day: date | None
    last_day: date | None
    records: int
    complete: bool = Field(
        description="False when the source publishes late, so the period keeps filling in."
    )
    fetched_at: datetime | None
    days_collected: int = Field(description="Days of the period read in full from the source.")
    days_partial: int = Field(
        description="Days of the period the source would not give in full; they wait to be read."
    )
    documents: int = Field(description="Raw answers kept from the source, each under its hash.")
    rejected_rows: int | None = Field(
        description="Rows of those answers the parser could not read, logged and left out. "
        "Null until every answer was seen by a parser that counts them."
    )
    counts: dict[str, int] = Field(
        description="What is held, by kind of row. `records` is the one the totals use."
    )


class Datasets(BaseModel):
    items: list[Dataset]


class MatchCount(BaseModel):
    count: int = 0
    amount: float = 0


class ProgrammeMatch(BaseModel):
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


class ProgrammeGroup(BaseModel):
    key: str
    name: str
    payments: int
    amount: float
    projects: int


class ProgrammeFile(BaseModel):
    """One payment file. The files give no payment day; the day in their name stands for it."""

    published_on: date | None
    payments: int
    amount: float
    with_tax_id: int = Field(description="Payments that name the builder by tax ID.")


class Programme(BaseModel):
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


class ProjectRow(BaseModel):
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
    match: str = Field(description="one, several, none or unnamed")


class ProjectPage(BaseModel):
    total: int
    items: list[ProjectRow]


class ProjectPayment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="The ministry's number for the request: ASA4-<id>.")
    published_on: date | None = Field(description="The day of the file that lists it.")
    registered_on: date | None
    requested_on: date | None
    amount: float
    progress: str | None = Field(description="As written in the file.")
    builder_text: str | None


class TraceParty(BaseModel):
    cui: int | None = Field(description="Null when the files give only the name.")
    name: str | None
    entity: EntityRef | None = Field(description="Set when the company has a page.")


class TraceContract(BaseModel):
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
    confidence: str = Field(
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
    match: str = Field(description="one, several, none or unnamed")
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
    confidence: str | None = Field(
        description="The weakest link among the contracts shown; null when there are none."
    )
    source: Source
    contracts_source: Source


class ReportIn(BaseModel):
    """What a reader says is wrong on a page of the site."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page: str | None = Field(None, max_length=300, description="The page the report is about.")
    message: str = Field(min_length=10, max_length=4000, description="What is wrong.")
    evidence: str | None = Field(
        None, max_length=500, description="A link or a document that shows the right value."
    )


class ReportReceived(BaseModel):
    id: int


class Correction(BaseModel):
    """A report we checked and acted on: where, and what we changed, in our words."""

    page: str | None = Field(
        description="The address of the page on the site; null when the report named no such page."
    )
    correction: str
    corrected_on: date


class Corrections(BaseModel):
    items: list[Correction]
