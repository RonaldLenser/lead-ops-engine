"""Health probes. Unversioned on purpose: they belong to the infrastructure, not the API.

/healthz (liveness): "is the process up?" It never touches the database, so
a slow database cannot get an otherwise healthy container restarted.

/readyz (readiness): "can this instance serve real traffic?" It returns 200
only when the database answers within a short timeout AND its migrations are
at the revision this code expects. Otherwise 503, so traffic is held back
instead of failing on a missing table after a deploy that skipped migrations.
"""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from leadops import __version__
from leadops.api.deps import EngineDep, SettingsDep
from leadops.db.schema import MigrationState, check_database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    database: Literal["ok", "unreachable"]
    migrations: MigrationState


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/readyz",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def readyz(engine: EngineDep, settings: SettingsDep, response: Response) -> ReadyResponse:
    result = await check_database(engine, timeout_seconds=settings.readiness_timeout_seconds)
    ready = result.reachable and result.migrations == "current"
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if ready else "unavailable",
        database="ok" if result.reachable else "unreachable",
        migrations=result.migrations,
    )
