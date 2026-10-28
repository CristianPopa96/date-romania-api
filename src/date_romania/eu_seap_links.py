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
The rules are written once, here: `dr link eu-seap` builds every link again, the
collectors of either side run it after a load, and the API reads what it stored.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import delete, func, insert, literal_column, or_, select
from sqlalchemy.orm import Session

from date_romania import money
from date_romania.models import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    DirectPurchase,
    DirectPurchaseDetail,
    EuProject,
    EuSeapLink,
    PnrrContract,
)

# How a SEAP record was tied, and how sure the tie is (see above).
BY_SMIS = "smis-in-text"
BY_FINANCING_NUMBER = "financing-number+buyer"
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
# What a text must hold for either rule, to read only those purchases from the database.
_HINT = "smis|finan[tţț][aăâ]re"


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
    pnrr: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for id_, cui, number in session.execute(
        select(PnrrContract.id, PnrrContract.beneficiary_cui, PnrrContract.number).where(
            PnrrContract.beneficiary_cui.is_not(None), PnrrContract.number.is_not(None)
        )
    ):
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
    return len(rows)
