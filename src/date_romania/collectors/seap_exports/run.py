"""Collecting the quarterly contract exports, and rebuilding rows from the raw store."""

import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import pnias
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run
from date_romania.collectors.seap_exports.load import load
from date_romania.collectors.seap_exports.parse import parse_contracts
from date_romania.dates import today
from date_romania.models import PniasPayment, SourceDocument
from date_romania.sources import SEAP_EXPORTS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = SEAP_EXPORTS.key
# The first year with a dataset of this shape, and one dataset per year since.
FIRST_YEAR = 2021

# "Contracte 2021 - T1", "Raport Contracte publicate T II 2024"; never "Date din
# modificare contract", which is another report.
_CONTRACTS = re.compile(r"\s*(raport\s+)?contracte\b", re.IGNORECASE)
_FORMAT = re.compile(r"\.(csv|xlsx?|ods)$", re.IGNORECASE)


def is_contracts(title: str | None) -> bool:
    return bool(_CONTRACTS.match(title or ""))


def chosen(urls: list[str]) -> list[str]:
    """The files to read: where a quarter is published twice, the workbook.

    Some quarters come as both a workbook and a text file. They hold the same rows,
    except for the first quarter of 2024, whose text file has only the last 21,434.
    """

    def stem(url: str) -> str:
        return _FORMAT.sub("", url.rsplit("/", 1)[-1]).lower()

    workbooks = {stem(url) for url in urls if not url.lower().endswith(".csv")}
    return [url for url in urls if not (url.lower().endswith(".csv") and stem(url) in workbooks)]


def _suppliers(session: Session) -> set[int]:
    """The companies whose contracts are kept: the builders the payment files name."""
    return set(
        session.scalars(
            select(PniasPayment.builder_cui).where(PniasPayment.builder_cui.is_not(None)).distinct()
        )
    )


def _parse_and_load(session: Session, doc: SourceDocument, suppliers: set[int]) -> int:
    parsed = parse_contracts(get_raw(doc.storage_key), suppliers)
    for row, reason in parsed.rejected:
        log.warning("source_document %d: rejected row %s: %.500r", doc.id, reason, row)
    load(session, parsed, doc.id)
    session.commit()
    log.info(
        "%s: %d contracts kept of %d, %d rows rejected",
        doc.request_body,
        len(parsed.contracts),
        parsed.seen,
        len(parsed.rejected),
    )
    return len(parsed.contracts)


def collect(session: Session, client: PoliteClient, last_year: int | None = None) -> int:
    """Fetch, store and load the contract exports not held yet; returns the contracts kept.

    A file is large (up to 280 MB) and is downloaded once. One that fails does not stop
    the rest: the run ends as `partial` and the next run takes it up again.
    """
    with job_run(session, JOB, today()) as run:
        suppliers = _suppliers(session)
        kept = failed = 0
        for year in range(FIRST_YEAR, (last_year or today().year) + 1):
            try:
                found = datagov.resources(client, f"achizitii-publice-{year}")
            except (datagov.DatagovError, httpx.HTTPError) as error:
                # The dataset of a new year appears with its first quarter, in April.
                log.warning("achizitii-publice-%d: no dataset: %r", year, error)
                continue
            files = {each.url: each for each in found if is_contracts(each.name)}
            for url in chosen(list(files)):
                doc = None
                try:
                    doc, new = datagov.fetch(session, client, SOURCE, files[url])
                    if new:
                        kept += _parse_and_load(session, doc, suppliers)
                except Exception:
                    failed += 1
                    log.exception("%s: failed", url)
                    if doc is not None and new:
                        datagov.forget(session, doc)
                    else:
                        session.rollback()
        run.records = kept
        if failed:
            run.status = "partial"
            run.error = f"{failed} files failed; run again to retry them"
    pnias.link(session)
    session.commit()
    return kept


def reparse(session: Session) -> int:
    """Rebuild the rows from the raw store, without calling data.gov.ro.

    Also the way to bring in the contracts of builders named by a new payment file.
    """
    docs = {
        doc.url: doc
        for doc in session.scalars(
            select(SourceDocument)
            .where(SourceDocument.source == SOURCE)
            .order_by(SourceDocument.id)
        )
    }
    suppliers = _suppliers(session)
    urls = chosen(list(docs))
    for url in urls:
        _parse_and_load(session, docs[url], suppliers)
    pnias.link(session)
    session.commit()
    return len(urls)
