"""A small PNRR edition, for the API tests and for the answers the site's browser tests run
on. The entities it names (the town hall, the hospital, the stationer) are seeded by the
tests that call it.

- 701, the town hall on C10.I3: its one contract on the measure, so the three payments
  to the town hall on C10.I3 are its own.
- 702 and 703, the hospital on C10.I3: two contracts on one measure, so its payments there
  belong to neither.
- 704, the stationer on two measures of C15, which disagree on status and progress.
- 705, a natural person on C2.I1 (afforestation): stored, never listed, no page.
- 706, the town hall on C2.I1. The hospital is paid on C2.I1 with no contract there.
"""

from datetime import date
from decimal import Decimal

from date_romania.models import (
    PnrrContract,
    PnrrContractLine,
    PnrrEdition,
    PnrrMeasure,
    PnrrPayment,
    PnrrTopRecipient,
    SourceDocument,
)

TOWN_HALL, HOSPITAL, STATIONER = 4981310, 4491342, 18288250
EDITION = date(2026, 10, 15)
ONE, SEVERAL, OTHER, MANY_MEASURES, PERSON, FOREST = 701, 702, 703, 704, 705, 706
BASE = "https://mfe.gov.ro/pnrr-dashboard/generator/data/20261015-"


def _document(session, endpoint: str, mark: str) -> int:
    doc = SourceDocument(
        source="pnrr",
        url=f"{BASE}{endpoint}.json.gz",
        sha256=mark * 64,
        storage_key=f"pnrr/{mark}",
        size_bytes=1,
        parser_version=1,
        rejected_rows=0,
    )
    session.add(doc)
    session.flush()
    return doc.id


def _measure(code, name, ministry, funding, allocated, contracted, paid_ron, paid_eur, doc):
    component, measure, *sub = code.split(".")
    return PnrrMeasure(
        code=code,
        component=component,
        measure=measure,
        submeasure=sub[0] if sub else None,
        name=name,
        ministry=ministry,
        ministry_name={"MDLPA": "Ministerul Dezvoltării", "MEC": "Ministerul Educației"}.get(
            ministry, "Ministerul Mediului"
        ),
        funding=funding,
        allocated_eur=Decimal(allocated),
        contracted_eu_ron=Decimal(contracted),
        paid_ron=Decimal(paid_ron),
        paid_eur=Decimal(paid_eur),
        source_document_id=doc,
        parser_version=1,
    )


def _contract(id, number, title, cui, name, kind, ministry, county, doc, natural=False):
    return PnrrContract(
        id=id,
        number=number,
        title=title,
        beneficiary_cui=cui,
        beneficiary_name=name,
        beneficiary_type=kind,
        natural_person=natural,
        ministry=ministry,
        signed_on=date(2024, 8, 26),
        starts_on=date(2024, 9, 1),
        impact="RURAL",
        county=county,
        locality=None,
        source_document_id=doc,
        parser_version=1,
    )


def _line(
    contract, position, measure, total, eu, status, physical, financial, ends=date(2026, 11, 30)
):
    return PnrrContractLine(
        contract_id=contract,
        position=position,
        measure_code=measure,
        funding="grant",
        total=Decimal(total),
        eu=Decimal(eu),
        national=Decimal(0),
        vat=Decimal(0),
        ineligible=Decimal(0),
        status=status,
        ends_on=ends,
        physical_progress=None if physical is None else Decimal(physical),
        financial_progress=None if financial is None else Decimal(financial),
    )


