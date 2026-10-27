"""Tying an EU project to its beneficiary's entity (eu_links.py), over the places of
places_seed.py: Gorj, its commune Țânțăreni and the town hall there."""

import places_seed
from places_seed import BUILDER, HOSPITAL, STATIONER, TOWN_HALL

from date_romania import eu_links
from date_romania.models import Entity, EuProject, SourceDocument


def test_a_name_is_compared_without_its_legal_form_spelling():
    assert eu_links.name_key("SC Kase Professional S.R.L.") == "KASE PROFESSIONAL SRL"
    assert eu_links.name_key("S.C. A&S DEVELOPMENT S.R.L.") == "A S DEVELOPMENT SRL"
    assert eu_links.name_key("Port Bazinul Nou S.A.") == "PORT BAZINUL NOU SA"
    # Only a leading 'SC' is the old company prefix.
    assert eu_links.name_key("SCOALA GIMNAZIALA") == "SCOALA GIMNAZIALA"


def test_every_kind_of_tie(session):
    session.add_all(
        [
            Entity(cui=TOWN_HALL, name="COMUNA TANTARENI", kind="authority"),
            Entity(cui=HOSPITAL, name="SPITALUL ORASENESC", kind="authority"),
            Entity(cui=BUILDER, name="SC Drumuri Gorj SRL", kind="company"),
            Entity(cui=STATIONER, name="Beta Birotica SRL", kind="company"),
            # A school of the same name in the commune and elsewhere in no county held.
            Entity(cui=900001, name="Scoala Gimnaziala Nr 1", kind="authority"),
        ]
    )
    session.flush()
    places_seed.seed(session)
    session.get(Entity, 900001).county = "Gorj"
    doc = SourceDocument(
        source="eu-projects",
        url="https://data.gov.ro/x.xlsx",
        sha256="c" * 64,
        storage_key="eu-projects/c",
        size_bytes=1,
    )
    session.add(doc)
    session.flush()
    listed = {
        1: (HOSPITAL, "Spitalul Orasenesc", "Gorj", None),
        2: (None, "UAT Comuna Țânțăreni", "GJ", "Țânțăreni"),
        3: (None, "DRUMURI GORJ S.R.L.", "Gorj", None),
        # The stationer is in Dolj: its name is a company's, held once in the country.
        4: (None, "SC BETA BIROTICĂ SRL", "Gorj", None),
        # The town hall is not in Dolj: a name and a place that disagree tie nothing.
        5: (None, "Comuna Tantareni", "Dolj", None),
        6: (None, "Scoala Gimnaziala Nr 1", "Gorj", None),
        7: (None, "Asociatia Nimeni", "Gorj", None),
    }
    session.add_all(
        EuProject(
            smis=smis,
            programme="POR",
            period="2014-2020",
            beneficiary_cui=cui,
            beneficiary_name=name,
            county=county,
            locality=locality,
            source_document_id=doc.id,
            parser_version=2,
        )
        for smis, (cui, name, county, locality) in listed.items()
    )
    session.flush()

    assert eu_links.link(session) == 4
    session.expire_all()
    ties = {
        p.smis: (p.entity_cui, p.entity_method, p.entity_confidence)
        for p in session.query(EuProject)
    }
    assert ties == {
        1: (HOSPITAL, eu_links.BY_CUI, eu_links.SURE),
        2: (TOWN_HALL, eu_links.BY_ADMINISTRATION, eu_links.PROBABLE),
        3: (BUILDER, eu_links.BY_NAME, eu_links.PROBABLE),
        4: (STATIONER, eu_links.BY_COMPANY_NAME, eu_links.PROBABLE),
        5: (None, None, None),
        6: (None, None, None),
        7: (None, None, None),
    }
