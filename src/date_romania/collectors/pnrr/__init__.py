"""The Recovery and Resilience Plan (PNRR), from the files MIPE's PNRR dashboard reads.

An edition every two weeks or so, listed in `contains.json`: every financing contract with
its progress, every payment since 2020, the measures, the largest recipients and the plan's
totals, as gzipped JSON. The newest complete edition replaces the one held.
"""

from date_romania.collectors.pnrr.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
