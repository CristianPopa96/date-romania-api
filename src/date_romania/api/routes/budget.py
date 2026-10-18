"""An institution's budget: for a town hall or a county council, its executed budget and
the Anghel Saligny payments to it."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from date_romania.api.routes.common import Db, ref
from date_romania.api.routes.place_common import local_budget, place_ref, programme_payments
from date_romania.api.schemas import InstitutionBudget
from date_romania.models import Entity, Place

router = APIRouter()


@router.get("/institutions/{cui}/budget", tags=["entities"])
def institution_budget(session: Db, cui: int) -> InstitutionBudget:
    """For a town hall or a county council: the latest executed budget held and the
    Anghel Saligny payments to it. Every institution: the one that funds it."""
    entity = session.get(Entity, cui)
    if entity is None:
        raise HTTPException(404, f"No institution or company with CUI {cui}")
    place = session.scalar(select(Place).where(Place.town_hall_cui == cui))
    funder = session.get(Entity, entity.parent_cui) if entity.parent_cui else None
    located = session.get(Place, entity.siruta) if entity.siruta else None
    return InstitutionBudget(
        place=place and place_ref(session, place),
        located=located and place_ref(session, located),
        funder=ref(funder),
        budget=place and local_budget(session, place.siruta),
        programme_payments=place and programme_payments(session, [place.siruta]),
    )
