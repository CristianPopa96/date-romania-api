"""Endpoints over the collected data, read-only except for a reader's error report.
Every answer about the data names its source."""

from fastapi import APIRouter

from date_romania.api.routes import (
    award_totals,
    awards,
    entities,
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
    purchases,
    rankings,
    awards,
    award_totals,
    programmes,
    programme_project,
    reports,
):
    router.include_router(module.router)
