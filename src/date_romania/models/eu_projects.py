"""EU cohesion projects, from the managing authorities' lists of contracted projects: the
2014-2020 operational programmes and the 2021-2027 national programmes MIPE runs; and from
MIPE's map of the 2021-2027 projects, those no list holds (the regional programmes,
Transport, and the projects a list leaves out).

One row per project (its SMIS code), from the newest list of its programme, else from the
newest edition of the map. A list gives
what the project was worth and paid at its cut-off day, never the day of a payment; the
Health programme also publishes its payments one by one (`eu_project_payment`).
Text is stored as published (Crispy, 22.10.2026); a route masks personal codes when serving.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base, SourceDocument
from date_romania.sources import EU_MAP


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
    # The lead's tax ID as MIPE's map of the 2021-2027 projects gives it (`CUI_LIDER`), on
    # the projects the map holds and on a list's project the map lists too.
    map_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    # The beneficiary's entity, tied by `eu_links.link()` after every load: by the tax ID
    # in the list (sure), or by name and place (probable). Null when nothing ties it.
    entity_cui: Mapped[int | None] = mapped_column(ForeignKey("entity.cui"), index=True)
    entity_method: Mapped[str | None] = mapped_column(String(32))
    entity_confidence: Mapped[str | None] = mapped_column(String(16))
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
    # The UAT the project is in, where the map names one alone (the lists never do).
    siruta: Mapped[int | None] = mapped_column(Integer, index=True)
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


def held_by_map():
    """The projects the map holds, not a list: those loaded from one of its editions."""
    return EuProject.source_document_id.in_(
        select(SourceDocument.id).where(SourceDocument.source == EU_MAP.key)
    )


def programme_day():
    """The day a programme's figures describe, over the projects grouped: its list's, where
    a list holds some of them, else the map edition's. A project the map adds to a list's
    programme has no paid figure, so the programme's paid is the list's, at the list's day."""
    return func.coalesce(
        func.max(EuProject.cut_off).filter(~held_by_map()), func.max(EuProject.cut_off)
    )


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


class EuSeapLink(Base):
    """A SEAP award notice or direct purchase tied to the cohesion project or PNRR contract
    its text cites (see `eu_seap_links.py`). Built from the tables, never edited: `dr link
    eu-seap` builds every row again."""

    __tablename__ = "eu_seap_link"
    __table_args__ = (
        CheckConstraint("num_nonnulls(smis, pnrr_contract_id) = 1", name="eu_seap_link_project"),
        CheckConstraint("num_nonnulls(notice_id, purchase_id) = 1", name="eu_seap_link_record"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The project: a cohesion project, or a PNRR contract.
    smis: Mapped[int | None] = mapped_column(
        ForeignKey("eu_project.smis", ondelete="CASCADE"), index=True
    )
    pnrr_contract_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pnrr_contract.id", ondelete="CASCADE"), index=True
    )
    # The SEAP record: an award notice (all its contracts), or a direct purchase.
    notice_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("award_notice.id", ondelete="CASCADE"), index=True
    )
    purchase_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("direct_purchase.id", ondelete="CASCADE"), index=True
    )
    # What the text cites, as written: '341497', '12321/26.08.2024'.
    cited: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(16))  # probable: never sure
