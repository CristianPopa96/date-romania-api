"""The trade register (collectors/onrc): reading an edition, loading it on top of the one
before, collecting about once a quarter, and tying a beneficiary named without a tax ID.

Over places_seed.py: Gorj and its commune Țânțăreni. The fixtures are a few rows in the
register's own format (byte-order mark, '^', CRLF), with a natural person on two of them.
"""

import shutil
from datetime import date
from pathlib import Path

import httpx
import places_seed
import pytest
from places_seed import GORJ, TANTARENI
from sqlalchemy import select

from date_romania import eu_links
from date_romania.api.routes.entities import supplier
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.onrc import parse, run
from date_romania.collectors.onrc.load import load
from date_romania.models import Entity, EuProject, RegisterCompany, SourceDocument
from date_romania.places import PlaceIndex
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures" / "onrc"
ALFA, PERSON, BETA, OLD, GAMMA_GORJ, GAMMA_DOLJ = (
    412052,
    1594424,
    18288250,
    334760,
    1590082,
    14399840,
)


@pytest.fixture
def placed(session):
    session.add(Entity(cui=places_seed.TOWN_HALL, name="COMUNA TANTARENI", kind="authority"))
    for cui in (places_seed.HOSPITAL, places_seed.BUILDER, places_seed.STATIONER):
        session.add(Entity(cui=cui, name=f"Entitate {cui}", kind="company"))
    session.flush()
    places_seed.seed(session)
    return PlaceIndex.load(session)


def _companies(index, read=None, name="od_firme.csv"):
    return list(parse.companies(FIXTURES / name, index, read or parse.Read()))


def test_only_legal_persons_are_read(session, placed):
    read = parse.Read()
    rows = {row[0]: row for row in _companies(placed, read)}
    # The natural persons are skipped unread, and so is a company with no tax ID.
    assert PERSON not in rows and read.persons == 2
    assert sorted(rows) == sorted([ALFA, BETA, OLD, GAMMA_GORJ, GAMMA_DOLJ])
    assert rows[ALFA] == (
        ALFA,
        "ALFA DRUM SRL",
        "ALFA DRUM SRL",
        "SRL",
        "J18/100/2010",
        date(2010, 3, 14),
        GORJ,
        TANTARENI,
    )
    # A registration with its time.
    assert date(2020, 8, 14) in {row[5] for row in _companies(placed) if row[0] == BETA}
    # A tax ID that fails its check, a form not known and a broken row are rejected, and
    # logged without a name: a broken row could be a person's.
    assert read.rejected == [
        ("J18/400/2005", "tax ID fails its check: '4245150'"),
        ("J18/500/2024", "legal form not known: 'XYZ'"),
        (None, "2 fields, not 20"),
    ]


def _load(session, index, edition, states="od_stare_firma.csv"):
    doc = SourceDocument(
        source="onrc",
        url=f"https://data.gov.ro/{edition}",
        sha256=str(edition).ljust(64, "0"),
        storage_key=f"onrc/{edition}",
        size_bytes=1,
    )
    session.add(doc)
    session.flush()
    listed = load(
        session,
        edition,
        doc.id,
        parse.companies(FIXTURES / "od_firme.csv", index, parse.Read()),
        parse.states(FIXTURES / states, parse.Read()),
        parse.state_names(FIXTURES / "n_stare_firma.csv", parse.Read()),
    )
    session.expire_all()
    return listed


def test_an_edition_is_loaded_on_top_of_the_one_before(session, placed, tmp_path):
    assert _load(session, placed, date(2026, 7, 8)) == 5
    # A company that moved keeps the registration it has, not the one struck off.
    beta = session.get(RegisterCompany, BETA)
    assert (beta.registration, beta.siruta, beta.deleted) == ("J18/200/2020", TANTARENI, False)
    assert beta.states == ["funcțiune", "sediu expirat"]
    old = session.get(RegisterCompany, OLD)
    assert (old.states, old.deleted) == (["radiată"], True)

    # The next edition: Alfa is being dissolved.
    later = tmp_path / "od_stare_firma.csv"
    text = (FIXTURES / "od_stare_firma.csv").read_text("utf-8-sig")
    later.write_text(text.replace("J18/100/2010^1048", "J18/100/2010^1049"), "utf-8-sig")
    shutil.copy(FIXTURES / "n_stare_firma.csv", tmp_path)
    shutil.copy(FIXTURES / "od_firme.csv", tmp_path)
    _load(session, placed, date(2026, 10, 19), states=later)
    alfa = session.get(RegisterCompany, ALFA)
    assert alfa.states == ["dizolvare"]
    assert (alfa.first_seen, alfa.state_since, alfa.last_seen) == (
        date(2026, 7, 8),
        date(2026, 10, 19),
        date(2026, 10, 19),
    )
    # A state that did not change keeps the edition it was first seen in.
    assert session.get(RegisterCompany, BETA).state_since == date(2026, 7, 8)


def test_an_edition_is_fetched_about_once_a_quarter():
    july, september, october = date(2026, 7, 8), date(2026, 9, 2), date(2026, 10, 19)
    assert run.due([], [july, september]) == september
    assert run.due([july], [july, september]) is None
    assert run.due([july], [july, september, october]) == october
    assert run.due([october], []) is None


