"""The road of the data, for the sources page: every answer kept whole, the rows read
from them, the links our rules make between them, and the projects the site shows."""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania.api.routes.common import Db
from date_romania.api.schemas.data_road import Counted, DataRoad, LinkCount
from date_romania.models import (
    AnafRecord,
    AwardContract,
    AwardNotice,
    DirectPurchase,
    DirectPurchaseDetail,
    Entity,
    EuProject,
    EuProjectPayment,
    EuSeapLink,
    ExportContract,
    LocalBudget,
    Place,
    PniasLink,
    PniasPayment,
    PnrrContract,
    PnrrPayment,
    Project,
    PublicEntity,
    RegisterCompany,
    SourceDocument,
)

router = APIRouter(tags=["overview"])

# The tables the parsers write, in the order the page reads them.
_READ = (
    DirectPurchase,
    DirectPurchaseDetail,
    AwardNotice,
    AwardContract,
    PniasPayment,
    ExportContract,
    PnrrContract,
    PnrrPayment,
    EuProject,
    EuProjectPayment,
    Place,
    PublicEntity,
    LocalBudget,
    AnafRecord,
    RegisterCompany,
)


def _grouped(session: Session, rule: str, method, confidence, *where) -> list[LinkCount]:
    return [
        LinkCount(rule=rule, method=method_, confidence=confidence_, count=count)
        for method_, confidence_, count in session.execute(
            select(method, confidence, func.count())
            .where(*where)
            .group_by(method, confidence)
            .order_by(method, confidence)
        )
        if method_
    ]


def _links(session: Session) -> list[LinkCount]:
    return [
        *_grouped(
            session,
            "eu-beneficiary",
            EuProject.entity_method,
            EuProject.entity_confidence,
            EuProject.entity_cui.is_not(None),
        ),
        # By what the builder was found from: its own tax ID, the project's, or the register.
        *_grouped(
            session,
            "anghel-saligny-contract",
            func.split_part(PniasLink.method, "+", 1),
            PniasLink.confidence,
        ),
        *_grouped(session, "eu-seap", EuSeapLink.method, EuSeapLink.confidence),
        LinkCount(
            rule="pnrr-payment-contract",
            method="only-contract-on-measure",
            confidence=None,
            count=session.scalar(select(func.count()).where(PnrrPayment.contract_id.is_not(None))),
        ),
        LinkCount(
            rule="entity-place",
            method="siruta",
            confidence=None,
            count=session.scalar(select(func.count()).where(Entity.siruta.is_not(None))),
        ),
    ]


def _counted(session: Session, column) -> list[Counted]:
    return [
        Counted(key=key, count=count)
        for key, count in session.execute(
            select(column, func.count()).group_by(column).order_by(func.count().desc(), column)
        )
    ]


@router.get("/data-road")
def data_road(session: Db) -> DataRoad:
    """Each step of the road from a public source to a page, in figures."""
    documents, stored, rejected = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(SourceDocument.size_bytes), 0),
            func.coalesce(func.sum(SourceDocument.rejected_rows), 0),
        )
    ).one()
    return DataRoad(
        documents=documents,
        stored_bytes=stored,
        rejected_rows=rejected,
        read=[
            Counted(
                key=model.__tablename__,
                count=session.scalar(select(func.count()).select_from(model)),
            )
            for model in _READ
        ],
        links=_links(session),
        entities=session.scalar(select(func.count()).select_from(Entity)),
        projects=_counted(session, Project.kind),
        reach=_counted(session, Project.reach),
    )
