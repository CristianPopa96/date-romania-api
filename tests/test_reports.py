"""Error reports from readers: the endpoint that takes one in, the queue and the review."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from date_romania import cli, reports
from date_romania.api.main import app
from date_romania.db import get_session
from date_romania.models import Report

runner = CliRunner()


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_report_waits_in_the_queue_and_is_not_public(client, session):
    sent = client.post(
        "/v1/reports",
        json={
            "page": " /contracte/9001 ",
            "message": "Valoarea include TVA, nu e fără TVA.",
            "evidence": "",
        },
    )
    assert sent.status_code == 201
    (waiting,) = reports.queue(session)
    assert sent.json() == {"id": waiting.id}
    assert (waiting.page, waiting.status, waiting.evidence) == ("/contracte/9001", "new", None)
    assert client.get("/v1/corrections").json() == {"items": []}


def test_a_report_must_say_what_is_wrong(client, session):
    assert client.post("/v1/reports", json={"message": "greșit"}).status_code == 422
    assert client.post("/v1/reports", json={"page": "/surse"}).status_code == 422
    assert client.post("/v1/reports", json={"message": "x" * 4001}).status_code == 422
    assert reports.queue(session) == []


def test_a_personal_code_in_a_report_is_hidden_before_it_is_stored(client, session):
    client.post("/v1/reports", json={"message": "Persoana cu CNP 1800101221144 apare aici."})
    (waiting,) = reports.queue(session)
    assert waiting.message == "Persoana cu CNP [CNP] apare aici."


def test_the_queue_takes_only_so_many_reports_an_hour(client, session, monkeypatch):
    monkeypatch.setattr(reports, "PER_HOUR", 2)
    # A report from two hours ago does not count against this hour.
    session.add(
        Report(
            message="An older report.",
            status="new",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    session.flush()
    body = {"message": "Valoarea include TVA."}
    assert client.post("/v1/reports", json=body).status_code == 201
    assert client.post("/v1/reports", json=body).status_code == 201
    assert client.post("/v1/reports", json=body).status_code == 429
    assert len(reports.queue(session)) == 3


def test_only_an_accepted_report_is_published_and_only_in_our_words(client, session):
    right = reports.file(session, "/contracte/9001", "Valoarea include TVA.", None)
    wrong = reports.file(session, "/surse", "Nu sunt de acord cu cifrele.", None)
    reports.settle(session, right.id, reports.ACCEPTED, "Valoarea era cu TVA; acum e fără TVA.")
    reports.settle(session, wrong.id, reports.REJECTED)

    (item,) = client.get("/v1/corrections").json()["items"]
    assert item["page"] == "/contracte/9001"
    assert item["correction"] == "Valoarea era cu TVA; acum e fără TVA."
    assert "message" not in item
    assert reports.queue(session) == []
    assert len(reports.queue(session, settled=True)) == 2
    assert reports.settle(session, 999_999, reports.REJECTED) is None


def test_the_review_commands_show_and_close_a_report(session, monkeypatch):
    # The commands open their own session; here it is the test's, left open at the end.
    monkeypatch.setattr(session, "close", lambda: None)
    monkeypatch.setattr(cli, "Session", lambda engine: session)
    filed = reports.file(session, "/contracte/9001", "Valoarea include TVA.", "https://x.test")

    listed = runner.invoke(cli.app, ["reports", "list"])
    assert f"#{filed.id} · new" in listed.output
    assert "Valoarea include TVA." in listed.output
    assert "1 reports" in listed.output

    accepted = runner.invoke(
        cli.app, ["reports", "accept", str(filed.id), "--correction", "Acum e fără TVA."]
    )
    assert accepted.exit_code == 0
    assert (filed.status, filed.correction) == ("accepted", "Acum e fără TVA.")
    assert "0 reports" in runner.invoke(cli.app, ["reports", "list"]).output
    assert runner.invoke(cli.app, ["reports", "reject", "999999"]).exit_code == 1
