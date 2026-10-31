"""One project of the Anghel Saligny programme, traced from the ministry to the contract."""

from collections import Counter

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from date_romania import pnias_links
from date_romania.api.routes.common import Db, ref
from date_romania.api.routes.programmes import project_row, source
from date_romania.api.schemas import (
    Project,
    ProjectPayment,
    TraceBuilder,
    TraceContract,
    TraceParty,
)
from date_romania.models import AwardNotice, Entity, ExportContract, PniasLink, PniasPayment
from date_romania.sources import PNIAS_PAYMENTS, SEAP_EXPORTS

router = APIRouter(prefix="/programmes/anghel-saligny", tags=["programmes"])


# What tells one contract of an export from another.
def _same_contract(contract: ExportContract) -> tuple:
    return contract.source_document_id, contract.notice_no, contract.contract_no


def _held_notices(session: Session, numbers: set[str | None]) -> dict[str, int]:
    """Our id for the award notices we collected ourselves, by SEAP's number: those have
    a page on the site. A republished notice has several ids; the latest is taken."""
    return dict(
        session.execute(
            select(AwardNotice.notice_no, func.max(AwardNotice.id))
            .where(AwardNotice.notice_no.in_(numbers - {None}))
            .group_by(AwardNotice.notice_no)
        ).all()
    )


def _winners(
    session: Session, contracts: list[ExportContract]
) -> dict[tuple, list[ExportContract]]:
    """Every winner row of the contracts given: an association has one per member.

    The rows of the same exports and notices are read and sorted here: a contract can
    lack its number, and SQL would not find a missing value equal to itself.
    """
    rows = session.scalars(
        select(ExportContract)
        .where(
            ExportContract.source_document_id.in_({each.source_document_id for each in contracts}),
            ExportContract.notice_no.in_({each.notice_no for each in contracts})
            | ExportContract.id.in_({each.id for each in contracts}),
        )
        .order_by(ExportContract.id)
    )
    winners: dict[tuple, list[ExportContract]] = {}
    for row in rows:
        winners.setdefault(_same_contract(row), []).append(row)
    return winners


def _parties(
    payments: list[PniasPayment], role: str
) -> list[tuple[int | None, str | None, list[PniasPayment]]]:
    """The payments of a project by who built (or designed) it, as (CUI, name, payments).

    The older files name a company without its tax ID. Inside one project, the same name
    is the same company, so those payments join the ones that carry the tax ID. A builder
    is the one the link rule found (`builder_found_cui`), the register's included.
    """
    column = "builder_found_cui" if role == "builder" else f"{role}_cui"
    named = [
        (getattr(payment, column), getattr(payment, f"{role}_text"), payment)
        for payment in payments
    ]
    cui_of = {name: cui for cui, name, _ in named if cui}
    groups: dict[int | str, list] = {}
    for cui, name, payment in named:
        cui = cui or cui_of.get(name)
        if cui or name:
            groups.setdefault(cui or name, [cui, name, []])[2].append(payment)
    return [(cui, name, theirs) for cui, name, theirs in groups.values()]


def _found_by(payments: list[PniasPayment]) -> str | None:
    """Where a builder's tax ID comes from: a payment file, when any payment gives it."""
    found = {payment.builder_found_by for payment in payments}
    if pnias_links.FROM_FILE in found:
        return pnias_links.FROM_FILE
    return next((each for each in found if each), None)


def _match(cui: int | None, contracts: list[ExportContract]) -> str:
    if not cui:
        return pnias_links.UNNAMED
    notices = {contract.notice_no for contract in contracts}
    return (
        pnias_links.NONE
        if not notices
        else pnias_links.ONE
        if len(notices) == 1
        else pnias_links.SEVERAL
    )


