"""The figures of a place, written once for an institution's budget, a UAT and a county:
the budget of a town hall, the Anghel Saligny payments to it, population, capital
spending, and the contracts of every buyer located there. Each figure keeps its own
period; nothing here adds one to another."""

from collections import defaultdict
from datetime import date

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from date_romania import local_money, place_names
from date_romania.api.routes.award_common import Buyer, awards_source, in_period, period
from date_romania.api.routes.common import last_fetched, ref
from date_romania.api.schemas import (
    Capital,
    ChapterAmount,
    LocalBudgetOut,
    PlaceContracts,
    PlaceRef,
    Population,
    ProgrammePayments,
    RevenueAmount,
    Source,
    SupplierCounties,
    TopWinner,
)
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardWinner,
    Entity,
    LocalBudget,
    Place,
    PniasPayment,
    SourceDocument,
)
from date_romania.models import Population as PopulationRow
from date_romania.sources import LOCAL_BUDGETS, PNIAS_PAYMENTS

TOP_WINNERS = 10


def place_ref(session: Session, place: Place) -> PlaceRef:
    county = session.get(Place, place.county) if place.county else place
    return PlaceRef(
        siruta=place.siruta,
        name=place_names.display(place),
        kind=place.kind,
        slug=place_names.county_slug(place) if place.kind == "county" else place_names.slug(place),
        county_slug=place_names.county_slug(county),
        county=place_names.display(county),
    )


def _budget_source(session: Session, year: int, document_id: int) -> Source:
    doc = session.get(SourceDocument, document_id)
    return Source(
        publisher=LOCAL_BUDGETS.publisher,
        record=f"MDLPA · Situația veniturilor și cheltuielilor {year}",
        url=LOCAL_BUDGETS.list_url,
        fetched_at=doc.fetched_at,
        document_id=doc.id,
        sha256=doc.sha256,
        parser_version=doc.parser_version,
    )


def local_budget(session: Session, siruta: int) -> LocalBudgetOut | None:
    """The latest budget held of the town hall of a UAT, or of a county's council."""
    found = local_money.budget(session, siruta)
    if found is None:
        return None
    return LocalBudgetOut(
        year=found.year,
        executed_on=date(found.year, 12, 31),
        revenue=found.revenue,
        revenue_lines=[
            RevenueAmount(line=line, amount=amount) for line, amount in found.revenue_lines.items()
        ],
        spending=found.spending,
        capital=found.capital,
        chapters=[
            ChapterAmount(chapter=chapter, amount=amount)
            for chapter, amount in sorted(found.chapters.items(), key=lambda each: -each[1])
            if amount
        ],
        source=_budget_source(session, found.year, found.document_id),
    )


def programme_payments(session: Session, sirutas: list[int]) -> ProgrammePayments | None:
    """The Anghel Saligny payments to the town halls (and councils) of these places."""
    found = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PniasPayment.amount), 0),
            func.count(PniasPayment.project_id.distinct()),
            func.min(PniasPayment.published_on),
            func.max(PniasPayment.published_on),
            func.count(PniasPayment.source_document_id.distinct()),
            func.min(PniasPayment.county),
            func.min(PniasPayment.town_hall),
            func.count(PniasPayment.town_hall.distinct()),
        ).where(PniasPayment.siruta.in_(sirutas))
    ).one()
    payments, amount, projects, first, last, files, county, town_hall, names = found
    if not payments:
        return None
    return ProgrammePayments(
        county=county,
        # One place, one name in the files; several places name no single town hall.
        town_hall=town_hall if names == 1 else None,
        amount=amount,
        payments=payments,
        projects=projects,
        first_published=first,
        last_published=last,
        source=Source(
            publisher=PNIAS_PAYMENTS.publisher,
            record=PNIAS_PAYMENTS.dataset,
            url=PNIAS_PAYMENTS.list_url,
            fetched_at=last_fetched(session, PNIAS_PAYMENTS),
            documents=files,
        ),
    )


