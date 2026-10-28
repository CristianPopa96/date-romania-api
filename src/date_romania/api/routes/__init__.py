"""Endpoints over the collected data, read-only except for a reader's error report.
Every answer about the data names its source."""

from fastapi import APIRouter

from date_romania.api.routes import (
    award_totals,
    awards,
    budget,
    entities,
    eu_beneficiaries,
    eu_projects,
    eu_seap,
    patterns,
    places,
    pnrr,
    programme_project,
    programmes,
    purchase_list,
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
    # Before `purchases`, whose /direct-purchases/{id} would take /direct-purchases/overview.
    purchase_list,
    purchases,
    rankings,
    patterns,
    awards,
    award_totals,
    programmes,
    programme_project,
    pnrr,
    eu_projects,
    eu_seap,
    eu_beneficiaries,
    places,
    reports,
):
    router.include_router(module.router)
