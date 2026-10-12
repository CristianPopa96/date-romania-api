"""Collecting the payment files and the contract exports from a made-up data.gov.ro, into
PostgreSQL, in a transaction that is rolled back (see conftest.py)."""

import hashlib
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from date_romania import pnias as links
from date_romania.collectors import pnias, seap_exports
from date_romania.collectors.http import PoliteClient
from date_romania.models import (
    ExportBuyer,
    ExportContract,
    JobRun,
    PniasLink,
    PniasPayment,
    SourceDocument,
)
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures"
FILES = "https://data.gov.ro/dataset/x/resource"
PAYMENTS = f"{FILES}/1/download/27-august-2026.xlsx"
CONTRACTS = f"{FILES}/2/download/contracte-t2-2025.xlsx"
CHANGES = f"{FILES}/3/download/date-din-modificare-contract-t2-2025.xlsx"
BROKEN = f"{FILES}/4/download/raport-contracte-ti-2026.xlsx"

BAHM = 33648158


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def datagov(monkeypatch):
    """A data.gov.ro with one payment file and, for 2025 and 2026, one contracts export
    each; the one of 2026 cannot be downloaded. Returns the addresses asked for."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha = hashlib.sha256(content).hexdigest()
        stored[f"{source}/{sha}"] = content
        return StoredObject(key=f"{source}/{sha}", sha256=sha, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr(pnias.run, "get_raw", lambda key: stored[key])
    monkeypatch.setattr(seap_exports.run, "get_raw", lambda key: stored[key])

    datasets = {
        pnias.run.DATASET: [("27 august 2026.xlsx", PAYMENTS, "2026-09-17")],
        "achizitii-publice-2025": [
            ("Contracte TII 2025", CONTRACTS, "2025-07-03"),
            ("Date din modificare contract publicate în SEAP TII 2025", CHANGES, "2025-07-03"),
        ],
        "achizitii-publice-2026": [("Contracte TI 2026", BROKEN, "2026-04-06")],
    }
    files = {
        PAYMENTS: (FIXTURES / "pnias_payments.xlsx").read_bytes(),
        CONTRACTS: (FIXTURES / "seap_export_2025.xlsx").read_bytes(),
    }
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if "package_show" in url:
            found = datasets.get(request.url.params["id"], [])
            resources = [
                {"name": name, "url": address, "created": f"{day}T10:00:00"}
                for name, address, day in found
            ]
            return httpx.Response(200, json={"success": True, "result": {"resources": resources}})
        if url in files:
            return httpx.Response(200, content=files[url])
        return httpx.Response(404)

    with PoliteClient(transport=httpx.MockTransport(answer), sleep=lambda seconds: None) as client:
        yield client, asked


def test_payment_files_are_stored_once_and_can_be_rebuilt(session, datagov):
    client, asked = datagov
    assert pnias.collect(session, client) == 5
    assert count(session, PniasPayment) == 5
    doc = session.scalars(select(SourceDocument)).one()
    # The title names the day of the payments; the address is how the file is known.
    assert (doc.source, doc.url, doc.request_body) == (
        "pnias-payments",
        PAYMENTS,
        "27 august 2026.xlsx",
    )
    assert session.scalars(select(JobRun.status)).all() == ["succeeded"]

    # A second run asks for the list and downloads nothing.
    asked.clear()
    assert pnias.collect(session, client) == 0
    assert [url for url in asked if "package_show" not in url] == []

    session.get(PniasPayment, 30695).amount = 1
    assert pnias.reparse(session) == 1
    session.expire_all()
    assert str(session.get(PniasPayment, 30695).amount) == "986843.46"
    assert count(session, PniasPayment) == 5


def test_exports_keep_the_contracts_of_the_builders_and_tie_them_to_payments(session, datagov):
    client, asked = datagov
    pnias.collect(session, client)
    asked.clear()

    # The contract of Șeica Mare, with its four winners. The report of contract changes
    # is not asked for, and the export that fails does not stop the run.
    assert seap_exports.collect(session, client, last_year=2026) == 4
    assert CHANGES not in asked
    assert count(session, ExportContract) == 4
    run = session.scalars(select(JobRun).where(JobRun.job == "seap-exports")).one()
    assert (run.status, run.records) == ("partial", 4)
    assert "1 files failed" in run.error

    # Both payments of Șeica Mare name BAHM, one of the four winners: each is tied to
    # BAHM's row, by the same rule and with the same confidence.
    tied = session.scalars(select(PniasLink).order_by(PniasLink.payment_id)).all()
    assert [link.payment_id for link in tied] == [29409, 30695]
    assert {session.get(ExportContract, link.contract_id).supplier_cui for link in tied} == {BAHM}
    # No export gives the buyer's county, and no other buyer is named Șeica Mare.
    assert {(link.method, link.confidence) for link in tied} == {
        ("builder-cui+only-town-hall-of-that-name", "probable")
    }
    # Every buyer of the export is kept, whoever it bought from.
    assert count(session, ExportBuyer) == 2
    states = dict(session.execute(select(PniasPayment.id, links.state())).all())
    assert states == {29409: "one", 30695: "one", 30437: "unnamed", 30677: "none", 29779: "none"}


def test_reading_the_exports_again_replaces_the_rows_and_ties_them_again(session, datagov):
    client, _ = datagov
    pnias.collect(session, client)
    seap_exports.collect(session, client, last_year=2025)
    before = set(session.scalars(select(ExportContract.id)))

    assert seap_exports.reparse(session) == 1
    after = set(session.scalars(select(ExportContract.id)))
    # The export gives a contract no id, so its rows are new rows; the links follow them.
    assert len(after) == 4 and not (before & after)
    assert set(session.scalars(select(PniasLink.contract_id))) <= after
    assert count(session, PniasLink) == 2


def test_a_project_is_tied_to_one_notice_when_all_its_payments_point_to_it(session, datagov):
    client, _ = datagov
    pnias.collect(session, client)
    seap_exports.collect(session, client, last_year=2025)
    project = links.projects()
    rows = {row.project_id: row for row in session.execute(select(project))}
    assert (rows[12519].payments, str(rows[12519].paid), rows[12519].match) == (
        2,
        "2537604.91",
        "one",
    )
    # The latest payment describes the project.
    assert rows[12519].id == 30695
    assert rows[5670].match == "unnamed"
    assert rows[2219].match == "none"


def test_a_file_that_cannot_be_read_is_fetched_again(session, datagov, monkeypatch):
    client, asked = datagov
    pnias.collect(session, client)

    def broken(content, suppliers):
        raise ValueError("a layout nobody has seen")

    working = seap_exports.run.parse_contracts
    monkeypatch.setattr(seap_exports.run, "parse_contracts", broken)
    seap_exports.collect(session, client, last_year=2025)
    # The run says so, and the file is not marked as held.
    run = session.scalars(select(JobRun).where(JobRun.job == "seap-exports")).one()
    assert run.status == "partial"
    assert session.scalars(select(SourceDocument.source)).all() == ["pnias-payments"]

    # Only the parser is put back: the made-up raw store must stay in place.
    monkeypatch.setattr(seap_exports.run, "parse_contracts", working)
    asked.clear()
    assert seap_exports.collect(session, client, last_year=2025) == 4
    assert CONTRACTS in asked


def test_a_year_without_a_dataset_is_passed_over(session, datagov):
    client, _ = datagov
    pnias.collect(session, client)
    # 2027 has no dataset yet: the made-up site answers "not found" for it.
    assert seap_exports.collect(session, client, last_year=2027) == 4
