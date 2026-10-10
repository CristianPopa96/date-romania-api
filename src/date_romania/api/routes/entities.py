"""Institutions and companies: search, and the page of one of them."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import ColumnElement, String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db, Limit, entity_out, list_source, summary, top
from date_romania.api.schemas import EntityPage, SearchResults
from date_romania.models import DirectPurchase, Entity, search_text

router = APIRouter()

_LIKE_ESCAPES = str.maketrans({"\\": r"\\", "%": r"\%", "_": r"\_"})


@router.get("/search", tags=["overview"])
def search(
    session: Db,
    q: Annotated[str, Query(min_length=2, max_length=100, description="A name or a CUI.")],
    kind: Literal["authority", "company"] | None = None,
    limit: Limit = 20,
) -> SearchResults:
    """Find institutions and companies by name (diacritics and small typos forgiven) or CUI."""
    query = select(Entity)
    if kind:
        query = query.where(Entity.kind == kind)
    digits = q.upper().removeprefix("RO").replace(" ", "")
    if digits.isdigit():
        query = query.where(cast(Entity.cui, String).startswith(digits)).order_by(Entity.cui)
    else:
        name, term = search_text(Entity.name), search_text(q.strip())
        # Best: every word of the query is in the name. Otherwise a close spelling will do.
        every_word = and_(
            *(
                name.like(search_text("%" + word.translate(_LIKE_ESCAPES) + "%"))
                for word in q.split()
            )
        )
        query = query.where(or_(every_word, term.op("<%")(name))).order_by(
            every_word.desc(),
            func.word_similarity(term, name).desc(),
            func.length(Entity.name),
            Entity.cui,
        )
    return SearchResults(items=[entity_out(e) for e in session.scalars(query.limit(limit))])


def _entity_page(
    session: Session, cui: int, own: ColumnElement, other: ColumnElement, partners: int
) -> EntityPage:
    entity = session.get(Entity, cui)
    if entity is None:
        raise HTTPException(404, f"No institution or company with CUI {cui}")
    return EntityPage(
        entity=entity_out(entity),
        direct_purchases=summary(session, own == cui),
        partners=top(session, other, [own == cui], partners),
        source=list_source(session),
    )


@router.get("/institutions/{cui}", tags=["entities"])
def institution(session: Db, cui: int, partners: Limit = 10) -> EntityPage:
    """An institution as a buyer: what it bought directly and from whom."""
    return _entity_page(
        session, cui, DirectPurchase.buyer_cui, DirectPurchase.supplier_cui, partners
    )


@router.get("/suppliers/{cui}", tags=["entities"])
def supplier(session: Db, cui: int, partners: Limit = 10) -> EntityPage:
    """A company as a supplier: what it sold directly and to whom."""
    return _entity_page(
        session, cui, DirectPurchase.supplier_cui, DirectPurchase.buyer_cui, partners
    )
