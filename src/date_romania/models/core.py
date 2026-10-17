"""The tables every source needs: stored documents, collector runs, entities."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from date_romania.dates import BUCHAREST


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
    # Set by the latest parse of the document, collect or reparse: the parser's version and
    # how many of its rows that parser could not read. Both null for a document kept from
    # before the count. A version with no count is a document that parser set aside
    # unread (an export published twice is read from its workbook).
    parser_version: Mapped[int | None] = mapped_column(SmallInteger)
    rejected_rows: Mapped[int | None] = mapped_column(Integer)


class JobRun(Base):
    """One run of one collector, so a missed day can be found and fetched later."""

    __tablename__ = "job_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job: Mapped[str] = mapped_column(String(64), index=True)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))  # one of the statuses below
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


# The status of a run. A day the source would not give in full ends as `partial`.
RUNNING, SUCCEEDED, PARTIAL, FAILED = "running", "succeeded", "partial", "failed"
# A partial day is done too: it is not fetched again by itself, since the source would cut
# it at the same place.
DONE = (SUCCEEDED, PARTIAL)


def done_days(session: Session, job: str) -> dict[date, bool]:
    """The Bucharest days `job` has a done run for, each True when a run read it in full."""
    days: dict[date, bool] = {}
    runs = session.execute(
        select(JobRun.period_start, JobRun.status)
        .where(JobRun.job == job, JobRun.status.in_(DONE), JobRun.period_start.is_not(None))
        .distinct()
    )
    for start, status in runs:
        day = start.astimezone(BUCHAREST).date()
        days[day] = days.get(day, False) or status == SUCCEEDED
    return days


class Entity(Base):
    """A buyer or supplier, keyed by its tax ID (CUI)."""

    __tablename__ = "entity"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))  # authority, company, other
    # The county and the UAT it is in, by name, and that UAT's SIRUTA code: from the
    # Finance Ministry's list of public entities, else ANAF (`places.locate`).
    county: Mapped[str | None] = mapped_column(String(64))
    locality: Mapped[str | None] = mapped_column(String(128))
    siruta: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"), index=True)
    # The institution that funds it (its main credit holder), when we hold that one too.
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
