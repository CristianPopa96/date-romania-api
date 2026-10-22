from decimal import Decimal

from date_romania.cpv import is_annex_2
from date_romania.money import is_above_limit, limit_of


def test_annex_2_is_told_by_the_first_eight_digits_of_the_cpv_code():
    assert is_annex_2("55520000-1")  # catering, printed 5552000-1 in the law
    assert is_annex_2("79430000-7")  # crisis management, printed 794300000-7
    assert is_annex_2("85323000-9")  # the last code of a range is in it
    assert is_annex_2("80000000-4")
    assert not is_annex_2("85400000-7")
    assert not is_annex_2("30192000-1")
    assert not is_annex_2(None)
    assert not is_annex_2("8551")


def test_a_purchase_is_held_to_the_limit_of_its_type():
    assert limit_of(1, "30192000-1") == Decimal("270120")
    assert limit_of(2, "72000000-5") == Decimal("270120")
    assert limit_of(3, "45233140-2") == Decimal("900400")
    assert limit_of(None, "30192000-1") == Decimal("900400")
    assert limit_of(1, "55520000-1") is None
    assert is_above_limit(7, Decimal("270120.01"), 1, "30192000-1")
    assert not is_above_limit(7, Decimal("270120"), 1, "30192000-1")
    assert not is_above_limit(7, Decimal("5000000"), 2, "85100000-0")
    assert not is_above_limit(3, Decimal("5000000"), 1, "30192000-1")
