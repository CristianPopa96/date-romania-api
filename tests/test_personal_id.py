from date_romania.personal_id import is_cnp, mask_cnp


def test_is_cnp_checks_the_birth_date_and_the_control_digit():
    assert is_cnp("1800101123450")
    assert not is_cnp("1800101123451")  # wrong control digit
    assert not is_cnp("4052899926516")  # a barcode: month 52


def test_mask_cnp_hides_any_13_digits_where_a_party_is_named():
    assert mask_cnp("1234567890123 Popescu Ion PFA") == "[CNP] Popescu Ion PFA"
    assert mask_cnp("RO 17886786 B.T.T. TOURS") == "RO 17886786 B.T.T. TOURS"
    assert mask_cnp(None) is None


def test_mask_cnp_checked_hides_only_valid_codes():
    assert mask_cnp("Servicii Popescu Ion 1800101123450", checked=True) == (
        "Servicii Popescu Ion [CNP]"
    )
    assert mask_cnp("BEC LED 4052899926516", checked=True) == "BEC LED 4052899926516"
