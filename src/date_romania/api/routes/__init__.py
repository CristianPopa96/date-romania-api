"""Endpoints over the collected data, read-only except for a reader's error report.
Every answer about the data names its source."""

from fastapi import APIRouter

from date_romania.api.routes import (
    award_totals,
    awards,
    budget,
    entities,
    eu_projects,
    patterns,
    places,
    pnrr,
    programme_project,
    programmes,
    purchases,
    rankings,
    reports,
    stats,
)

router = APIRouter(prefix="/v1")
for module in (
    stats,
    entities,
    budget,
    purchases,
    rankings,
    patterns,
    awards,
    award_totals,
    programmes,
    programme_project,
    pnrr,
    eu_projects,
    places,
    reports,
):
    router.include_router(module.router)
