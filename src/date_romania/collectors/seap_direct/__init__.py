"""SEAP direct purchases (achiziții directe), from the public list on e-licitatie.ro.

The API is unofficial. It returns at most 2,000 rows per query, will not page past them,
and ignores the time of day in its date filters, while a working day has well over 10,000
purchases. So one day is split by the filters that do work until every slice fits.
"""

from date_romania.collectors.seap_direct.run import JOB, SOURCE, collect_day, reparse

__all__ = ["JOB", "SOURCE", "collect_day", "reparse"]
