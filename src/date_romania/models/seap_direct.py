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
from sqlalchemy.orm import Mapped, mapped_column

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
