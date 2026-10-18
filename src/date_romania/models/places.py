"""Places and local money: the national list of places (SIRUTA), the Finance Ministry's
list of public entities, the yearly budgets of town halls and county councils, and what
ANAF says of a tax ID."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class Place(Base):
    """A county, a UAT (the unit with a town hall: municipality, town, commune, Bucharest
    sector) or a village, by its SIRUTA code from the national statistics office."""

    __tablename__ = "place"

    siruta: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # As INS writes it: 'MUNICIPIUL ALBA IULIA', 'ORAŞ ABRUD', 'ALBAC', 'BUCUREŞTI SECTORUL 1'.
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # one of places.KINDS
    # The place it belongs to: a village's UAT, a UAT's county, a sector's Bucharest.
    parent: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"), index=True)
    # The county (or Bucharest) the place is in; a county is its own.
    county: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"), index=True)
    urban: Mapped[bool] = mapped_column(Boolean)
    # The tax ID of its town hall (a UAT) or county council (a county), from the Finance
    # Ministry's list (`places.locate`). No foreign key: not every one is in `entity`.
    town_hall_cui: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PublicEntity(Base):
    """One row of the Finance Ministry's list of public entities ("Lista entităților
    publice", refreshed each month): where the entity works and who funds it."""

    __tablename__ = "public_entity"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    county: Mapped[str] = mapped_column(String(64))
    # The UAT it works in, as written: 'Municipiul Blaj', 'Comuna Albac', 'Sectorul 2'.
    uat: Mapped[str] = mapped_column(Text)
    # That UAT found in SIRUTA; null when the name matches no UAT of the county.
    siruta: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"), index=True)
    # Up to two main credit holders, the institutions that fund it: a school names its
    # town hall and the Ministry of Education. No foreign key: most are not otherwise held.
    funder_cui: Mapped[int | None] = mapped_column(BigInteger)
    funder_name: Mapped[str | None] = mapped_column(Text)
    second_funder_cui: Mapped[int | None] = mapped_column(BigInteger)
    second_funder_name: Mapped[str | None] = mapped_column(Text)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LocalBudget(Base):
    """One figure of a UAT's or a county council's executed budget for a year, from the
    Ministry of Development's yearly file. A county council is filed under its county.

    A row is one column of the file: its number, its budget code and its title as the
    file prints them, so nothing is renamed on the way in.
    """

    __tablename__ = "local_budget"

    siruta: Mapped[int] = mapped_column(ForeignKey("place.siruta"), primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # The file's own column number (row 'A, 1, 2, 3...'): 1 is total revenue.
    column_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # 'revenue', 'spending' (by title: staff, capital...) or 'chapter' (by purpose:
    # education, transport...). The totals of each are 'revenue' and 'spending'.
    section: Mapped[str] = mapped_column(String(16))
    code: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class Population(Base):
    """How many people lived in a UAT on a day, from the Ministry of Development's
    population tables (INS figures at 1 January)."""

    __tablename__ = "population"

    siruta: Mapped[int] = mapped_column(ForeignKey("place.siruta"), primary_key=True)
    on: Mapped[date] = mapped_column(Date, primary_key=True)
    people: Mapped[int] = mapped_column(Integer)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class AnafRecord(Base):
    """What ANAF's public register says of a tax ID on the day it was asked.

    Only the county and the locality of the registered office are kept, never the
    street: a sole trader's office can be a home.
    """

    __tablename__ = "anaf_record"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    asked_on: Mapped[date] = mapped_column(Date)
    # False when ANAF does not know the tax ID ('notFound').
    found: Mapped[bool] = mapped_column(Boolean)
    name: Mapped[str | None] = mapped_column(Text)
    # As ANAF writes them: 'IAŞI', 'IS'; 'Sat Gilău Com. Gilău', 'Sector 2 Mun. Bucureşti'.
    county: Mapped[str | None] = mapped_column(String(64))
    county_code: Mapped[str | None] = mapped_column(String(2))
    locality: Mapped[str | None] = mapped_column(Text)
    # The UAT of that locality, found in SIRUTA; null when its name matches none.
    siruta: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"), index=True)
    caen: Mapped[int | None] = mapped_column(Integer)
    # 'INREGISTRAT din data 01.02.2003', 'RADIERE din data ...', as written.
    registration: Mapped[str | None] = mapped_column(Text)
    inactive: Mapped[bool | None] = mapped_column(Boolean)
    vat_payer: Mapped[bool | None] = mapped_column(Boolean)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
