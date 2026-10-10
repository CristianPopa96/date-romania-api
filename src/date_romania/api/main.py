from fastapi import FastAPI
from pydantic import BaseModel

from date_romania import __version__
from date_romania.api.routes import router
from date_romania.db import database_ok

app = FastAPI(
    title="Date România API",
    version=__version__,
    description="Public, read-only data on Romanian public money. Every record carries its source.",
    license_info={"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
    docs_url="/docs",
    openapi_url="/openapi.json",
)


class Health(BaseModel):
    status: str
    database: str
    version: str


@app.get("/v1/health", tags=["system"])
def health() -> Health:
    db = database_ok()
    return Health(
        status="ok" if db else "degraded",
        database="ok" if db else "unavailable",
        version=__version__,
    )


app.include_router(router)
