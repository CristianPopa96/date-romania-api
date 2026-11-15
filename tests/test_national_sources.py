"""Eurostat's COFOG table and the Finance Ministry's budget execution: reading the files
as they were published (cut by `research/national-budget/cut_fixtures.py`), and the two
collectors."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from date_romania import national
from date_romania.collectors import budget_execution, cofog
from date_romania.collectors.budget_execution.parse import (
    SPENDING,
    BudgetExecutionError,
    file_day,
    line_name,
)
from date_romania.collectors.budget_execution.parse import parse as parse_execution
from date_romania.collectors.budget_execution.run import month_ends, url_of
from date_romania.collectors.cofog.parse import URL as COFOG_URL
from date_romania.collectors.cofog.parse import CofogError
from date_romania.collectors.cofog.parse import parse as parse_cofog
from date_romania.collectors.http import PoliteClient
from date_romania.models import PARTIAL, SUCCEEDED, BudgetExecution, CofogSpending, JobRun
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures"
EXECUTION = (FIXTURES / "budget_execution_202412.xlsx").read_bytes()
COFOG = (FIXTURES / "eurostat_cofog.json").read_bytes()
DECEMBER_2024 = date(2024, 12, 31)


def test_cofog_gives_every_year_sector_and_purpose():
    parsed = parse_cofog(COFOG)
    found = {(row["year"], row["sector"], row["cofog"]): row["amount"] for row in parsed.rows}
    assert not parsed.rejected
    assert {row["sector"] for row in parsed.rows} == {"S13", "S1311", "S1313", "S1314"}
    assert {row["year"] for row in parsed.rows} == {2023, 2024}
    assert found[2024, "S13", "TOTAL"] == Decimal("761482.5")
    assert found[2024, "S1313", "TOTAL"] == Decimal("166215.8")
    # Local government spends nothing on defence: a figure of zero, not a missing one.
    assert found[2024, "S1313", "GF02"] == 0
    assert parsed.updated_at.date() == date(2026, 10, 21)
    labels = {row["cofog"]: row["label"] for row in parsed.rows}
    assert labels["GF09"] == "Education"


def test_cofog_refuses_an_answer_that_is_not_json_stat():
    with pytest.raises(CofogError):
        parse_cofog(b"<html>maintenance</html>")


def test_the_execution_gives_each_line_in_each_budget():
    parsed = parse_execution(EXECUTION)
    found = {(row["section"], row["line"], row["budget"]): row["amount"] for row in parsed.rows}
    assert parsed.period_end == DECEMBER_2024
    assert not parsed.rejected
    assert found["spending", "total", "consolidated"] == Decimal("727316.168")
    assert found["spending", "total", "local"] == Decimal("157114.624")
    assert found["revenue", "total", "consolidated"] == Decimal("574598.756")
    assert found["balance", "balance", "consolidated"] == Decimal("-152717.412")
    assert found["spending", "goods_services", "consolidated"] == Decimal("93658.779")
    assert found["spending", "pnrr_grants", "consolidated"] == Decimal("10690.701")
    assert found["spending", "pnrr_loans", "consolidated"] == Decimal("12814.787")
    assert found["spending", "eu_projects", "consolidated"] == Decimal("29281.416")
    assert found["spending", "eu_projects_2014_2020", "consolidated"] == Decimal("17460.825")
    # The share of GDP is not an amount, and is not read.
    assert {row["budget"] for row in parsed.rows} >= {"state", "local", "health", "total"}
    assert not any(row["budget"] is None for row in parsed.rows)
    titles = {row["line"]: row["title"] for row in parsed.rows if row["section"] == SPENDING}
    assert titles["goods_services"] == "Bunuri si servicii"


def test_lines_are_named_by_their_words():
    assert line_name(SPENDING, "Cheltuieli de personal") == "personnel"
    pnrr = (
        "Proiecte cu finantare din sumele \nreprezentând asistenta financiara\n"
        "nerambursabila aferenta PNRR"
    )
    assert line_name(SPENDING, pnrr) == "pnrr_grants"
    loans = "Proiecte cu finantare din sumele aferente\ncomponentei de imprumut a PNRR"
    assert line_name(SPENDING, loans) == "pnrr_loans"
    assert line_name(SPENDING, "Cheltuieli aferente planului SAFE") == "safe"
    # A line we do not name keeps its plain title, and two long titles stay apart.
    assert line_name(SPENDING, "Cheltuieli noi") == "cheltuieli_noi"
    first = "Sume primite de la UE/alti donatori în contul platilor efectuate si prefinantari"
    second = first + " aferente cadrului financiar 2014-2020"
    assert line_name("revenue", first) != line_name("revenue", second)
    assert len(line_name("revenue", second)) <= 64


def test_a_workbook_with_another_layout_is_refused():
    with pytest.raises(BudgetExecutionError):
        parse_execution((FIXTURES / "local_budget.xlsx").read_bytes())
    with pytest.raises(BudgetExecutionError):
        parse_execution(b"<html>Request Rejected</html>")


def test_months_and_their_addresses():
    assert month_ends(date(2024, 11, 30), date(2025, 3, 2)) == [
        date(2024, 11, 30),
        date(2024, 12, 31),
        date(2025, 1, 31),
        date(2025, 2, 28),
    ]
    assert url_of(DECEMBER_2024).endswith("/bgc31122024.xlsx")
    assert file_day(url_of(date(2026, 2, 28))) == date(2026, 2, 28)
    assert file_day("https://example.org/other.xlsx") is None


@pytest.fixture
def published(monkeypatch):
    """The ministry with December 2024 out and nothing else, Eurostat with its answer.
    Returns a client, the addresses asked, and the answers to change."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha = hashlib.sha256(content).hexdigest()
        stored[f"{source}/{sha}"] = content
        return StoredObject(key=f"{source}/{sha}", sha256=sha, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    for collector in (cofog, budget_execution):
        monkeypatch.setattr(collector.run, "get_raw", lambda key: stored[key])
    # Runs on 10.02.2025: January 2024 to January 2025 are due.
    monkeypatch.setattr(budget_execution.run, "today", lambda: date(2025, 2, 10))
    answers = {url_of(DECEMBER_2024): EXECUTION, COFOG_URL: COFOG}
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        content = answers.get(str(request.url))
        return httpx.Response(404) if content is None else httpx.Response(200, content=content)

    with PoliteClient(transport=httpx.MockTransport(answer), sleep=lambda seconds: None) as client:
        yield client, asked, answers


def _runs(session, job):
    return list(session.scalars(select(JobRun).where(JobRun.job == job).order_by(JobRun.id)))


def test_the_execution_is_collected_month_by_month(session, published):
    client, asked, _ = published
    assert budget_execution.collect(session, client) == 503
    assert len(asked) == 13
    held = session.scalars(select(BudgetExecution.period_end).distinct()).all()
    assert held == [DECEMBER_2024]
    assert _runs(session, budget_execution.JOB)[-1].status == SUCCEEDED
    # A month held is not asked for again; the ones not published yet are.
    asked.clear()
    assert budget_execution.collect(session, client) == 0
    assert url_of(DECEMBER_2024) not in asked
    assert len(asked) == 12


def test_a_month_that_cannot_be_read_is_asked_for_again(session, published):
    client, asked, answers = published
    answers[url_of(date(2024, 11, 30))] = b"<html>Request Rejected</html>"
    budget_execution.collect(session, client)
    assert _runs(session, budget_execution.JOB)[-1].status == PARTIAL
    held = session.scalars(select(BudgetExecution.period_end).distinct()).all()
    assert held == [DECEMBER_2024]
    asked.clear()
    budget_execution.collect(session, client)
    assert url_of(date(2024, 11, 30)) in asked


def test_the_execution_is_loaded_again_from_the_raw_store(session, published):
    client, _, _ = published
    budget_execution.collect(session, client)
    session.execute(BudgetExecution.__table__.delete())
    assert budget_execution.reparse(session) == 1
    assert session.scalar(select(func.count()).select_from(BudgetExecution)) == 503


def test_cofog_is_loaded_once_per_answer(session, published):
    client, _, _ = published
    assert cofog.collect(session, client) == 640
    assert cofog.collect(session, client) == 0
    total = session.scalar(
        select(CofogSpending.amount).where(
            CofogSpending.year == 2024,
            CofogSpending.sector == "S13",
            CofogSpending.cofog == "TOTAL",
        )
    )
    assert total == Decimal("761482.5")
    assert cofog.reparse(session) == 1
    assert session.scalar(select(func.count()).select_from(CofogSpending)) == 640


def test_the_spending_lines_add_up_to_the_total():
    """`national.SPENDING_PARTS` are the lines that make total spending, nothing twice, in
    every column: what "other" is the rest of."""
    parsed = parse_execution(EXECUTION)
    for budget in ("consolidated", "local", "state"):
        lines = {
            row["line"]: row["amount"]
            for row in parsed.rows
            if row["section"] == SPENDING and row["budget"] == budget
        }
        parts = sum((lines.get(line, Decimal(0)) for line in national.SPENDING_PARTS), Decimal(0))
        assert parts == pytest.approx(lines["total"], abs=Decimal("0.01"))


def test_whole_shares_add_up_to_a_hundred():
    assert national.whole_shares([Decimal(360.81), Decimal(186.99), Decimal(53.2)]) == [60, 31, 9]
    assert national.whole_shares([Decimal(1), Decimal(1), Decimal(1)]) == [34, 33, 33]
    assert national.whole_shares([Decimal(0), Decimal(0)]) == [0, 0]