def _datagov(asked: list[str]) -> httpx.MockTransport:
    files = {
        "OD_FIRME.CSV": "od_firme.csv",
        "OD_STARE_FIRMA.CSV": "od_stare_firma.csv",
        "N_STARE_FIRMA.CSV": "n_stare_firma.csv",
        # Never asked for: the legal representatives are natural persons.
        "OD_REPREZENTANTI_LEGALI.CSV": None,
    }

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if "package_search" in url:
            kind = "firme" if "firme" in request.url.params["q"] else "nomenclatoare"
            found = [{"name": f"{kind}-19-10-2026"}, {"name": f"{kind}-02-09-2026"}]
            return httpx.Response(200, json={"success": True, "result": {"results": found}})
        if "package_show" in url:
            dataset = request.url.params["id"]
            names = (
                ["N_STARE_FIRMA.CSV"] if dataset.startswith("nomenclatoare") else list(files)[:2]
            ) + (["OD_REPREZENTANTI_LEGALI.CSV"] if dataset.startswith("firme") else [])
            resources = [
                {"name": name, "url": f"https://data.gov.ro/{dataset}/{name.lower()}"}
                for name in names
            ]
            return httpx.Response(200, json={"success": True, "result": {"resources": resources}})
        name = url.rsplit("/", 1)[-1].upper()
        if files.get(name):
            return httpx.Response(200, content=(FIXTURES / files[name]).read_bytes())
        return httpx.Response(404)

    return httpx.MockTransport(answer)


def test_an_edition_is_collected_and_ties_a_beneficiary(session, placed, monkeypatch):
    stored: dict[str, bytes] = {}

    def put_raw_file(source, path, content_type=None):
        content = path.read_bytes()
        key = f"{source}/{len(stored)}"
        stored[key] = content
        return StoredObject(
            key=key, sha256=str(len(stored)).ljust(64, "0"), size_bytes=len(content)
        )

    def get_raw_file(key, path):
        path.write_bytes(stored[key])
        return path

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw_file", put_raw_file)
    monkeypatch.setattr(run, "get_raw_file", get_raw_file)
    monkeypatch.setattr(run.eu_seap_links, "link", lambda s: 0)
    doc = SourceDocument(
        source="eu-projects",
        url="https://x/por.xlsx",
        sha256="e" * 64,
        storage_key="e",
        size_bytes=1,
    )
    session.add(doc)
    session.flush()
    named = {
        1: ("ALFA DRUM S.R.L.", "Dolj"),
        # Two companies carry the name; the project's county tells them apart.
        2: ("SC Gamma Construct SRL", "GJ"),
        3: ("Gamma Construct SRL", "Vaslui"),
        4: ("POPESCU ION PERSOANĂ FIZICĂ AUTORIZATĂ", "Gorj"),
    }
    session.add_all(
        EuProject(
            smis=smis,
            programme="POR",
            period="2014-2020",
            beneficiary_name=name,
            county=county,
            source_document_id=doc.id,
            parser_version=2,
        )
        for smis, (name, county) in named.items()
    )
    session.flush()
    asked: list[str] = []
    with PoliteClient(transport=_datagov(asked), sleep=lambda seconds: None) as client:
        assert run.collect(session, client) == 5
        assert not any("reprezentanti" in url for url in asked)
        # The edition held is the newest: nothing more is fetched.
        asked.clear()
        assert run.collect(session, client) == 0
        assert not any(url.endswith(".csv") for url in asked)
    session.expire_all()
    ties = {p.smis: (p.entity_cui, p.entity_method) for p in session.scalars(select(EuProject))}
    assert ties == {
        1: (ALFA, eu_links.BY_REGISTER),
        2: (GAMMA_GORJ, eu_links.BY_REGISTER),
        3: (None, None),
        4: (None, None),
    }
    # The company tied becomes an entity, with its official name and its place.
    alfa = session.get(Entity, ALFA)
    assert (alfa.name, alfa.kind, alfa.siruta, alfa.county) == (
        "ALFA DRUM SRL",
        "company",
        TANTARENI,
        "Gorj",
    )
    # A company held (the seed's stationer) takes its official name and its place from
    # the register.
    beta = session.get(Entity, BETA)
    assert (beta.name, beta.siruta) == ("BETA BIROTICA S.R.L.", TANTARENI)

    # Its page says what the register says, from the edition it was read in.
    page = supplier(session, BETA)
    assert page.trade_register.registration == "J18/200/2020"
    assert (page.trade_register.states, page.trade_register.deleted, page.trade_register.since) == (
        ["funcțiune", "sediu expirat"],
        False,
        None,
    )
    assert page.trade_register.edition == date(2026, 10, 19)
    assert page.trade_register.source.url == "https://data.gov.ro/dataset/firme-19-10-2026"
    assert supplier(session, places_seed.HOSPITAL).trade_register is None

    # Every edition is read again from the raw store, with no request.
    assert run.reparse(session) == 1
    assert session.get(RegisterCompany, ALFA).first_seen == date(2026, 10, 19)
    assert session.scalar(select(RegisterCompany).where(RegisterCompany.cui == PERSON)) is None
