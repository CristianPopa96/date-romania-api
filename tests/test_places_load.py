"""Collecting the place sources from a made-up data.gov.ro, ministry portal and ANAF, into
PostgreSQL, in a transaction that is rolled back (see conftest.py), and placing the
entities from what they give."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from python_calamine import CalamineError
from sqlalchemy import func, select

from date_romania import places
from date_romania.collectors import anaf, local_budgets, public_entities, siruta
from date_romania.collectors.http import PoliteClient
from date_romania.dates import today
from date_romania.models import (
    AnafRecord,
    Entity,
    JobRun,
    LocalBudget,
    Place,
    Population,
    PublicEntity,
    SourceDocument,
)
from date_romania.sources import PUBLIC_ENTITIES
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures"
FILES = "https://data.gov.ro/dataset/x/resource"
SIRUTA_CSV = f"{FILES}/1/download/siruta_s1_2026.csv"
OLDER_SIRUTA = f"{FILES}/5/download/siruta_an_2025.csv"
BUDGET = f"{FILES}/2/download/situaia-veniturilor-i-cheltuielilor-2024.xlsx"
PEOPLE_2021 = f"{FILES}/3/download/populaia-2021.xlsx"
PEOPLE_2024 = f"{FILES}/4/download/populaia-2024.xlsx"
PORTAL = "https://extranet.anaf.mfinante.gov.ro/anaf/extranet/EXECUTIEBUGETARA/info_utile/"
LIST = "https://extranet.anaf.mfinante.gov.ro/anaf/wcm/connect/1/Lista_EP_portal_01102026.xls"

ZLATNA, SCHOOL, ALBAC, SECTOR_2, PALACE = 4331031, 4331007, 4562362, 4204038, 4322300


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def sources(monkeypatch):
    """The four sources as they answered on 17.10.2026, cut to a few rows. Returns a
    client, the requests sent, and a set of addresses to break: one put there answers
    HTTP 200 with an HTML "Request Rejected" page instead."""
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha = hashlib.sha256(content).hexdigest()
        stored[f"{source}/{sha}"] = content
        return StoredObject(key=f"{source}/{sha}", sha256=sha, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    for collector in (siruta, public_entities, local_budgets, anaf):
        monkeypatch.setattr(collector.run, "get_raw", lambda key: stored[key])

    datasets = {
        "siruta_s1-2026": [("SIRUTA_s1 2026", SIRUTA_CSV)],
        # Edited after the newer edition: its date must not make it the one taken.
        "siruta_an-2025": [("SIRUTA_an 2025", OLDER_SIRUTA)],
        local_budgets.run.DATASET: [
            ("Populația definitivă a României la 1 ianuarie 2021.xlsx", PEOPLE_2021),
            ("Populația definitivă a României la 1 ianuarie 2024.xlsx", PEOPLE_2024),
            ("Situația veniturilor și cheltuielilor - 2024.xlsx", BUDGET),
        ],
    }
    files = {
        SIRUTA_CSV: "siruta.csv",
        BUDGET: "local_budget.xlsx",
        PEOPLE_2021: "population_2021.xlsx",
        PEOPLE_2024: "population_2024.xlsx",
        LIST: "public_entities.xlsx",
    }
    sent: list[httpx.Request] = []
    broken: set[str] = set()

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        url = str(request.url)
        if any(url.startswith(address) for address in broken):
            return httpx.Response(200, text="<html>Request Rejected</html>")
        if "package_search" in url:
            found = [{"name": "siruta_an-2025"}, {"name": "siruta_s1-2026"}, {"name": "x"}]
            return httpx.Response(200, json={"success": True, "result": {"results": found}})
        if "package_show" in url:
            found = datasets.get(request.url.params["id"], [])
            resources = [
                {"name": name, "url": address, "created": f"2026-04-0{n}T10:00:00"}
                for n, (name, address) in enumerate(found, 1)
            ]
            return httpx.Response(200, json={"success": True, "result": {"resources": resources}})
        if url == PUBLIC_ENTITIES.list_url:
            return httpx.Response(302, headers={"location": PORTAL})
        if url == PORTAL:
            page = '<a href="?uri=nm:oid:Z6_1">Rapoarte Entități Publice</a>'
            page += '<a href="?uri=nm:oid:Z6_2"><span>Alte Rapoarte</span></a>'
            return httpx.Response(200, text=page)
        if url == f"{PORTAL}?uri=nm:oid:Z6_2":
            page = '<a href="/anaf/wcm/connect/1/Lista_EP_portal_01102026.xls?MOD=AJPERES">'
            page += "Lista entitatilor publice - actualizata 01.10.2026</a>"
            return httpx.Response(200, text=page)
        if url.startswith(LIST):
            return httpx.Response(200, content=(FIXTURES / files[LIST]).read_bytes())
        if url == anaf.run.URL:
            return httpx.Response(200, content=(FIXTURES / "anaf.json").read_bytes())
        if url in files:
            return httpx.Response(200, content=(FIXTURES / files[url]).read_bytes())
        return httpx.Response(404)

    with PoliteClient(transport=httpx.MockTransport(answer), sleep=lambda seconds: None) as client:
        yield client, sent, broken


@pytest.fixture
def held(session):
    """The entities of a few SEAP rows: a town, its high school, a commune, a Bucharest
    sector, a school in Târgu Mureș, and a company."""
    for cui, name, kind in (
        (ZLATNA, "ORAS ZLATNA", "authority"),
        (SCHOOL, "LICEUL CORNELIU MEDREA", "authority"),
        (ALBAC, "COMUNA ALBAC", "authority"),
        (SECTOR_2, "SECTORUL 2", "authority"),
        (PALACE, "PALATUL COPIILOR", "authority"),
        (99999999, "FIRMA SRL", "company"),
    ):
        session.add(Entity(cui=cui, name=name, kind=kind))
    session.flush()


def test_siruta_is_stored_once_and_gives_every_place(session, sources):
    client, sent, broken = sources
    assert siruta.collect(session, client) == 15
    assert count(session, Place) == 15
    assert session.get(Place, 179150).parent == 179132
    # The newest edition was asked for, and a second run downloads nothing.
    # The newest edition by its file name, though both datasets were listed.
    downloads = [str(r.url) for r in sent if "download" in str(r.url)]
    assert downloads == [SIRUTA_CSV]
    sent.clear()
    assert siruta.collect(session, client) == 0
    assert [r for r in sent if "download" in str(r.url)] == []


def test_the_list_places_institutions_and_names_their_funder(session, sources, held):
    client, _, broken = sources
    siruta.collect(session, client)
    assert public_entities.collect(session, client) == 7
    doc = session.scalars(select(SourceDocument).where(SourceDocument.source == "public-entities"))
    assert doc.one().request_body == "Lista entitatilor publice - actualizata 01.10.2026"

    school = session.get(Entity, SCHOOL)
    assert (school.siruta, school.county, school.locality) == (1936, "Alba", "ORAŞ ZLATNA")
    # Its first funder is the town, which we hold.
    assert school.parent_cui == ZLATNA
    # Old spelling in the list: 'Tirgu Mures'. Its funder, the ministry, is not held.
    palace = session.get(Entity, PALACE)
    assert (palace.siruta, palace.county, palace.parent_cui) == (114319, "Mureș", None)
    # A commune SIRUTA no longer holds stays unplaced.
    assert session.get(PublicEntity, 4801400).siruta is None


def test_anaf_places_the_rest_and_is_not_asked_twice(session, sources, held):
    client, sent, broken = sources
    siruta.collect(session, client)
    public_entities.collect(session, client)
    sent.clear()
    # Every entity is asked, the company too, 100 to a call.
    assert anaf.collect(session, client) == 5
    body = json.loads(next(r for r in sent if str(r.url) == anaf.run.URL).content)
    assert {item["cui"] for item in body} == {ZLATNA, SCHOOL, ALBAC, SECTOR_2, PALACE, 99999999}
    assert {item["data"] for item in body} == {today().isoformat()}

    # Only ANAF names the commune of Albac and the sector.
    assert session.get(Entity, ALBAC).siruta == 2130
    assert session.get(Entity, SECTOR_2).siruta == 179150
    assert session.get(Entity, SECTOR_2).county == "București"
    assert session.get(AnafRecord, 99999999).found is False
    assert session.get(Entity, 99999999).siruta is None

    # A tax ID asked once is not asked again.
    assert anaf.run.due(session) == [PALACE]
    session.get(Entity, ALBAC).siruta = None
    assert anaf.reparse(session) == 1
    session.expire_all()
    assert session.get(Entity, ALBAC).siruta == 2130


def test_budgets_and_population_are_filed_by_siruta(session, sources):
    client, _, broken = sources
    siruta.collect(session, client)
    assert local_budgets.collect(session, client) > 0
    filed = set(session.scalars(select(LocalBudget.siruta).where(LocalBudget.column_no == 1)))
    # The county council of Alba under the county; the city hall of Bucharest next to its
    # sector.
    assert filed == {10, 1017, 1936, 2130, 179132, 179141}
    assert str(session.get(LocalBudget, (10, 2024, 1)).amount) == "471110222.00"

    people = dict(session.execute(select(Population.siruta, Population.people)).all())
    people_2021 = dict(
        session.execute(
            select(Population.siruta, Population.people).where(Population.on == date(2021, 1, 1))
        ).all()
    )
    # 2021 lists Bucharest's total next to its sectors: left out, it is theirs added up.
    assert set(people_2021) == {1017, 2130, 179141, 179150}
    # 2024 names the sectors with no code.
    assert session.get(Population, (179150, date(2024, 1, 1))).people == 359968
    assert 179132 not in people

    assert local_budgets.reparse(session) == 3


def test_placing_again_follows_the_sources_held(session, sources, held):
    client, _, broken = sources
    siruta.collect(session, client)
    public_entities.collect(session, client)
    session.get(Entity, SCHOOL).county = None
    assert places.locate(session) == 3
    session.expire_all()
    assert session.get(Entity, SCHOOL).county == "Alba"


def test_an_edition_that_cannot_be_read_is_fetched_again(session, sources, held):
    client, sent, broken = sources
    siruta.collect(session, client)
    broken.add(LIST)
    # An HTML page where the workbook should be.
    with pytest.raises(CalamineError):
        public_entities.collect(session, client)
    held_docs = select(SourceDocument).where(SourceDocument.source == "public-entities")
    assert session.scalars(held_docs).all() == []
    run = session.scalars(select(JobRun).where(JobRun.job == "public-entities")).one()
    assert run.status == "failed"

    broken.clear()
    assert public_entities.collect(session, client) == 7
    # A second run asks the portal and downloads nothing.
    sent.clear()
    assert public_entities.collect(session, client) == 0
    assert not [r for r in sent if str(r.url).startswith(LIST)]


def test_an_html_answer_from_anaf_is_not_kept(session, sources, held):
    client, _, broken = sources
    siruta.collect(session, client)
    public_entities.collect(session, client)
    broken.add(anaf.run.URL)
    assert anaf.collect(session, client) == 0
    assert count(session, AnafRecord) == 0
    assert (
        session.scalars(select(SourceDocument).where(SourceDocument.source == "anaf")).all() == []
    )
    run = session.scalars(select(JobRun).where(JobRun.job == "anaf")).one()
    assert run.status == "partial"
    assert "6 tax IDs left" in run.error
    # The entities are still placed from what is held.
    assert session.get(Entity, SCHOOL).siruta == 1936
    # The next run asks again.
    broken.clear()
    assert anaf.collect(session, client) == 5


def test_budgets_need_places_first(session, sources):
    client, _, _ = sources
    with pytest.raises(local_budgets.run.NoPlaces):
        local_budgets.collect(session, client)
    assert count(session, LocalBudget) == 0


def test_a_file_that_cannot_be_read_does_not_stop_the_others(session, sources):
    client, sent, broken = sources
    siruta.collect(session, client)
    broken.add(PEOPLE_2021)
    assert local_budgets.collect(session, client) > 0
    run = session.scalars(select(JobRun).where(JobRun.job == "local-budgets")).one()
    assert (run.status, run.error) == ("partial", "1 files failed; run again to retry them")
    # The files after it were read.
    assert session.get(Population, (179150, date(2024, 1, 1))) is not None
    assert count(session, LocalBudget) > 0
    # The next run fetches only the one that failed.
    broken.clear()
    sent.clear()
    local_budgets.collect(session, client)
    assert [str(r.url) for r in sent if "download" in str(r.url)] == [PEOPLE_2021]
    assert session.get(Population, (179150, date(2021, 1, 1))) is not None
