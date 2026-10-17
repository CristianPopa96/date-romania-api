"""Award notices and their contracts, the contract totals and rankings."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from date_romania.api.schemas.common import EntityRef, Period, Source


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
