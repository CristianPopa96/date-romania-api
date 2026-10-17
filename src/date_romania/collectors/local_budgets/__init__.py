"""Local budgets and population, from the Ministry of Development's dataset on
data.gov.ro ("Politici fiscale și bugetare locale").

One workbook a year with the executed budget of every UAT and county council (revenue by
source, spending by title and by chapter), and one workbook a year with the population
of every UAT. Both name a UAT by its SIRUTA code.
"""

from date_romania.collectors.local_budgets.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
