"""Every project of every programme held, one row each, for the site's list of projects
(design D22): an Anghel Saligny project, a PNRR financing contract, a cohesion project.

Built from the programmes' own tables and the links between records, never edited:
`projects.build()` writes every row again after the links change (see `projects.py`).
"""

from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("kind", "key", name="project_kind_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 'anghel_saligny', 'pnrr' or 'cohesion' (`projects.KINDS`).
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # The programme's own key: the ministry's project id, the PNRR commitment id, the SMIS.
    key: Mapped[int] = mapped_column(BigInteger)
    # The programme: 'AS', 'PNRR', or the cohesion programme's code ('POR', 'PEO'...).
    programme: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    # A number the programme gives the project besides its key: the financing contract.
    number: Mapped[str | None] = mapped_column(String(64))
    beneficiary_cui: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entity.cui"), index=True
    )
    # As the programme writes it; null for a natural person, who is never named.
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    natural_person: Mapped[bool] = mapped_column(Boolean, default=False)
    # Two-letter county codes ('CJ', 'B'); several for a project over several counties,
    # none for a national one or a county the programme does not name.
    counties: Mapped[list[str]] = mapped_column(ARRAY(String(2)))
    # The UAT it lands in: the place an Anghel Saligny payment is for, else the place ANAF
    # records its beneficiary in. Null when neither is known.
    siruta: Mapped[int | None] = mapped_column(Integer, index=True)
    # The project's value in lei, as its programme gives it.
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    # Ours ('in_progress', 'finished', 'terminated'), or null; and as the programme writes it.
    status: Mapped[str | None] = mapped_column(String(16))
    status_written: Mapped[str | None] = mapped_column(Text)
    # How far its road is followed (`projects.REACHES`), and the step we cannot follow.
    reach: Mapped[str] = mapped_column(String(16), index=True)
    gap: Mapped[str | None] = mapped_column(String(16))
