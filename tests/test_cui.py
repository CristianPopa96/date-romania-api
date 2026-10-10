from date_romania.cui import is_valid_cui, parse_cui


def test_valid_checksum():
    # 001234567 x 753217532 = 95; 95 * 10 % 11 = 4
    assert is_valid_cui("12345674")


def test_wrong_checksum():
    assert not is_valid_cui("12345675")


def test_parse_strips_prefix_and_spaces():
    assert parse_cui("RO 12345674") == 12345674
    assert parse_cui(" 12345674") == 12345674
    assert parse_cui(12345674) == 12345674


def test_parse_rejects_invalid():
    assert parse_cui("12345675") is None
    assert parse_cui("") is None
    assert parse_cui("12345678901") is None
    assert parse_cui("00") is None
