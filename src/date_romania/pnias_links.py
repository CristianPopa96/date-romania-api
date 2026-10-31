"""The Anghel Saligny programme: tying a payment to the SEAP contract it settles.

The payment files name the builder by tax ID and the town hall by name only; SEAP names
both. A payment is tied to the works contracts its builder won from a buyer whose name
is that town hall's, unless an export puts that buyer in another county. The rule is
written once, here: the collectors build the links with it and the API reads them.
"""

import re

from sqlalchemy import ColumnElement, Subquery, case, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from date_romania import register
from date_romania.counties import COUNTIES
from date_romania.eu_links import name_key
from date_romania.models import ExportBuyer, ExportContract, PniasLink, PniasPayment
from date_romania.text import plain

# How a payment was tied to a contract, and how sure the tie is. The builder is the same
# company on both sides, by tax ID. The buyer is matched by name, so no link is sure:
#   probable  an export says the buyer is in the payment's county, or no other buyer in
#             SEAP's exports carries that name
#   possible  other buyers carry the same name, and nothing says which county this one is in
BY_COUNTY = "builder-cui+town-hall-name+county"
BY_ONLY_NAME = "builder-cui+only-town-hall-of-that-name"
BY_NAME = "builder-cui+town-hall-name"
PROBABLE, POSSIBLE = "probable", "possible"
# The older files name the builder without its tax ID. Inside one project, the same name
# is the same company, so such a payment takes the tax ID a newer payment of the project
# gives that name; its link says so, with the same confidence: 'builder-cui-of-project+...'.
OF_PROJECT = "builder-cui-of-project"
# When no payment of the project gives it, the tax ID of the one company in the trade
# register that carries the name, with the same confidence: 'builder-name-in-register+...'.
OF_REGISTER = "builder-name-in-register"
# Where a payment's builder tax ID was found (`PniasPayment.builder_found_by`).
FROM_FILE, FROM_PROJECT, FROM_REGISTER = "file", "project", "register"
_METHOD_OF = {FROM_PROJECT: OF_PROJECT, FROM_REGISTER: OF_REGISTER}

# The match states of a payment.
ONE = "one"  # contracts of a single award notice
SEVERAL = "several"  # more than one notice: the files do not say which
NONE = "none"  # the builder is named by tax ID, and no contract was found
UNNAMED = "unnamed"  # the builder is named without a tax ID that could be found

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
                # A buyer written with another county after its name ('COMUNA VALEA MARE
                # DAMBOVITA') is still a Valea Mare: it is counted under both readings.
                for read_as in (county, *_counties_after(name)):
                    index.setdefault(buyer_place(name, read_as), set()).add(cui)
            self._named[county] = index
        return self._named[county].get(place, set())


def _counties_after(buyer: str | None) -> list[str]:
    """The counties a buyer's name could end with: 'Comuna Slatina Timis' gives Timiș,
    though that commune is in Caraș-Severin and Timiș is part of its name."""
    name = plain(_BRACKETS.sub(" ", buyer or ""))
    return [county for county in COUNTIES if name.endswith(" " + county)]


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
    links = []
    for payment_id, builder, found_by, town_hall, county in _builders(session):
        place = payment_place(town_hall, county)
        for contract_id, buyer_cui, buyer in candidates.get(builder, ()):
            if buyer_place(buyer, county) != place:
                continue
            evidence = _evidence(buyers, buyer_cui, place, county)
            if evidence:
                method = evidence[0]
                if found_by in _METHOD_OF:
                    method = method.replace("builder-cui", _METHOD_OF[found_by], 1)
                links.append(
                    {
                        "payment_id": payment_id,
                        "contract_id": contract_id,
                        "method": method,
                        "confidence": evidence[1],
                    }
                )
    session.execute(delete(PniasLink))
    if links:
        session.execute(insert(PniasLink), links)
    session.flush()
    # A payment tied to a contract or not changes how far its project's road is followed.
    from date_romania import projects  # projects reads this module's projects()

    projects.build(session)
    return len(links)


def _builders(session: Session) -> list[tuple[int, int, str, str | None, str]]:
    """Every payment whose builder's tax ID is found, as (payment, builder, where it was
    found, town hall, county), kept on the payment (`builder_found_cui`, `builder_found_by`).

    The payment's own comes first, then the one a newer payment of the project gives the
    same name, then the one company of the trade register that carries the name, in the
    whole country: a builder works away from its seat, so its county tells nothing."""
    payments = session.execute(
        select(
            PniasPayment.id,
            PniasPayment.project_id,
            PniasPayment.builder_cui,
            PniasPayment.builder_text,
            PniasPayment.town_hall,
            PniasPayment.county,
        )
    ).all()
    named: dict[tuple[int, str], set[int]] = {}
    for _, project, cui, name, *_ in payments:
        if cui is not None and name:
            named.setdefault((project, name), set()).add(cui)
    unnamed = {
        name_key(name)
        for _, project, cui, name, *_ in payments
        if cui is None and name and len(named.get((project, name), ())) != 1
    }
    carriers = register.carriers(session, unnamed)
    found, rows = [], []
    for payment_id, project, cui, name, town_hall, county in payments:
        cuis = named.get((project, name or ""), set())
        in_register = {each for each, _ in carriers.get(name_key(name), ())} if name else set()
        if cui is not None:
            by = FROM_FILE
        elif len(cuis) == 1:
            cui, by = next(iter(cuis)), FROM_PROJECT
        elif len(in_register) == 1:
            cui, by = next(iter(in_register)), FROM_REGISTER
        else:
            by = None
        rows.append({"id": payment_id, "builder_found_cui": cui, "builder_found_by": by})
        if cui is not None:
            found.append((payment_id, cui, by, town_hall, county))
    if rows:
        session.execute(update(PniasPayment), rows)
    return found


def by_own_tax_id(method: str) -> bool:
    """True for a link through the tax ID the payment itself gives its builder."""
    return method.startswith("builder-cui+")


def builders(session: Session) -> set[int]:
    """The tax IDs of every builder found: the companies whose contracts the exports keep.
    Found again by `link()`, so a reparse of the exports follows it."""
    return set(
        session.scalars(
            select(PniasPayment.builder_found_cui)
            .where(PniasPayment.builder_found_cui.is_not(None))
            .distinct()
        )
    )


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
    """The match state of a payment. One with no tax ID of its own is tied only through
    the one its builder is found by: another payment of its project that names the same
    builder with one, or the trade register."""
    linked = notices_linked()
    return case(
        (linked == 1, ONE),
        (linked > 1, SEVERAL),
        (PniasPayment.builder_found_cui.is_(None), UNNAMED),
        else_=NONE,
    )


def projects() -> Subquery:
    """One row per project: its latest payment's description of it, what was paid in all,
    and its match state.

    A project is tied to one notice when every payment of it that could be tied points
    to the same one. Payments whose builder's tax ID is not found take no part, so a
    project is `unnamed` only when none is found for any of its payments.
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
            func.count(PniasPayment.builder_found_cui).label("named"),
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
