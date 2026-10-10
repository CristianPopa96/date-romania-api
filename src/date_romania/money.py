"""What counts as money spent. One place, so the API, rankings and exports add up the same.

Only an accepted direct purchase is money spent. Values are in lei without VAT, as SEAP
publishes them. An accepted purchase published above the legal limit is left out of totals
and reported apart; it is what SEAP publishes, not something we call an error.
"""

from decimal import Decimal

from sqlalchemy import Date, and_, cast, func

from date_romania.dates import BUCHAREST
from date_romania.models import DirectPurchase

# SEAP's state id for a direct purchase whose offer was accepted.
DIRECT_PURCHASE_ACCEPTED = 7
# Law 98/2016 art. 7(5): a direct purchase must stay under 900,400 lei without VAT for works
# and 270,120 lei for goods and services. We use the works limit for every purchase, as the
# highest value any direct purchase may have: the list does not give the contract type, and
# the CPV code does not tell works from the rest reliably (street lighting works, for one,
# are filed under a goods code).
DIRECT_PURCHASE_LIMIT_RON = Decimal("900400")
DIRECT_PURCHASE_LIMIT_GOODS_SERVICES_RON = Decimal("270120")

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
