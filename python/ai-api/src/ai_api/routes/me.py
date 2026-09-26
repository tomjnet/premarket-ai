"""``/me/watchlist``: the caller's watchlist (long-term memory).

- ``GET``: the saved tickers and sectors, plus the sectors to choose from
  (the lab universe's GICS sectors).
- ``PUT``: replaces them. Tickers are upper-cased and must be in the SEC
  ticker registry (once it has been downloaded); at most 25. ``422`` names
  the first bad value. Every change is audited.

The watchlist puts the caller's items first in the brief, tells the chat
agents what "my watchlist" means, and sends a FAKE or MISLEADING verdict
for a watched ticker to an analyst.
"""

from __future__ import annotations

import fastapi

from ai_api import deps
from ai_api import memory as memory_lib
from ai_api import schemas

_OFF = "The watchlist is not configured"

router = fastapi.APIRouter(
    tags=["me"],
    dependencies=[
        fastapi.Depends(deps.require_role("TRADER", "ANALYST", "ADMIN"))
    ],
    responses={401: {}, 403: {}, 503: {}},
)


def _memory(services: deps.Services) -> memory_lib.Memory:
    if services.memory is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    return services.memory


def _out(
    services: deps.Services, watchlist: memory_lib.Watchlist
) -> schemas.WatchlistOut:
    return schemas.WatchlistOut(
        tickers=list(watchlist.tickers),
        sectors=list(watchlist.sectors),
        available_sectors=list(services.sectors),
    )


@router.get("/me/watchlist")
async def get_watchlist(
    services: deps.ServicesDep, user: deps.CurrentUser
) -> schemas.WatchlistOut:
    """The caller's watchlist."""
    memory = _memory(services)
    return _out(services, await memory.watchlist(user.username))


@router.put("/me/watchlist", responses={422: {}})
async def put_watchlist(
    body: schemas.WatchlistIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.WatchlistOut:
    """Replaces the caller's watchlist.

    Raises:
        fastapi.HTTPException: 422 for a bad ticker or sector.
    """
    memory = _memory(services)
    try:
        tickers = memory_lib.normalize_tickers(body.tickers)
        sectors = memory_lib.normalize_sectors(body.sectors, services.sectors)
    except memory_lib.WatchlistError as e:
        raise fastapi.HTTPException(status_code=422, detail=str(e)) from e
    known = await services.news.known_tickers(tickers)
    if known is not None:
        unknown = [t for t in tickers if t not in known]
        if unknown:
            raise fastapi.HTTPException(
                status_code=422,
                detail=f"Not in the SEC ticker registry: {unknown[0]}",
            )
    watchlist = memory_lib.Watchlist(tickers, sectors)
    await memory.save_watchlist(user.username, watchlist)
    await services.users.audit(
        "watchlist",
        user.username,
        deps.client_ip(request),
        {"tickers": len(tickers), "sectors": len(sectors)},
    )
    return _out(services, watchlist)
