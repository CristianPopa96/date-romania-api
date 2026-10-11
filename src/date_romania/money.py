"""What counts as money spent. One place, so the API, rankings and exports add up the same.

Only an accepted direct purchase is money spent. Values are in lei without VAT, as SEAP
publishes them. An accepted purchase published above the legal limit is left out of totals
and reported apart; it is what SEAP publishes, not something we call an error.

A contract from an award notice counts when it is an ordinary or a subsequent contract,
was signed on a day we collected and belongs to a notice still in force. Direct purchases
and contracts are never added together.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, Date, Text, and_, cast, false, func, select
from sqlalchemy.orm import Session

from date_romania.dates import BUCHAREST, day_bounds
from date_romania.models import (
    AwardContract,
    AwardNoticeVersion,
    AwardWinner,
    DirectPurchase,
    JobRun,
)
from date_romania.sources import SEAP_AWARDS

# SEAP's state id for a direct purchase whose offer was accepted.
DIRECT_PURCHASE_ACCEPTED = 7
# Law 98/2016 art. 7(5): a direct purchase must stay under 900,400 lei without VAT for works
# and 270,120 lei for goods and services. We use the works limit for every purchase, as the
# highest value any direct purchase may have: the list does not give the contract type, and
# the CPV code does not tell works from the rest reliably (street lighting works, for one,
# are filed under a goods code).
DIRECT_PURCHASE_LIMIT_RON = Decimal("900400")
DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON = Decimal("270120")

# SEAP's contractType for a contract in an award notice. A framework agreement carries a
# ceiling, not money committed: what is committed under it are its subsequent contracts.
# Totals over award contracts must count kinds 1 and 3 and never add kind 2 to them.
AWARD_CONTRACT = 1
AWARD_FRAMEWORK = 2
AWARD_SUBSEQUENT = 3

accepted = DirectPurchase.state_id == DIRECT_PURCHASE_ACCEPTED
counted = and_(accepted, DirectPurchase.closing_value <= DIRECT_PURCHASE_LIMIT_RON)
above_limit = and_(accepted, DirectPurchase.closing_value > DIRECT_PURCHASE_LIMIT_RON)
# The Romanian calendar day a purchase was finalized on.
day = cast(func.timezone(BUCHAREST.key, DirectPurchase.finalized_at), Date)
value = func.coalesce(func.sum(DirectPurchase.closing_value).filter(counted), 0)

# The columns of a summary over any set of direct purchases.
SUMMARY = (
    func.count().label("purchases"),
    func.count().filter(accepted).label("accepted"),
    value.label("value"),
    func.count().filter(above_limit).label("above_limit"),
    func.coalesce(func.sum(DirectPurchase.closing_value).filter(above_limit), 0).label(
        "above_limit_value"
    ),
    func.min(day).label("first_day"),
    func.max(day).label("last_day"),
)


def is_above_limit(state_id: int | None, closing_value: Decimal | None) -> bool:
    """The same rule as `above_limit`, for one row already read.

    Only an accepted purchase can be above the limit: a refused offer is left out of the
    totals because it was refused, whatever value it carries.
    """
    return (
        state_id == DIRECT_PURCHASE_ACCEPTED
        and closing_value is not None
        and closing_value > DIRECT_PURCHASE_LIMIT_RON
    )


# --- Contracts from award notices ---

_COUNTED_KINDS = (AWARD_CONTRACT, AWARD_SUBSEQUENT)
contract_counted = AwardContract.kind.in_(_COUNTED_KINDS)
contract_value = func.coalesce(func.sum(AwardContract.value_ron), 0)

# SEAP publishes a changed notice under a new id, with every contract again, and withdraws
# the one before. When both were collected, the contracts of the withdrawn one must not be
# counted a second time.
contract_in_force = AwardContract.notice_id.not_in(
    select(AwardNoticeVersion.version_id).where(
        AwardNoticeVersion.version_id != AwardNoticeVersion.notice_id
    )
)

# An association: a contract with more than one winner. SEAP gives one value for the whole
# contract and names no leader, so the value is never split between the members and never
# added to what a member won alone. SEAP can list one company twice among the winners of
# a contract; it is still one winner.
is_association = (
    select(
        func.count(
            func.distinct(
                func.coalesce(cast(AwardWinner.supplier_cui, Text), AwardWinner.supplier_text)
            )
        )
    )
    .where(AwardWinner.contract_id == AwardContract.id)
    .correlate(AwardContract)
    .scalar_subquery()
    > 1
)


def is_counted_contract(kind: int | None) -> bool:
    """The same rule as `contract_counted`, for one row already read."""
    return kind in _COUNTED_KINDS


def contracts_period(session: Session) -> tuple[date, date] | None:
    """The publication days collected for award notices: the latest unbroken run of them.

    A day collected on its own, far from the rest, does not stretch the period over the
    days between, which were never read.

    A notice is published again with every contract it ever had, so the notices of these
    days carry contracts signed years before; for those years we hold only what happened
    to be republished. Totals therefore count the contracts signed inside these days. Even
    that list is incomplete: SEAP publishes many contracts weeks after they are signed.
    """
    starts = session.scalars(
        select(JobRun.period_start)
        .where(JobRun.job == SEAP_AWARDS.key, JobRun.status.in_(("succeeded", "partial")))
        .distinct()
    )
    days = sorted({start.astimezone(BUCHAREST).date() for start in starts}, reverse=True)
    if not days:
        return None
    first = last = days[0]
    for day in days[1:]:
        if first - day > timedelta(days=1):
            break
        first = day
    return first, last


def signed_in(period: tuple[date, date] | None) -> list[ColumnElement[bool]]:
    """Filters for contracts signed from the first to the last day of `period`."""
    if period is None:
        return [false()]
    return [
        AwardContract.contract_date >= day_bounds(period[0])[0],
        AwardContract.contract_date < day_bounds(period[1])[1],
    ]
