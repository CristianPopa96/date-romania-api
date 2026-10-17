"""Collecting the dataset's budget and population workbooks, and rebuilding the rows from
the raw store."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import (
    job_run,
    record_parse,
    record_skipped,
    stored_documents,
)
from date_romania.collectors.local_budgets.parse import (
    BUDGET,
    PARSER_VERSION,
    Parsed,
    file_kind,
    parse_budget,
    parse_population,
)
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import PARTIAL, LocalBudget, Place, Population, SourceDocument
from date_romania.places import SECTOR, PlaceIndex
from date_romania.sources import LOCAL_BUDGETS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = LOCAL_BUDGETS.key
DATASET = "politici-fiscale-si-bugetare-locale"


def _placed(session: Session, parsed: Parsed) -> list[dict]:
    """The rows with their SIRUTA code: a county council's is its county's, a place named
    only by name is found by it. A row whose place SIRUTA does not hold is rejected."""
    index = PlaceIndex.load(session)
    known = set(session.scalars(select(Place.siruta)))
    rows = []
    for row in parsed.rows:
        place = row.pop("place")
        match place:
            case ("county", county):
                siruta = index.county(county)
            case ("uat", county, name):
                siruta = index.uat(county, name)
            case _:
                siruta = place
        if siruta not in known:
            parsed.rejected.append((row, f"place {place} not in SIRUTA"))
            continue
        rows.append({**row, "siruta": siruta})
    return rows


def _without_sector_sums(session: Session, rows: list[dict]) -> list[dict]:
    """People only: a UAT listed together with its sectors (Bucharest, in some years)
    counts their people again. Budgets keep it, since the city hall has its own."""
    parents = set(
        session.scalars(
            select(Place.parent).where(
                Place.kind == SECTOR, Place.siruta.in_({row["siruta"] for row in rows})
            )
        )
    )
    return [row for row in rows if row["siruta"] not in parents]


def _parse_and_load(session: Session, doc: SourceDocument) -> int:
    kind = file_kind(doc.request_body)
    if kind is None:
        record_skipped(doc, PARSER_VERSION, f"not a budget or population file: {doc.request_body}")
        session.commit()
        return 0
    what, year = kind
    content = get_raw(doc.storage_key)
    parsed = parse_budget(content, year) if what == BUDGET else parse_population(content, year)
    rows = _placed(session, parsed)
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION}
    if what == BUDGET:
        key = ("siruta", "year", "column_no")
        upsert_rows(session, LocalBudget, [{**r, **stamp} for r in rows], key)
    else:
        rows = _without_sector_sums(session, rows)
        upsert_rows(session, Population, [{**r, **stamp} for r in rows], ("siruta", "on"))
    session.commit()
    log.info("%s: %d rows, %d rejected", doc.request_body, len(rows), len(parsed.rejected))
    return len(rows)


class NoPlaces(Exception):
    """SIRUTA is not held yet: every row would be rejected."""


def _need_places(session: Session) -> None:
    if session.scalar(select(Place.siruta).limit(1)) is None:
        raise NoPlaces("no places held: run `dr collect siruta` first")


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch and load the files of the dataset not held yet; returns the rows they
    brought. Needs SIRUTA (`dr collect siruta`): a place it does not hold is rejected.

    A file that cannot be read is forgotten and does not stop the others: the run ends
    `partial`, and the next run takes it up again.
    """
    _need_places(session)
    with job_run(session, JOB, today()) as run:
        failed = 0
        for resource in datagov.resources(client, DATASET):
            doc = None
            try:
                doc, new = datagov.fetch(session, client, SOURCE, resource)
                if new:
                    run.records += _parse_and_load(session, doc)
            except Exception:
                failed += 1
                log.exception("%s: failed", resource.name)
                if doc is not None and new:
                    datagov.forget(session, doc)
                else:
                    session.rollback()
        if failed:
            run.status = PARTIAL
            run.error = f"{failed} files failed; run again to retry them"
    return run.records


def reparse(session: Session) -> int:
    """Load every stored file again, oldest first, without calling data.gov.ro. A file
    that cannot be read is logged and does not stop the ones after it."""
    _need_places(session)
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        try:
            _parse_and_load(session, doc)
        except Exception:
            log.exception("%s: not read", doc.request_body)
            session.rollback()
    return len(docs)
