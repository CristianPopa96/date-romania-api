"""EU cohesion projects, from the managing authorities' lists of contracted projects.

The 2014-2020 lists are files of one data.gov.ro dataset; the 2021-2027 lists of the
national programmes MIPE runs are attached to posts on mfe.gov.ro; the Health programme
keeps its lists and its monthly payments on a page of its own. The newest list of each
programme replaces its projects. The regional programmes 2021-2027 are left out for now
(Crispy, 22.10.2026).
"""

from date_romania.collectors.eu_projects.run import JOB, SOURCE, collect, reparse

__all__ = ["JOB", "SOURCE", "collect", "reparse"]
