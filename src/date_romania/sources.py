"""The public sources we collect: one name each, and where a reader can check a figure."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicSource:
    # The one name of the source: `source_document.source` and `job_run.job`.
    key: str
    publisher: str
    # The public page that lists the records.
    list_url: str
    # The public page of one record, with `{id}` for the publisher's own id.
    record_url: str


SEAP_DIRECT = PublicSource(
    key="seap-direct",
    publisher="SEAP",
    list_url="https://e-licitatie.ro/pub/direct-acquisitions/list/1",
    record_url="https://e-licitatie.ro/pub/direct-acquisition/view/{id}",
)

SOURCES = {source.key: source for source in (SEAP_DIRECT,)}
