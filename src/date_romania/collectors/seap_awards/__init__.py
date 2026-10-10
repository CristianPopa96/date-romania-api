"""SEAP contract award notices (anunțuri de atribuire), from the public list on e-licitatie.ro.

The API is unofficial. The list is asked one publication day at a time (a day has a few
hundred notices, the cap is 3,000). The list names the buyer but not the winners, so each
notice costs one more request for its contracts.
"""

from date_romania.collectors.seap_awards.run import JOB, SOURCE, collect_day, reparse

__all__ = ["JOB", "SOURCE", "collect_day", "reparse"]