@router.get("/projects/{project_id}")
def project(session: Db, project_id: int) -> Project:
    """One project: what it is, every payment for it, who builds it, and the contracts
    its payments could be tied to."""
    view = pnias_links.projects()
    row = session.execute(select(view).where(view.c.project_id == project_id)).one_or_none()
    if row is None:
        raise HTTPException(404, f"No project {project_id} in the Anghel Saligny programme")
    payments = session.scalars(
        select(PniasPayment)
        .where(PniasPayment.project_id == project_id)
        .order_by(PniasPayment.published_on.desc(), PniasPayment.id.desc())
    ).all()
    linked: dict[int, list[ExportContract]] = {}
    evidence: dict[int, PniasLink] = {}
    for link, contract in session.execute(
        select(PniasLink, ExportContract)
        .join(ExportContract, ExportContract.id == PniasLink.contract_id)
        .where(PniasLink.payment_id.in_([payment.id for payment in payments]))
        .order_by(ExportContract.contract_date, ExportContract.id)
    ):
        linked.setdefault(link.payment_id, []).append(contract)
        # A payment that names the builder by its own tax ID says best what a tie rests on.
        known = evidence.get(contract.id)
        if known is None or not pnias_links.by_own_tax_id(known.method):
            evidence[contract.id] = link
    contracts = list({each.id: each for found in linked.values() for each in found}.values())
    winners = _winners(session, contracts)
    parties = {role: _parties(payments, role) for role in ("builder", "designer")}
    cuis = {cui for groups in parties.values() for cui, _, _ in groups}
    cuis.update(winner.supplier_cui for found in winners.values() for winner in found)
    cuis.update(contract.buyer_cui for contract in contracts)
    entities = {
        entity.cui: entity
        for entity in session.scalars(select(Entity).where(Entity.cui.in_(cuis - {None})))
    }
    held = _held_notices(session, {contract.notice_no for contract in contracts})

    def party(cui: int | None, name: str | None) -> dict:
        return {"cui": cui, "name": name, "entity": ref(entities.get(cui))}

    def traced(contract: ExportContract) -> TraceContract:
        value = contract.value_ron
        return TraceContract(
            notice_no=contract.notice_no,
            notice_id=held.get(contract.notice_no),
            notice_date=contract.notice_date,
            contract_no=contract.contract_no,
            contract_date=contract.contract_date,
            title=contract.title,
            lot=contract.lot,
            value_ron=value,
            procedure_type=contract.procedure_type,
            contract_type=contract.contract_type,
            is_framework=contract.is_framework,
            buyer=ref(entities.get(contract.buyer_cui)),
            buyer_text=contract.buyer_text,
            confidence=evidence[contract.id].confidence,
            method=evidence[contract.id].method,
            partners=[
                TraceParty(**party(winner.supplier_cui, winner.supplier_text))
                for winner in winners.get(_same_contract(contract), ())
                if winner.id != contract.id
            ],
            ratio=float(value / row.total_value) if value and row.total_value else None,
        )

    builders = []
    for cui, name, theirs in parties["builder"]:
        found = {each.id: each for payment in theirs for each in linked.get(payment.id, ())}
        builders.append(
            TraceBuilder(
                **party(cui, name),
                found_by=_found_by(theirs) if cui else None,
                payments=len(theirs),
                amount=sum(payment.amount for payment in theirs),
                match=_match(cui, list(found.values())),
                contracts=[traced(contract) for contract in found.values()],
            )
        )
    # The town hall has no tax ID in the payment files; the buyer of the tied contracts
    # is the same town hall as SEAP names it.
    buyers = Counter(contract.buyer_cui for contract in contracts if contract.buyer_cui)
    town_hall = entities.get(buyers.most_common(1)[0][0]) if buyers else None
    return Project(
        **project_row(row).model_dump(),
        town_hall_entity=ref(town_hall),
        ministry_contract_no=row.ministry_contract_no,
        ministry_contract_date=row.ministry_contract_date,
        poim=row.poim,
        state=row.state,
        progress=next((payment.progress for payment in payments if payment.progress), None),
        estimated_end=row.estimated_end,
        items=[ProjectPayment.model_validate(payment) for payment in payments],
        builders=builders,
        designers=[TraceParty(**party(cui, name)) for cui, name, _ in parties["designer"]],
        confidence=None
        if not evidence
        else pnias_links.POSSIBLE
        if any(link.confidence == pnias_links.POSSIBLE for link in evidence.values())
        else pnias_links.PROBABLE,
        source=source(session, PNIAS_PAYMENTS, len({p.source_document_id for p in payments})),
        contracts_source=source(
            session, SEAP_EXPORTS, len({c.source_document_id for c in contracts})
        ),
    )
