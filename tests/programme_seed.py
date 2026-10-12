"""A handful of Anghel Saligny payments and export contracts, for the API tests and for the
answers the site's browser tests run on. The links between them are built by the real rule.

Four projects, one per match state:
- 101, Țânțăreni: three payments, the oldest without a tax ID; one notice, won by an
  association, which is also a notice we collected from SEAP ourselves.
- 102, the county of Cluj: the builder has two notices from the county council.
- 103, Turceni: the builder is named by tax ID and has no contract from that town hall.
- 104, Șandra: the builder is named by name only.

An export puts the town hall of Țânțăreni in Gorj, so its link is probable. Two buyers
are named "JUDETUL CLUJ" and no export says where either is, so the links of project
102 are only possible.
"""

from datetime import date
from decimal import Decimal

from date_romania import pnias
from date_romania.models import ExportBuyer, ExportContract, PniasPayment, SourceDocument

TOWN_HALL, BUILDER, DESIGNER = 4981310, 17886786, 18288250
# Companies the rest of the test data does not hold, so they have no page.
PARTNER, PIPES, LONELY = 30000011, 30000022, 30000033


def _document(session, source: str, title: str, mark: str) -> int:
    doc = SourceDocument(
        source=source,
        url=f"https://data.gov.ro/{mark}",
        request_body=title,
        sha256=mark * 64,
        storage_key="k",
        size_bytes=1,
    )
    session.add(doc)
    session.flush()
    return doc.id


def _payment(n: int, project: int, day: date, amount: str, doc: int, **more) -> PniasPayment:
    return PniasPayment(
        id=n,
        registered_on=day,
        requested_on=day,
        published_on=more.pop("published_on", date(2026, 8, 27)),
        network=more.pop("network", "infra"),
        project_id=project,
        amount=Decimal(amount),
        state="Finalizată",
        source_document_id=doc,
        parser_version=1,
        **more,
    )


def _contract(notice: str, number: str, day: date, value: str, doc: int, **more) -> ExportContract:
    return ExportContract(
        notice_no=notice,
        notice_date=day,
        contract_no=number,
        contract_date=day,
        value_ron=Decimal(value),
        procedure_type=more.pop("procedure_type", "Procedura simplificata"),
        contract_type="Lucrari",
        is_framework=more.pop("is_framework", False),
        cpv_code="45233120-6",
        cpv_name="Lucrari de constructii de drumuri (Rev.2)",
        source_document_id=doc,
        parser_version=1,
        **more,
    )