def seed(session) -> None:
    contracts = _document(session, "progres_tehnic_proiecte", "6")
    payments = _document(session, "plati_pnrr", "7")
    measures = _document(session, "masuri", "8")
    totals = _document(session, "indicatori_total", "9")
    top = _document(session, "persons", "5")
    session.add(
        PnrrEdition(
            day=EDITION,
            allocated_eur=Decimal("20106860700"),
            paid_eur=Decimal("14939205346.68"),
            received_eur=Decimal("13274906265"),
            prefinancing_eur=Decimal("4081717802"),
            suspended_eur=Decimal(0),
            revoked_eur=Decimal("468128928"),
            beneficiaries_contracted=13758,
            beneficiaries_paid=7768,
            contracts=21710,
            source_document_id=totals,
            parser_version=1,
        )
    )
    session.add_all(
        [
            _measure(
                "C10.I3",
                "Investiția 3. Renovarea energetică a clădirilor publice",
                "MDLPA",
                "grant",
                "500000000",
                "2000000000",
                "900000000",
                "180000000",
                measures,
            ),
            _measure(
                "C15.I9",
                "Investiția 9. Dotarea laboratoarelor",
                "MEC",
                "grant",
                "200000000",
                "700000000",
                "300000000",
                "60000000",
                measures,
            ),
            _measure(
                "C15.I11",
                "Investiția 11. Echipamente digitale",
                "MEC",
                "grant",
                "100000000",
                "400000000",
                "100000000",
                "20000000",
                measures,
            ),
            _measure(
                "C2.I1",
                "Investiția 1. Campania națională de împădurire",
                "MMAP",
                "grant",
                "300000000",
                "150000000",
                "60000000",
                "12000000",
                measures,
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            _contract(
                ONE,
                "12321",
                "Renovarea energetică a Școlii Gimnaziale Țânțăreni",
                TOWN_HALL,
                "COMUNA TANTARENI",
                "UAT",
                "MDLPA",
                "GORJ",
                contracts,
            ),
            _contract(
                SEVERAL,
                "12345",
                "Renovare energetică Spitalul Județean",
                HOSPITAL,
                "SPITALUL JUDETEAN",
                "SPITAL",
                "MDLPA",
                "CLUJ",
                contracts,
            ),
            _contract(
                OTHER,
                "12346",
                "Renovare energetică ambulatoriu",
                HOSPITAL,
                "SPITALUL JUDETEAN",
                "SPITAL",
                "MDLPA",
                "CLUJ",
                contracts,
            ),
            # A personal code typed into a title is masked when served.
            _contract(
                MANY_MEASURES,
                "8811",
                "Dotări școlare Beta 1800101123450",
                STATIONER,
                "BETA BIROTICA SRL",
                "IMM",
                "MEC",
                "GORJ",
                contracts,
            ),
            _contract(
                PERSON,
                "991",
                "Împădurire teren agricol",
                None,
                "NUME FICTIV",
                "PF",
                "MMAP",
                "IALOMIȚA",
                contracts,
                natural=True,
            ),
            _contract(
                FOREST,
                "992",
                "Împădurire teren comunal",
                TOWN_HALL,
                "COMUNA TANTARENI",
                "UAT",
                "MMAP",
                "GORJ",
                contracts,
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            _line(ONE, 1, "C10.I3", "6200000", "5200000", "ÎN IMPLEMENTARE", "0.4", "0.35"),
            _line(SEVERAL, 1, "C10.I3", "2450000", "2000000", "ÎN IMPLEMENTARE", "0.6", "0.5"),
            _line(OTHER, 1, "C10.I3", "1900000", "1500000", "FINALIZAT", "1", "1"),
            _line(
                MANY_MEASURES,
                1,
                "C15.I11",
                "807781.76",
                "807781.76",
                "ÎN IMPLEMENTARE",
                "0.9529",
                "0.9019",
            ),
            _line(
                MANY_MEASURES,
                2,
                "C15.I9",
                "608294.79",
                "608294.79",
                "ÎN IMPLEMENTARE (sub 30%)",
                "0",
                None,
            ),
            _line(PERSON, 1, "C2.I1", "120000", "120000", "ÎN IMPLEMENTARE", "0.2", "0.1"),
            _line(FOREST, 1, "C2.I1", "300000", "300000", "ÎN IMPLEMENTARE", "0.5", "0.3"),
        ]
    )
    rows = [
        # (paid_on, amount, cui, measure, contracts on the measure, contract)
        (date(2025, 12, 19), "750000", TOWN_HALL, "C10.I3", 1, ONE),
        (date(2026, 6, 11), "910000", TOWN_HALL, "C10.I3", 1, ONE),
        (date(2026, 10, 2), "640000", TOWN_HALL, "C10.I3", 1, ONE),
        (date(2026, 3, 4), "1000000", HOSPITAL, "C10.I3", 2, None),
        (date(2026, 7, 8), "800000", HOSPITAL, "C10.I3", 2, None),
        (date(2026, 5, 5), "612245", STATIONER, "C15.I11", 1, MANY_MEASURES),
        (date(2026, 2, 2), "50000", HOSPITAL, "C2.I1", 0, None),
    ]
    session.add_all(
        [
            PnrrPayment(
                position=n,
                measure_code=measure,
                funding="grant",
                amount=Decimal(amount),
                amount_eur=Decimal(amount) / 5,
                paid_on=day,
                reported_on=day,
                beneficiary_cui=cui,
                beneficiary_name=None,
                natural_person=False,
                county=None,
                locality=None,
                caen_division=None,
                contracts_on_measure=count,
                contract_id=contract,
                source_document_id=payments,
                parser_version=1,
            )
            for n, (day, amount, cui, measure, count, contract) in enumerate(rows, 1)
        ]
    )
    session.add_all(
        [
            PnrrTopRecipient(
                cui=HOSPITAL,
                name="SPITALUL JUDETEAN",
                total=Decimal("1800000"),
                last_received_on=date(2026, 7, 8),
                source_document_id=top,
                parser_version=1,
            ),
            PnrrTopRecipient(
                cui=TOWN_HALL,
                name="COMUNA TANTARENI",
                total=Decimal("2300000"),
                last_received_on=date(2026, 10, 2),
                source_document_id=top,
                parser_version=1,
            ),
        ]
    )
    session.flush()
