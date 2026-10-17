"""SEAP award notices: the notice, its contracts and winners, its detail and versions."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class AwardNotice(Base):
    """One SEAP contract award notice (anunț de atribuire), as the public list shows it.

    A notice is published again when contracts are added or changed, so a row is the latest
    copy seen. Its contracts and their winners are in `award_contract` and `award_winner`.
    """

    __tablename__ = "award_notice"

    # SEAP's own caNoticeId.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    notice_no: Mapped[str | None] = mapped_column(String(32), index=True)  # e.g. CAN1138069
    # 3 award notice, 18 after a simplified procedure, 13 after a request for offers,
    # 16 concession.
    notice_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    buyer_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    buyer_text: Mapped[str | None] = mapped_column(Text)
    cpv_code: Mapped[str | None] = mapped_column(String(16), index=True)
    cpv_name: Mapped[str | None] = mapped_column(Text)
    # 1 goods, 2 services, 3 works.
    contract_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    contract_type: Mapped[str | None] = mapped_column(String(64))
    procedure_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    procedure_type: Mapped[str | None] = mapped_column(String(128))
    procedure_state_id: Mapped[int | None] = mapped_column(SmallInteger)
    procedure_state: Mapped[str | None] = mapped_column(String(64))
    # 1 a public contract, 3 a framework agreement.
    assignment_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    assignment_type: Mapped[str | None] = mapped_column(String(64))
    # The value SEAP shows for the whole notice, in lei. Never add it to the contracts below.
    value_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    is_utility: Mapped[bool | None] = mapped_column(Boolean)
    has_subsequent_contracts: Mapped[bool | None] = mapped_column(Boolean)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AwardContract(Base):
    """One contract listed in an award notice."""

    __tablename__ = "award_contract"

    # SEAP's own caNoticeContractId.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    notice_id: Mapped[int] = mapped_column(ForeignKey("award_notice.id"), index=True)
    contract_no: Mapped[str | None] = mapped_column(Text)
    contract_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    # SEAP's contractType: see the AWARD_* constants in money.py.
    kind: Mapped[int | None] = mapped_column(SmallInteger)
    lots: Mapped[str | None] = mapped_column(Text)
    # As published, in `currency`; `value_ron` is SEAP's own conversion to lei.
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    value_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # The lowest and highest offer in lei, where SEAP gives them.
    min_offer_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_offer_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # How many times the contract was modified after signing.
    modified_count: Mapped[int | None] = mapped_column(Integer)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AwardWinner(Base):
    """A company a contract was awarded to; an association has one row per member.

    The contract value is not split between the members: SEAP gives one value per contract.
    """

    __tablename__ = "award_winner"

    contract_id: Mapped[int] = mapped_column(
        ForeignKey("award_contract.id", ondelete="CASCADE"), primary_key=True
    )
    # Place in SEAP's list of winners, from 0.
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # The CUI is null for a foreign company or an invalid tax ID; the text is always kept.
    supplier_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    supplier_text: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(64))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))


class AwardNoticeDetail(Base):
    """What the page of one award notice adds to the list row: the notice that opened the
    procedure, and how its lots are financed. One row per notice, from one detail answer.
    """

    __tablename__ = "award_notice_detail"

    notice_id: Mapped[int] = mapped_column(
        ForeignKey("award_notice.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    # The contract notice (anunț de participare) the award follows, e.g. CN1056026, and
    # the day it was published. Empty for an award with no earlier notice.
    call_notice_no: Mapped[str | None] = mapped_column(String(32))
    call_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Its number in the EU's Official Journal, e.g. 2023/S 111-348303.
    ted_notice_no: Mapped[str | None] = mapped_column(String(64))
    lots: Mapped[int] = mapped_column(SmallInteger)
    # True if any lot is marked as paid from EU funds, false if none is, null if SEAP
    # does not say.
    eu_funded: Mapped[bool | None] = mapped_column(Boolean)
    # SEAP's own words, each once, over all lots: 'Fonduri bugetare', 'Program / Proiect'.
    financing_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # The programmes named, e.g. 'Planul National de Redresare si Rezilienta – PNRR'.
    eu_funds: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # The buyer's free text about the project; an SMIS code is often inside it.
    eu_project: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AwardNoticeVersion(Base):
    """One publication of a notice. SEAP gives a corrected or extended notice a new id and
    withdraws the one before it, so the versions of a notice tell when it first appeared.
    """

    __tablename__ = "award_notice_version"

    # The notice we hold, which is the version in force when it was collected.
    notice_id: Mapped[int] = mapped_column(
        ForeignKey("award_notice.id", ondelete="CASCADE"), primary_key=True
    )
    # SEAP's caNoticeID of this version; equal to `notice_id` for the one in force.
    version_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 2 published, 10 withdrawn (replaced by a later version).
    state_id: Mapped[int | None] = mapped_column(SmallInteger)
    state: Mapped[str | None] = mapped_column(String(64))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
