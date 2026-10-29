"""Every project of every programme held, as one list, and how far its money's road is
followed (design D22, round 13).

A project is money earmarked for one purpose by someone above the one who spends it:
an Anghel Saligny project (the ministry's payments to a town hall), a PNRR financing
contract, a cohesion project (SMIS). Its road has seven steps: funder, programme or
measure, financing contract, beneficiary, payments, purchases, companies. The first four
are what every programme publishes; the last three are followed only where the data
holds them:

- payments: Anghel Saligny always (its projects come from payments); PNRR when the
  payments name the beneficiary and a measure it has one contract on; cohesion when the
  list gives an amount paid, or Health its payments.
- purchases: a SEAP record tied to the project (`pnias_link`, `eu_seap_link`).
- companies: a tied record names who won it.

A step we cannot follow while a later one is followed is the project's `gap`: PNRR
payments on a measure where the beneficiary has several contracts ("Nu putem spune"), or
purchases tied to a project whose payments are not published.

Text is written with valid personal codes masked, so neither the list nor its search ever
reads one.

`build()` writes the `project` table again from what is held; the link builders that
change a road (`pnias_links.link()`, `eu_seap_links.link()`) run it last.
"""

import difflib
import re
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from date_romania import eu_programmes, pnias_links
from date_romania.counties import CODES
from date_romania.models import (
    AwardContract,
    AwardWinner,
    DirectPurchase,
    EuProject,
    EuProjectPayment,
    EuSeapLink,
    Place,
    PnrrContract,
    PnrrContractLine,
    PnrrPayment,
    Project,
)
from date_romania.personal_id import mask_cnp
from date_romania.text import plain

AS, PNRR, COHESION = "anghel_saligny", "pnrr", "cohesion"
KINDS = (AS, PNRR, COHESION)

# How far a road is followed, in the order of its steps.
BENEFICIARY, PAYMENTS, PURCHASES, COMPANIES = "beneficiary", "payments", "purchases", "companies"
REACHES = (BENEFICIARY, PAYMENTS, PURCHASES, COMPANIES)

IN_PROGRESS, FINISHED = "in_progress", "finished"

_CODE_BY_NAME = {name: code for code, name in CODES.items()}
# Words the lists write for a project of the whole country: no county.
_NATIONAL = {"RO", "ROMANIA", "NATIONAL", "NIVEL NATIONAL"}


def county_codes(written: str | None) -> list[str]:
    """The counties a programme names, as codes: 'Arad, Hunedoara' is ['AR', 'HD'].

    Lists write a county as its code, its name in any case, with or without diacritics,
    and sometimes with a letter lost ('CONSTANA'); several are split by commas or spaces.
    A word that is no county, or names the whole country, gives none.
    """
    codes: list[str] = []
    for part in re.split(r"[,;/]|\bsi\b", plain(written)):
        part = re.sub(r"^(MUNICIPIUL|JUDETUL|JUD)\b", "", part.strip()).strip()
        if not part or part in _NATIONAL:
            continue
        found = _county(part)
        if found is None:
            # 'BRAILA BUZAU': names written one after another.
            found_each = [_county(" ".join(w)) for w in _runs(part.split())]
            codes.extend(code for code in found_each if code)
        else:
            codes.append(found)
    return list(dict.fromkeys(codes))


def _county(word: str) -> str | None:
    if word in CODES:
        return word
    if word in _CODE_BY_NAME:
        return _CODE_BY_NAME[word]
    close = difflib.get_close_matches(word, _CODE_BY_NAME, n=1, cutoff=0.85)
    return _CODE_BY_NAME[close[0]] if close else None


def _runs(words: list[str]):
    """Split words into county names, the longest first: 'SATU MARE CLUJ'."""
    i = 0
    while i < len(words):
        for size in (3, 2, 1):
            chunk = words[i : i + size]
            if len(chunk) == size and " ".join(chunk) in _CODE_BY_NAME:
                yield chunk
                i += size
                break
        else:
            yield words[i : i + 1]
            i += 1


def _reach(payments: bool, purchases: bool, companies: bool) -> str:
    if companies:
        return COMPANIES
    if purchases:
        return PURCHASES
    return PAYMENTS if payments else BENEFICIARY


def _road(payments: bool, purchases: bool, companies: bool, shared: bool = False) -> dict:
    """How far a project's road is followed, and the step it cannot follow: `shared` when its
    payments are on a measure it has several contracts on."""
    reach = _reach(payments, purchases, companies)
    unfollowed = not payments and reach in (PURCHASES, COMPANIES)
    return {"reach": reach, "gap": PAYMENTS if shared or unfollowed else None}


