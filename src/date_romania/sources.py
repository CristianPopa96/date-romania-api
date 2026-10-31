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

# The page of one direct purchase (its lines and conditions) is stored under its own key,
# so that the list's fetch time and count of answers stay the list's own. Same publisher
# and record page as SEAP_DIRECT.
SEAP_DIRECT_DETAILS_KEY = f"{SEAP_DIRECT.key}-details"

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

# The Recovery and Resilience Plan, from the files MIPE's dashboard reads (every contract,
# every payment, the measures). A contract has no public page of its own.
PNRR = PublicSource(
    key="pnrr",
    publisher="MIPE",
    dataset="Tabloul de bord PNRR",
    list_url="https://mfe.gov.ro/pnrr-dashboard/",
    record_url="https://mfe.gov.ro/pnrr-dashboard/",
)

# The lists of contracted EU cohesion projects: the 2014-2020 programmes on data.gov.ro, the
# 2021-2027 national programmes on mfe.gov.ro. A project has no public page of its own.
EU_PROJECTS = PublicSource(
    key="eu-projects",
    publisher="MIPE",
    dataset="Liste de proiecte contractate",
    list_url="https://mfe.gov.ro/programe/",
    record_url="https://mfe.gov.ro/programe/",
)

# MIPE's map of the 2021-2027 cohesion projects: one file a week, every programme, the
# lead's tax ID on every row. It adds the projects no list of contracted projects holds.
EU_MAP = PublicSource(
    key="eu-map",
    publisher="MIPE",
    dataset="Harta fondurilor europene 2021-2027",
    list_url="https://mfe.gov.ro/map2021/",
    record_url="https://mfe.gov.ro/map2021/",
)

# SEAP's own quarterly exports, published by ADR. One dataset per year.
SEAP_EXPORTS = PublicSource(
    key="seap-exports",
    publisher="data.gov.ro",
    dataset="ADR · Achiziții publice, contracte",
    list_url="https://data.gov.ro/dataset/achizitii-publice-{id}",
    record_url="https://data.gov.ro/dataset/achizitii-publice-{id}",
)

# The national list of places (INS), published twice a year, one dataset each time.
SIRUTA = PublicSource(
    key="siruta",
    publisher="data.gov.ro",
    dataset="INS · SIRUTA",
    list_url="https://data.gov.ro/organization/ins",
    record_url="https://data.gov.ro/dataset/{id}",
)

# The Finance Ministry's monthly list of public entities, on its budget reports portal
# ("Alte Rapoarte"; the reports themselves need a captcha, this list does not).
PUBLIC_ENTITIES = PublicSource(
    key="public-entities",
    publisher="Ministerul Finanțelor",
    dataset="Lista entităților publice",
    list_url="https://extranet.anaf.mfinante.gov.ro/anaf/extranet/EXECUTIEBUGETARA",
    record_url="https://extranet.anaf.mfinante.gov.ro/anaf/extranet/EXECUTIEBUGETARA",
)

# The Ministry of Development's yearly budgets of town halls and county councils, and the
# population of every UAT.
LOCAL_BUDGETS = PublicSource(
    key="local-budgets",
    publisher="data.gov.ro",
    dataset="MDLPA · Politici fiscale și bugetare locale",
    list_url="https://data.gov.ro/dataset/politici-fiscale-si-bugetare-locale",
    record_url="https://data.gov.ro/dataset/politici-fiscale-si-bugetare-locale",
)

# ANAF's public web services, asked by tax ID: a taxpayer has no page of its own.
ANAF = PublicSource(
    key="anaf",
    publisher="ANAF",
    dataset="Servicii web · registrul plătitorilor de TVA",
    list_url="https://www.anaf.ro/anaf/internet/ANAF/servicii_online/servicii_web_anaf",
    record_url="https://www.anaf.ro/anaf/internet/ANAF/servicii_online/servicii_web_anaf",
)

# The trade register (ONRC) on data.gov.ro: one dataset per edition, about monthly; we read
# one a quarter. Only legal persons are read from it, never the natural persons it lists.
ONRC = PublicSource(
    key="onrc",
    publisher="ONRC",
    dataset="Registrul Comerțului · firme înregistrate",
    list_url="https://data.gov.ro/organization/onrc",
    record_url="https://data.gov.ro/dataset/{id}",
)

SOURCES = {
    source.key: source
    for source in (
        SEAP_DIRECT,
        SEAP_AWARDS,
        PNIAS_PAYMENTS,
        SEAP_EXPORTS,
        SIRUTA,
        PUBLIC_ENTITIES,
        LOCAL_BUDGETS,
        ANAF,
        ONRC,
    )
}
