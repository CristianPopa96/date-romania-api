"""Collecting the newest edition of the PNRR dashboard data, and loading it again from the
raw store."""

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.collectors.pnrr import fetch
from date_romania.collectors.pnrr.load import load
from date_romania.collectors.pnrr.parse import (
    CONTRACTS,
    ENDPOINTS,
    MEASURES,
    PARSER_VERSION,
    PAYMENTS,
    TOP,
    TOP_DAYS,
    TOTALS,
    Parsed,
    parse_contracts,
    parse_measures,
    parse_payments,
    parse_top,
    parse_totals,
    read,
)
from date_romania.dates import today
from date_romania.models import PnrrEdition, SourceDocument
from date_romania.sources import PNRR
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = PNRR.key


def _held(session: Session, url: str) -> SourceDocument | None:
    return session.scalar(
        select(SourceDocument)
        .where(SourceDocument.source == SOURCE, SourceDocument.url == url)
        .order_by(SourceDocument.id.desc())
        .limit(1)
    )


def _drop_unknown_measures(parsed: dict[str, Parsed]) -> None:
    """A line or payment on a measure the edition does not list cannot be stored: it is
    rejected, with the reason, instead of failing the edition."""
    known = {row["code"] for row in parsed[MEASURES].measures}
    for endpoint, name in ((CONTRACTS, "lines"), (PAYMENTS, "payments")):
        rows = getattr(parsed[endpoint], name)
        kept = [row for row in rows if row["measure_code"] in known]
        parsed[endpoint].rejected += [
            (row, f"measure {row['measure_code']} is not in the edition's measures")
            for row in rows
            if row["measure_code"] not in known
        ]
        setattr(parsed[endpoint], name, kept)
    lined = {row["contract_id"] for row in parsed[CONTRACTS].lines}
    parsed[CONTRACTS].contracts = [row for row in parsed[CONTRACTS].contracts if row["id"] in lined]


def _parse_and_load(session: Session, day: date, docs: dict[str, SourceDocument]) -> int:
    data = {endpoint: read(get_raw(doc.storage_key)) for endpoint, doc in docs.items()}
    parsed = {
        CONTRACTS: parse_contracts(data[CONTRACTS]),
        PAYMENTS: parse_payments(data[PAYMENTS]),
        MEASURES: parse_measures(data[MEASURES]),
        TOP: parse_top(data[TOP], data[TOP_DAYS]),
        TOTALS: parse_totals(data[TOTALS], day),
    }
    _drop_unknown_measures(parsed)
    for endpoint, doc in docs.items():
        # The full list of the top recipients is read with the preview, and counted there.
        found = parsed.get(endpoint, Parsed())
        record_parse(doc, found.rejected, PARSER_VERSION)
    load(session, {endpoint: (parsed[endpoint], docs[endpoint].id) for endpoint in parsed})
    session.commit()
    contracts = parsed[CONTRACTS]
    log.info(
        "PNRR %s: %d contracts on %d lines, %d payments, %d measures, %d top recipients; "
        "%d rows rejected, %d tax IDs not valid",
        day,
        len(contracts.contracts),
        len(contracts.lines),
        len(parsed[PAYMENTS].payments),
        len(parsed[MEASURES].measures),
        len(parsed[TOP].top),
        sum(len(each.rejected) for each in parsed.values()),
        contracts.invalid_cuis + parsed[PAYMENTS].invalid_cuis,
    )
    return len(contracts.contracts)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch the newest complete edition if it is newer than the one held, and load it in
    its place; returns its contracts, or 0 when there is nothing new. An index that falls
    back to an older edition never takes the data backwards."""
    with job_run(session, JOB, today()) as run:
        edition = fetch.newest(client)
        held = session.scalar(select(func.max(PnrrEdition.day)))
        if held is not None and edition.day <= held:
            log.info("PNRR %s: nothing newer than the edition of %s held", edition.day, held)
            return 0
        docs: dict[str, SourceDocument] = {}
        for endpoint, url in edition.files.items():
            doc = _held(session, url)
            if doc is None:
                response = client.request("GET", url)
                doc = store_document(
                    session, SOURCE, url, response.content, None, "application/gzip"
                )
                session.commit()
            docs[endpoint] = doc
        run.records = _parse_and_load(session, edition.day, docs)
        places.locate(session)
    return run.records


def reparse(session: Session) -> int:
    """Load the newest complete edition held again, without calling MIPE."""
    stored: dict[date, dict[str, SourceDocument]] = {}
    for doc in stored_documents(session, SOURCE):
        named = fetch.edition_of(doc.url)
        if named and named[1] in ENDPOINTS:
            stored.setdefault(named[0], {})[named[1]] = doc
    complete = [day for day, docs in stored.items() if set(docs) == set(ENDPOINTS)]
    if not complete:
        return 0
    day = max(complete)
    _parse_and_load(session, day, stored[day])
    places.locate(session)
    session.commit()
    return len(stored[day])
