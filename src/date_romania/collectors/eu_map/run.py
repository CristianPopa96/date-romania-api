"""Collecting the newest edition of the map, and loading it again from the raw store."""

import json
import logging
import re
from datetime import date

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from date_romania import entities, eu_links, eu_seap_links, places
from date_romania.collectors.eu_map.parse import PARSER_VERSION, parse
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.dates import today
from date_romania.eu_programmes import BY_CODE
from date_romania.models import EuProject, Place, SourceDocument, held_by_map
from date_romania.places import UATS
from date_romania.sources import EU_MAP
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = EU_MAP.key
EDITIONS = "https://mfe.gov.ro/map2021/map_export.php"
FILES = "https://mfe.gov.ro/map2021/value/"
# The export page offers every edition: <option value="27102026-funds.json">.
_EDITION = re.compile(r'value="(\d{2})(\d{2})(\d{4})-funds\.json"')


def newest_edition(client: PoliteClient) -> tuple[date, str]:
    """The day and address of the newest edition the map offers."""
    page = client.request("GET", EDITIONS).text
    days = {date(int(y), int(m), int(d)) for d, m, y in _EDITION.findall(page)}
    if not days:
        raise ValueError(f"no edition offered on {EDITIONS}")
    day = max(days)
    return day, f"{FILES}{day:%d%m%Y}-funds.json"


def _edition(doc: SourceDocument) -> date:
    return date.fromisoformat(json.loads(doc.request_body or "{}")["edition"])


def load(session: Session) -> int:
    """Load the newest stored edition in place of the one before; returns the projects the
    map holds. A list's project stays the list's: the map adds the projects no list holds,
    and gives a list's project the tax ID and the UAT the map has for it. Run after every
    load of the map or of a list. The caller ties them and commits."""
    docs = stored_documents(session, SOURCE)
    if not docs:
        return 0
    doc = max(docs, key=lambda each: (_edition(each), each.id))
    parsed = parse(get_raw(doc.storage_key), _edition(doc))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    if not parsed.projects:
        raise ValueError(f"no projects in the map's edition of {_edition(doc)}")
    entities.upsert(session, parsed.entities, doc.id)
    uats = set(session.scalars(select(Place.siruta).where(Place.kind.in_(UATS))))
    for project in parsed.projects.values():
        if project["siruta"] not in uats:
            project["siruta"] = None
    session.execute(delete(EuProject).where(held_by_map()))
    listed = set(session.scalars(select(EuProject.smis)))
    rows = []
    for smis, project in parsed.projects.items():
        if smis in listed:
            continue
        if BY_CODE[project["programme"]].health_page:
            # The Health programme publishes its payments one by one, dated: those are the
            # project's payments, never added to the map's total.
            project["paid"] = None
        rows.append({**project, "source_document_id": doc.id, "parser_version": PARSER_VERSION})
    if rows:
        session.execute(insert(EuProject), rows)
    # What the map adds to a list's project, never in place of what the list gives.
    filled = [
        {
            "smis": smis,
            "map_cui": parsed.projects[smis]["map_cui"],
            "siruta": parsed.projects[smis]["siruta"],
        }
        for smis in listed & parsed.projects.keys()
    ]
    if filled:
        session.execute(update(EuProject), filled)
    session.flush()
    log.info(
        "map of %s: %d projects added, %d of the lists'", _edition(doc), len(rows), len(filled)
    )
    return len(rows)


def _tie(session: Session) -> None:
    places.locate(session)
    eu_links.link(session)
    eu_seap_links.link(session)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch the newest edition if it is not held, and load it; returns the projects the
    map holds."""
    with job_run(session, JOB, today()) as run:
        day, url = newest_edition(client)
        held = session.scalar(
            select(SourceDocument.id).where(
                SourceDocument.source == SOURCE, SourceDocument.url == url
            )
        )
        if held is not None:
            log.info("map of %s already held", day)
            return 0
        response = client.request("GET", url)
        doc = store_document(
            session,
            SOURCE,
            url,
            response.content,
            request_body=json.dumps({"edition": day.isoformat()}),
            content_type=response.headers.get("content-type"),
        )
        session.commit()
        log.info("map of %s: stored (%d bytes)", day, doc.size_bytes)
        run.records = load(session)
        _tie(session)
    return run.records


def reparse(session: Session) -> int:
    """Load the newest stored edition again, without calling anyone; returns the files
    read (one, or none when no edition is held)."""
    load(session)
    _tie(session)
    session.commit()
    return min(1, len(stored_documents(session, SOURCE)))
