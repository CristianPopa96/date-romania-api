"""Collecting the payment files, and rebuilding rows from the raw store."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import pnias
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse
from date_romania.collectors.pnias.load import load
from date_romania.collectors.pnias.parse import PARSER_VERSION, file_day, parse_payments
from date_romania.dates import today
from date_romania.models import SourceDocument
from date_romania.sources import PNIAS_PAYMENTS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = PNIAS_PAYMENTS.key
DATASET = "plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent"


def _parse_and_load(session: Session, doc: SourceDocument) -> int:
    """The publisher's title of the file, kept in `request_body`, gives the payments' day."""
    parsed = parse_payments(get_raw(doc.storage_key), file_day(doc.request_body))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    load(session, parsed, doc.id)
    session.commit()
    log.info(
        "%s: %d payments, %d rows rejected, %d tax IDs not valid",
        doc.request_body,
        len(parsed.payments),
        len(parsed.rejected),
        parsed.invalid_cuis,
    )
    return len(parsed.payments)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch, store and load the files of the dataset not held yet; returns the payments
    they brought. The ministry adds a file for every batch of payments.
    """
    with job_run(session, JOB, today()) as run:
        payments = 0
        for resource in datagov.resources(client, DATASET):
            doc, new = datagov.fetch(session, client, SOURCE, resource)
            if new:
                try:
                    payments += _parse_and_load(session, doc)
                except Exception:
                    datagov.forget(session, doc)
                    raise
        run.records = payments
    # A new file can name builders whose contracts are not kept yet: `dr reparse
    # seap-exports` reads them from the stored exports.
    pnias.link(session)
    session.commit()
    return payments


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, oldest file first, without calling data.gov.ro."""
    docs = session.scalars(
        select(SourceDocument).where(SourceDocument.source == SOURCE).order_by(SourceDocument.id)
    ).all()
    for doc in docs:
        _parse_and_load(session, doc)
    pnias.link(session)
    session.commit()
    return len(docs)
