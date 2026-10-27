"""A few EU cohesion projects, for the API tests and for the answers the site's browser tests
run on. The entities it ties (the town hall, the hospital) are seeded by the tests that
call it.

- 312456, PEO 2021-2027: the hospital, its CUI in the list (sure); in implementation.
- 118001, POR 2014-2020: the town hall, tied by its administration's name (probable);
  finished.
- 118002, POCU 2014-2020: an association no entity carries; no total published, a status
  of the list's own ('etapizat').
- 118003, POIM 2014-2020: terminated, nothing paid.
- 324809, Health 2021-2027: the hospital, with two payments published one by one.
"""

from datetime import date
from decimal import Decimal

from date_romania.models import EuProject, EuProjectPayment, SourceDocument

TOWN_HALL, HOSPITAL = 4981310, 4491342
PEO, POR, POCU, POIM, HEALTH = 312456, 118001, 118002, 118003, 324809


def _document(session, url: str, mark: str) -> int:
    doc = SourceDocument(
        source="eu-projects",
        url=url,
        sha256=mark * 32,
        storage_key=f"eu-projects/{mark}",
        size_bytes=1,
        parser_version=2,
        rejected_rows=0,
    )
    session.add(doc)
    session.flush()
    return doc.id


def _project(smis, programme, period, doc, cut_off, **fields) -> EuProject:
    return EuProject(
        smis=smis,
        programme=programme,
        period=period,
        cut_off=cut_off,
        source_document_id=doc,
        parser_version=2,
        **fields,
    )


def seed(session) -> None:
    new = _document(session, "https://mfe.gov.ro/wp-content/uploads/2026/10/peo.xlsx", "e1")
    old = _document(
        session, "https://data.gov.ro/dataset/proiecte-contractate/resource/1/por.xlsx", "e2"
    )
    health = _document(session, "https://mfe.gov.ro/wp-content/uploads/2026/10/ps.xlsx", "e3")
    paid = _document(session, "https://mfe.gov.ro/wp-content/uploads/2026/10/plati.xlsx", "e4")
    sure = {"entity_method": "cui-in-list", "entity_confidence": "sure"}
    session.add_all(
        [
            _project(
                PEO,
                "PEO",
                "2021-2027",
                new,
                date(2026, 9, 30),
                title="Dotarea laboratoarelor spitalului",
                beneficiary_cui=HOSPITAL,
                beneficiary_name="SPITALUL JUDETEAN DE URGENTA",
                entity_cui=HOSPITAL,
                partners="Asociația Sănătate pentru Toți",
                starts_on=date(2024, 3, 1),
                ends_on=date(2027, 2, 28),
                cofinancing_rate=Decimal("0.85"),
                county="GJ",
                locality="Târgu Jiu",
                total_value=Decimal("2100000"),
                eu_value=Decimal("1785000"),
                paid=Decimal("600000"),
                status="în implementare",
                **sure,
            ),
            _project(
                POR,
                "POR",
                "2014-2020",
                old,
                date(2025, 8, 31),
                title="Modernizarea drumului comunal DC 12",
                beneficiary_name="UAT Comuna Țânțăreni",
                entity_cui=TOWN_HALL,
                entity_method="administration-name+place",
                entity_confidence="probable",
                county="Gorj",
                locality="Țânțăreni",
                total_value=Decimal("6200000"),
                eu_value=Decimal("5270000"),
                paid=Decimal("6100000"),
                status="Proiect finalizat",
            ),
            _project(
                POCU,
                "POCU",
                "2014-2020",
                old,
                date(2025, 8, 31),
                title="Competențe digitale pentru adulți",
                beneficiary_name="ASOCIATIA PENTRU EDUCATIE DIGITALA",
                county="Gorj",
                eu_value=Decimal("850000"),
                paid=Decimal("400000"),
                status="etapizat",
            ),
            _project(
                POIM,
                "POIM",
                "2014-2020",
                old,
                date(2025, 8, 31),
                title="Extinderea rețelei de apă",
                beneficiary_name="APAREGIO GORJ SA",
                county="Gorj",
                total_value=Decimal("9000000"),
                eu_value=Decimal("7650000"),
                paid=Decimal("0"),
                status="REZILIAT",
            ),
            _project(
                HEALTH,
                "PS",
                "2021-2027",
                health,
                date(2026, 8, 31),
                title="Echipamente pentru secția de terapie intensivă",
                beneficiary_cui=HOSPITAL,
                beneficiary_name="SPITALUL JUDETEAN DE URGENTA",
                entity_cui=HOSPITAL,
                county="GJ",
                total_value=Decimal("3000000"),
                eu_value=Decimal("2550000"),
                paid=Decimal("900000"),
                status="in implementare",
                **sure,
            ),
        ]
    )
    session.add_all(
        EuProjectPayment(
            source_document_id=paid,
            position=position,
            smis=HEALTH,
            programme="PS",
            beneficiary_name="SPITALUL JUDETEAN DE URGENTA",
            kind=kind,
            amount=Decimal(amount),
            paid_on=day,
            funding="FEDR",
            parser_version=2,
        )
        for position, kind, amount, day in (
            (1, "Prefinanțare", "300000", date(2025, 12, 19)),
            (2, "Plată", "600000", date(2026, 9, 2)),
        )
    )
    session.flush()
