"""Endpoints over the collected data, read-only except for a reader's error report.
Every answer about the data names its source."""

from fastapi import APIRouter

from date_romania.api.routes import (
    award_totals,
    awards,
    budget,
    contract_list,
    entities,
    eu_beneficiaries,
    eu_project_list,
    eu_projects,
    eu_seap,
    patterns,
    places,
    pnrr,
    pnrr_contract_list,
    pnrr_contracts,
    programme_list,
    programme_project,
    programmes,
    projects,
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
    contract_list,
    awards,
    award_totals,
    # Before `programmes` and `programme_project`, whose /projects/{id} would take
    # /projects/overview.
    programme_list,
    programmes,
    programme_project,
    pnrr,
    # Before `pnrr_contracts`, whose /contracts/{contract_id} would take /contracts/overview.
    pnrr_contract_list,
    pnrr_contracts,
    # Before `eu_projects`, whose /projects/{smis} would take /projects/overview.
    eu_project_list,
    eu_projects,
    eu_seap,
    eu_beneficiaries,
    projects,
    places,
    reports,
):
    router.include_router(module.router)
