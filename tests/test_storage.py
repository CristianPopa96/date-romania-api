from date_romania.storage import object_key


def test_object_key_is_sharded_by_hash_prefix():
    sha = "ab" + "0" * 62
    assert object_key("seap", sha) == f"seap/ab/{sha}"
