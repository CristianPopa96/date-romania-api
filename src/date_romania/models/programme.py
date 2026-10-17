"""The Anghel Saligny programme: payment files, contract exports, and the ties between them."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


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
    """A payment tied to a contract that may be the one it settles (see `pnias_links.py`).

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
