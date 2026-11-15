"""Eurostat's spending of the public administration by purpose (COFOG, table
`gov_10a_exp`), for Romania: every year from 2015, for all of the public administration
and for each level of government (central, local, social security), in million lei.

One JSON-stat answer holds it all; Eurostat updates it about once a year and revises past
years, so each new answer replaces the table.
"""

from date_romania.collectors.cofog.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
