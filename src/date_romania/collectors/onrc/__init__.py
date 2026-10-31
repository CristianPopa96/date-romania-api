"""The trade register (ONRC): every legal person registered in Romania, from the editions
data.gov.ro publishes about monthly; one is read about once a quarter. Natural persons are
never read. After a load the link rules run again: the register ties beneficiaries named
without a tax ID.
"""

from date_romania.collectors.onrc.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
