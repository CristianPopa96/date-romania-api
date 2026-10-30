"""Every project of every programme as one list (projects.py): reading a programme's counties."""

from date_romania.projects import county_codes


def test_a_county_is_read_however_a_programme_writes_it():
    # A code, a name in any case, with or without diacritics.
    assert county_codes("DJ") == ["DJ"]
    assert county_codes("Hunedoara") == ["HD"]
    assert county_codes("BISTRITA-NASAUD") == ["BN"]
    assert county_codes("MUNICIPIUL BUCUREȘTI") == ["B"]
    # Several, by commas, or one name after another.
    assert county_codes("Arad, Hunedoara") == ["AR", "HD"]
    assert county_codes("B,BH,CJ") == ["B", "BH", "CJ"]
    assert county_codes("BRAILA BUZAU") == ["BR", "BZ"]
    assert county_codes("SATU MARE CLUJ") == ["SM", "CJ"]
    # A letter lost on the way.
    assert county_codes("CONSTANA") == ["CT"]


def test_a_national_project_or_a_word_that_is_no_county_has_none():
    assert county_codes("NAȚIONAL") == []
    assert county_codes("Nivel național") == []
    assert county_codes("RO") == []
    assert county_codes(None) == []
    assert county_codes("Regiunea Centru") == []
