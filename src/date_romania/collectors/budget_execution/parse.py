"""Reading the Finance Ministry's monthly workbook of the consolidated general budget
(`bgcDDMMYYYY.xlsx`, annex 1): one row per line, budget column and period.

The sheet has the period in its title ("Realizări 01.01 - 30.09.2026"), a header of six
rows naming one budget per column, then the revenue lines from "VENITURI TOTALE", the
spending lines from "CHELTUIELI TOTALE" and the balance ("EXCEDENT(+) / DEFICIT(-)").
Amounts are million lei. The same layout from January 2024 to September 2026 (checked
14.11.2026).
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from date_romania.collectors.sheets import is_workbook, workbook_sheets
from date_romania.text import plain

PARSER_VERSION = 1

REVENUE, SPENDING, BALANCE = "revenue", "spending", "balance"

# A budget column, by the words its header holds (plain form), checked in this order: the
# consolidated totals before "TOTAL" alone.
BUDGETS: tuple[tuple[str, str], ...] = (
    ("BUGET GENERAL CONSOLIDAT SUME", "consolidated"),
    ("TOTAL BUGET GENERAL CONSOLIDAT", "consolidated_before_financial"),
    ("TRANSFERURI INTRE BUGETE", "transfers"),
    ("OPERA TIUNI FINAN", "financial_operations"),
    ("BUGETUL DE STAT", "state"),
    ("UNITATILOR ADM", "local"),
    ("ASIG SOCIALE DE STAT", "social_insurance"),
    ("SOMAJ", "unemployment"),
    ("SANATATE", "health"),
    ("CREDITE EXTERNE", "external_credits"),
    ("VENITURI PROPRII", "own_revenue"),
    ("FONDURI EXTERNE NERAM", "eu_funds"),
    ("TREZORERIEI", "treasury"),
    ("INFRASTRUCTURII RUTIERE", "cnair"),
    ("EXIM", "eximbank"),
    ("PIB", None),  # a share of GDP, not an amount
)
TOTAL_COLUMN = "TOTAL"

# Our names for the lines the site reads; any other keeps its plain title. A rule is the
# words the title starts with, and words it must or must not also hold.
LINES: dict[str, tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], ...]] = {
    REVENUE: (("VENITURI TOTALE", (), (), "total"),),
    SPENDING: (
        ("CHELTUIELI TOTALE", (), (), "total"),
        ("CHELTUIELI CURENTE", (), (), "current"),
        ("CHELTUIELI DE PERSONAL", (), (), "personnel"),
        ("BUNURI SI SERVICII", (), (), "goods_services"),
        ("DOBANZI", (), (), "interest"),
        ("SUBVENTII", (), (), "subsidies"),
        ("TRANSFERURI INTRE UNITATI", (), (), "transfers_public"),
        ("ALTE TRANSFERURI", (), (), "other_transfers"),
        ("PROIECTE CU FINANTARE DIN FONDURI EXTERNE", ("2014",), (), "eu_projects_2014_2020"),
        ("PROIECTE CU FINANTARE DIN FONDURI EXTERNE", (), ("2014",), "eu_projects"),
        ("ASISTENTA SOCIALA", (), (), "social_assistance"),
        ("ALTE CHELTUIELI", (), (), "other"),
        ("PROIECTE CU FINANTARE", ("PNRR", "IMPRUMUT"), (), "pnrr_loans"),
        ("PROIECTE CU FINANTARE", ("PNRR",), ("IMPRUMUT",), "pnrr_grants"),
        ("CHELTUIELI AFERENTE PROGRAMELOR CU FINANTARE RAMBURSABILA", (), (), "reimbursable"),
        ("CHELTUIELI AFERENTE PLANULUI SAFE", (), (), "safe"),
        ("CHELTUIELI DE CAPITAL", (), (), "capital"),
        ("ACTIVE NEFINANCIARE", (), (), "nonfinancial_assets"),
        ("ACTIVE FINANCIARE", (), (), "financial_assets"),
        ("OPERATIUNI FINANCIARE", (), (), "financial_operations"),
        ("IMPRUMUTURI", (), (), "loans"),
        ("RAMBURSARI DE CREDITE", (), (), "credit_repayments"),
        ("PLATI EFECTUATE IN ANII PRECEDENTI", (), (), "prior_years_recovered"),
    ),
    BALANCE: (("EXCEDENT", (), (), "balance"),),
}

_PERIOD = re.compile(r"01\.01\s*-\s*(\d{2})\.(\d{2})\.(\d{4})")
_FILE_DAY = re.compile(r"bgc(\d{2})(\d{2})(\d{4})\.xlsx?$", re.IGNORECASE)


class BudgetExecutionError(ValueError):
    pass


@dataclass
class Parsed:
    period_end: date | None = None
    rows: list[dict] = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)


def file_day(url: str) -> date | None:
    """The period end an address names (`bgc30092026.xlsx` is 30.09.2026)."""
    found = _FILE_DAY.search(url)
    if not found:
        return None
    day, month, year = (int(part) for part in found.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def line_name(section: str, title: str) -> str:
    words = plain(title)
    for start, holds, lacks, name in LINES[section]:
        if (
            words.startswith(start)
            and all(word in words for word in holds)
            and not any(word in words for word in lacks)
        ):
            return name
    slug = words.lower().replace(" ", "_")
    if len(slug) <= 64:
        return slug
    # Two long titles can start alike ("Sume primite de la UE... prefinantari" and the
    # same "... aferente cadrului financiar 2014-2020"): the whole title tells them apart.
    return f"{slug[:55]}_{hashlib.sha1(words.encode()).hexdigest()[:8]}"


def _columns(header: list[list]) -> dict[int, str]:
    """Each amount column's budget, from the words of the header rows above it."""
    width = max(len(row) for row in header)
    found: dict[int, str] = {}
    for column in range(1, width):
        words = plain(" ".join(str(row[column]) for row in header if column < len(row)))
        if not words:
            continue
        if words == TOTAL_COLUMN:
            found[column] = "total"
            continue
        for marker, budget in BUDGETS:
            if marker in words:
                if budget:
                    found[column] = budget
                break
        else:
            raise BudgetExecutionError(f"column {column} is not a budget we know: {words!r}")
    if "consolidated" not in found.values() or "local" not in found.values():
        raise BudgetExecutionError(f"the header names no consolidated or local column: {found}")
    return found


