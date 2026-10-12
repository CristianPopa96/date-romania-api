"""The Anghel Saligny programme: tying a payment to the SEAP contract it settles.

The payment files name the builder by tax ID and the town hall by name only; SEAP names
both. A payment is tied to the contracts its builder won from a buyer whose name is that
town hall's. The rule is written once, here: the collectors build the links with it and
the API reads them.
"""

import re
from itertools import groupby

from sqlalchemy import ColumnElement, Subquery, case, delete, func, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from date_romania.collectors.sheets import plain
from date_romania.models import ExportContract, PniasLink, PniasPayment

# How a payment was tied to a contract, and how sure the tie is. The builder is the same
# company on both sides; the buyer is matched by name, so the link is probable, not sure.
METHOD = "builder-cui+town-hall-name"
CONFIDENCE = "probable"

# The match states of a payment.
ONE = "one"  # contracts of a single award notice
SEVERAL = "several"  # more than one notice: the files do not say which
NONE = "none"  # the builder is named by tax ID, and no contract was found
UNNAMED = "unnamed"  # the file names the builder by name only, so nothing can be tied

# Words that say what kind of place a buyer is, not which one.
_KIND = re.compile(
    r"\b(UNITATEA ADMINISTRATIV TERITORIALA|UNITATE ADMINISTRATIV TERITORIALA|UAT|U A T|"
    r"COMUNA|COMUNEI|ORASUL|ORASULUI|ORAS|MUNICIPIUL|MUNICIPIULUI|MUNICIPIU|PRIMARIA|"
    r"PRIMARIEI|CONSILIUL LOCAL AL|CONSILIUL LOCAL|CONSILIUL JUDETEAN|JUDETUL|JUDETULUI|"
    r"JUDET|JUD|AL|A|DE|SAT|SATUL|COM)\b"
)
_COUNTY_BUYER = re.compile(
    r"(UAT |U A T |UNITATEA ADMINISTRATIV TERITORIALA )?(JUDETUL|CONSILIUL JUDETEAN)\b"
)
_BRACKETS = re.compile(r"\(.*?\)|\(.*$")


def _key(name: str, county: str) -> str:
    """A place name as it is compared.

    'STALPENI ARGES' in Argeș is Stâlpeni. The two spellings of one sound ('Bârzava',
    'Bîrzava') and a missing space ('Poiana Mărului', 'Poianamarului') must not matter.
    """
    name = re.sub(r"\s+", " ", _KIND.sub(" ", name)).strip()
    if county and name.endswith(" " + county):
        name = name[: -len(county)].strip()
    return re.sub(r"[AI]", "A", name.replace(" ", ""))


def payment_place(town_hall: str | None, county: str) -> tuple[bool, str]:
    """(is it the county itself, the place) for a beneficiary as the ministry names it:
    'TĂUTEU', or 'Județul ALBA prin Consiliul Județean' for a county council.
    """
    name = plain(town_hall)
    if name.startswith("JUDETUL"):
        return True, _key(county, "")
    return False, _key(name, county)


def buyer_place(buyer: str | None, county: str) -> tuple[bool, str]:
    """The same for a buyer as SEAP names it, read as a buyer of `county`:
    'COMUNA STALPENI ARGES', 'Comuna Sanzieni Covasna (Primaria Sanzieni)', 'JUDETUL ALBA'.
    """
    name = plain(_BRACKETS.sub(" ", buyer or ""))
    if _COUNTY_BUYER.match(name):
        return True, _key(re.sub(r"\bPRIN CONSILIUL.*$", "", name), "")
    key = _key(name, county)
    # 'COMUNA (PRIMARIA JILAVELE)': the name is only between the brackets.
    return False, key or _key(plain(buyer), county)


