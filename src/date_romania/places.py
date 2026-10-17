"""Where things are: the kinds of place, how each source names a UAT, and the rule that
gives an institution or a company its county and its UAT.

A UAT is the unit with a town hall: a municipality, a town, a commune or a Bucharest
sector (Bucharest itself is a municipality and its own county). A village belongs to its
UAT. Every source names a UAT its own way; they are compared in one form, the county,
the kind and the bare name (`plain`), and found in SIRUTA.
"""

import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from date_romania.counties import county_name
from date_romania.models import AnafRecord, Entity, Place, PublicEntity
from date_romania.text import plain

COUNTY, MUNICIPALITY, TOWN, COMMUNE, SECTOR, VILLAGE = (
    "county",
    "municipality",
    "town",
    "commune",
    "sector",
    "village",
)
KINDS = (COUNTY, MUNICIPALITY, TOWN, COMMUNE, SECTOR, VILLAGE)
UATS = (MUNICIPALITY, TOWN, COMMUNE, SECTOR)

# The words sources put before a UAT's name, in `plain` form.
_PREFIXES = {
    "MUNICIPIUL": MUNICIPALITY,
    "MUN": MUNICIPALITY,
    "ORASUL": TOWN,
    "ORAS": TOWN,
    "ORS": TOWN,
    "COMUNA": COMMUNE,
    "COM": COMMUNE,
}
_SECTOR = re.compile(r"\bSECTOR(?:UL)? ([1-6])\b")


def county_key(name: str | None) -> str:
    """'JUDEŢUL BISTRIŢA-NĂSĂUD', 'Bistrita - Nasaud' and 'MUNICIPIUL BUCUREŞTI' as one
    form: 'BISTRITA NASAUD', 'BUCURESTI'."""
    key = plain(name)
    for prefix in ("JUDETUL ", "JUD ", "MUNICIPIUL "):
        key = key.removeprefix(prefix)
    return key


def uat_key(name: str | None) -> tuple[str | None, str]:
    """A UAT as (kind, bare name), however a source writes it; kind None when the name
    says none (SIRUTA writes a commune bare, and some lists drop the word).

    'Municipiul Blaj', 'Mun. Blaj' -> municipality BLAJ; 'Sat Gilău Com. Gilău' -> commune
    GILAU (a village is filed under its commune); 'Sector 2 Mun. Bucureşti', 'Sectorul 2',
    'BUCUREŞTI SECTORUL 2' -> sector SECTORUL 2.
    """
    text = plain(name)
    sector = _SECTOR.search(text)
    if sector:
        return SECTOR, f"SECTORUL {sector.group(1)}"
    words = text.split()
    # The last kind word names the UAT: a village comes first, its commune after it.
    for at in range(len(words) - 1, -1, -1):
        kind = _PREFIXES.get(words[at])
        if kind and at + 1 < len(words):
            return kind, " ".join(words[at + 1 :])
    return None, text


def _loose(bare: str) -> str:
    """A bare name with the letters old spelling changes taken out: lists still write
    'Tirgu Mures', 'Rimnicu Sarat', 'Sfantul Gheorghe' for SIRUTA's 'TÂRGU MUREŞ',
    'RÂMNICU SĂRAT', 'SFÂNTU GHEORGHE' (î for â; and a dropped article)."""
    return re.sub(r"[AI]", "", re.sub(r"UL\b", "U", bare)).replace(" ", "")


def _without_county(name: object, bare: str, county: str | None) -> str:
    """'ORSOVA' for 'Municipiul Orsova - Mehedinti'; a dash that is part of the name, as
    in 'Popesti - Leordeni', stays."""
    head, dash, tail = str(name).rpartition(" - ")
    if dash and county_key(tail) == county_key(county):
        return uat_key(head)[1]
    return bare


