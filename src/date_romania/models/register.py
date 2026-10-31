"""The trade register (ONRC): every legal person registered in Romania, one row per tax ID.

The authority on what a company is (its official name, legal form, registration, the UAT
of its registered office, its state), and where a company named without its tax ID is
looked up. Natural persons (PF, PFA, II, IF, AF) are never read into it. Only the county
and the UAT of the office are kept, never the street, as for ANAF.
"""

from datetime import date

from sqlalchemy import ARRAY, BigInteger, Boolean, Date, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from date_romania.models.core import Base


class RegisterCompany(Base):
    __tablename__ = "register_company"

    cui: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    # The name as names are compared (`eu_links.name_key`): a name written without a tax ID
    # is looked up by it.
    name_key: Mapped[str] = mapped_column(Text, index=True)
    # 'SRL', 'SA', 'SNC', 'RA'...
    legal_form: Mapped[str] = mapped_column(String(8))
    # 'J40/1116/1991' or 'J2023001161055'. The EUID is 'ROONRC.' and the same, so it is
    # not kept.
    registration: Mapped[str] = mapped_column(String(32))
    registered_on: Mapped[date | None] = mapped_column(Date)
    # The county and the UAT of the registered office, found in SIRUTA; null when its name
    # matches none.
    county: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"))
    siruta: Mapped[int | None] = mapped_column(ForeignKey("place.siruta"))
    # Its states as the register writes them ('funcțiune', 'radiată'), in the order of
    # their codes.
    states: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Struck off the register ('radiată'): it no longer exists, its records stay.
    deleted: Mapped[bool] = mapped_column(Boolean)
    # The days of the editions it was first seen in, last seen in, and whose states it has
    # had since. A state change is known only to the edition: the register gives no date.
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)
    state_since: Mapped[date] = mapped_column(Date)
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
