"""Award notices and their contracts, the contract totals and rankings."""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from date_romania.api.schemas.common import Answer, EntityRef, Period, Source

# A contract won by one company, or by an association of several.
Won = Literal["alone", "association"]


class Winner(Answer):
    supplier: EntityRef | None = Field(description="Null for a foreign company or an invalid CUI.")
    text: str | None = Field(description="The winner as SEAP writes it.")
    country: str | None


class Contract(Answer):
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


class ContractPage(Answer):
    total: int
    period: Period | None = Field(description="Null for the contracts of one notice.")
    items: list[Contract]


class NoticeDetail(Answer):
    model_config = ConfigDict(from_attributes=True)

    call_notice_no: str | None = Field(description="The notice that opened the procedure.")
    call_published_at: datetime | None
    ted_notice_no: str | None
    lots: int
    eu_funded: bool | None = Field(description="Null when SEAP does not say.")
    financing_types: list[str]
    eu_funds: list[str]
    eu_project: str | None


class AwardNoticeOut(Answer):
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
    replaced_by: int | None = Field(
        description="The newest notice we hold that SEAP published in place of this one. "
        "Its contracts then count there, not here."
    )
    detail: NoticeDetail | None = Field(description="Null until the detail is collected.")
    contracts: int
    ordinary: int
    frameworks: int
    subsequent: int
    total: float = Field(
        description="Ordinary and subsequent contracts of this notice, whatever their date."
    )
    source: Source


class ContractTotals(Answer):
    contracts: int
    value: float


class InstitutionContracts(ContractTotals):
    period: Period
    source: Source


class SupplierContracts(Answer):
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


class ContractRanking(Answer):
    period: Period
    won: Won | None = Field(description="alone or association, for a ranking of winners.")
    total: int = Field(description="Every party ranked under the filters, beyond the page.")
    items: list[ContractRankingRow] = Field(
        description="`rank` is the place in the order asked for, counted from the first page."
    )
    source: Source
