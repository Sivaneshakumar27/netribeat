"""Liveness and readiness. Unauthenticated; reveal nothing beyond up/down per dependency."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from netribeat.api_model import ApiModel

router = APIRouter(tags=["Health"])


class Health(ApiModel):
    status: str
    checks: dict[str, str] | None = None


@router.get("/health", response_model=Health, summary="Liveness: the process is up")
async def health() -> Health:
    return Health(status="ok")


@router.get(
    "/health/ready", response_model=Health, summary="Readiness: database and Redis reachable"
)
async def ready(request: Request, response: Response) -> Health:
    checks: dict[str, str] = {}
    try:
        async with request.app.state.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # readiness boundary: report, never raise
        checks["database"] = "unavailable"
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        checks["redis"] = "not_configured"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:  # readiness boundary
            checks["redis"] = "unavailable"
    healthy = all(v in {"ok", "not_configured"} for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(status="ok" if healthy else "degraded", checks=checks)
