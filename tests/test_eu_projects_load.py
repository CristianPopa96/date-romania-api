"""Finding, storing and loading the lists of EU projects, against a stand-in for
data.gov.ro and mfe.gov.ro, inside a transaction that is rolled back."""

import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from date_romania.collectors.eu_projects import run
from date_romania.collectors.eu_projects.discover import HEALTH_PAGE, POSTS
from date_romania.collectors.http import PoliteClient
from date_romania.models import EuProject, EuProjectPayment, JobRun, SourceDocument
from date_romania.storage import StoredObject

FIXTURES = Path(__file__).parent / "fixtures" / "eu_projects"
UPLOADS = "https://mfe.gov.ro/wp-content/uploads/2026/10/"
FILES = {
    "https://data.gov.ro/por-2025-08.xlsx": "por.xlsx",
    f"{UPLOADS}poids.xlsx": "poids.xlsx",
    f"{UPLOADS}pocidif.7z": "pocidif.7z",
    f"{UPLOADS}pddtj.zip": "pddtj.zip",
    f"{UPLOADS}ps-list.xlsx": "ps_list.xlsx",
    f"{UPLOADS}ps-september.xlsx": "ps_payments.xlsx",
    f"{UPLOADS}ps-august.xlsx": "ps_not_payments.xlsx",
}
PACKAGE = {
    "success": True,
    "result": {
        "resources": [
            {
                "name": "POR - Lista proiectelor contractate la 31 decembrie 2024",
                "url": "https://data.gov.ro/por-2024-12.xlsx",
                "created": "2024-09-16",
            },
            {
                "name": "POR -Lista proiectelor contractate la 31 august 2025",
                "url": "https://data.gov.ro/por-2025-08.xlsx",
                "created": "2026-07-09",
            },
            {"name": "Ghid", "url": "https://data.gov.ro/ghid.pdf", "created": "2026-07-09"},
        ]
    },
}
# PEO, PoAT and the Just Transition part of PDDTJ have no post here: they are not found.
POSTS_FOUND = [
    ("2026-10-19", "PoIDS: Lista proiectelor PoIDS contractate la 30 septembrie 2026", "poids"),
    ("2026-09-17", "PoCIDIF: Lista proiectelor contractate la 15 septembrie 2026", "pocidif"),
    (
        "2026-08-19",
        "PDDTJ: Lista proiectelor contractate actualizată la data de 30 iunie 2026 – "
        "Prioritatea Dezvoltare Durabilă",
        "pddtj",
    ),
    # Same initials, an older programme: left out by its day.
    ("2019-10-10", "Lista proiectelor contractate POAT – actualizată la 30 septembrie 2019", "x"),
]
HEALTH = f"""
<table><tr><td> 1 octombrie 2026 </td><td>
<a href="{UPLOADS}ps-list.xlsx" class="mtli_xlsx">Lista proiectelor contractate
Program Sănătate_31 august 2026</a>
</td></tr>
<tr><td style="width: 15%"> 1 septembrie - 30 septembrie 2026 </td><td>
<a href="{UPLOADS}ps-september.xlsx">Plăți efectuate</a></td></tr>
<tr><td style="width: 15%"> 1 august - 31 august 2026 </td><td>
<a href="{UPLOADS}ps-august.xlsx">Plăți efectuate</a></td></tr></table>
"""


