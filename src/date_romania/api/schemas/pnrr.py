"""The Recovery and Resilience Plan: the programme, a measure, a contract.

Natural persons (afforestation grants) never appear by name: their contracts are left out
of every list and have no page, and an answer that leaves some out says how many.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from date_romania.api.schemas.common import Answer, EntityRef, Source

PnrrStatus = Literal["in_progress", "under_30", "finished"]


class PnrrMeasureRow(Answer):
    code: str = Field(description="'C10.I3', or 'C10.I3.a' for a sub-measure.")
    component: str
    name: str | None
    ministry: str | None = Field(description="The coordinating ministry, e.g. 'MDLPA'.")
    funding: str | None = Field(description="'grant' or 'loan'.")
    allocated_eur: float | None = Field(description="Published in euro only.")
    contracted_ron: float | None = Field(description="EU money contracted, published in lei only.")
    paid_ron: float | None
    paid_eur: float | None
    contracts: int = Field(description="Contracts held on the measure, natural persons' too.")


class PnrrTopRecipient(Answer):
    cui: int
    name: str | None = Field(description="As the dashboard writes it.")
    entity: EntityRef | None = Field(
        description="The entity we hold under the CUI, with its kind: which page it opens."
    )
    received: float | None = Field(description="Lei received, grants and loans together.")
    last_received_on: date | None


class PnrrProgramme(Answer):
    """The plan as one edition of MIPE's dashboard gives it."""

    edition: date = Field(description="The day of the dashboard edition held.")
    allocated_eur: float | None
    paid_eur: float | None
    received_eur: float | None = Field(description="What the EU has paid Romania so far.")
    contracts: int | None = Field(description="As the edition counts them.")
    beneficiaries_contracted: int | None
    beneficiaries_paid: int | None
    contracted_ron: float = Field(description="EU money contracted, the measures added up.")
    measures: list[PnrrMeasureRow]
    top: list[PnrrTopRecipient] = Field(
        description="The largest final recipients (EU Reg. 2021/241 art. 25a), largest first."
    )
    source: Source


class PnrrContractRow(Answer):
    id: int = Field(description="MIPE's commitment id: the page's address.")
    number: str | None = Field(description="The contract's own number; not unique.")
    title: str | None
    beneficiary: EntityRef | None
    beneficiary_name: str | None = Field(description="As the dashboard writes it.")
    county: str | None
    total: float | None = Field(description="Lei, every measure of the contract added up.")
    status: PnrrStatus | None = Field(
        description="Null when its measures differ, or when none gives a status we know."
    )
    physical_progress: float | None = Field(
        description="0 to 1; null when its measures differ, or when none gives it."
    )
    measures_differ: bool = Field(
        description="Its measures report different statuses or progress: see the contract."
    )


class PnrrContractPage(Answer):
    total: int
    items: list[PnrrContractRow]
    natural_persons: int = Field(
        description="Contracts of natural persons that match and are left out: never named."
    )


class PnrrMeasure(PnrrMeasureRow):
    ministry_name: str | None
    paid_without_contract: float = Field(
        description="Paid on the measure to beneficiaries with no contract on it in the list "
        "(state companies, transfers)."
    )
    payments_without_contract: int
    natural_persons: int = Field(description="Contracts of natural persons on the measure.")
    counties: list[str] = Field(
        description="The counties of its listed contracts, as the dashboard writes them: what "
        "`/contracts?county=` takes."
    )
    edition: date
    source: Source


class PnrrLine(Answer):
    """The part of a contract under one measure and funding, as the dashboard gives it."""

    measure: str
    measure_name: str | None
    funding: str | None
    total: float | None
    eu: float | None
    status: PnrrStatus | None
    ends_on: date | None
    physical_progress: float | None
    financial_progress: float | None


class PnrrPayment(Answer):
    paid_on: date | None
    amount: float
    funding: str | None


class PnrrSibling(Answer):
    id: int
    number: str | None
    title: str | None
    total: float | None


class PnrrPayments(Answer):
    """The payments to the beneficiary on one measure. They name the beneficiary and the
    measure, never the contract: they are this contract's only when it is the beneficiary's
    one contract on the measure (`contracts` is 1)."""

    measure: str
    contracts: int = Field(description="The beneficiary's contracts on the measure.")
    paid: float
    count: int
    first_day: date | None
    last_day: date | None
    items: list[PnrrPayment]
    others: list[PnrrSibling] = Field(
        description="The beneficiary's other contracts on the measure, when it has several."
    )


class PnrrContract(Answer):
    id: int
    number: str | None
    title: str | None
    beneficiary: EntityRef | None
    ministry: str | None
    ministry_name: str | None
    signed_on: date | None
    starts_on: date | None
    county: str | None
    locality: str | None
    total: float | None
    eu: float | None
    status: PnrrStatus | None = Field(
        description="Null when its measures differ (see `lines`) or none gives a status."
    )
    ends_on: date | None
    physical_progress: float | None = Field(
        description="Null when its measures differ or none gives it."
    )
    financial_progress: float | None
    measures_differ: bool = Field(
        description="Its measures report different statuses or progress; `lines` has each."
    )
    lines: list[PnrrLine]
    payments: list[PnrrPayments] = Field(description="One per measure of the contract.")
    edition: date
    source: Source
