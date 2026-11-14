"""Collecting the monthly workbooks of the consolidated general budget's execution, and
loading them again from the raw store."""

import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from date_romania.collectors import datagov
from date_romania.collectors.budget_execution.parse import PARSER_VERSION, file_day, parse
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.dates import today
from date_romania.models import PARTIAL, BudgetExecution, SourceDocument
from date_romania.sources import BUDGET_EXECUTION
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = BUDGET_EXECUTION.key
BASE = "https://mfinante.gov.ro/static/10/Mfp/buletin/executii/"
# December 2024 is the first period the home page compares (the local budgets of 2024).
FIRST_MONTH = date(2024, 1, 31)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def url_of(period_end: date) -> str:
    return f"{BASE}bgc{period_end:%d%m%Y}.xlsx"


def month_ends(first: date, until: date) -> list[date]:
    """The last day of every month from `first`'s to the month before `until`'s."""
    ends, month = [], date(first.year, first.month, 1)
    while month < date(until.year, until.month, 1):
        following = (month + timedelta(days=32)).replace(day=1)
        ends.append(following - timedelta(days=1))
        month = following
    return ends


def _load(session: Session, doc: SourceDocument) -> int:
    """One month in place of what was held for it."""
    parsed = parse(get_raw(doc.storage_key))
    named = file_day(doc.url)
    if named and parsed.period_end != named:
        raise ValueError(f"{doc.url} holds the period to {parsed.period_end}, not {named}")
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION}
    session.execute(delete(BudgetExecution).where(BudgetExecution.period_end == parsed.period_end))
    session.execute(insert(BudgetExecution), [{**row, **stamp} for row in parsed.rows])
    session.commit()
    log.info(
        "budget execution to %s: %d figures, %d rejected",
        parsed.period_end,
        len(parsed.rows),
        len(parsed.rejected),
    )
    return len(parsed.rows)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch and load every month since January 2024 not held yet; returns the figures
    they brought. A month the ministry has not published yet (HTTP 404) is asked for
    again on the next run; a month that fails otherwise makes the run `partial`."""
    with job_run(session, JOB, today()) as run:
        held = set(
            session.scalars(select(SourceDocument.url).where(SourceDocument.source == SOURCE))
        )
        failed = 0
        for period_end in month_ends(FIRST_MONTH, today()):
            url = url_of(period_end)
            if url in held:
                continue
            try:
                response = client.request("GET", url)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    log.info("budget execution to %s: not published yet", period_end)
                    continue
                failed += 1
                log.exception("budget execution to %s: failed", period_end)
                continue
            except httpx.HTTPError:
                failed += 1
                log.exception("budget execution to %s: failed", period_end)
                continue
            doc = store_document(session, SOURCE, url, response.content, None, XLSX)
            session.commit()
            try:
                run.records += _load(session, doc)
            except Exception:
                failed += 1
                log.exception("budget execution to %s: not read", period_end)
                datagov.forget(session, doc)
        if failed:
            run.status = PARTIAL
            run.error = f"{failed} months failed; run again to retry them"
    return run.records


def reparse(session: Session) -> int:
    """Load every stored month again, without calling the ministry; the newest file of a
    month wins. A file that cannot be read is logged and does not stop the others."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        try:
            _load(session, doc)
        except Exception:
            log.exception("%s: not read", doc.url)
            session.rollback()
    return len(docs)
