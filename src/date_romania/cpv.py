"""CPV codes the procurement law names. Shared by the model, which stores the fact on each
direct purchase, and by `money`, which holds the limits.
"""

# The social and other specific services of Annex 2 (health, social, education, culture,
# hotels and restaurants, legal, security, postal...) have no direct purchase limit: under
# 3,701,850 lei the buyer follows its own procedure (art. 7(1)(d) and art. 111). They are
# told by CPV code, whatever type the buyer filed, and are never above a limit (Crispy,
# 22.10.2026). The ranges of the annex, first eight digits, both ends included; two codes
# printed wrong in the law are read as the directive's Annex XIV gives them (55520000,
# 79430000).
ANNEX_2_CPV = (
    ("50116510", "50116510"),
    ("55100000", "55410000"),
    ("55510000", "55524000"),
    ("64000000", "64122000"),
    ("71550000", "71550000"),
    ("75000000", "75000000"),
    ("75100000", "75131000"),
    ("75200000", "75252000"),
    ("75300000", "75340000"),
    ("79100000", "79140000"),
    ("79430000", "79430000"),
    ("79611000", "79611000"),
    ("79622000", "79622000"),
    ("79624000", "79625000"),
    ("79700000", "79723000"),
    ("79950000", "79956000"),
    ("79995000", "79995200"),
    ("80000000", "80660000"),
    ("85000000", "85323000"),
    ("92000000", "92700000"),
    ("98000000", "98000000"),
    ("98113100", "98113100"),
    ("98120000", "98120000"),
    ("98130000", "98133110"),
    ("98200000", "98200000"),
    ("98500000", "98500000"),
    ("98513000", "98514000"),
    ("98900000", "98910000"),
)


def is_annex_2(cpv_code: str | None) -> bool:
    """Whether a CPV code is one of the services of Annex 2."""
    head = (cpv_code or "")[:8]
    return len(head) == 8 and any(low <= head <= high for low, high in ANNEX_2_CPV)


def annex_2_sql(column: str) -> str:
    """The same rule in SQL, over a column holding a CPV code, for a generated column."""
    head = f'left({column}, 8) COLLATE "C"'
    ranges = " OR ".join(f"{head} BETWEEN '{low}' AND '{high}'" for low, high in ANNEX_2_CPV)
    return f"coalesce({ranges}, false)"
