"""Read-only endpoints over the collected data. Every answer names its source."""

from fastapi import APIRouter

from date_romania.api.routes import (
    award_totals,
    awards,
    entities,
    purchases,
    rankings,
    stats,
)

router = APIRouter(prefix="/v1")
for module in (stats, entities, purchases, rankings, awards, award_totals):
    router.include_router(module.router)
