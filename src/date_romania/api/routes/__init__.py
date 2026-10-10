"""Read-only endpoints over the collected data. Every answer names its source."""

from fastapi import APIRouter

from date_romania.api.routes import entities, purchases, rankings, stats

router = APIRouter(prefix="/v1")
for module in (stats, entities, purchases, rankings):
    router.include_router(module.router)
