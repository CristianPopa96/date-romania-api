"""Shared database helpers, inside a transaction that is rolled back (see conftest.py)."""

from date_romania import entities
from date_romania.db import upsert_rows
from date_romania.models import Entity


def test_upsert_keeps_a_known_name_and_promotes_a_buyer(session):
    session.add(Entity(cui=17886786, name="Known name", kind="company"))
    session.flush()

    entities.upsert(
        session,
        {17886786: ("B.T.T. TOURS", "authority"), 4981310: ("Comuna Vladila", "authority")},
        None,
    )
    session.expire_all()

    known = session.get(Entity, 17886786)
    assert (known.name, known.kind) == ("Known name", "authority")
    assert session.get(Entity, 4981310).name == "Comuna Vladila"


def test_upsert_never_turns_an_authority_back_into_a_company(session):
    session.add(Entity(cui=4981310, name="Comuna Vladila", kind="authority"))
    session.flush()

    entities.upsert(session, {4981310: ("COMUNA VLADILA", "company")}, None)
    session.expire_all()

    assert session.get(Entity, 4981310).kind == "authority"


def test_upsert_with_nothing_to_add_does_nothing(session):
    entities.upsert(session, {}, None)


def test_upsert_rows_replaces_a_stored_row_by_the_given_key(session):
    upsert_rows(session, Entity, [{"cui": 14399840, "name": "Old", "kind": "company"}], ("cui",))
    upsert_rows(
        session,
        Entity,
        [
            {"cui": 14399840, "name": "New", "kind": "authority"},
            {"cui": 4981310, "name": "Comuna Vladila", "kind": "authority"},
        ],
        ("cui",),
    )
    session.expire_all()

    replaced = session.get(Entity, 14399840)
    assert (replaced.name, replaced.kind) == ("New", "authority")
    assert session.get(Entity, 4981310).name == "Comuna Vladila"
