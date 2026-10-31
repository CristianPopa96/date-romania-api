"""SEAP direct purchases."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from date_romania.cpv import annex_2_sql
from date_romania.models.core import Base


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
    # A service of Annex 2 of Law 98/2016, which has no direct purchase limit: worked out
    # by the database from the CPV code, so totals compare a stored flag.
    annex_2: Mapped[bool] = mapped_column(
        Boolean, Computed(annex_2_sql("cpv_code"), persisted=True)
    )
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


class DirectPurchaseDetail(Base):
    """What the page of one direct purchase adds to the list row: the buyer's description,
    the payment and delivery conditions and the financing. One row per purchase, from one
    detail answer; collected for some purchases only (`seap_direct.details`).

    The answer also names the officials who handled the purchase; that stays in the raw
    store and is never parsed.
    """

    __tablename__ = "direct_purchase_detail"

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("direct_purchase.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    # The buyer's own words, e.g. 'OP la 30 de zile', 'La sediul unitatii'. A contact
    # person they name is kept as SEAP publishes it (Crispy, 22.10.2026).
    payment_condition: Mapped[str | None] = mapped_column(Text)
    delivery_condition: Mapped[str | None] = mapped_column(Text)
    # SEAP's `financingType`: true when the buyer named an EU fund or programme.
    eu_funded: Mapped[bool | None] = mapped_column(Boolean)
    # The fund's name, or its key when SEAP gives no name, e.g. 'PEO'.
    eu_fund: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["DirectPurchaseItem"]] = relationship(
        order_by="DirectPurchaseItem.position", viewonly=True
    )


class DirectPurchaseItem(Base):
    """One line of a direct purchase, in SEAP's order; the lines of a purchase are replaced
    as a whole each time its detail is read."""

    __tablename__ = "direct_purchase_item"

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("direct_purchase_detail.purchase_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    cpv_code: Mapped[str | None] = mapped_column(String(16))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    # As the buyer writes it: 'bucata', or 'Cutie cu 10 pungi din poliolefine (freeflex) a
    # 300 ml solutie perfuzabila'.
    unit: Mapped[str | None] = mapped_column(Text)
    # Lei without VAT, for one unit: the line is worth `unit_price` times `quantity`.
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    # The supplier turned this line down.
    rejected: Mapped[bool | None] = mapped_column(Boolean)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
