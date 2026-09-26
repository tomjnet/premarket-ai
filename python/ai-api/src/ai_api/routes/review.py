"""``/review``: the human review queue (ANALYST, ADMIN).

- ``GET /review``: tasks, pending first, ordered by market impact (company
  size x relevance of the news kind).
- ``POST /review/{id}``: approve the AI verdict, or override it with a new
  verdict and a comment. The decision is stored at once (409 if someone
  decided first); the worker then resumes the item's graph, which writes
  the final verdict. Every decision is in the audit log.
"""

from __future__ import annotations

import datetime
from typing import Annotated

import fastapi

from ai_api import deps
from ai_api import schemas
from ai_api import verdicts

_OFF = "The review queue is not configured"
_NOT_FOUND = "Not found"

router = fastapi.APIRouter(
    tags=["review"],
    dependencies=[fastapi.Depends(deps.require_role("ANALYST", "ADMIN"))],
    responses={401: {}, 403: {}},
)


@router.get("/review")
async def review_queue(
    services: deps.ServicesDep,
    status: schemas.ReviewStatus | None = "PENDING",
    day: Annotated[datetime.date | None, fastapi.Query(alias="date")] = None,
    limit: Annotated[int, fastapi.Query(ge=1, le=500)] = 200,
) -> schemas.ReviewListOut:
    """The review queue.

    Args:
        services: Injected services.
        status: Only tasks in this state (default PENDING).
        day: Only this feed date.
        limit: At most this many tasks.

    Returns:
        The tasks, pending first, highest market impact first.
    """
    if services.verdicts is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    found = await services.verdicts.queue(status, day, limit)
    items = [schemas.ReviewTaskOut.from_row(row) for row in found]
    return schemas.ReviewListOut(count=len(items), items=items)


@router.post("/review/{task_id}", responses={404: {}, 409: {}, 503: {}})
async def decide(
    body: schemas.ReviewIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
    task_id: Annotated[int, fastapi.Path(ge=1, le=2**63 - 1)],
) -> schemas.ReviewTaskOut:
    """Approves or overrides the AI verdict of one task.

    Raises:
        fastapi.HTTPException: 404 for an unknown task, 409 when it was
            already decided, 503 when the queue isn't configured.
    """
    if services.verdicts is None or services.queue is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    decision = verdicts.Decision(
        action=body.action,
        reviewer=user.username,
        verdict=body.verdict,
        comment=body.comment.strip(),
    )
    try:
        task = await services.verdicts.decide(task_id, decision)
    except verdicts.ReviewConflictError as e:
        raise fastapi.HTTPException(
            status_code=409, detail="This item was already reviewed"
        ) from e
    if task is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    await services.users.audit(
        "review",
        user.username,
        deps.client_ip(request),
        {
            "task": task_id,
            "action": body.action,
            "from": task["ai_verdict"],
            "to": task["final_verdict"],
        },
    )
    await services.queue.resume(
        task["run_id"],
        task["news_id"],
        task["thread_id"],
        decision.resume_value(),
    )
    return schemas.ReviewTaskOut.from_row(task)
