"""EU projects: tying a SEAP award notice or direct purchase to the project that pays for it.

SEAP has no field for the project. A buyer writes it, when it does, in free text: a
notice's title, its project field or a contract's title; a purchase's name or
description. Two rules read that text; neither tie is sure, since the text is the buyer's
own and nothing checks it:
  probable  the text cites the SMIS code of a cohesion project held ('cod SMIS 341497').
            The buyer is not checked: a partner buys for the project as well as its lead.
  probable  the text cites a financing contract number ('contract de finanțare nr.
            12321/26.08.2024'), and that is the number of one PNRR contract of the buyer
            itself. A number alone is not unique: several beneficiaries use the same ones.
  probable  the text names the PNRR, cites no number that decides, and the buyer has one
            PNRR contract on what the text cites: the component ('C10', 'Componenta
            15'), narrowed by the investment ('I3', 'Investiția 6') when that leaves
            some; with neither cited, the buyer's only PNRR contract. As a PNRR payment
            belongs to a contract only when its beneficiary has one on the measure.
The rules are written once, here: `dr link eu-seap` builds every link again, the
collectors of either side run it after a load, and the API reads what it stored.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import delete, func, insert, literal_column, or_, select
from sqlalchemy.orm import Session

from date_romania import money, projects
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    DirectPurchase,
    DirectPurchaseDetail,
    EuProject,
    EuSeapLink,
    PnrrContract,
    PnrrContractLine,
)

# How a SEAP record was tied, and how sure the tie is (see above).
BY_SMIS = "smis-in-text"
BY_FINANCING_NUMBER = "financing-number+buyer"
BY_PNRR_MEASURE = "pnrr-measure+buyer"
PROBABLE = "probable"

# 'SMIS 341497', 'cod SMIS: 331827', 'MySMIS2014 cod 120063', 'cod SMIS 2014+ 118001'.
_SMIS = re.compile(r"SMIS(?:\s*20(?:14|21)\+?)?\D{0,20}?(\d{6})(?!\d)", re.IGNORECASE)
# 'contract de finanțare nr. 12321/26.08.2024', 'contractului de finantare 2491DOT'. The
# number starts right after the words, and holds a digit.
_FINANCING = re.compile(
    r"contract(?:ul|ului)?\s+de\s+finan[tţț][aăâ]re\s*(?:nr\.?|num[aă]r(?:ul)?)?\s*[:.]?\s*"
    r"([0-9A-Z][0-9A-Z._/-]*)",
    re.IGNORECASE,
)
# 'PNRR', 'Planul Național de Redresare și Reziliență', 'PNRR/2022/C10/I3', 'NRR/2022/C10'.
_PNRR = re.compile(r"PNRR|redresare|(?<!\w)NRR/", re.IGNORECASE)
# The component and the investment of a measure, as buyers write them: 'C10', 'C 5',
# 'Componenta 15', 'Componenta C10'; 'I3', 'I.3', 'Investiția 6'. A letter or digit right
# before is part of another word ('și 2' is not an investment).
_COMPONENT = re.compile(r"(?<!\w)(?:Componenta\s*(?:C\s*)?|C\s?)(\d{1,2})(?!\d)", re.IGNORECASE)
_INVESTMENT = re.compile(r"(?<!\w)(?:Investi[tţț]i[ae]i?|I)\s*\.?\s*(\d{1,2})(?!\d)", re.IGNORECASE)
# What a text must hold for any rule, to read only those notices and purchases from the
# database.
_HINT = "smis|finan[tţț][aăâ]re|pnrr|redresare|nrr/"


def smis_codes(text: str) -> list[int]:
    """The SMIS codes a text cites, in its order."""
    return [int(code) for code in _SMIS.findall(text)]


def financing_numbers(text: str) -> list[str]:
    """The financing contract numbers a text cites, as written."""
    return [number for number in _FINANCING.findall(text) if any(c.isdigit() for c in number)]


def _number_key(number: str) -> str:
    return re.sub(r"\s+", "", number).upper().rstrip("./-")


def same_number(cited: str, held: str) -> bool:
    """True when a number cited in SEAP is a PNRR contract's: the same, or the same before
    the first '/' (the rest is usually a date, written in many ways: '12560/04.10.2023' is
    contract 12560), when that part is long enough to mean something."""
    cited, held = _number_key(cited), _number_key(held)
    if cited == held:
        return True
    head = cited.split("/")[0]
    return head == held.split("/")[0] and len(head) >= 3 and any(c.isdigit() for c in head)


def _pnrr_contract(cited: str, contracts: list[tuple[int, str]]) -> int | None:
    """The one contract of the buyer a cited number names, or None when none or several
    do and an exact number does not decide."""
    found = [(id_, number) for id_, number in contracts if same_number(cited, number)]
    if len(found) > 1:
        found = [
            (id_, number) for id_, number in found if _number_key(number) == _number_key(cited)
        ]
    return found[0][0] if len(found) == 1 else None


def measures_cited(text: str) -> tuple[set[str], set[str]]:
    """The PNRR components and investments a text cites, as numbers: ({'10'}, {'3'})."""
    return set(_COMPONENT.findall(text)), set(_INVESTMENT.findall(text))


def _measure_parts(code: str) -> tuple[str, str | None]:
    """'C10.I3.a' is component '10', investment '3'; a reform ('C5.R1') has no investment."""
    component, *rest = code.split(".")
    investment = rest[0] if rest and rest[0].startswith("I") else None
    return component[1:], re.sub(r"\D", "", investment) if investment else None


def _pnrr_by_measure(text: str, contracts: list[tuple[int, set[str]]]) -> tuple[int, str] | None:
    """The one PNRR contract of the buyer on what a text cites, with the measure that
    decided ('C10.I3'), or 'PNRR' when the buyer has a single contract and the text names
    no measure; None when none or several fit."""
    components, investments = measures_cited(text)

    def fits(code: str, investment_too: bool) -> bool:
        component, investment = _measure_parts(code)
        if components and component not in components:
            return False
        return not investment_too or investment in investments

    found = contracts
    if components:
        found = [each for each in found if any(fits(code, False) for code in each[1])]
    if investments:
        narrowed = [each for each in found if any(fits(code, True) for code in each[1])]
        # With no component, an investment number alone must fit, or nothing is tied.
        if narrowed or not components:
            found = narrowed
    if len(found) != 1:
        return None
    id_, codes = found[0]
    if not components:
        return id_, "PNRR"
    decided = sorted(code for code in codes if fits(code, bool(investments)))
    return id_, (decided or sorted(code for code in codes if fits(code, False)))[0]


def _notices(session: Session) -> Iterable[tuple[int, int | None, str]]:
    titles = (
        select(
            AwardContract.notice_id,
            func.string_agg(AwardContract.title, literal_column("' '")).label("titles"),
        )
        .group_by(AwardContract.notice_id)
        .subquery()
    )
    rows = session.execute(
        select(
            AwardNotice.id,
            AwardNotice.buyer_cui,
            AwardNotice.title,
            AwardNoticeDetail.eu_project,
            titles.c.titles,
        )
        .outerjoin(AwardNoticeDetail, AwardNoticeDetail.notice_id == AwardNotice.id)
        .outerjoin(titles, titles.c.notice_id == AwardNotice.id)
        .where(
            or_(
                AwardNotice.title.op("~*")(_HINT),
                AwardNoticeDetail.eu_project.op("~*")(_HINT),
                titles.c.titles.op("~*")(_HINT),
            )
        )
    )
    for id_, buyer, *texts in rows:
        yield id_, buyer, " ".join(text for text in texts if text)


def _purchases(session: Session) -> Iterable[tuple[int, int | None, str]]:
    """Accepted purchases only: the others bought nothing."""
    rows = session.execute(
        select(
            DirectPurchase.id,
            DirectPurchase.buyer_cui,
            DirectPurchase.name,
            DirectPurchaseDetail.description,
        )
        .outerjoin(DirectPurchaseDetail, DirectPurchaseDetail.purchase_id == DirectPurchase.id)
        .where(
            money.accepted,
            or_(
                DirectPurchase.name.op("~*")(_HINT),
                DirectPurchaseDetail.description.op("~*")(_HINT),
            ),
        )
    )
    for id_, buyer, *texts in rows:
        yield id_, buyer, " ".join(text for text in texts if text)


def link(session: Session) -> int:
    """Build every link between SEAP records and EU projects again; returns how many.

    Run after either side changes: a project or PNRR contract loaded again takes its links
    with it. The caller commits.
    """
    held = set(session.scalars(select(EuProject.smis)))
    lines: dict[int, set[str]] = defaultdict(set)
    for id_, code in session.execute(
        select(PnrrContractLine.contract_id, PnrrContractLine.measure_code)
    ):
        lines[id_].add(code)
    pnrr: dict[int, list[tuple[int, str]]] = defaultdict(list)
    on_measures: dict[int, list[tuple[int, set[str]]]] = defaultdict(list)
    for id_, cui, number in session.execute(
        select(PnrrContract.id, PnrrContract.beneficiary_cui, PnrrContract.number).where(
            PnrrContract.beneficiary_cui.is_not(None)
        )
    ):
        on_measures[cui].append((id_, lines[id_]))
        if number is not None:
            pnrr[cui].append((id_, number))

    links: dict[tuple[str, int, str, int], dict] = {}
    for record, rows in (("notice_id", _notices(session)), ("purchase_id", _purchases(session))):
        for id_, buyer, text in rows:
            for code in smis_codes(text):
                if code in held:
                    links.setdefault(
                        (record, id_, "smis", code),
                        {record: id_, "smis": code, "cited": str(code), "method": BY_SMIS},
                    )
            for cited in financing_numbers(text) if buyer in pnrr else ():
                contract = _pnrr_contract(cited, pnrr[buyer])
                if contract is not None:
                    links.setdefault(
                        (record, id_, "pnrr_contract_id", contract),
                        {
                            record: id_,
                            "pnrr_contract_id": contract,
                            "cited": cited[:64],
                            "method": BY_FINANCING_NUMBER,
                        },
                    )
            tied = any(key[:2] == (record, id_) for key in links)
            if not tied and buyer in on_measures and _PNRR.search(text):
                found = _pnrr_by_measure(text, on_measures[buyer])
                if found is not None:
                    links[record, id_, "pnrr_contract_id", found[0]] = {
                        record: id_,
                        "pnrr_contract_id": found[0],
                        "cited": found[1],
                        "method": BY_PNRR_MEASURE,
                    }
    session.execute(delete(EuSeapLink))
    rows = [
        {
            "notice_id": None,
            "purchase_id": None,
            "smis": None,
            "pnrr_contract_id": None,
            **each,
            "confidence": PROBABLE,
        }
        for each in links.values()
    ]
    if rows:
        session.execute(insert(EuSeapLink), rows)
    session.flush()
    # A record tied to a project or not changes how far the project's road is followed.
    projects.build(session)
    return len(rows)
