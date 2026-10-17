"""ANAF's public register of VAT payers, asked by tax ID.

One POST takes up to 100 tax IDs and answers, for each, its name, registered office
(county and locality), registration state, CAEN code and VAT status. We ask once for
every entity held; the answers are kept whole in the private raw store.
"""

from date_romania.collectors.anaf.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
