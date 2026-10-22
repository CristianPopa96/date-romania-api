"""EU cohesion projects, from the managing authorities' lists of contracted projects: the
2014-2020 operational programmes and the 2021-2027 national programmes MIPE runs.

One row per project (its SMIS code), from the newest list of its programme. A list gives
what the project was worth and paid at its cut-off day, never the day of a payment; the
Health programme also publishes its payments one by one (`eu_project_payment`).
Text is stored as published (Crispy, 22.10.2026); a route masks personal codes when serving.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class EuProject(Base):
    __tablename__ = "eu_project"

    # The SMIS code (MySMIS2014 or MySMIS2021): the key every list and SEAP notice uses.
    smis: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # 'POR', 'POIM', 'PEO', 'PoIDS'... and '2014-2020' or '2021-2027'.
    programme: Mapped[str] = mapped_column(String(16), index=True)
    period: Mapped[str] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(Text)
    # Given by the 2021-2027 lists of PEO, PoIDS and Health ('CUI LIDER'); null elsewhere,
    # where only the name is published.
    beneficiary_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    beneficiary_type: Mapped[str | None] = mapped_column(Text)
    partners: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    # The EU's share of the eligible value, from 0 to 1.
    cofinancing_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    region: Mapped[str | None] = mapped_column(Text)
    county: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    # Lei. The EU money in the eligible value, and the whole value of the project.
    eu_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Paid to the beneficiary up to `cut_off` (EU and national money); null when the list
    # does not give it.
    paid: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # As written, in many spellings: 'finalizat', 'În implementare', 'reziliat'...
    status: Mapped[str | None] = mapped_column(Text)
    # The day the list describes ('la 31 august 2025').
    cut_off: Mapped[date | None] = mapped_column(Date)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class EuProjectPayment(Base):
    """One payment to a project, as the Health programme publishes them month by month.
    The rows of a file are replaced as a whole when it is read again."""

    __tablename__ = "eu_project_payment"

    source_document_id: Mapped[int] = mapped_column(
        ForeignKey("source_document.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # Not a foreign key: a payment can name a project its programme's list leaves out.
    smis: Mapped[int] = mapped_column(Integer, index=True)
    programme: Mapped[str] = mapped_column(String(16))
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    # 'Plată', 'Prefinanțare'...; the kind of request, its number and the payment order's.
    kind: Mapped[str | None] = mapped_column(Text)
    request_kind: Mapped[str | None] = mapped_column(Text)
    request_number: Mapped[str | None] = mapped_column(String(64))
    order_number: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_on: Mapped[date | None] = mapped_column(Date, index=True)
    funding: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[int] = mapped_column(SmallInteger)
