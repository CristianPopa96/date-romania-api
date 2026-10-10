"""Data model. Release 0 holds only what every collector needs; release 1 adds procurement."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def search_text(text) -> ColumnElement[str]:
    """Text as search compares it: lower case, no diacritics (`dr_unaccent` is our SQL function)."""
    return func.dr_unaccent(func.lower(text))


class Base(DeclarativeBase):
    pass


class SourceDocument(Base):
    """One raw response or file, stored untouched in object storage under its SHA-256."""

    __tablename__ = "source_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(Text)
    # Body sent with a POST, so the exact request can be repeated.
    request_body: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_key: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(Base):
    """One run of one collector, so a missed day can be found and fetched later."""

    __tablename__ = "job_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # running, succeeded, partial, failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Entity(Base):
    """A buyer or supplier, keyed by its tax ID (CUI)."""

    __tablename__ = "entity"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # authority, company, other
    county: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(128))
    parent_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"))
    source_document_id: Mapped[int | None] = mapped_column(ForeignKey("source_document.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Trigram index for search by name, with diacritics and small typos forgiven.
        Index(
            "ix_entity_name_search",
            search_text(name).label("search"),
            postgresql_using="gin",
            postgresql_ops={"search": "gin_trgm_ops"},
        ),
    )


class DirectPurchase(Base):
    """One SEAP direct purchase (achiziție directă), as the public list shows it."""

    __tablename__ = "direct_purchase"

    # SEAP's own directAcquisitionId, so a purchase fetched twice is updated, not duplicated.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code: Mapped[str | None] = mapped_column(String(32), index=True)  # e.g. DA41316672
    name: Mapped[str | None] = mapped_column(Text)
    state_id: Mapped[int | None] = mapped_column(SmallInteger)
    state: Mapped[str | None] = mapped_column(String(64))
    cpv_code: Mapped[str | None] = mapped_column(String(16), index=True)
    cpv_name: Mapped[str | None] = mapped_column(Text)
    # The CUI is null when SEAP's text holds no valid Romanian tax ID; the text is always kept.
    buyer_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    buyer_text: Mapped[str | None] = mapped_column(Text)
    supplier_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    supplier_text: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    estimated_value_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # The list names no currency for the closing value; the purchase's page gives it in lei
    # without VAT.
    closing_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
