"""The Anghel Saligny programme: tying a payment to the SEAP contract it settles.

The payment files name the builder by tax ID and the town hall by name only; SEAP names
both. A payment is tied to the works contracts its builder won from a buyer whose name
is that town hall's, unless an export puts that buyer in another county. The rule is
written once, here: the collectors build the links with it and the API reads them.
"""

import re

from sqlalchemy import ColumnElement, Subquery, case, delete, func, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from date_romania.collectors.sheets import plain
from date_romania.models import ExportBuyer, ExportContract, PniasLink, PniasPayment

# How a payment was tied to a contract, and how sure the tie is. The builder is the same
# company on both sides, by tax ID. The buyer is matched by name, so no link is sure:
#   probable  an export says the buyer is in the payment's county, or no other buyer in
#             SEAP's exports carries that name
#   possible  other buyers carry the same name, and nothing says which county this one is in
BY_COUNTY = "builder-cui+town-hall-name+county"
BY_ONLY_NAME = "builder-cui+only-town-hall-of-that-name"
BY_NAME = "builder-cui+town-hall-name"
PROBABLE, POSSIBLE = "probable", "possible"

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


def _candidates(session: Session) -> dict[int, list[tuple[int, int | None, str | None]]]:
    """For each builder, its works contracts as (id, buyer CUI, buyer name).

    A contract is in every export published after it, so only its latest copy is taken.
    The programme pays for works: a services or supply contract between the same two
    (snow clearing, a pump) is not what a payment settles. A row whose export gives no
    contract type is kept.
    """
    works = (
        ExportContract.contract_type.is_(None)
        | (func.lower(ExportContract.contract_type) == "lucrari")
        | ExportContract.cpv_code.like("45%")
    )
    rows = session.execute(
        select(
            ExportContract.supplier_cui,
            ExportContract.notice_no,
            ExportContract.contract_no,
            ExportContract.contract_date,
            ExportContract.id,
            ExportContract.buyer_cui,
            ExportContract.buyer_text,
        )
        .where(ExportContract.supplier_cui.is_not(None), works)
        .order_by(ExportContract.notice_date, ExportContract.id)
    )
    latest: dict[tuple, tuple] = {}
    for builder, notice, number, signed, contract_id, buyer_cui, buyer in rows:
        latest[builder, notice, number, signed, buyer] = (builder, contract_id, buyer_cui, buyer)
    candidates: dict[int, list[tuple[int, int | None, str | None]]] = {}
    for builder, contract_id, buyer_cui, buyer in latest.values():
        candidates.setdefault(builder, []).append((contract_id, buyer_cui, buyer))
    return candidates


class _Buyers:
    """Every buyer SEAP's exports name, to tell whether a town hall's name is one buyer's
    alone, and which county a buyer is in where an export says so."""

    def __init__(self, session: Session) -> None:
        self._rows = session.execute(select(ExportBuyer.cui, ExportBuyer.name)).all()
        self.county = dict(
            session.execute(
                select(ExportBuyer.cui, ExportBuyer.county).where(ExportBuyer.county.is_not(None))
            ).all()
        )
        self._named: dict[str, dict[tuple[bool, str], set[int]]] = {}

    def named(self, place: tuple[bool, str], county: str) -> set[int]:
        """The buyers whose name, read as a buyer of `county`, is this place."""
        if county not in self._named:
            index: dict[tuple[bool, str], set[int]] = {}
            for cui, name in self._rows:
                index.setdefault(buyer_place(name, county), set()).add(cui)
            self._named[county] = index
        return self._named[county].get(place, set())


def _evidence(
    buyers: _Buyers, buyer_cui: int | None, place: tuple[bool, str], county: str
) -> tuple[str, str] | None:
    """How a buyer whose name fits was told to be the payment's town hall, as (method,
    confidence); None when an export puts the buyer in another county.

    Many communes share a name. The name alone is enough only when a single buyer in
    all of SEAP's exports carries it.
    """
    known = buyers.county.get(buyer_cui)
    if known:
        return (BY_COUNTY, PROBABLE) if known == county else None
    if len(buyers.named(place, county)) <= 1:
        return BY_ONLY_NAME, PROBABLE
    return BY_NAME, POSSIBLE


def link(session: Session) -> int:
    """Build the links between payments and export contracts again; returns how many.

    Run after either side changes: the contracts read from an export are replaced as a
    whole, which takes their links with them. The caller commits.
    """
    candidates = _candidates(session)
    buyers = _Buyers(session)
    payments = session.execute(
        select(
            PniasPayment.id, PniasPayment.builder_cui, PniasPayment.town_hall, PniasPayment.county
        ).where(PniasPayment.builder_cui.is_not(None))
    )
    links = []
    for payment_id, builder, town_hall, county in payments:
        place = payment_place(town_hall, county)
        for contract_id, buyer_cui, buyer in candidates.get(builder, ()):
            if buyer_place(buyer, county) != place:
                continue
            evidence = _evidence(buyers, buyer_cui, place, county)
            if evidence:
                links.append(
                    {
                        "payment_id": payment_id,
                        "contract_id": contract_id,
                        "method": evidence[0],
                        "confidence": evidence[1],
                    }
                )
    session.execute(delete(PniasLink))
    if links:
        session.execute(insert(PniasLink), links)
    session.flush()
    return len(links)


def only_possible() -> ColumnElement[bool]:
    """True for a payment tied to contracts by links that are all only possible."""
    links = select(PniasLink.confidence).where(PniasLink.payment_id == PniasPayment.id)
    return (
        links.exists()
        & ~links.where(PniasLink.confidence != POSSIBLE).correlate(PniasPayment).exists()
    )


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