def _anghel_saligny(session: Session) -> list[dict]:
    project = pnias_links.projects()
    town_halls = dict(
        session.execute(
            select(Place.siruta, Place.town_hall_cui).where(Place.town_hall_cui.is_not(None))
        ).all()
    )
    tied = (pnias_links.ONE, pnias_links.SEVERAL)
    return [
        {
            "kind": AS,
            "key": each["project_id"],
            "programme": "AS",
            "title": each["investment"],
            "number": each["ministry_contract_no"],
            "beneficiary_cui": town_halls.get(each["siruta"]),
            "beneficiary_name": each["town_hall"],
            "natural_person": False,
            "counties": county_codes(each["county"]),
            "value": each["total_value"],
            "status": FINISHED if plain(each["state"]) == "FINALIZATA" else None,
            "status_written": each["state"],
            # A project is held because it was paid; the contract is found from the builder.
            **_road(True, each["match"] in tied, each["match"] in tied),
        }
        for each in session.execute(select(project)).mappings()
    ]


def _seap_reach(session: Session, column) -> tuple[set[int], set[int]]:
    """The projects with a tied SEAP record, and those whose tied record names a winner."""
    tied = set(session.scalars(select(column).where(column.is_not(None)).distinct()))
    won_notice = (
        select(column)
        .join(AwardContract, AwardContract.notice_id == EuSeapLink.notice_id)
        .join(AwardWinner, AwardWinner.contract_id == AwardContract.id)
        .where(column.is_not(None))
    )
    won_purchase = (
        select(column)
        .join(DirectPurchase, DirectPurchase.id == EuSeapLink.purchase_id)
        .where(column.is_not(None), DirectPurchase.supplier_cui.is_not(None))
    )
    won = set(session.scalars(won_notice.union(won_purchase)))
    return tied, won


def _pnrr(session: Session) -> list[dict]:
    lines: dict[int, list[PnrrContractLine]] = defaultdict(list)
    for line in session.scalars(select(PnrrContractLine)):
        lines[line.contract_id].append(line)
    paid = set(
        session.scalars(select(PnrrPayment.contract_id).where(PnrrPayment.contract_id.is_not(None)))
    )
    # Payments that name the beneficiary and a measure it has several contracts on.
    shared = set(
        session.execute(
            select(PnrrPayment.beneficiary_cui, PnrrPayment.measure_code)
            .where(PnrrPayment.contract_id.is_(None), PnrrPayment.contracts_on_measure > 1)
            .distinct()
        ).all()
    )
    tied, won = _seap_reach(session, EuSeapLink.pnrr_contract_id)
    rows = []
    for contract in session.scalars(select(PnrrContract)):
        own = lines.get(contract.id, [])
        # A contract over several measures: its status only where they all agree.
        written = own[0].status if len({plain(line.status) for line in own}) == 1 else None
        status = None
        if written:
            status = FINISHED if plain(written) == "FINALIZAT" else IN_PROGRESS
        totals = [line.total for line in own if line.total is not None]
        on_shared = any((contract.beneficiary_cui, line.measure_code) in shared for line in own)
        rows.append(
            {
                "kind": PNRR,
                "key": contract.id,
                "programme": "PNRR",
                "title": contract.title,
                "number": contract.number,
                "beneficiary_cui": contract.beneficiary_cui,
                # A natural person is never named (Crispy, 22.10.2026).
                "beneficiary_name": None if contract.natural_person else contract.beneficiary_name,
                "natural_person": contract.natural_person,
                "counties": county_codes(contract.county),
                "value": sum(totals, Decimal(0)) if totals else None,
                "status": status,
                "status_written": written,
                **_road(
                    contract.id in paid,
                    contract.id in tied,
                    contract.id in won,
                    shared=on_shared and contract.id not in paid,
                ),
            }
        )
    return rows


def _cohesion(session: Session) -> list[dict]:
    dated = set(session.scalars(select(EuProjectPayment.smis).distinct()))
    tied, won = _seap_reach(session, EuSeapLink.smis)
    return [
        {
            "kind": COHESION,
            "key": project.smis,
            "programme": project.programme,
            "title": project.title,
            "number": None,
            "beneficiary_cui": project.entity_cui,
            "beneficiary_name": project.beneficiary_name,
            "natural_person": False,
            "counties": county_codes(project.county),
            "value": project.total_value,
            "status": eu_programmes.status(project.status),
            "status_written": project.status,
            **_road(
                bool(project.paid) or project.smis in dated,
                project.smis in tied,
                project.smis in won,
            ),
        }
        for project in session.scalars(select(EuProject))
    ]


def _masked(row: dict) -> dict:
    for field in ("title", "number", "beneficiary_name"):
        row[field] = mask_cnp(row[field], checked=True)
    return row


def build(session: Session) -> int:
    """Write every project again from what is held; returns how many. The caller commits."""
    rows = [
        _masked(row) for row in (*_anghel_saligny(session), *_pnrr(session), *_cohesion(session))
    ]
    session.execute(delete(Project))
    if rows:
        session.execute(insert(Project), rows)
    session.flush()
    return len(rows)
