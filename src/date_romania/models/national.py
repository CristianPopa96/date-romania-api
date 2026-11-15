"""The country's official totals: what the whole public administration spent by purpose
(Eurostat COFOG), and the Finance Ministry's monthly cash execution of the consolidated
general budget (BGC). They are what our own figures are set against on the home page;
they never enter a total of ours."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Numeric

from date_romania.models.core import Base


class CofogSpending(Base):
    """What one level of government spent on one purpose in one year, in million lei, as
    Eurostat's table `gov_10a_exp` gives it (total general government expenditure, TE).

    The table is replaced whole by each answer: Eurostat revises past years.
    """

    __tablename__ = "cofog_spending"

    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    # S13 all of public administration, S1311 central, S1313 local, S1314 social security.
    sector: Mapped[str] = mapped_column(String(8), primary_key=True)
    # 'TOTAL', a division ('GF09') or a group ('GF0901').
    cofog: Mapped[str] = mapped_column(String(8), primary_key=True)
    # Eurostat's English label, as it gives it.
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 1))
    # When Eurostat last updated the table, from the answer itself.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)


class BudgetExecution(Base):
    """One figure of the consolidated general budget's execution, from 1 January to
    `period_end`, in million lei, cash: one line of the Finance Ministry's monthly table
    (annex 1) in one of its columns (a budget: state, local, social insurance... or the
    consolidated total).

    A line keeps the title the file prints; `line` is our name for the ones the site
    reads, and the plain title for any other, so a new line is kept, never dropped.
    """

    __tablename__ = "budget_execution"

    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    # 'revenue', 'spending' or 'balance'.
    section: Mapped[str] = mapped_column(String(8), primary_key=True)
    line: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The column: 'state', 'local', ..., 'consolidated' (see the parser's BUDGETS).
    budget: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    # The line's place in the file, to show them in its order.
    line_no: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    source_document_id: Mapped[int] = mapped_column(ForeignKey("source_document.id"))
    parser_version: Mapped[int] = mapped_column(SmallInteger)
