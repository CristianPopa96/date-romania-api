"""EU cohesion projects 2021-2027, from MIPE's map of them (mfe.gov.ro/map2021).

The map holds every contracted project of every 2021-2027 programme, a new edition about
every week. The lists of contracted projects stay the source of the projects they hold;
the map adds those no list holds (the eight regional programmes, Transport, and what a
list leaves out), and gives a list's project the tax ID and UAT the list does not.
"""

from date_romania.collectors.eu_map.run import JOB, SOURCE, collect, load, reparse

__all__ = ["JOB", "SOURCE", "collect", "load", "reparse"]