def population(session: Session, sirutas: list[int]) -> Population | None:
    """People at the latest 1 January held for all of these places."""
    on = session.scalar(select(func.max(PopulationRow.on)).where(PopulationRow.siruta.in_(sirutas)))
    if on is None:
        return None
    people = session.scalar(
        select(func.sum(PopulationRow.people)).where(
            PopulationRow.siruta.in_(sirutas), PopulationRow.on == on
        )
    )
    return Population(people=people, on=on)


def capital(session: Session, sirutas: list[int]) -> Capital | None:
    """Capital spending in the latest budget year held for these places."""
    year = session.scalar(select(func.max(LocalBudget.year)).where(LocalBudget.siruta.in_(sirutas)))
    if year is None:
        return None
    amount, places, document = session.execute(
        select(
            func.sum(LocalBudget.amount),
            func.count(LocalBudget.siruta.distinct()),
            func.min(LocalBudget.source_document_id),
        ).where(
            LocalBudget.siruta.in_(sirutas),
            LocalBudget.year == year,
            LocalBudget.column_no == local_money.CAPITAL,
        )
    ).one()
    if not places:
        return None
    return Capital(
        amount=amount, year=year, places=places, source=_budget_source(session, year, document)
    )


def bought_in(sirutas: list[int]) -> ColumnElement[bool]:
    """A contract whose buyer is located in one of these places."""
    return Buyer.siruta.in_(sirutas)


def _counted(session: Session, sirutas: list[int]):
    return (
        select(AwardContract.id, AwardContract.value_ron)
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .join(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .where(*in_period(session), bought_in(sirutas))
    )


def place_contracts(session: Session, sirutas: list[int]) -> PlaceContracts:
    value, contracts, buyers = session.execute(
        select(
            func.coalesce(func.sum(AwardContract.value_ron), 0),
            func.count(AwardContract.id),
            func.count(AwardNotice.buyer_cui.distinct()),
        )
        .join(AwardNotice, AwardContract.notice_id == AwardNotice.id)
        .join(Buyer, AwardNotice.buyer_cui == Buyer.cui)
        .where(*in_period(session), bought_in(sirutas))
    ).one()
    return PlaceContracts(
        value=value,
        contracts=contracts,
        buyers=buyers,
        period=period(session),
        source=awards_source(session, AwardNotice.buyer_cui.in_(_buyers(sirutas))),
    )


def _buyers(sirutas: list[int]):
    return select(Entity.cui).where(Entity.siruta.in_(sirutas))


def winners(
    session: Session, sirutas: list[int], county: str
) -> tuple[SupplierCounties, list[TopWinner]]:
    """Where the contract value of these places went, by the winners' county, and the
    winners that took the most. An association is one winner, with its whole value."""
    counted = _counted(session, sirutas).subquery()
    rows = session.execute(
        select(counted.c.id, counted.c.value_ron, Entity)
        .join(AwardWinner, AwardWinner.contract_id == counted.c.id)
        .outerjoin(Entity, AwardWinner.supplier_cui == Entity.cui)
        .order_by(counted.c.id, AwardWinner.position)
    ).all()
    members: dict[int, list[Entity | None]] = defaultdict(list)
    values: dict[int, float] = {}
    for contract, value, entity in rows:
        # SEAP can list one company twice in one contract: still one winner.
        if entity is None or entity not in members[contract]:
            members[contract].append(entity)
        values[contract] = float(value or 0)
    totals = {"local": 0.0, "mixed": 0.0, "elsewhere": 0.0}
    groups: dict[tuple, dict] = {}
    for contract, found in members.items():
        local = [entity is not None and entity.county == county for entity in found]
        side = "local" if all(local) else "mixed" if any(local) else "elsewhere"
        totals[side] += values[contract]
        held = [entity for entity in found if entity is not None]
        if not held:
            continue
        key = tuple(sorted(entity.cui for entity in held))
        group = groups.setdefault(key, {"members": held, "value": 0.0, "contracts": 0})
        group["value"] += values[contract]
        group["contracts"] += 1
    top = sorted(groups.values(), key=lambda group: -group["value"])[:TOP_WINNERS]
    return SupplierCounties(county=county, **totals), [
        TopWinner(
            members=[ref(entity) for entity in group["members"]],
            counties=[entity.county for entity in group["members"]],
            value=group["value"],
            contracts=group["contracts"],
        )
        for group in top
    ]
