"""Readers' error reports."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


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
