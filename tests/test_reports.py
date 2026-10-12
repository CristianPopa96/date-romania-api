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


def test_characters_that_act_on_a_terminal_are_dropped(client, session):
    client.post("/v1/reports", json={"message": "Valoarea \x1b[2J\x07e greșită,\n pe rând nou."})
    (waiting,) = reports.queue(session)
    assert waiting.message == "Valoarea [2Je greșită,\n pe rând nou."


def test_one_reader_cannot_fill_the_queue_for_the_others(client, session, monkeypatch):
    monkeypatch.setattr(reports, "PER_READER_HOUR", 2)
    body = {"message": "Valoarea include TVA."}
    one, other = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}, {"X-Forwarded-For": "203.0.113.8"}
    assert client.post("/v1/reports", json=body, headers=one).status_code == 201
    assert client.post("/v1/reports", json=body, headers=one).status_code == 201
    assert client.post("/v1/reports", json=body, headers=one).status_code == 429
    assert client.post("/v1/reports", json=body, headers=other).status_code == 201
    # What is kept is a hash, never the address.
    senders = {each.sender for each in reports.queue(session)}
    assert len(senders) == 2
    assert all(len(sender) == 64 and "203" not in sender for sender in senders)


def test_the_queue_takes_only_so_many_reports_an_hour(client, session, monkeypatch):
    monkeypatch.setattr(reports, "PER_HOUR", 2)
    monkeypatch.setattr(reports, "PER_READER_HOUR", 99)
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


def test_a_page_is_published_only_if_it_is_a_page_of_the_site(client, session):
    typed = (
        "Ion Popescu, 0722 000 000",
        "/Ion.Popescu.0722000000",
        "https://example.test/contracte/1",
        "/contracte/9001?x=Ion#y",
        None,
    )
    for page in typed:
        filed = reports.file(session, page, "Valoarea include TVA.", None)
        reports.settle(session, filed.id, reports.ACCEPTED, "Am corectat valoarea.")
    # The reviewer can name the page where the reader gave none.
    reports.settle(session, filed.id, reports.ACCEPTED, "Am corectat valoarea.", "/surse")

    pages = [item["page"] for item in client.get("/v1/corrections").json()["items"]]
    assert sorted(pages, key=str) == ["/contracte/9001", "/surse", None, None, None]
    assert reports.site_page("/") == "/"
    assert reports.site_page("/institutii/4981310") == "/institutii/4981310"
    assert reports.site_page("/programe/anghel-saligny") == "/programe/anghel-saligny"
    project = "/programe/anghel-saligny/proiecte/12519"
    assert reports.site_page(project) == project
    assert reports.site_page("/programe/altul") is None
    assert reports.site_page("//example.test") is None
    assert reports.site_page("/contracte/abc") is None


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

    # The reviewer's page must be a page of the site too.
    named = ["reports", "accept", str(filed.id), "--correction", "Acum e fără TVA.", "--page"]
    assert runner.invoke(cli.app, [*named, "Ion Popescu"]).exit_code == 1
    assert filed.page == "/contracte/9001"
    assert runner.invoke(cli.app, [*named, "/institutii/4981310"]).exit_code == 0
    assert filed.page == "/institutii/4981310"
