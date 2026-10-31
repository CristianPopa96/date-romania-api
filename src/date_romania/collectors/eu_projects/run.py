"""Collecting the lists of contracted projects and the Health payments, and loading them
again from the raw store."""

import json
import logging
from datetime import date

import httpx
from sqlalchemy import and_, delete, insert, or_, select
from sqlalchemy.orm import Session

from date_romania import entities, eu_links, eu_seap_links, places
from date_romania.collectors import eu_map
from date_romania.collectors.eu_projects.discover import Found, discover
from date_romania.collectors.eu_projects.parse import (
    PARSER_VERSION,
    Parsed,
    parse_payments,
    parse_projects,
)
from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import (
    job_run,
    record_parse,
    record_skipped,
    store_document,
    stored_documents,
)
from date_romania.dates import today
from date_romania.eu_programmes import BY_CODE
from date_romania.models import (
    PARTIAL,
    EuProject,
    EuProjectPayment,
    SourceDocument,
    held_by_map,
)
from date_romania.sources import EU_PROJECTS
from date_romania.storage import get_raw

log = logging.getLogger(__name__)

SOURCE = JOB = EU_PROJECTS.key


def _about(doc: SourceDocument) -> dict:
    """What a stored file is, kept in `request_body` when it was fetched."""
    return json.loads(doc.request_body or "{}")


def _held(session: Session, url: str) -> SourceDocument | None:
    return session.scalar(
        select(SourceDocument)
        .where(SourceDocument.source == SOURCE, SourceDocument.url == url)
        .order_by(SourceDocument.id.desc())
        .limit(1)
    )


def _fetch(session: Session, client: PoliteClient, found: Found) -> tuple[SourceDocument, bool]:
    doc = _held(session, found.url)
    if doc is not None:
        # Held but never read (its read failed): read it again, as the run promises.
        return doc, doc.parser_version is None
    response = client.request("GET", found.url, follow_redirects=True)
    about = {
        "programme": found.programme,
        "kind": found.kind,
        "part": found.part,
        "label": found.label,
        "cut_off": found.cut_off and found.cut_off.isoformat(),
    }
    doc = store_document(
        session,
        SOURCE,
        found.url,
        response.content,
        request_body=json.dumps(about, ensure_ascii=False),
        content_type=response.headers.get("content-type"),
    )
    session.commit()
    log.info("%s: stored %s (%d bytes)", found.programme, found.label, doc.size_bytes)
    return doc, True


def _log_unread(name: str, parsed: Parsed) -> None:
    if parsed.unread:
        log.warning("%s: cells not read, field kept empty: %s", name, dict(parsed.unread))


def _load_programme(session: Session, code: str, docs: list[SourceDocument]) -> int:
    """Replace a programme's projects by those of its newest list (all its parts)."""
    programme = BY_CODE[code]
    rows: list[dict] = []
    for doc in docs:
        about = _about(doc)
        cut_off = date.fromisoformat(about["cut_off"]) if about.get("cut_off") else None
        parsed = parse_projects(get_raw(doc.storage_key), code, programme.period, cut_off)
        if not parsed.projects:
            # Never empty a programme for a file that is not its list.
            raise ValueError(f"{code}: no projects in {about.get('label')!r}")
        # A SMIS code another programme's list holds stays with it; one met in two parts
        # of a list keeps the first. One the map holds is the list's from now on.
        taken = set(
            session.scalars(
                select(EuProject.smis).where(EuProject.programme != code, ~held_by_map())
            )
        ) | {row["smis"] for row in rows}
        for row in parsed.projects:
            if row["smis"] in taken:
                parsed.rejected.append((row, f"SMIS {row['smis']} is held by another list"))
        kept = [row for row in parsed.projects if row["smis"] not in taken]
        record_parse(doc, parsed.rejected, PARSER_VERSION)
        _log_unread(f"{code} {about.get('label')}", parsed)
        entities.upsert(session, parsed.entities, doc.id)
        rows += [
            {**row, "source_document_id": doc.id, "parser_version": PARSER_VERSION} for row in kept
        ]
    session.execute(
        delete(EuProject).where(
            or_(
                and_(EuProject.programme == code, ~held_by_map()),
                and_(held_by_map(), EuProject.smis.in_([row["smis"] for row in rows])),
            )
        )
    )
    if rows:
        session.execute(insert(EuProject), rows)
    session.commit()
    log.info("%s: %d projects", code, len(rows))
    return len(rows)


