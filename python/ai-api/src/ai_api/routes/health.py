"""``GET /health``: liveness plus the database and Redis."""

from __future__ import annotations

import logging

import fastapi

from ai_api import deps
from ai_api import schemas

_log = logging.getLogger(__name__)

router = fastapi.APIRouter(tags=["health"])


@router.get("/health", responses={503: {"model": schemas.HealthOut}})
async def health(
    services: deps.ServicesDep, response: fastapi.Response
) -> schemas.HealthOut:
    """``ok`` when PostgreSQL and Redis answer, else 503 ``unavailable``.

    No details are returned: the endpoint is public.
    """
    try:
        await services.ping()
    except Exception:  # noqa: BLE001 - any failure means "not healthy".
        _log.exception("health check failed")
        response.status_code = 503
        return schemas.HealthOut(status="unavailable")
    return schemas.HealthOut(status="ok")
