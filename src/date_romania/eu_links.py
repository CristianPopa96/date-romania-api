"""EU cohesion projects: tying a project to its beneficiary's entity.

Every list names the beneficiary; only some give its tax ID (the 2021-2027 lists of PEO,
PoIDS and Health, and POCU's). The others are tied by name and place, never surely. The
rule is written once, here: the collector runs it after every load, `dr link eu-projects`
runs it alone, and the API reads what it stored on `eu_project`.
"""

import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from date_romania.models import Entity, EuProject, Place
from date_romania.places import PlaceIndex, governed
from date_romania.text import plain

# How a project was tied to its beneficiary, and how sure the tie is.
#   sure      the list gives the beneficiary's tax ID
#   probable  the name is an administration's ('UAT Comuna Albac', 'Județul Alba'), and the
#             place it names, in the project's county, has one town hall or council; or the
#             name is that of one entity in the project's county (or, when the county has
#             several, one in the UAT the list names); or the name is a company's, which
#             the trade register keeps unique in the country, and one entity carries it
# A name that ties nothing whole is tried again without what follows a '/', where some
# lists add the department that runs the project: 'MUNICIPIUL ZALĂU/Entitate de drept
# public', 'COMUNA HOLBOCA/primarie'. The tie keeps the method of the part that matched.
BY_CUI = "cui-in-list"
BY_ADMINISTRATION = "administration-name+place"
BY_NAME = "name+place"
BY_COMPANY_NAME = "company-name"
SURE, PROBABLE = "sure", "probable"

# What some lists put before an administration's own name: 'UAT Orasul Cugir'.
_UAT = re.compile(r"^(UNITATEA ADMINISTRATIV TERITORIALA|UNITATE ADMINISTRATIV TERITORIALA|UAT) ")
# A company's legal form, however it is spelled: 'S.R.L.', 'S. A.', and the old 'SC' first.
_FORMS = ((re.compile(r"\bS R L\b"), "SRL"), (re.compile(r"\bS A\b"), "SA"))
_SC = re.compile(r"^S ?C ")
# A name that ends in a company's legal form, in `name_key` form.
_COMPANY = re.compile(r" (SRL|SA)$")


def name_key(name: str | None) -> str:
    """A beneficiary's name as it is compared: 'SC Kase Professional S.R.L.' and
    'KASE PROFESSIONAL SRL' are one."""
    text = plain(name)
    for form, written in _FORMS:
        text = form.sub(written, text)
    return _SC.sub("", text)


def administration(index: PlaceIndex, county: str | None, name: str | None) -> int | None:
    """The place an administration named as a beneficiary governs, or None."""
    return governed(index, county, _UAT.sub("", plain(name)))


def link(session: Session) -> int:
    """Tie every project to its beneficiary's entity, from what is held; returns how many
    are tied."""
    places = {place.siruta: place for place in session.scalars(select(Place))}
    index = PlaceIndex(list(places.values()))
    named: dict[str, list[tuple[int, int | None, int | None]]] = {}
    for cui, name, siruta in session.execute(select(Entity.cui, Entity.name, Entity.siruta)):
        county = places[siruta].county if siruta in places else None
        named.setdefault(name_key(name), []).append((cui, siruta, county))
    rows = []
    for smis, cui, name, county, locality in session.execute(
        select(
            EuProject.smis,
            EuProject.beneficiary_cui,
            EuProject.beneficiary_name,
            EuProject.county,
            EuProject.locality,
        )
    ):
        found = _tie(index, places, named, cui, name, county, locality)
        entity, method, confidence = found or (None, None, None)
        rows.append(
            {
                "smis": smis,
                "entity_cui": entity,
                "entity_method": method,
                "entity_confidence": confidence,
            }
        )
    if rows:
        session.execute(update(EuProject), rows)
    return sum(1 for row in rows if row["entity_cui"] is not None)


def _tie(index, places, named, cui, name, county, locality) -> tuple[int, str, str] | None:
    if cui is not None:
        return cui, BY_CUI, SURE
    found = _by_name(index, places, named, name, county, locality)
    if found is None and name and "/" in name:
        found = _by_name(index, places, named, name.split("/")[0], county, locality)
    return found


def _by_name(index, places, named, name, county, locality) -> tuple[int, str, str] | None:
    governs = administration(index, county, name)
    if governs is not None:
        town_hall = places[governs].town_hall_cui
        return (town_hall, BY_ADMINISTRATION, PROBABLE) if town_hall else None
    key = name_key(name)
    held = named.get(key, [])
    in_county = index.county(county)
    same = [each for each in held if in_county is not None and each[2] == in_county]
    if len(same) > 1:
        uat = index.uat(county, locality)
        same = [each for each in same if each[1] == uat]
    if len(same) == 1:
        return same[0][0], BY_NAME, PROBABLE
    if not same and len(held) == 1 and _COMPANY.search(key):
        return held[0][0], BY_COMPANY_NAME, PROBABLE
    return None
