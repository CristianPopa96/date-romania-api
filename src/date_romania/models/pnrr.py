"""The Recovery and Resilience Plan (PNRR), as MIPE's dashboard publishes it: the measures,
every financing contract, every payment, the largest recipients.

Text is stored as published, personal codes included (Crispy, 22.10.2026: personal data
from these sources is collected, not shown). Whatever a route serves from it goes through
`personal_id.mask_cnp()` first, and a natural person's name is never served at all.

Every table holds one edition, the newest held: a new edition replaces them all, since
each file gives everything again (contracts with their progress, payments since 2020).
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class PnrrEdition(Base):
    """One edition of the dashboard data, with the plan's own totals as it gives them."""

    __tablename__ = "pnrr_edition"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    allocated_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # What the EU has paid Romania, and of it the advance at the start.
    received_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    prefinancing_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    suspended_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    revoked_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    beneficiaries_contracted: Mapped[int | None] = mapped_column(Integer)
    beneficiaries_paid: Mapped[int | None] = mapped_column(Integer)
    contracts: Mapped[int | None] = mapped_column(Integer)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class PnrrMeasure(Base):
    """One measure of the plan (an investment or a reform), e.g. C10 I3, with its money."""

    __tablename__ = "pnrr_measure"

    # 'C10.I3', or 'C10.I3.a' for a sub-measure: what every contract and payment names.
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    component: Mapped[str] = mapped_column(String(8))
    measure: Mapped[str] = mapped_column(String(16))
    submeasure: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(Text)
    # The ministry that runs it ('MDLPA') and its name.
    ministry: Mapped[str | None] = mapped_column(String(32))
    ministry_name: Mapped[str | None] = mapped_column(Text)
    # 'grant' or 'loan', as the plan funds it.
    funding: Mapped[str | None] = mapped_column(String(16))
    # The allocation exists only in euro.
    allocated_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    contracted_eu_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class PnrrContract(Base):
    """One financing contract (`id_angajament`). What can differ between its measures
    (values, status, progress) is on its lines."""

    __tablename__ = "pnrr_contract"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # The number on the contract. Not unique: several beneficiaries use the same numbers.
    number: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    # Null when the file gives no valid CUI, as for a natural person.
    beneficiary_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    # As published. For a natural person this is the person's name: stored, never shown or
    # served (Crispy, 22.10.2026).
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    # The ministry's own words, about 150 spellings ('UAT', 'IMM', 'Unitate de învățământ').
    beneficiary_type: Mapped[str | None] = mapped_column(Text)
    natural_person: Mapped[bool] = mapped_column(Boolean)
    ministry: Mapped[str | None] = mapped_column(String(32))
    signed_on: Mapped[date | None] = mapped_column(Date)
    starts_on: Mapped[date | None] = mapped_column(Date)
    # 'RURAL' or 'URBAN'.
    impact: Mapped[str | None] = mapped_column(String(16))
    county: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class PnrrContractLine(Base):
    """The part of a contract under one measure and funding, in the file's order. A contract
    on one measure has one line; its values are the sum of its lines."""

    __tablename__ = "pnrr_contract_line"

    contract_id: Mapped[int] = mapped_column(
        ForeignKey("pnrr_contract.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    measure_code: Mapped[str] = mapped_column(ForeignKey("pnrr_measure.code"), index=True)
    # 'grant', 'loan' or 'grant/loan'.
    funding: Mapped[str | None] = mapped_column(String(16))
    # Lei: the whole value, of it EU money, national money, VAT and ineligible costs.
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    eu: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    national: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    vat: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    ineligible: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # 'ÎN IMPLEMENTARE', 'ÎN IMPLEMENTARE (sub 30%)', 'FINALIZAT'.
    status: Mapped[str | None] = mapped_column(String(64))
    ends_on: Mapped[date | None] = mapped_column(Date)
    # As the ministry reports them, from 0 to 1. Never worked out from the payments.
    physical_progress: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    financial_progress: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))


class PnrrPayment(Base):
    """One payment of EU money to a final beneficiary, in the file's order. It names the
    beneficiary and the measure, never the contract: `contract_id` is set only when the
    beneficiary has one contract on that measure. Two payments can be alike in every field;
    both are kept, as published."""

    __tablename__ = "pnrr_payment"

    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    measure_code: Mapped[str] = mapped_column(ForeignKey("pnrr_measure.code"), index=True)
    funding: Mapped[str | None] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    paid_on: Mapped[date | None] = mapped_column(Date, index=True)
    reported_on: Mapped[date | None] = mapped_column(Date)
    beneficiary_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    # A payment does not say what its beneficiary is: without a valid CUI the name may be a
    # person's, so it is flagged as one, stored, and never served.
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    natural_person: Mapped[bool] = mapped_column(Boolean)
    county: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    caen_division: Mapped[str | None] = mapped_column(String(8))
    # How many contracts the beneficiary has on the measure: 0, 1 or more.
    contracts_on_measure: Mapped[int] = mapped_column(SmallInteger)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("pnrr_contract.id"), index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class PnrrTopRecipient(Base):
    """One of the largest final recipients, as the plan must publish them (EU Reg.
    2021/241 art. 25a): what it received, and when last. Grants and loans apart only for
    the few the dashboard's preview splits; null for the others."""

    __tablename__ = "pnrr_top_recipient"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(Text)
    grant: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    loan: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_eur: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    last_received_on: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