def _candidates(session: Session) -> dict[int, list[tuple[int, str | None]]]:
    """For each builder, its contracts as (id, buyer). A contract is in every export
    published after it, so only its newest copy is taken.
    """
    newest = (
        select(func.max(ExportContract.id))
        .group_by(
            ExportContract.supplier_cui,
            ExportContract.notice_no,
            ExportContract.contract_no,
            ExportContract.contract_date,
            ExportContract.buyer_text,
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(ExportContract.supplier_cui, ExportContract.id, ExportContract.buyer_text)
        .where(ExportContract.id.in_(newest))
        .order_by(ExportContract.supplier_cui, ExportContract.id)
    )
    return {
        builder: [(contract_id, buyer) for _, contract_id, buyer in group]
        for builder, group in groupby(rows, key=lambda row: row[0])
    }


def link(session: Session) -> int:
    """Build the links between payments and export contracts again; returns how many.

    Run after either side changes: the contracts read from an export are replaced as a
    whole, which takes their links with them. The caller commits.
    """
    candidates = _candidates(session)
    payments = session.execute(
        select(
            PniasPayment.id, PniasPayment.builder_cui, PniasPayment.town_hall, PniasPayment.county
        ).where(PniasPayment.builder_cui.is_not(None))
    )
    links = [
        {
            "payment_id": payment_id,
            "contract_id": contract_id,
            "method": METHOD,
            "confidence": CONFIDENCE,
        }
        for payment_id, builder, town_hall, county in payments
        for contract_id, buyer in candidates.get(builder, ())
        if buyer_place(buyer, county) == payment_place(town_hall, county)
    ]
    session.execute(delete(PniasLink))
    if links:
        session.execute(insert(PniasLink), links)
    session.flush()
    return len(links)


def notices_linked() -> ColumnElement[int]:
    """How many award notices a payment is tied to, as a correlated count.

    Contracts are counted by their notice: one notice can hold several contracts of a
    project (lots), and that is still one answer to "which procedure paid for this".
    """
    return (
        select(func.count(func.coalesce(ExportContract.notice_no, "").distinct()))
        .join(PniasLink, PniasLink.contract_id == ExportContract.id)
        .where(PniasLink.payment_id == PniasPayment.id)
        .correlate(PniasPayment)
        .scalar_subquery()
    )


def state() -> ColumnElement[str]:
    """The match state of a payment."""
    linked = notices_linked()
    return case(
        (PniasPayment.builder_cui.is_(None), UNNAMED),
        (linked == 0, NONE),
        (linked == 1, ONE),
        else_=SEVERAL,
    )


def projects() -> Subquery:
    """One row per project: its latest payment's description of it, what was paid in all,
    and its match state.

    A project is tied to one notice when every payment of it that could be tied points
    to the same one. Payments from files without tax IDs take no part, so a project is
    `unnamed` only when none of its payments names the builder by tax ID.
    """
    latest = (
        select(PniasPayment)
        .ext(distinct_on(PniasPayment.project_id))
        .order_by(PniasPayment.project_id, PniasPayment.id.desc())
        .subquery("latest")
    )
    totals = (
        select(
            PniasPayment.project_id,
            func.count().label("payments"),
            func.sum(PniasPayment.amount).label("paid"),
            func.count(PniasPayment.builder_cui).label("named"),
        )
        .group_by(PniasPayment.project_id)
        .subquery("totals")
    )
    linked = (
        select(
            PniasPayment.project_id,
            func.count(func.coalesce(ExportContract.notice_no, "").distinct()).label("notices"),
        )
        .join(PniasLink, PniasLink.payment_id == PniasPayment.id)
        .join(ExportContract, ExportContract.id == PniasLink.contract_id)
        .group_by(PniasPayment.project_id)
        .subquery("linked")
    )
    notices = func.coalesce(linked.c.notices, 0)
    return (
        select(
            latest,
            totals.c.payments,
            totals.c.paid,
            case(
                (totals.c.named == 0, UNNAMED),
                (notices == 0, NONE),
                (notices == 1, ONE),
                else_=SEVERAL,
            ).label("match"),
        )
        .join(totals, totals.c.project_id == latest.c.project_id)
        .outerjoin(linked, linked.c.project_id == latest.c.project_id)
        .subquery("project")
    )
