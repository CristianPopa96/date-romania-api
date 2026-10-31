"""The trade register as the link rules read it: who carries a name, and the entity of a
company that a rule ties to before any source named its tax ID.

A company's name is unique in the register among the companies that exist; one struck
off can share it with a newer one, so a name held by several tax IDs ties nothing unless
the place tells them apart.
"""

from collections.abc import Iterable
from itertools import batched

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from date_romania.models import Entity, Place, RegisterCompany
from date_romania.places import placed


def carriers(session: Session, keys: Iterable[str]) -> dict[str, list[tuple[int, int | None]]]:
    """Every company the register lists under each name, in `eu_links.name_key` form, as
    (cui, county)."""
    found: dict[str, list[tuple[int, int | None]]] = {}
    keys = sorted(set(keys))
    for start in range(0, len(keys), 5000):
        for key, cui, county in session.execute(
            select(RegisterCompany.name_key, RegisterCompany.cui, RegisterCompany.county).where(
                RegisterCompany.name_key.in_(keys[start : start + 5000])
            )
        ):
            found.setdefault(key, []).append((cui, county))
    return found


def add_entities(session: Session, cuis: Iterable[int]) -> None:
    """Give an entity to each company of the register in `cuis` not held yet, with its
    official name and its place."""
    cuis = set(cuis)
    if not cuis:
        return
    places = {place.siruta: place for place in session.scalars(select(Place))}
    rows = [
        {
            "cui": company.cui,
            "name": company.name,
            "kind": "company",
            **placed(places, company.siruta),
            "source_document_id": company.source_document_id,
        }
        for company in session.scalars(select(RegisterCompany).where(RegisterCompany.cui.in_(cuis)))
    ]
    for batch in batched(rows, 1000):
        session.execute(insert(Entity).values(list(batch)).on_conflict_do_nothing())
