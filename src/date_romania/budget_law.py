"""The planned year, from the budget law and the documents that go with it: a short table
entered by hand, each figure with the document and page it was read from (code inspection
A21).

A rectification adds rows with its own date; nothing here is ever overwritten, so the
history of what was planned stays. The newest row of a figure for a year is the one in
force. Amounts are million lei, as the documents print them.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# What a row plans.
SPENDING = "spending"  # consolidated general budget, total spending
REVENUE = "revenue"  # consolidated general budget, total revenue
ANGHEL_SALIGNY = "anghel_saligny"  # subsidies from the state budget for the programme


@dataclass(frozen=True)
class Document:
    title: str
    # The act it belongs to, as the site names it ("Legea nr. 43/2026").
    act: str
    published_on: date
    url: str


@dataclass(frozen=True)
class Planned:
    year: int
    figure: str
    amount: Decimal  # million lei
    document: Document
    # The page of the PDF the figure is printed on (the printed number can differ).
    page: int


# The government's report on the 2026 budget, sent to Parliament with the law (Legea nr.
# 43/2026, Monitorul Oficial nr. 242 of 27.03.2026); the consolidated totals are only in it,
# the law's own articles give the state budget. Checked 14.11.2026 on the copy the Senate
# publishes (120 pages).
REPORT_2026 = Document(
    title=(
        "Raport privind situația macroeconomică pe anul 2026 și proiecția acesteia "
        "pe anii 2027-2029"
    ),
    act="Legea nr. 43/2026",
    published_on=date(2026, 3, 27),
    url="https://www.senat.ro/PAGINI/Buget/2026/Buget%20de%20stat/Raport%20buget%202026.pdf",
)

PLANNED: tuple[Planned, ...] = (
    # "Cheltuieli bugetare total ... 864.284"; the table on page 24 prints 864.283,7.
    Planned(2026, SPENDING, Decimal("864283.7"), REPORT_2026, 24),
    # "Venituri bugetare total ... 736.532".
    Planned(2026, REVENUE, Decimal("736532.0"), REPORT_2026, 59),
    # "i) finanțarea Programului național de investiții „Anghel Saligny” (6.000 mil.lei)",
    # among the subsidies the local budgets receive from the state budget.
    Planned(2026, ANGHEL_SALIGNY, Decimal("6000"), REPORT_2026, 91),
)


def latest_year(figure: str) -> int | None:
    """The newest year the figure is entered for."""
    return max((row.year for row in PLANNED if row.figure == figure), default=None)


def planned(year: int, figure: str) -> Planned | None:
    """The figure in force for a year: the newest document's."""
    rows = [row for row in PLANNED if row.year == year and row.figure == figure]
    return max(rows, key=lambda row: row.document.published_on, default=None)
