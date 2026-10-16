"""Data model. Release 0 holds only what every collector needs; release 1 adds procurement."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    Date,
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
from sqlalchemy.dialects.postgresql import ARRAY
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
    # 1 goods, 2 services, 3 works. The list rows do not give it: it is the filter of the
    # query that returned the row. Null when the day fit under the cap without that filter.
    contract_type_id: Mapped[int | None] = mapped_column(SmallInteger)
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


class PniasPayment(Base):
    """One settlement request the ministry paid in the Anghel Saligny programme (PNIAS).

    A project has many of them. The files name the town hall by name and county only, and
    the builder and the designer by tax ID only from the file of 27 August 2026 on.
    """

    __tablename__ = "pnias_payment"

    # The number the ministry registered the request under: 25421 for 'ASA4-25421'.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    registered_on: Mapped[date | None] = mapped_column(Date)
    # The town hall's own number and day for the request.
    request_no: Mapped[str | None] = mapped_column(String(32))
    requested_on: Mapped[date | None] = mapped_column(Date)
    # The day in the name of the file: the files give no payment day of their own.
    published_on: Mapped[date | None] = mapped_column(Date, index=True)
    # 'infra' (roads, water, sewage) or 'gas': the two sheets of every file.
    network: Mapped[str] = mapped_column(String(8))
    county: Mapped[str] = mapped_column(String(64), index=True)
    town_hall: Mapped[str] = mapped_column(Text)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True)
    investment: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    # The financing contract between the ministry and the town hall.
    ministry_contract_no: Mapped[str | None] = mapped_column(String(32))
    ministry_contract_date: Mapped[date | None] = mapped_column(Date)
    total_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    state_budget_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # 'Valoarea solicitată pentru decontare': what this request settled.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    state: Mapped[str | None] = mapped_column(String(64))
    # As written: '26,04', '40%', or a phrase.
    progress: Mapped[str | None] = mapped_column(Text)
    # Also financed from the EU programme for large infrastructure (gas only).
    poim: Mapped[bool | None] = mapped_column(Boolean)
    # No foreign key: most builders are not otherwise held, and get no page of their own.
    builder_cui: Mapped[int | None] = mapped_column(BigInteger, index=True)
    builder_text: Mapped[str | None] = mapped_column(Text)
    designer_cui: Mapped[int | None] = mapped_column(BigInteger, index=True)
    designer_text: Mapped[str | None] = mapped_column(Text)
    estimated_end: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExportContract(Base):
    """A contract from SEAP's quarterly exports on data.gov.ro, older than the notices we
    collect ourselves.

    Kept only for the builders of the Anghel Saligny programme, to tie a payment to the
    contract it settles. These rows never enter a total, a ranking or an entity page:
    they are another reading of SEAP, with fewer fields, and a contract can be in both.

    A row is one winner of a contract: an association has one row per member, each with
    the value of the whole contract. A contract is also in every export published after
    it, so it has a row in each.
    """

    __tablename__ = "export_contract"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notice_no: Mapped[str | None] = mapped_column(String(32), index=True)  # e.g. CAN1058324
    notice_date: Mapped[date | None] = mapped_column(Date)
    contract_no: Mapped[str | None] = mapped_column(Text)
    contract_date: Mapped[date | None] = mapped_column(Date)
    # Only the 2021 and 2022 exports carry a title.
    title: Mapped[str | None] = mapped_column(Text)
    lot: Mapped[str | None] = mapped_column(Text)
    buyer_cui: Mapped[int | None] = mapped_column(BigInteger, index=True)
    buyer_text: Mapped[str | None] = mapped_column(Text)
    # Null for a foreign company or an invalid tax ID, as for award winners.
    supplier_cui: Mapped[int | None] = mapped_column(BigInteger, index=True)
    supplier_text: Mapped[str | None] = mapped_column(Text)
    value_ron: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    procedure_type: Mapped[str | None] = mapped_column(String(128))
    contract_type: Mapped[str | None] = mapped_column(String(64))
    is_framework: Mapped[bool | None] = mapped_column(Boolean)
    cpv_code: Mapped[str | None] = mapped_column(String(16))
    cpv_name: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"), index=True)
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class ExportBuyer(Base):
    """A buyer named in SEAP's quarterly exports, whoever it bought from.

    Kept to check a town hall matched by name: how many buyers carry that name, and the
    county of the buyer where an export gives one (only the first quarter of 2022 does).
    """

    __tablename__ = "export_buyer"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    # As `counties.COUNTIES` keys it: 'BISTRITA NASAUD'.
    county: Mapped[str | None] = mapped_column(String(64))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))


class PniasLink(Base):
    """A payment tied to a contract that may be the one it settles (see `pnias.py`).

    Built from the two tables, never edited: `dr link pnias` builds every row again.
    """

    __tablename__ = "pnias_link"

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("pnias_payment.id", ondelete="CASCADE"), primary_key=True
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("export_contract.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[str] = mapped_column(String(16))  # sure, probable, possible


class Report(Base):
    """What a reader says is wrong on a page of the site. It waits until a person reviews it."""

    __tablename__ = "report"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The page the report is about, as the reader's browser gave it or as they typed it.
    # Published only when it is the address of a page of the site (`reports.site_page`).
    page: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    # A link or a document the reader says shows the right value.
    evidence: Mapped[str | None] = mapped_column(Text)
    # A keyed hash of the reader's address, for the hourly limit; never the address.
    sender: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)  # new, accepted, rejected
    # What we changed, in our words. The only free text of a report the site ever shows.
    correction: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
