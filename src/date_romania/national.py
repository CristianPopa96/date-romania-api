"""How the country's official totals are read and set against ours, written once (code
inspection A22, design round 18).

The rule that drives it: a difference between an official figure and ours is computed only
when both measure the same thing over the same period (the GapPanel rule). Otherwise the
two stand side by side, with the reason they differ.
"""

from decimal import ROUND_FLOOR, Decimal

# The Finance Ministry's figures are million lei; the API answers in lei.
MILLION = Decimal(1_000_000)

# The consolidated general budget's column of the execution.
CONSOLIDATED, LOCAL = "consolidated", "local"

# "Pe ce s-a cheltuit": the execution's spending in these groups of lines, largest first,
# then "other" for every line not named, so that the groups add up to the total.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "social_assistance": ("social_assistance",),
    "personnel": ("personnel",),
    "goods_services": ("goods_services",),
    "interest": ("interest",),
    "pnrr_projects": ("pnrr_grants", "pnrr_loans"),
    "capital": ("capital",),
    "eu_projects": ("eu_projects", "eu_projects_2014_2020"),
}
OTHER = "other"

# The lines that add up to total spending, with nothing counted twice: current spending's
# own lines, capital, financial operations and the payments of earlier years recovered.
SPENDING_PARTS = (
    "personnel",
    "goods_services",
    "interest",
    "subsidies",
    "transfers_public",
    "other_transfers",
    "eu_projects",
    "social_assistance",
    "eu_projects_2014_2020",
    "other",
    "pnrr_grants",
    "pnrr_loans",
    "reimbursable",
    "safe",
    "capital",
    "financial_operations",
    "prior_years_recovered",
)

# The SpendingBand: what never goes through procurement (no contract can explain it), what
# can, and the rest. Always in this order.
NOT_PROCUREMENT, PROCUREMENT, REST = "not_procurement", "procurement", "rest"
BAND: dict[str, tuple[str, ...]] = {
    NOT_PROCUREMENT: ("social_assistance", "personnel", "interest"),
    PROCUREMENT: (
        "goods_services",
        "capital",
        "eu_projects",
        "eu_projects_2014_2020",
        "pnrr_grants",
        "pnrr_loans",
    ),
}

# Projects with EU funds and PNRR projects, as the execution names their lines.
EU_PROJECT_LINES = CATEGORIES["eu_projects"]
PNRR_PROJECT_LINES = CATEGORIES["pnrr_projects"]

# Eurostat COFOG: all of public administration, and local government.
ALL_GOVERNMENT, LOCAL_GOVERNMENT = "S13", "S1313"
COFOG_TOTAL = "TOTAL"
DIVISIONS = tuple(f"GF{number:02d}" for number in range(1, 11))

# Our local budget chapters (`local_money.CHAPTERS`) by the COFOG divisions they are
# closest to. Close, not identical: a budget chapter does not always fall in the same
# division.
CHAPTER_DIVISIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "general_services": (("general_services",), ("GF01",)),
    "defence_order": (("defence_order",), ("GF02", "GF03")),
    "economic_affairs": (
        ("economic_affairs", "energy", "agriculture", "transport", "other_economic"),
        ("GF04",),
    ),
    "environment": (("environment",), ("GF05",)),
    "housing": (("housing",), ("GF06",)),
    "health": (("health",), ("GF07",)),
    "culture": (("culture",), ("GF08",)),
    "education": (("education",), ("GF09",)),
    "social": (("social",), ("GF10",)),
}

# Why the figures of a check differ, or do not compare. The site words each.
REASON_LOCAL_SCOPE = "local_scope"  # town halls and county councils only
REASON_CLASSIFICATIONS = "classifications_close"
REASON_CREDITS_YEAR = "credits_for_the_year"  # credits for the year, payments to a file
REASON_CONTRACTS_NOT_PAYMENTS = "contracts_not_payments"
REASON_PAYMENTS_UNDATED = "payments_undated"

# The checks, in the order they are defined; the answer orders them for the table.
LOCAL_BUDGETS, LOCAL_DOMAINS, ANGHEL_SALIGNY, PNRR, EU_FUNDS = (
    "local_budgets",
    "local_domains",
    "anghel_saligny",
    "pnrr",
    "eu_funds",
)


def whole_shares(amounts: list[Decimal]) -> list[int]:
    """Whole percents of the amounts' sum that add up to 100: each share rounded down,
    then the points left go to the largest remainders."""
    total = sum(amounts, Decimal(0))
    if total <= 0:
        return [0 for _ in amounts]
    exact = [amount * 100 / total for amount in amounts]
    shares = [int(share.to_integral_value(ROUND_FLOOR)) for share in exact]
    order = sorted(range(len(amounts)), key=lambda i: exact[i] - shares[i], reverse=True)
    for i in order[: 100 - sum(shares)]:
        shares[i] += 1
    return shares
