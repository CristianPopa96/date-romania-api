"""Places and a town hall's budget, for the API tests (see test_api_data.py).

- Gorj, its commune Țânțăreni (whose town hall is TOWN_HALL) and the village Țânțăreni.
- The commune's 2024 budget, a few columns of the Ministry of Development's file, and
  the Anghel Saligny payments of the programme seed placed there.
"""

from decimal import Decimal

from sqlalchemy import update

from date_romania.models import Entity, LocalBudget, Place, PniasPayment, SourceDocument

GORJ, TANTARENI, VILLAGE = 79, 84914, 84923
TOWN_HALL, HOSPITAL = 4981310, 4491342

# Column number -> amount in lei. Revenue: 1 total, 2 own (with the income tax shares 3
# and 4 inside it), 9 VAT, 16 state subsidies, 18 EU money. Spending: 22 total, 35
# capital; chapters 40 education, 49 transport, 38 general services.
FIGURES = {
    1: "10000000",
    2: "2500000",
    3: "1200000",
    4: "300000",
    9: "1500000",
    16: "5000000",
    18: "1000000",
    22: "9800000",
    35: "6000000",
    38: "1300000",
    40: "2000000",
    49: "6500000",
}


def seed(session) -> None:
    doc = SourceDocument(
        source="local-budgets",
        url="https://data.gov.ro/dataset/x/resource/1/download/situatia-2024.xlsx",
        request_body="Situația veniturilor și cheltuielilor - 2024.xlsx",
        sha256="5eed" * 16,
        storage_key="local-budgets/e",
        size_bytes=1,
        parser_version=1,
        rejected_rows=0,
    )
    session.add(doc)
    session.flush()
    stamp = {"source_document_id": doc.id, "parser_version": 1, "urban": False}
    session.add(Place(siruta=GORJ, name="JUDEŢUL GORJ", kind="county", county=GORJ, **stamp))
    session.flush()
    session.add(
        Place(
            siruta=TANTARENI,
            name="ŢÂNŢĂRENI",
            kind="commune",
            parent=GORJ,
            county=GORJ,
            town_hall_cui=TOWN_HALL,
            **stamp,
        )
    )
    session.flush()
    session.add(
        Place(
            siruta=VILLAGE, name="ŢÂNŢĂRENI", kind="village", parent=TANTARENI, county=GORJ, **stamp
        )
    )
    session.add_all(
        LocalBudget(
            siruta=TANTARENI,
            year=2024,
            column_no=number,
            section="revenue" if number < 22 else "spending" if number < 38 else "chapter",
            code=None,
            title=f"coloana {number}",
            amount=Decimal(amount),
            source_document_id=doc.id,
            parser_version=1,
        )
        for number, amount in FIGURES.items()
    )
    session.execute(
        update(PniasPayment).where(PniasPayment.town_hall == "ȚÂNȚĂRENI").values(siruta=TANTARENI)
    )
    # The hospital is funded by the town hall.
    session.get(Entity, HOSPITAL).parent_cui = TOWN_HALL
    session.flush()