def mfe(asked: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url.startswith("https://data.gov.ro/api/3/action/package_show"):
            return httpx.Response(200, json=PACKAGE)
        if url.startswith(POSTS):
            posts = [
                {
                    "date": f"{day}T10:00:00",
                    "link": f"https://mfe.gov.ro/{slug}/",
                    "title": {"rendered": title},
                }
                for day, title, slug in POSTS_FOUND
            ]
            # WordPress starts its answer with a byte-order mark.
            body = b"\xef\xbb\xbf" + json.dumps(posts).encode()
            return httpx.Response(200, content=body, headers={"X-WP-TotalPages": "1"})
        for slug in ("poids", "pocidif", "pddtj"):
            if url == f"https://mfe.gov.ro/{slug}/":
                ext = {"poids": "xlsx", "pocidif": "7z", "pddtj": "zip"}[slug]
                return httpx.Response(200, text=f'<p><a href="{UPLOADS}{slug}.{ext}">Lista</a></p>')
        if url == HEALTH_PAGE:
            return httpx.Response(200, text=HEALTH)
        if url in FILES:
            return httpx.Response(200, content=(FIXTURES / FILES[url]).read_bytes())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def raw_store(monkeypatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}

    def put_raw(source, content, content_type=None):
        sha256 = hashlib.sha256(content).hexdigest()
        stored[sha256] = content
        return StoredObject(key=sha256, sha256=sha256, size_bytes=len(content))

    monkeypatch.setattr("date_romania.collectors.jobs.put_raw", put_raw)
    monkeypatch.setattr("date_romania.collectors.eu_projects.run.get_raw", lambda key: stored[key])
    monkeypatch.setattr("date_romania.collectors.eu_projects.run.places.locate", lambda s: None)
    return stored


def no_sleep(seconds: float) -> None:
    pass


def count(session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_collect_finds_the_newest_list_of_each_programme(session, raw_store):
    asked: list[str] = []
    with PoliteClient(transport=mfe(asked), sleep=no_sleep) as client:
        assert run.collect(session, client) == 15
    # The newest POR list, never the older one.
    assert "https://data.gov.ro/por-2024-12.xlsx" not in asked
    by_programme = dict(
        session.execute(
            select(EuProject.programme, func.count()).group_by(EuProject.programme)
        ).all()
    )
    assert by_programme == {"POR": 3, "PoIDS": 3, "PoCIDIF": 4, "PDDTJ": 3, "PS": 2}
    por = session.get(EuProject, 103910)
    assert (por.programme, por.period, por.cut_off) == ("POR", "2014-2020", date(2025, 8, 31))
    assert session.scalar(select(EuProject.cut_off).where(EuProject.programme == "PS")) == date(
        2026, 8, 31
    )
    # The programmes with no post found: the run says so, and the others are loaded.
    job = session.scalars(select(JobRun).where(JobRun.job == run.JOB)).one()
    assert job.status == "partial"
    assert "PEO" in job.error and "PoAT" in job.error and "PDDTJ" in job.error


def test_a_smis_held_by_one_programme_is_not_taken_by_another(session, raw_store):
    with PoliteClient(transport=mfe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    poids = session.scalar(
        select(SourceDocument).where(SourceDocument.url == f"{UPLOADS}poids.xlsx")
    )
    # The same list read as another programme's: PoIDS keeps its projects.
    run._load_programme(session, "PEO", [poids])
    assert (
        session.scalar(
            select(func.count()).select_from(EuProject).where(EuProject.programme == "PEO")
        )
        == 0
    )
    assert poids.rejected_rows == 3


def test_a_list_with_no_projects_never_empties_its_programme(session, raw_store):
    with PoliteClient(transport=mfe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    august = session.scalar(
        select(SourceDocument).where(SourceDocument.url == f"{UPLOADS}ps-august.xlsx")
    )
    with pytest.raises(ValueError, match="no projects"):
        run._load_programme(session, "PS", [august])
    assert count(session, EuProject, EuProject.programme == "PS") == 2


def test_health_payments_are_kept_and_a_file_that_is_not_payments_is_set_aside(session, raw_store):
    with PoliteClient(transport=mfe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    assert count(session, EuProjectPayment) == 3
    august = session.scalar(
        select(SourceDocument).where(SourceDocument.url == f"{UPLOADS}ps-august.xlsx")
    )
    # Seen and set aside: counted as read, with no rejected rows to show.
    assert (august.parser_version, august.rejected_rows) == (1, None)
    september = session.scalar(
        select(SourceDocument).where(SourceDocument.url == f"{UPLOADS}ps-september.xlsx")
    )
    assert json.loads(september.request_body)["cut_off"] == "2026-09-30"


def test_a_second_run_fetches_nothing_new(session, raw_store):
    with PoliteClient(transport=mfe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    asked: list[str] = []
    with PoliteClient(transport=mfe(asked), sleep=no_sleep) as client:
        assert run.collect(session, client) == 0
    assert not any(url in FILES for url in asked)


def test_reparse_loads_the_stored_lists_again(session, raw_store):
    with PoliteClient(transport=mfe([]), sleep=no_sleep) as client:
        run.collect(session, client)
    held = count(session, EuProject)
    session.execute(EuProject.__table__.delete())
    session.execute(EuProjectPayment.__table__.delete())
    run.reparse(session)
    assert count(session, EuProject) == held
    assert count(session, EuProjectPayment) == 3
