"""Data model. Release 0 holds only what every collector needs; release 1 adds procurement."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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

# SEAP's state id for a direct purchase whose offer was accepted: the only ones that count
# as money spent.
DIRECT_PURCHASE_ACCEPTED = 7
# Law 98/2016 art. 7(5): a direct purchase must stay under 900,400 lei without VAT for works
# (270,120 for goods and services). A higher published value is an error at the source, so
# totals leave it out and report it separately.
DIRECT_PURCHASE_LIMIT_RON = Decimal("900400")


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
    # SEAP names no currency for the closing value.
    closing_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
