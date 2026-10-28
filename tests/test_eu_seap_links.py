"""Tying a SEAP notice or direct purchase to the EU project its text cites
(eu_seap_links.py)."""

from datetime import datetime
from decimal import Decimal

import eu_seed
import pnrr_seed

from date_romania import eu_seap_links
from date_romania.models import (
    AwardNotice,
    AwardNoticeDetail,
    DirectPurchase,
    Entity,
    EuSeapLink,
    SourceDocument,
)


def test_a_smis_code_is_read_however_it_is_written():
    assert eu_seap_links.smis_codes("Sursă de tensiune - SMIS: 315746") == [315746]
    assert eu_seap_links.smis_codes("PROIECT FAST -COD SMIS 324861- REF.3986") == [324861]
    assert eu_seap_links.smis_codes("cod MySMIS2014 120063 si cod SMIS 2014+: 118001") == [
        120063,
        118001,
    ]
    # Seven digits are not a SMIS code, nor a code far from the word.
    assert eu_seap_links.smis_codes("SMIS 1234567") == []
    assert eu_seap_links.smis_codes("SMIS, finanțat prin programul regional 2021-2027") == []


def test_a_financing_contract_number_is_read_as_written():
    read = eu_seap_links.financing_numbers
    assert read("contract de finanțare nr. 12321/26.08.2024 semnat cu MDLPA") == [
        "12321/26.08.2024"
    ]
    assert read("conform Contractului de finantare 2491DOT, PNRR") == ["2491DOT"]
    assert read("contractul de finanţare numărul: C3I1A0122000488") == ["C3I1A0122000488"]
    # Words after it are not a number.
    assert read("contractul de finanțare semnat în 2024") == []


def test_a_cited_number_names_a_contract_by_its_whole_or_its_first_part():
    same = eu_seap_links.same_number
    assert same("12560/04.10.2023.", "12560")
    assert same("1721/68/133/2024", "1721/68/I3.3/12.09.2024")
    assert same("c3i1a0122000488", "C3I1A0122000488")
    # A first part too short to mean anything needs the whole number.
    assert not same("1/4546/2023", "1/4548/2023")
    assert same("1/4548/2023", "1/4548/2023")
    # A first part with no digit ('NOSO/858/35') says nothing alone.
    assert not same("NOSO/858/35/23.11.2023", "NOSO/857/35/23.11.2023")


def test_records_are_tied_by_smis_code_and_by_the_buyers_own_contract_number(session):
    session.add_all(
        [
            Entity(cui=eu_seed.TOWN_HALL, name="COMUNA TANTARENI", kind="authority"),
            Entity(cui=eu_seed.HOSPITAL, name="SPITALUL JUDETEAN", kind="authority"),
            Entity(cui=pnrr_seed.STATIONER, name="Beta Birotica SRL", kind="company"),
        ]
    )
    session.flush()
    eu_seed.seed(session)
    pnrr_seed.seed(session)
    doc = SourceDocument(
        source="seap-awards",
        url="https://example.test",
        sha256="f" * 64,
        storage_key="f",
        size_bytes=1,
    )
    session.add(doc)
    session.flush()

    def notice(id_, buyer, title, project=None):
        session.add(
            AwardNotice(
                id=id_, buyer_cui=buyer, title=title, source_document_id=doc.id, parser_version=2
            )
        )
        session.flush()
        if project:
            session.add(
                AwardNoticeDetail(
                    notice_id=id_,
                    lots=1,
                    financing_types=[],
                    eu_funds=[],
                    eu_project=project,
                    source_document_id=doc.id,
                    parser_version=2,
                )
            )

    def purchase(id_, buyer, name, state=7):
        session.add(
            DirectPurchase(
                id=id_,
                name=name,
                state_id=state,
                buyer_cui=buyer,
                closing_value=Decimal(100),
                finalized_at=datetime(2026, 10, 6),
                source_document_id=doc.id,
                parser_version=3,
            )
        )

    # A partner buys for the project too: a SMIS code ties whatever the buyer.
    notice(1, eu_seed.HOSPITAL, "Lucrari", project=f"Proiect cod SMIS {eu_seed.POR}")
    # A code of a project not held (a regional programme) ties nothing.
    notice(2, eu_seed.TOWN_HALL, "Lucrari SMIS 399999")
    # The town hall's own PNRR contract, 12321; the hospital's numbers are 12345 and 12346.
    notice(3, eu_seed.TOWN_HALL, "Lucrari, contract de finantare nr. 12321/26.08.2024")
    # The stationer has no contract numbered 12345: another's number ties nothing.
    notice(4, pnrr_seed.STATIONER, "Furnizare, contract de finantare nr. 12345")
    purchase(5, eu_seed.HOSPITAL, f"Echipamente SMIS {eu_seed.HEALTH}, contract de finantare 12346")
    # A purchase not accepted bought nothing.
    purchase(6, eu_seed.HOSPITAL, f"Echipamente SMIS {eu_seed.HEALTH}", state=3)
    session.flush()

    assert eu_seap_links.link(session) == 4
    links = {
        (each.notice_id or each.purchase_id, each.smis or each.pnrr_contract_id, each.method)
        for each in session.query(EuSeapLink)
    }
    assert links == {
        (1, eu_seed.POR, eu_seap_links.BY_SMIS),
        (3, pnrr_seed.ONE, eu_seap_links.BY_FINANCING_NUMBER),
        (5, eu_seed.HEALTH, eu_seap_links.BY_SMIS),
        (5, pnrr_seed.OTHER, eu_seap_links.BY_FINANCING_NUMBER),
    }
    # Built again from scratch, not added to.
    assert eu_seap_links.link(session) == 4
