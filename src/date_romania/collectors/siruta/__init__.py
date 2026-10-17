"""SIRUTA, the national list of places from the statistics office (INS), on data.gov.ro.

One CSV for every edition, twice a year: every county, UAT and village with its code,
the place it belongs to and its kind. The other place sources are joined through it.
"""

from date_romania.collectors.siruta.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
