"""The Finance Ministry's list of public entities ("Lista entităților publice").

An `.xls` on the ministry's budget reports portal, refreshed every month: every public
entity with its county, the UAT it works in and the institutions that fund it. Its link
is read from the portal's "Alte Rapoarte" page, which needs no captcha.
"""

from date_romania.collectors.public_entities.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
