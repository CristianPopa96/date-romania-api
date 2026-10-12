"""Payments of the Anghel Saligny investment programme (PNIAS), from the ministry's files
on data.gov.ro.

One file per batch of payments, each with a sheet for roads, water and sewage and one for
gas. A row is a settlement request the ministry paid: the town hall, the project, the
amount, the designer and the builder. Layouts differ from file to file.
"""

from date_romania.collectors.pnias.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
