"""Places: how each source names a UAT, and reading SIRUTA, the list of public entities,
the local budgets, the population tables and ANAF's answers. The fixtures are the real
files cut to a few rows (`research/places/cut_fixtures.py`)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from date_romania import places
from date_romania.collectors.anaf.parse import parse_answer
from date_romania.collectors.local_budgets.parse import (
    Parsed,
    _heading_problem,
    _read_row,
    file_kind,
    parse_budget,
    parse_population,
)
from date_romania.collectors.public_entities.parse import parse_entities
from date_romania.collectors.siruta.parse import edition, parse_places
from date_romania.models import Place
from date_romania.places import PlaceIndex, county_key, uat_key

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def siruta():
    parsed = parse_places((FIXTURES / "siruta.csv").read_bytes())
    assert parsed.rejected == []
    return {row["siruta"]: row for row in parsed.places}


@pytest.fixture(scope="module")
def index(siruta):
    return PlaceIndex([Place(**row) for row in siruta.values()])


def test_every_source_names_a_uat_in_one_form():
    assert uat_key("Municipiul Blaj") == (places.MUNICIPALITY, "BLAJ")
    assert uat_key("Mun. Iaşi") == (places.MUNICIPALITY, "IASI")
    assert uat_key("Orş. Zlatna") == (places.TOWN, "ZLATNA")
    assert uat_key("ORAŞ ZLATNA") == (places.TOWN, "ZLATNA")
    # A village comes first, its commune after it: the commune is the UAT.
    assert uat_key("Sat Gilău Com. Gilău") == (places.COMMUNE, "GILAU")
    # SIRUTA writes a commune with no word before it.
    assert uat_key("ALBAC") == (None, "ALBAC")
    for sector in ("Sector 2 Mun. Bucureşti", "Sectorul 2", "BUCUREŞTI SECTORUL 2"):
        assert uat_key(sector) == (places.SECTOR, "SECTORUL 2")
    assert county_key("JUDEŢUL BISTRIŢA-NĂSĂUD") == county_key("Bistrita - Nasaud")
    assert county_key("MUNICIPIUL BUCUREŞTI") == "BUCURESTI"


def test_siruta_gives_every_place_its_kind_parent_and_county(siruta):
    assert siruta[10] == {
        "siruta": 10,
        "name": "JUDEŢUL ALBA",
        "kind": "county",
        "parent": None,
        "county": 10,
        "urban": False,
    }
    assert (siruta[1017]["kind"], siruta[1017]["parent"]) == ("municipality", 10)
    assert siruta[1936]["kind"] == "town"
    assert siruta[2130]["kind"] == "commune"
    # The village Albac belongs to the commune Albac.
    assert (siruta[2149]["kind"], siruta[2149]["parent"]) == ("village", 2130)
    # Bucharest is its own county; its sectors belong to the municipality.
    assert (siruta[179132]["kind"], siruta[179132]["county"]) == ("municipality", 403)
    assert (siruta[179141]["kind"], siruta[179141]["parent"]) == ("sector", 179132)


def test_a_place_comes_after_the_one_it_belongs_to():
    parsed = parse_places((FIXTURES / "siruta.csv").read_bytes())
    seen: set[int] = set()
    for place in parsed.places:
        assert place["parent"] is None or place["parent"] in seen
        seen.add(place["siruta"])


def test_a_uat_is_found_however_a_source_writes_it(index):
    assert index.uat("Alba", "Orasul Zlatna") == 1936
    assert index.uat("ALBA", "Orş. Zlatna") == 1936
    assert index.uat("ALBA", "Sat Albac Com. Albac") == 2130
    assert index.uat("Alba", "Municipiul Alba Iulia") == 1017
    # Old spelling: î for â.
    assert index.uat("Mures", "Municipiul Tirgu Mures") == 114319
    # The county after a dash.
    assert index.uat("Mehedinti", "Municipiul Orsova - Mehedinti") == 110063
    assert index.uat("Bucuresti", "Sectorul 2 al Municipiului Bucuresti") == 179150
    assert index.uat("MUNICIPIUL BUCUREŞTI", "Sector 2 Mun. Bucureşti") == 179150
    assert index.uat("Bucuresti", "Municipiul Bucuresti") == 179132
    # Near misses are not forgiven: only î for â inside a word, and an article.
    assert index.uat("Alba", "Orasul Zlatno") is None
    assert index.uat("Alba", "Orasul Zlatina") is None
    assert index.uat("Mures", "Comuna Tirgu Mures") is None
    # A commune SIRUTA does not hold, a county it does not know, nothing at all.
    assert index.uat("Brasov", "Comuna Ticus") is None
    assert index.uat("Atlantis", "Orasul Zlatna") is None
    assert index.uat("Alba", "") is None


def test_an_edition_is_told_by_its_file_name():
    assert edition("siruta_s1_2026.csv") == (2026, 1)
    assert edition("siruta_an_2025.csv") == (2025, 2)
    assert (
        edition("siruta_s1_2026.csv")
        > edition("siruta_an_2025.csv")
        > edition("siruta_s1_2025.csv")
    )
    assert edition("legenda-siruta.xml") is None


def test_a_bad_level_rejects_its_row_not_the_file():
    village = b"2149;ALBAC;517005;1;2130;22;3;3;"
    content = (
        (FIXTURES / "siruta.csv").read_bytes().replace(village, village.replace(b";3;3;", b";x;3;"))
    )
    parsed = parse_places(content)
    assert [reason for _, reason in parsed.rejected] == ["no SIRUTA code, parent or level"]
    assert len(parsed.places) == 14


def test_the_list_of_public_entities_names_each_ones_uat_and_funders():
    parsed = parse_entities((FIXTURES / "public_entities.xlsx").read_bytes())
    # A made-up row whose funder's tax ID fails its checksum: the row is kept, the
    # funder is not, and it is counted.
    assert [reason for _, reason in parsed.rejected] == ["funder tax ID not valid: 4331032"]
    entities = {row["cui"]: row for row in parsed.entities}
    assert len(entities) == 7
    assert entities[4331040]["funder_cui"] is None
    school = entities[4331007]
    assert (school["county"], school["uat"]) == ("Alba", "Orasul Zlatna")
    # A school is funded by its town and by the Ministry of Education.
    assert (school["funder_cui"], school["funder_name"]) == (4331031, "ORAS ZLATNA")
    assert school["second_funder_cui"] == 13729380
    town = entities[4331031]
    assert (town["funder_cui"], town["funder_name"], town["second_funder_cui"]) == (
        None,
        None,
        None,
    )


def test_a_budget_file_and_a_population_file_are_told_apart_by_title():
    assert file_kind("Situația veniturilor și cheltuielilor - 2024.xlsx") == ("budget", 2024)
    assert file_kind("Populația definitivă a României la 1 ianuarie 2021.xlsx") == (
        "population",
        2021,
    )
    assert file_kind("Ghid de completare.pdf") is None


@pytest.fixture(scope="module")
def budget():
    parsed = parse_budget((FIXTURES / "local_budget.xlsx").read_bytes(), 2024)
    assert parsed.rejected == []
    return parsed.rows


def figure(rows, place, column):
    return next(row for row in rows if row["place"] == place and row["column_no"] == column)


def test_a_budget_row_is_one_column_of_one_uat(budget):
    revenue = figure(budget, 1017, 1)
    assert revenue["amount"] == Decimal("360835146")
    assert (revenue["section"], revenue["title"], revenue["year"]) == (
        "revenue",
        "VENITURI TOTALE",
        2024,
    )
    assert figure(budget, 1017, 22)["section"] == "spending"
    assert figure(budget, 1017, 22)["title"] == "CHELTUIELI TOTALE"
    assert figure(budget, 1017, 35)["title"] == "Cheltuieli de capital"
    assert figure(budget, 1017, 40)["section"] == "chapter"
    assert figure(budget, 1017, 40)["title"] == "Învăţământ"
    # Codes typed as numbers lose their '.0'.
    assert figure(budget, 1017, 35)["code"] == "70"
    # Every column with a figure: Alba Iulia has none under "Alte venituri" (21).
    assert {row["column_no"] for row in budget if row["place"] == 1017} == set(range(1, 51)) - {21}


def test_a_county_council_is_filed_under_its_county_and_an_empty_one_is_left_out(budget):
    council = figure(budget, ("county", "ALBA"), 1)
    assert council["amount"] == Decimal("471110222")
    # Bucharest has no county council: its row is all zeros.
    assert not [row for row in budget if row["place"] == ("county", "BUCURESTI")]
    # The city hall of Bucharest has its own budget, next to its sectors'.
    assert figure(budget, 179132, 1)["amount"] == Decimal("6478669635")
    assert figure(budget, 179141, 1)["amount"] == Decimal("1434018986")


def test_a_code_comes_from_the_country_sheet(budget):
    # Sheet 42 prints '49.90' over total revenue; the country's sheet has '00.01.02'.
    assert figure(budget, 179141, 1)["code"] == "00.01.02"
    assert figure(budget, 179141, 2)["code"] == "49.90"


def test_a_sheet_that_is_not_the_whole_year_in_lei_is_rejected():
    heading = [["Judeţul: ALBA"], ["Perioada: 31.12.2024"], ["", "- lei -"]]
    assert _heading_problem(heading, 2024) is None
    # Suceava's sheet names no unit; the file's others do.
    assert _heading_problem(heading[:2], 2024) is None
    assert "unit" in _heading_problem([*heading[:2], ["- mii lei -"]], 2024)
    assert "period" in _heading_problem([heading[0], ["Perioada: 30.09.2024"]], 2024)
    assert "period" in _heading_problem(heading[:1], 2024)
    # The file of one year read as another: every sheet is rejected, nothing is kept.
    wrong = parse_budget((FIXTURES / "local_budget.xlsx").read_bytes(), 2023)
    assert wrong.rows == []
    assert {reason for _, reason in wrong.rejected} == {
        "period ['PERIOADA 31 12 2024'], not 31.12.2023"
    }


def test_a_cell_that_is_not_a_number_is_counted_not_dropped():
    columns = [(3, 1, "revenue", "00.01.02", "VENITURI TOTALE"), (4, 2, "revenue", None, "X")]
    parsed = Parsed()
    _read_row(parsed, ["1", 1017, "ALBA IULIA", "100", "o sută"], columns, "ALBA", 2024)
    assert [row["column_no"] for row in parsed.rows] == [1]
    assert parsed.rejected == [((1017, 2, "o sută"), "figure that is not a number")]
    # A named UAT with no SIRUTA code is counted; an empty padding row is not.
    _read_row(parsed, ["2", "", "AIUD", "5"], columns, "ALBA", 2024)
    _read_row(parsed, ["3", "", "", "0"], columns, "ALBA", 2024)
    assert parsed.rejected[-1] == (["2", "", "AIUD"], "UAT without its SIRUTA code")
    assert len(parsed.rejected) == 2


def test_population_comes_in_two_layouts():
    old = parse_population((FIXTURES / "population_2021.xlsx").read_bytes(), 2021)
    assert old.rejected == []
    people = {row["place"]: row["people"] for row in old.rows}
    assert people[1017] == 74688
    assert people[2130] == 1984
    # 2021 lists Bucharest's total next to its sectors; the load leaves it out.
    assert {179132, 179141, 179150} <= set(people)
    assert {row["on"] for row in old.rows} == {date(2021, 1, 1)}

    new = parse_population((FIXTURES / "population_2024.xlsx").read_bytes(), 2024)
    assert new.rejected == []
    people = {row["place"]: row["people"] for row in new.rows}
    # County totals are not UATs; Bucharest's sectors are named, with no code.
    assert people == {
        1017: 74448,
        ("uat", "BUCURESTI", "SECTORUL 1"): 265361,
        ("uat", "BUCURESTI", "SECTORUL 2"): 359968,
    }


def test_anaf_gives_the_county_and_locality_never_the_street():
    parsed = parse_answer((FIXTURES / "anaf.json").read_bytes(), date(2026, 10, 17))
    assert parsed.rejected == []
    records = {row["cui"]: row for row in parsed.records}
    town = records[4331031]
    assert town["found"] is True
    assert (town["county"], town["county_code"], town["locality"]) == (
        "ALBA",
        "AB",
        "Orş. Zlatna",
    )
    assert town["asked_on"] == date(2026, 10, 17)
    assert records[4562362]["locality"] == "Sat Albac Com. Albac"
    assert records[99999999]["found"] is False
    assert records[99999999]["name"] is None
    # Nothing of the street is read.
    assert not any("Strada" in str(value) for row in parsed.records for value in row.values())
