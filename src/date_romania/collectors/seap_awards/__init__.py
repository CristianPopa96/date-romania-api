"""SEAP contract award notices (anunțuri de atribuire), from the public list on e-licitatie.ro.

The API is unofficial. The list is asked one publication day at a time (a day has a few
hundred notices, the cap is 3,000). The list names the buyer but not the winners, so each
notice costs more requests: one or more for its contracts, one for its detail (financing,
the notice that opened the procedure) and one for its versions (when it first appeared).
"""

from date_romania.collectors.seap_awards.run import (
    JOB,
    SOURCE,
    collect_day,
    collect_details,
    reparse,
)

__all__ = ["JOB", "SOURCE", "collect_day", "collect_details", "reparse"]
