"""Reading MIPE's map of the 2021-2027 projects, and loading it next to the lists, against a
stand-in for mfe.gov.ro, inside a transaction that is rolled back."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import eu_seed
import httpx
import pytest
from sqlalchemy import select

from date_romania.api.routes.eu_projects import eu_funds
from date_romania.collectors.eu_map import parse, run
from date_romania.collectors.eu_projects import run as lists
from date_romania.collectors.http import PoliteClient
from date_romania.models import Entity, EuProject, Place, SourceDocument
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures" / "eu_map"
EDITION = f"{run.FILES}27102026-funds.json"
ALBA_IULIA, STATIONER = 1017, 18288250


def test_an_edition_is_read_one_project_per_smis_code():
    parsed = parse.parse((FIXTURES / "edition.json").read_bytes(), date(2026, 10, 27))
    assert sorted(parsed.projects) == [312456, 400001, 400002, 400003, 400004, 400006]
    regional = parsed.projects[400001]
    assert (regional["programme"], regional["period"]) == ("PRC", "2021-2027")
    assert (regional["map_cui"], regional["beneficiary_cui"]) == (STATIONER, None)
    assert (regional["siruta"], regional["county"]) == (ALBA_IULIA, "AB")
    assert (regional["starts_on"], regional["cut_off"]) == (date(2023, 10, 27), date(2026, 10, 27))
    # One project on two funds: its rows are added.
    both = parsed.projects[400002]
    assert (both["total_value"], both["eu_value"], both["paid"]) == (
        Decimal("1000000"),
        Decimal("800000"),
        Decimal("100000"),
    )
    # A foreign lead has no tax ID here; several localities name no UAT.
    assert (parsed.projects[400004]["map_cui"], parsed.projects[400004]["siruta"]) == (None, None)
    # A programme not known is rejected, never guessed; so is a fund listed again, never
    # added twice.
    assert [smis for smis, _ in parsed.rejected] == ["400005", "400001"]
    assert regional["paid"] == Decimal("250000")
    assert parsed.entities[STATIONER] == ("Beta Birotica SRL", "company")


def mfe(asked: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url == run.EDITIONS:
            return httpx.Response(200, text=(FIXTURES / "export.html").read_text("utf-8"))
        if url == EDITION:
            return httpx.Response(200, content=(FIXTURES / "edition.json").read_bytes())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def held(session, monkeypatch) -> dict[str, bytes]:
    """The lists' projects of the seed, a place, and a raw store in memory."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha256 = hashlib.sha256(content).hexdigest()
        stored[sha256] = content
        return StoredObject(key=sha256, sha256=sha256, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr(run, "get_raw", lambda key: stored[key])
    monkeypatch.setattr(lists, "get_raw", lambda key: stored[key])
    monkeypatch.setattr(run.places, "locate", lambda s: None)
    session.add_all(
        [
            Entity(cui=eu_seed.TOWN_HALL, name="Comuna Țânțăreni", kind="authority"),
            Entity(cui=eu_seed.HOSPITAL, name="SPITALUL JUDETEAN DE URGENTA", kind="authority"),
        ]
    )
    eu_seed.seed(session)
    session.add(
        Place(
            siruta=ALBA_IULIA,
            name="MUNICIPIUL ALBA IULIA",
            kind="municipality",
            urban=True,
            source_document_id=session.scalar(select(SourceDocument.id).limit(1)),
            parser_version=1,
        )
    )
    session.flush()
    return stored


def no_sleep(seconds: float) -> None:
    pass


def collect(session) -> list[str]:
    asked: list[str] = []
    with PoliteClient(transport=mfe(asked), sleep=no_sleep) as client:
        run.collect(session, client)
    return asked


def test_the_map_adds_what_no_list_holds(session, held):
    assert collect(session) == [run.EDITIONS, EDITION]
    regional = session.get(EuProject, 400001)
    assert (regional.programme, regional.siruta, regional.paid) == ("PRC", ALBA_IULIA, 250000)
    # Its lead becomes an entity, tied surely by the map's tax ID.
    assert session.get(Entity, STATIONER).kind == "company"
    assert (regional.entity_cui, regional.entity_method) == (STATIONER, "cui-in-map")
    # Health's payments are the ministry's, dated: the map's total is not kept. Nor is it
    # for a project the map adds to a list's programme: its validated payments are not
    # what the list calls paid, at another day.
    assert session.get(EuProject, 400003).paid is None
    added = session.get(EuProject, 400006)
    assert (added.programme, added.paid, added.cut_off) == ("PEO", None, date(2026, 10, 27))
    # A programme's day is its list's where a list holds some of its projects.
    funds = {each.code: each for each in eu_funds(session).programmes}
    assert (funds["PEO"].cut_off, funds["PEO"].paid, funds["PEO"].paid_as) == (
        date(2026, 9, 30),
        600000,
        "cumulative",
    )
    assert (funds["PRC"].cut_off, funds["PRC"].paid, funds["PRC"].paid_as) == (
        date(2026, 10, 27),
        250000,
        "validated",
    )
    # The list's project stays the list's, with what the map adds next to it.
    peo = session.get(EuProject, eu_seed.PEO)
    doc = session.get(SourceDocument, peo.source_document_id)
    assert (doc.source, peo.title, peo.county, peo.paid) == (
        "eu-projects",
        "Dotarea laboratoarelor spitalului",
        "GJ",
        600000,
    )
    assert (peo.beneficiary_cui, peo.map_cui, peo.siruta) == (
        eu_seed.HOSPITAL,
        eu_seed.HOSPITAL,
        ALBA_IULIA,
    )
    assert peo.entity_method == "cui-in-list"
    # The same edition is not fetched again.
    assert collect(session) == [run.EDITIONS]


def test_a_list_takes_back_a_project_the_map_held(session, held, monkeypatch):
    collect(session)
    doc = session.scalars(
        select(SourceDocument).where(SourceDocument.source == "eu-projects")
    ).first()
    doc.request_body = '{"cut_off": "2026-09-30"}'
    listed = {
        "smis": 400002,
        "programme": "PoIDS",
        "period": "2021-2027",
        "title": "Din lista PoIDS",
        "cut_off": date(2026, 9, 30),
    }

    class Parsed:
        projects = [listed]
        rejected: list = []
        entities: dict = {}
        unread: dict = {}

    monkeypatch.setattr(lists, "parse_projects", lambda *args: Parsed)
    held[doc.storage_key] = b""
    lists._load_programme(session, "PoIDS", [doc])
    run.load(session)
    session.flush()
    project = session.get(EuProject, 400002)
    assert (project.title, project.source_document_id) == ("Din lista PoIDS", doc.id)
    # What the map adds comes back once the map is loaded again.
    assert project.map_cui == eu_seed.TOWN_HALL
    # The map's other projects stay.
    assert session.get(EuProject, 400001) is not None
