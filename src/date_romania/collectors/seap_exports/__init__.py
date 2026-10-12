"""SEAP's quarterly contract exports ("Contracte"), published by ADR on data.gov.ro.

One dataset per year since 2021 and one file per quarter, each with every contract
published in SEAP in that quarter: 3.6 million rows in all. Six layouts and four file
formats in six years. Only the contracts of the companies we ask for are kept; the files
themselves stay whole in the raw store.
"""

from date_romania.collectors.seap_exports.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
