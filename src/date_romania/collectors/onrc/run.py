"""Collecting an edition of the trade register about once a quarter, and loading every
stored edition again from the raw store.

An edition is two datasets on data.gov.ro, published the same day: `firme-19-10-2026`
(the companies and their states, among other files) and `nomenclatoare-19-10-2026` (what
each state's code means). Three files are kept: `OD_FIRME.CSV`, `OD_STARE_FIRMA.CSV` and
`N_STARE_FIRMA.CSV`. The others hold activities and legal representatives, who are
natural persons: never fetched.
"""

import json
import logging
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from date_romania import eu_links, eu_seap_links, places
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_file, stored_documents
from date_romania.collectors.onrc import parse
from date_romania.collectors.onrc.load import load
from date_romania.dates import today
from date_romania.models import RegisterCompany, SourceDocument
from date_romania.places import PlaceIndex
from date_romania.sources import ONRC
from date_romania.storage import get_raw_file

log = logging.getLogger(__name__)

SOURCE = JOB = ONRC.key
COMPANIES, STATES, STATE_NAMES = "OD_FIRME.CSV", "OD_STARE_FIRMA.CSV", "N_STARE_FIRMA.CSV"
# An edition is fetched once the one held is this old: about one in two, a quarter apart.
EVERY = timedelta(days=80)

_EDITION = re.compile(r"^(firme|nomenclatoare)-(\d{2})-(\d{2})-(\d{4})$")


def editions(client: PoliteClient) -> dict[date, dict[str, str]]:
    """The editions on data.gov.ro that have both datasets: their day, and their datasets'
    names by kind ('firme', 'nomenclatoare')."""
    found: dict[date, dict[str, str]] = {}
    for query, prefix in (("firme onrc", "firme-"), ("nomenclatoare onrc", "nomenclatoare-")):
        for name in datagov.datasets(client, query, prefix, newest=True):
            if match := _EDITION.match(name):
                kind, day, month, year = match.groups()
                found.setdefault(date(int(year), int(month), int(day)), {})[kind] = name
    return {day: names for day, names in found.items() if len(names) == 2}


def _about(doc: SourceDocument) -> dict:
    return json.loads(doc.request_body or "{}")


def held_editions(session: Session) -> dict[date, dict[str, SourceDocument]]:
    """The editions whose three files are stored, oldest first, each file by its name."""
    held: dict[date, dict[str, SourceDocument]] = {}
    for doc in stored_documents(session, SOURCE):
        about = _about(doc)
        held.setdefault(date.fromisoformat(about["edition"]), {})[about["file"]] = doc
    return {
        day: files
        for day, files in sorted(held.items())
        if {COMPANIES, STATES, STATE_NAMES} <= files.keys()
    }


def due(held: list[date], offered: list[date]) -> date | None:
    """The edition to fetch: the newest offered, when none is held or the newest held is
    `EVERY` older than it."""
    if not offered:
        return None
    newest = max(offered)
    if held and newest < max(held) + EVERY:
        return None
    return newest


def _fetch(
    session: Session, client: PoliteClient, day: date, datasets: dict[str, str], folder: Path
) -> dict[str, tuple[SourceDocument, Path]]:
    """Download and store the three files of an edition."""
    wanted = {"firme": (COMPANIES, STATES), "nomenclatoare": (STATE_NAMES,)}
    fetched = {}
    for kind, names in wanted.items():
        files = {each.name.upper(): each for each in datagov.resources(client, datasets[kind])}
        for name in names:
            resource = files.get(name)
            if resource is None:
                raise ValueError(f"{datasets[kind]}: no file {name}")
            path = folder / name
            content_type = client.download(resource.url, path)
            doc = store_file(
                session,
                SOURCE,
                resource.url,
                path,
                request_body=json.dumps({"edition": day.isoformat(), "file": name}),
                content_type=content_type,
            )
            session.commit()
            log.info("onrc %s: stored %s (%d bytes)", day, name, doc.size_bytes)
            fetched[name] = (doc, path)
    return fetched


def _load(
    session: Session, day: date, files: dict[str, tuple[SourceDocument, Path]], index: PlaceIndex
) -> int:
    """Read one edition's files and load it on top of what is held."""
    reads = {name: parse.Read() for name in files}
    state_names = parse.state_names(files[STATE_NAMES][1], reads[STATE_NAMES])
    companies_doc, companies_path = files[COMPANIES]
    listed = load(
        session,
        day,
        companies_doc.id,
        parse.companies(companies_path, index, reads[COMPANIES]),
        parse.states(files[STATES][1], reads[STATES]),
        state_names,
    )
    for name, (doc, _) in files.items():
        record_parse(doc, reads[name].rejected, parse.PARSER_VERSION)
    log.info(
        "onrc %s: %d companies, %d rows of natural persons not read, %d rejected",
        day,
        listed,
        reads[COMPANIES].persons,
        len(reads[COMPANIES].rejected),
    )
    return listed


def _tie(session: Session) -> None:
    places.locate(session)
    eu_links.link(session)
    eu_seap_links.link(session)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch and load the newest edition when it is due; returns the companies it lists."""
    with job_run(session, JOB, today()) as run:
        offered = editions(client)
        day = due(list(held_editions(session)), list(offered))
        if day is None:
            log.info("onrc: no edition due (offered: %s)", max(offered, default=None))
            return 0
        with tempfile.TemporaryDirectory(prefix="onrc-") as folder:
            files = _fetch(session, client, day, offered[day], Path(folder))
            run.records = _load(session, day, files, PlaceIndex.load(session))
        _tie(session)
    return run.records


def reparse(session: Session) -> int:
    """Load every stored edition again, oldest first, without calling anyone; returns the
    editions read."""
    held = held_editions(session)
    session.execute(delete(RegisterCompany))
    index = PlaceIndex.load(session)
    for day, docs in held.items():
        with tempfile.TemporaryDirectory(prefix="onrc-") as folder:
            files = {
                name: (doc, get_raw_file(doc.storage_key, Path(folder) / name))
                for name, doc in docs.items()
            }
            _load(session, day, files, index)
        session.commit()
    _tie(session)
    session.commit()
    return len(held)
