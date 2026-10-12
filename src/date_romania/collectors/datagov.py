"""data.gov.ro (CKAN): the files of a dataset, and keeping the ones not yet stored."""

import logging
from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from date_romania.collectors.http import PoliteClient
from date_romania.collectors.jobs import store_document
from date_romania.models import SourceDocument

log = logging.getLogger(__name__)

PACKAGE_URL = "https://data.gov.ro/api/3/action/package_show?id={dataset}"


class DatagovError(Exception):
    """data.gov.ro answered, but not with the dataset."""


@dataclass(frozen=True)
class Resource:
    """One file of a dataset. `name` is the publisher's title for it, `created` its day."""

    dataset: str
    name: str
    url: str
    created: str


def resources(client: PoliteClient, dataset: str) -> list[Resource]:
    """The files of `dataset`, oldest first."""
    answer = client.request("GET", PACKAGE_URL.format(dataset=dataset)).json()
    if not answer.get("success"):
        raise DatagovError(f"{dataset}: {str(answer.get('error'))[:500]}")
    found = [
        Resource(
            dataset=dataset,
            name=(item.get("name") or "").strip(),
            url=item["url"],
            created=(item.get("created") or "")[:10],
        )
        for item in answer["result"]["resources"]
        if item.get("url")
    ]
    return sorted(found, key=lambda each: (each.created, each.url))


def stored(session: Session, source: str, url: str) -> SourceDocument | None:
    """The document kept for this address, if the file was fetched before."""
    return session.scalar(
        select(SourceDocument)
        .where(SourceDocument.source == source, SourceDocument.url == url)
        .order_by(SourceDocument.id.desc())
        .limit(1)
    )


def fetch(
    session: Session, client: PoliteClient, source: str, resource: Resource
) -> tuple[SourceDocument, bool]:
    """The stored document of one file, downloading it only if we do not hold it.

    The publisher's title goes in `request_body`: it names the quarter or the day of the
    file, which the address does not always do.
    """
    doc = stored(session, source, resource.url)
    if doc is not None:
        return doc, False
    # Some addresses hold Romanian letters, which must be escaped to be sent.
    response = client.request("GET", quote(resource.url, safe=":/?=&%"), follow_redirects=True)
    doc = store_document(
        session,
        source,
        resource.url,
        response.content,
        request_body=resource.name,
        content_type=response.headers.get("content-type"),
    )
    session.commit()
    log.info("%s: stored %s (%d bytes)", source, resource.name, doc.size_bytes)
    return doc, True
