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
    # For a source that is a dataset of files: its title, shown as the record.
    dataset: str | None = None


SEAP_DIRECT = PublicSource(
    key="seap-direct",
    publisher="SEAP",
    list_url="https://e-licitatie.ro/pub/direct-acquisitions/list/1",
    record_url="https://e-licitatie.ro/pub/direct-acquisition/view/{id}",
)

SEAP_AWARDS = PublicSource(
    key="seap-awards",
    publisher="SEAP",
    list_url="https://e-licitatie.ro/pub/notices/contract-award-notices/list/0/0",
    # Checked for notices of type 3 (CAN) only; the other types may use another page.
    record_url="https://e-licitatie.ro/pub/notices/ca-notices/view-c/{id}",
)

PNIAS_PAYMENTS = PublicSource(
    key="pnias-payments",
    publisher="data.gov.ro",
    dataset="MDLPA · Plăți PNIAS 2026-prezent",
    list_url="https://data.gov.ro/dataset/plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent",
    # A payment has no page of its own: the dataset lists the files.
    record_url="https://data.gov.ro/dataset/plati-programul-national-de-investitii-anghel-saligny-pnias-2026-prezent",
)

# SEAP's own quarterly exports, published by ADR. One dataset per year.
SEAP_EXPORTS = PublicSource(
    key="seap-exports",
    publisher="data.gov.ro",
    dataset="ADR · Achiziții publice, contracte",
    list_url="https://data.gov.ro/dataset/achizitii-publice-{id}",
    record_url="https://data.gov.ro/dataset/achizitii-publice-{id}",
)

SOURCES = {
    source.key: source for source in (SEAP_DIRECT, SEAP_AWARDS, PNIAS_PAYMENTS, SEAP_EXPORTS)
}