class PlaceIndex:
    """The UATs of SIRUTA by county and name, to find the one a source means."""

    def __init__(self, places: list[Place]) -> None:
        counties = {place.siruta: place for place in places if place.kind == COUNTY}
        self.counties = {county_key(place.name): place.siruta for place in counties.values()}
        self._exact: dict[tuple[int, str, str], int] = {}
        self._bare: dict[tuple[int, str], list[int]] = {}
        self._loose: dict[tuple[int, str], list[int]] = {}
        for place in places:
            if place.kind not in UATS or place.county is None:
                continue
            kind, bare = uat_key(place.name)
            kind = place.kind if kind is None or place.kind == SECTOR else kind
            self._exact[(place.county, kind, bare)] = place.siruta
            self._bare.setdefault((place.county, bare), []).append(place.siruta)
            self._loose.setdefault((place.county, _loose(bare)), []).append(place.siruta)

    @classmethod
    def load(cls, session: Session) -> "PlaceIndex":
        return cls(list(session.scalars(select(Place))))

    def county(self, name: str | None) -> int | None:
        return self.counties.get(county_key(name))

    def uat(self, county: str | None, name: str | None) -> int | None:
        """The SIRUTA code of the UAT `name` in `county`, or None.

        Failing the exact kind and name, a single UAT of that name in the county is
        taken, then a single one in old spelling; two are never told apart.
        """
        in_county = self.county(county)
        if in_county is None or not plain(name):
            return None
        kind, whole = uat_key(name)
        if whole == "BUCURESTI" and kind in (None, MUNICIPALITY):
            kind = MUNICIPALITY
        # A list may add the county after a dash, 'Municipiul Orsova - Mehedinti', though
        # 'Dărăşti-Ilfov' is the commune's own name: both are tried.
        for bare in dict.fromkeys((_without_county(name, whole, county), whole)):
            exact = self._exact.get((in_county, kind, bare)) if kind else None
            if exact is not None:
                return exact
            # Old spelling, or no kind named: a single UAT of that name in the county.
            for found in (
                self._bare.get((in_county, bare), []),
                self._loose.get((in_county, _loose(bare)), []),
            ):
                if len(found) == 1:
                    return found[0]
        return None


def _resolve(session: Session, index: PlaceIndex) -> None:
    """Find in SIRUTA the UAT each list row and each ANAF record names. Done again on every
    run from the names as stored, so the sources can be collected in any order."""
    for model, place in ((PublicEntity, PublicEntity.uat), (AnafRecord, AnafRecord.locality)):
        rows = [
            {"cui": cui, "siruta": index.uat(county, name)}
            for cui, county, name in session.execute(select(model.cui, model.county, place))
        ]
        if rows:
            session.execute(update(model), rows)


def locate(session: Session) -> int:
    """Give every entity its county, UAT and funder from what is held; returns how many
    have a UAT.

    The Finance Ministry's list comes first: it names the UAT an institution works in.
    ANAF's registered office comes next, for the rest and for companies. The funder is
    the first main credit holder that is another entity we hold.
    """
    places = {place.siruta: place for place in session.scalars(select(Place))}
    _resolve(session, PlaceIndex(list(places.values())))
    held = set(session.scalars(select(Entity.cui)))
    found: dict[int, int] = {}
    funders: dict[int, int] = {}
    for row in session.scalars(select(AnafRecord).where(AnafRecord.siruta.is_not(None))):
        found[row.cui] = row.siruta
    for row in session.scalars(select(PublicEntity)):
        if row.siruta is not None:
            found[row.cui] = row.siruta
        funder = next(
            (cui for cui in (row.funder_cui, row.second_funder_cui) if cui and cui != row.cui),
            None,
        )
        if funder in held:
            funders[row.cui] = funder
    rows = []
    for cui in held:
        place = places.get(found.get(cui, 0))
        county = places.get(place.county) if place and place.county else None
        rows.append(
            {
                "cui": cui,
                "siruta": place.siruta if place else None,
                "locality": place.name if place else None,
                "county": county_name(county_key(county.name)) if county else None,
                "parent_cui": funders.get(cui),
            }
        )
    if rows:
        session.execute(update(Entity), rows)
    return sum(1 for row in rows if row["siruta"] is not None)