def _amount(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.001"))
    except InvalidOperation:
        raise ValueError(value) from None


def parse(content: bytes) -> Parsed:
    if not is_workbook(content):
        raise BudgetExecutionError(f"not a workbook: {content[:100]!r}")
    _, sheet = next(workbook_sheets(content))
    rows = [list(row) for row in sheet]
    parsed = Parsed()
    for row in rows[:12]:
        found = _PERIOD.search(" ".join(str(cell) for cell in row))
        if found:
            day, month, year = (int(part) for part in found.groups())
            parsed.period_end = date(year, month, day)
            break
    if parsed.period_end is None:
        raise BudgetExecutionError("the sheet names no period")
    # The header's first row: each budget's name starts there ("Bugetul", then "de" and
    # "stat" in the rows under it).
    start = next(
        (
            i
            for i, row in enumerate(rows)
            if sum(plain(cell).startswith("BUGETUL") for cell in row) >= 3
        ),
        None,
    )
    if start is None:
        raise BudgetExecutionError("the sheet has no header of budgets")
    columns = _columns(rows[start : start + 6])

    section: str | None = None
    names: set[tuple[str, str]] = set()
    for line_no, row in enumerate(rows[start + 6 :], start + 6):
        title = str(row[0]).strip() if row else ""
        words = plain(title)
        if words == "VENITURI TOTALE":
            section = REVENUE
        elif words == "CHELTUIELI TOTALE":
            section = SPENDING
        elif words.startswith("EXCEDENT"):
            section = BALANCE
        if section is None:
            continue
        try:
            amounts = {
                budget: _amount(row[column]) if column < len(row) else None
                for column, budget in columns.items()
            }
        except ValueError as exc:
            parsed.rejected.append((row, f"not an amount: {exc}"))
            continue
        amounts = {budget: amount for budget, amount in amounts.items() if amount is not None}
        if not title:
            if any(amounts.values()):
                parsed.rejected.append((row, "amounts on a line with no title"))
            continue
        if not amounts:
            # A heading with no figures of its own.
            continue
        line = line_name(section, title)
        if (section, line) in names:
            parsed.rejected.append((row, f"{section} line {line} is in the sheet twice"))
            continue
        names.add((section, line))
        title = " ".join(title.split())
        parsed.rows += [
            {
                "period_end": parsed.period_end,
                "section": section,
                "line": line,
                "budget": budget,
                "title": title,
                "line_no": line_no,
                "amount": amount,
            }
            for budget, amount in amounts.items()
        ]
        if section == BALANCE:
            break
    if not any(row["section"] == SPENDING and row["line"] == "total" for row in parsed.rows):
        raise BudgetExecutionError("the sheet has no total spending")
    return parsed
