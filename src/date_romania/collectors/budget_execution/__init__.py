"""The Finance Ministry's monthly execution of the consolidated general budget (BGC):
revenue and spending from 1 January to each month's end, cash, in million lei, by line
(personnel, goods and services, interest, social assistance, EU and PNRR projects,
capital...) and by budget (state, local, social insurance, health...).

One workbook a month on mfinante.gov.ro (`bgcDDMMYYYY.xlsx`), about four weeks after the
month ends; the same month also comes as PDF and DOC, and the explanatory note and annex 2
(this year against last, consolidated only) as PDF. Only the workbook is read.
"""

from date_romania.collectors.budget_execution.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
