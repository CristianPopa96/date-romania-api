"""Places (flow 6): the counties, one county with its UATs, one UAT, and a search that
finds a UAT by its name or a village's. A place is addressed by its slugs:
`/v1/places/alba/comuna-albac`."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import local_money, place_names, places, pnias_links
from date_romania.api.routes.award_common import Buyer, in_period
from date_romania.api.routes.common import Db, Limit, containing, ref
from date_romania.api.routes.place_common import (
    capital,
    local_budget,
    place_contracts,
    place_ref,
    population,
    programme_payments,
    winners,
)
from date_romania.api.schemas import (
    Counties,
    County,
    CountyRow,
    CountyUat,
    LocalInstitution,
    Locality,
    LocalProject,
    PlaceFigures,
    PlaceHit,
    PlaceResults,
)
from date_romania.models import AwardContract, AwardNotice, Entity, LocalBudget, Place, search_text
from date_romania.models import Population as PopulationRow

router = APIRouter(tags=["places"])


def _counties(session: Session) -> list[Place]:
    return list(session.scalars(select(Place).where(Place.kind == places.COUNTY)))


def _county(session: Session, slug: str) -> Place:
    for county in _counties(session):
        if place_names.county_slug(county) == slug:
            return county
    raise HTTPException(404, f"No county {slug}")


def _uats(session: Session, county: Place) -> list[Place]:
    return list(
        session.scalars(
            select(Place).where(Place.county == county.siruta, Place.kind.in_(places.UATS))
        )
    )


def _figures(session: Session, sirutas: list[int], budgets: list[int], county: str) -> PlaceFigures:
    """`sirutas`: where the buyers, people and payments are; `budgets`: whose capital
    spending counts (a town hall's, or every one of a county's and its council's)."""
    shares, top = winners(session, sirutas, county)
    return PlaceFigures(
        population=population(session, sirutas),
        programme_payments=programme_payments(session, sirutas),
        capital=capital(session, budgets),
        contracts=place_contracts(session, sirutas),
        supplier_counties=shares,
        top_winners=top,
    )


def _latest_people(session: Session, sirutas: list[int]) -> dict[int, int]:
    on = session.scalar(select(func.max(PopulationRow.on)).where(PopulationRow.siruta.in_(sirutas)))
    return dict(
        session.execute(
            select(PopulationRow.siruta, PopulationRow.people).where(
                PopulationRow.siruta.in_(sirutas), PopulationRow.on == on
            )
        ).all()
    )


def _contracts_by_buyer_place(session: Session, sirutas: list[int]) -> dict[int, tuple]:
    rows = session.execute(
        select(Buyer.siruta, func.sum(AwardContract.value_ron), func.count(AwardContract.id))
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .join(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .where(*in_period(session), Buyer.siruta.in_(sirutas))
        .group_by(Buyer.siruta)
    )
    return {siruta: (float(value or 0), count) for siruta, value, count in rows}


@router.get("/places")
def counties(session: Db) -> Counties:
    """The 42 counties (Bucharest is one), with how many UATs and people each has."""
    found = _counties(session)
    in_county = session.execute(
        select(Place.siruta, Place.county).where(Place.kind.in_(places.UATS))
    ).all()
    people_of = _latest_people(session, [siruta for siruta, _ in in_county])
    uats: dict[int, int] = {}
    people: dict[int, int] = {}
    for siruta, county in in_county:
        uats[county] = uats.get(county, 0) + 1
        if siruta in people_of:
            people[county] = people.get(county, 0) + people_of[siruta]
    rows = [
        CountyRow(
            place=place_ref(session, county),
            uats=uats.get(county.siruta, 0),
            population=people.get(county.siruta),
        )
        for county in found
    ]
    return Counties(items=sorted(rows, key=lambda row: row.place.slug))


@router.get("/places/search")
def search_places(
    session: Db,
    q: Annotated[str, Query(min_length=2, max_length=100, description="A place's name.")],
    limit: Limit = 20,
) -> PlaceResults:
    """UATs by name, and villages, each found as the UAT it belongs to."""
    name, term = search_text(Place.name), search_text(q.strip())
    found = session.scalars(
        select(Place)
        .where(Place.kind.in_((*places.UATS, places.VILLAGE)), name.like(containing(q.strip())))
        .order_by((name == term).desc(), Place.kind == places.VILLAGE, func.length(Place.name))
        .limit(limit * 2)
    )
    hits: list[PlaceHit] = []
    seen: set[tuple[int, str | None]] = set()
    for place in found:
        uat, village = place, None
        if place.kind == places.VILLAGE:
            uat = session.get(Place, place.parent) if place.parent else None
            # A village named like its commune is the commune itself.
            village = place_names.title(place.name)
            if uat is None or uat.kind not in places.UATS:
                continue
            if place_names.title(place_names.bare(uat)) == village:
                village = None
        if (uat.siruta, village) in seen:
            continue
        seen.add((uat.siruta, village))
        hits.append(PlaceHit(place=place_ref(session, uat), village=village))
    return PlaceResults(items=hits[:limit])


@router.get("/places/{county}")
def county(session: Db, county: str) -> County:
    """A county: its figures added up over its UATs and its council, and every UAT."""
    found = _county(session, county)
    uats = _uats(session, found)
    sirutas = [uat.siruta for uat in uats]
    name = place_names.display(found)
    people = _latest_people(session, sirutas)
    year = session.scalar(select(func.max(LocalBudget.year)).where(LocalBudget.siruta.in_(sirutas)))
    capitals = dict(
        session.execute(
            select(LocalBudget.siruta, LocalBudget.amount).where(
                LocalBudget.siruta.in_(sirutas),
                LocalBudget.year == year,
                LocalBudget.column_no == local_money.CAPITAL,
            )
        ).all()
    )
    contracts = _contracts_by_buyer_place(session, sirutas)
    council = session.get(Entity, found.town_hall_cui) if found.town_hall_cui else None
    rows = [
        CountyUat(
            place=place_ref(session, uat),
            population=people.get(uat.siruta),
            capital=capitals.get(uat.siruta),
            contract_value=contracts.get(uat.siruta, (0.0, 0))[0],
            contracts=contracts.get(uat.siruta, (0.0, 0))[1],
        )
        for uat in uats
    ]
    return County(
        place=place_ref(session, found),
        council=ref(council),
        figures=_figures(session, [*sirutas, found.siruta], [*sirutas, found.siruta], name),
        uats=sorted(rows, key=lambda row: row.place.slug.split("-", 1)[-1]),
    )


def _projects(session: Session, sirutas: list[int]) -> list[LocalProject]:
    project = pnias_links.projects()
    found = session.execute(
        select(project, Entity)
        .outerjoin(Entity, project.c.builder_cui == Entity.cui)
        .where(project.c.siruta.in_(sirutas))
        .order_by(project.c.paid.desc(), project.c.project_id)
    ).all()
    return [
        LocalProject(
            id=row.project_id,
            investment=row.investment,
            builder=ref(row.Entity),
            builder_text=row.builder_text,
            progress=row.progress,
            paid=row.paid,
            payments=row.payments,
            match=row.match,
        )
        for row in found
    ]


def _institutions(session: Session, uat: Place) -> list[LocalInstitution]:
    totals = dict(
        (cui, (float(value or 0), count))
        for cui, value, count in session.execute(
            select(Buyer.cui, func.sum(AwardContract.value_ron), func.count(AwardContract.id))
            .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
            .join(Buyer, AwardNotice.buyer_cui == Buyer.cui)
            .where(*in_period(session), Buyer.siruta == uat.siruta)
            .group_by(Buyer.cui)
        )
    )
    found = session.scalars(
        select(Entity).where(Entity.siruta == uat.siruta, Entity.kind == "authority")
    )
    rows = [
        LocalInstitution(
            entity=ref(entity),
            town_hall=entity.cui == uat.town_hall_cui,
            contract_value=totals.get(entity.cui, (0.0, 0))[0],
            contracts=totals.get(entity.cui, (0.0, 0))[1],
        )
        for entity in found
    ]
    return sorted(rows, key=lambda row: (not row.town_hall, -row.contract_value, row.entity.name))


@router.get("/places/{county}/{uat}")
def locality(session: Db, county: str, uat: str) -> Locality:
    """One UAT: its town hall's budget, the payments to it, the contracts of every buyer
    located there, its Anghel Saligny projects and its institutions. Bucharest adds up
    its sectors' people, buyers and payments, and lists them."""
    found_county = _county(session, county)
    found = next(
        (place for place in _uats(session, found_county) if place_names.slug(place) == uat),
        None,
    )
    if found is None:
        raise HTTPException(404, f"No UAT {uat} in {county}")
    parts = list(
        session.scalars(
            select(Place)
            .where(Place.parent == found.siruta, Place.kind == places.SECTOR)
            .order_by(Place.siruta)
        )
    )
    sirutas = [found.siruta, *(part.siruta for part in parts)]
    town_hall = session.get(Entity, found.town_hall_cui) if found.town_hall_cui else None
    return Locality(
        place=place_ref(session, found),
        town_hall=ref(town_hall),
        parts=[place_ref(session, part) for part in parts],
        figures=_figures(session, sirutas, [found.siruta], place_names.display(found_county)),
        budget=local_budget(session, found.siruta),
        projects=_projects(session, sirutas),
        institutions=_institutions(session, found),
    )