def _load_payments(session: Session, doc: SourceDocument) -> int:
    about = _about(doc)
    parsed = parse_payments(get_raw(doc.storage_key), about["programme"])
    if not parsed.found:
        # Published under the payments, but something else (a budget summary, once).
        log.warning("%s: no payments sheet in %r", about["programme"], about.get("label"))
        record_skipped(doc, PARSER_VERSION, "no payments sheet")
        session.commit()
        return 0
    record_parse(doc, parsed.rejected, PARSER_VERSION)
    _log_unread(f"{about['programme']} {about.get('label')}", parsed)
    session.execute(delete(EuProjectPayment).where(EuProjectPayment.source_document_id == doc.id))
    if parsed.payments:
        session.execute(
            insert(EuProjectPayment),
            [
                {**row, "source_document_id": doc.id, "parser_version": PARSER_VERSION}
                for row in parsed.payments
            ],
        )
    session.commit()
    return len(parsed.payments)


def collect(session: Session, client: PoliteClient) -> int:
    """Fetch the newest list of each programme and the Health payments not held, and load
    what is new; returns the projects loaded. A programme whose list cannot be found or
    read does not stop the others: the run ends as `partial`."""
    with job_run(session, JOB, today()) as run:
        found, failed = discover(client)
        for problem in failed:
            log.warning("not found: %s", problem)
        by_programme: dict[str, list[Found]] = {}
        for each in found:
            if each.kind == "projects":
                by_programme.setdefault(each.programme, []).append(each)
        projects = 0
        for code, lists in by_programme.items():
            parts = max(1, len(BY_CODE[code].posts))
            if len({each.part for each in lists}) < parts:
                # Loading one part alone would drop the other's projects: keep them all.
                failed.append(f"{code}: {len(lists)} of its {parts} lists found")
                continue
            try:
                fetched = [
                    _fetch(session, client, each) for each in sorted(lists, key=lambda f: f.part)
                ]
                if any(new for _, new in fetched):
                    projects += _load_programme(session, code, [doc for doc, _ in fetched])
            except (httpx.HTTPError, ValueError) as exc:
                session.rollback()
                failed.append(code)
                log.warning("%s: %r", code, exc)
        for each in (f for f in found if f.kind == "payments"):
            try:
                doc, new = _fetch(session, client, each)
                if new:
                    _load_payments(session, doc)
            except (httpx.HTTPError, ValueError) as exc:
                session.rollback()
                failed.append(f"{each.programme} payments {each.label}")
                log.warning("%s: %r", each.url, exc)
        run.records = projects
        if failed:
            run.status = PARTIAL
            run.error = f"not read: {', '.join(failed)}; run again to retry them"
        # A list loaded again holds its projects alone: what the map adds, again.
        eu_map.load(session)
        places.locate(session)
        eu_links.link(session)
        eu_seap_links.link(session)
    return projects


def reparse(session: Session) -> int:
    """Load again, without calling anyone, the newest stored list of each programme part
    and every stored payment file."""
    docs = stored_documents(session, SOURCE)
    newest: dict[tuple[str, int], SourceDocument] = {}
    for doc in docs:
        about = _about(doc)
        if about.get("kind") != "projects":
            continue
        key = (about["programme"], about.get("part", 1))
        held = newest.get(key)
        if held is None or (about.get("cut_off") or "", doc.id) > (
            _about(held).get("cut_off") or "",
            held.id,
        ):
            newest[key] = doc
    for code in sorted({code for code, _ in newest}):
        parts = sorted((part, doc) for (each, part), doc in newest.items() if each == code)
        _load_programme(session, code, [doc for _, doc in parts])
    for doc in docs:
        if _about(doc).get("kind") == "payments":
            _load_payments(session, doc)
    eu_map.load(session)
    places.locate(session)
    eu_links.link(session)
    eu_seap_links.link(session)
    session.commit()
    return len(docs)