def seed(session) -> None:
    may = _document(session, "pnias-payments", "18 mai 2026.xlsx", "1")
    august = _document(session, "pnias-payments", "27 august 2026.xlsx", "2")
    export = _document(session, "seap-exports", "Contracte TII 2025", "3")
    road = {
        "county": "GORJ",
        "town_hall": "ȚÂNȚĂRENI",
        "investment": "Modernizare drumuri comunale în comuna Țânțăreni, județul Gorj",
        "category": "Drumurile publice",
        "ministry_contract_no": "1872",
        "ministry_contract_date": date(2023, 5, 18),
        "total_value": Decimal("8500000"),
        "state_budget_value": Decimal("8100000"),
        "builder_text": "ALFA CONSTRUCT S.R.L.",
        "designer_text": "Beta Birotică SRL",
        "estimated_end": date(2026, 12, 31),
    }
    named = {"builder_cui": BUILDER, "designer_cui": DESIGNER}
    session.add_all(
        [
            _payment(
                25001, 101, date(2026, 3, 2), "2400000", may, published_on=date(2026, 5, 18), **road
            ),
            _payment(
                29001, 101, date(2026, 6, 26), "1800000", august, progress="48,5", **road, **named
            ),
            _payment(
                30001, 101, date(2026, 8, 21), "1200000", august, progress="64%", **road, **named
            ),
            _payment(
                30002,
                102,
                date(2026, 8, 11),
                "950000",
                august,
                county="CLUJ",
                town_hall="Județul CLUJ prin Consiliul Județean",
                investment="Modernizare drum județean DJ 109, km 0+000 - km 12+400",
                category="Drumurile publice",
                total_value=Decimal("40000000"),
                state_budget_value=Decimal("38500000"),
                builder_cui=PIPES,
                builder_text="Delta Drumuri SRL",
                designer_cui=PIPES,
                designer_text="Delta Drumuri SRL",
                progress="PT RECEPTIONAT SI APROBAT",
            ),
            _payment(
                30003,
                103,
                date(2026, 8, 12),
                "310000",
                august,
                network="gas",
                county="GORJ",
                town_hall="TURCENI",
                investment="Înființare rețea de distribuție gaze naturale în orașul Turceni",
                category="Sisteme de distribuție gaze naturale",
                total_value=Decimal("12000000"),
                state_budget_value=Decimal("9000000"),
                poim=True,
                builder_cui=LONELY,
                builder_text="Omega Gaz SRL",
                progress="12",
            ),
            _payment(
                26004,
                104,
                date(2026, 4, 9),
                "500000",
                may,
                published_on=date(2026, 5, 18),
                county="TIMIS",
                town_hall="ȘANDRA",
                investment="Extindere rețea de canalizare în comuna Șandra",
                category="Sisteme de canalizare și stații de epurare a apelor uzate",
                total_value=Decimal("7000000"),
                state_budget_value=Decimal("6500000"),
                builder_text="Sigma Canal SRL",
            ),
        ]
    )
    town_hall = {"buyer_cui": TOWN_HALL, "buyer_text": "COMUNA TANTARENI (PRIMARIA TANTARENI)"}
    county = {"buyer_cui": 4288110, "buyer_text": "JUDETUL CLUJ"}
    session.add_all(
        [
            # One contract, two winners: the notice the test data also holds from SEAP.
            _contract(
                "CAN0000001",
                "4521",
                date(2023, 9, 14),
                "6120000",
                export,
                lot="1",
                supplier_cui=BUILDER,
                supplier_text="ALFA CONSTRUCT",
                **town_hall,
            ),
            _contract(
                "CAN0000001",
                "4521",
                date(2023, 9, 14),
                "6120000",
                export,
                lot="1",
                supplier_cui=PARTNER,
                supplier_text="GAMA ASFALT",
                **town_hall,
            ),
            _contract(
                "CAN1050001",
                "88",
                date(2021, 6, 3),
                "31500000",
                export,
                title="Modernizare DJ 109, lot 1",
                procedure_type="Licitatie deschisa",
                supplier_cui=PIPES,
                supplier_text="DELTA DRUMURI",
                **county,
            ),
            _contract(
                "CAN1070002",
                "140",
                date(2022, 2, 20),
                "9000000",
                export,
                is_framework=True,
                procedure_type="Licitatie deschisa",
                supplier_cui=PIPES,
                supplier_text="DELTA DRUMURI",
                **county,
            ),
            # The same builder, another buyer: it must not be tied to Turceni.
            _contract(
                "SCNA1100003",
                "12",
                date(2024, 4, 2),
                "800000",
                export,
                supplier_cui=LONELY,
                supplier_text="OMEGA GAZ",
                buyer_cui=4666380,
                buyer_text="ORAS ROVINARI",
            ),
        ]
    )
    session.add_all(
        [
            ExportBuyer(
                cui=TOWN_HALL,
                name="COMUNA TANTARENI (PRIMARIA TANTARENI)",
                county="GORJ",
                source_document_id=export,
            ),
            ExportBuyer(cui=4288110, name="JUDETUL CLUJ", source_document_id=export),
            ExportBuyer(cui=30000044, name="Judetul Cluj", source_document_id=export),
            ExportBuyer(cui=4666380, name="ORAS ROVINARI", source_document_id=export),
        ]
    )
    session.flush()
    pnias.link(session)
