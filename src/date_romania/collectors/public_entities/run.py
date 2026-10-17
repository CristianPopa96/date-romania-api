"""Collecting the list of public entities from the ministry's portal, and rebuilding the
rows from the raw store."""

import html
import logging
import re
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania import places
from date_romania.collectors import datagov
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import job_run, record_parse, store_document, stored_documents
from date_romania.collectors.public_entities.parse import PARSER_VERSION, parse_entities
from date_romania.dates import today
from date_romania.db import upsert_rows
from date_romania.models import PublicEntity, SourceDocument
from date_romania.sources import PUBLIC_ENTITIES
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = PUBLIC_ENTITIES.key
_LINK = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)


class PortalError(Exception):
    """The portal answered, but the page or the file was not where it was."""


def _link(page: str, base: str, wanted: re.Pattern[str]) -> tuple[str, str]:
    """The first link of `page` whose address or text matches: (address, text)."""
    for address, label in _LINK.findall(page):
        address, label = html.unescape(address), " ".join(re.sub(r"<[^>]+>", " ", label).split())
        if wanted.search(address) or wanted.search(label):
            return urljoin(base, address), label
    raise PortalError(f"no link like {wanted.pattern} on {base}")


def find_list(client: PoliteClient) -> tuple[str, str]:
    """The address and title of the current list ('Lista entitatilor publice - actualizata
    01.10.2026'), from the portal's "Alte Rapoarte" tab."""
    portal = client.request("GET", PUBLIC_ENTITIES.list_url, follow_redirects=True)
    other, _ = _link(portal.text, str(portal.url), re.compile(r"^Alte Rapoarte$"))
    page = client.request("GET", other, follow_redirects=True)
    return _link(page.text, str(page.url), re.compile(r"Lista_EP|Lista entit", re.I))


def _parse_and_load(session: Session, doc: SourceDocument) -> int:
    parsed = parse_entities(get_raw(doc.storage_key))
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    stamp = {"source_document_id": doc.id, "parser_version": PARSER_VERSION, "siruta": None}
    upsert_rows(session, PublicEntity, [{**row, **stamp} for row in parsed.entities], ("cui",))
    session.commit()
    log.info(
        "%s: %d entities, %d rows rejected",
        doc.request_body,
        len(parsed.entities),
        len(parsed.rejected),
    )
    return len(parsed.entities)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch the current list if this edition is not held, load it and place every
    entity; returns the entities it brought. An edition that cannot be read is
    forgotten, and the run fails."""
    with job_run(session, JOB, today()) as run:
        url, title = find_list(client)
        held = session.scalar(
            select(SourceDocument).where(SourceDocument.source == SOURCE, SourceDocument.url == url)
        )
        if held is None:
            response = client.request("GET", url, follow_redirects=True)
            doc = store_document(
                session,
                SOURCE,
                url,
                response.content,
                request_body=title,
                content_type=response.headers.get("content-type"),
            )
            session.commit()
            try:
                run.records = _parse_and_load(session, doc)
            except Exception:
                # Forgotten, so the next run fetches and reads this edition again.
                datagov.forget(session, doc)
                raise
        places.locate(session)
    return run.records


def reparse(session: Session) -> int:
    """Load every stored edition again, oldest first, without calling the portal."""
    docs = stored_documents(session, SOURCE)
    for doc in docs:
        _parse_and_load(session, doc)
    places.locate(session)
    session.commit()
    return len(docs)
