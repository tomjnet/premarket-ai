"""``/admin/*``: users, source reputation and LLM settings (ADMIN only).

- ``GET /admin/users``; ``POST /admin/users`` creates one;
  ``POST /admin/users/{username}`` changes its role, disables or enables
  it, or resets its password. An admin can't disable or demote themselves,
  so there is always at least one admin. A disabled user's sessions end at
  once; a changed role takes effect at the user's next login.
- ``GET /admin/sources?q=``; ``POST /admin/sources`` adds or changes a
  domain's tier, score and note.
- ``GET /admin/llm``: the models of the hardware profile, the cloud
  aliases, the month's budget and the cloud switches; ``POST /admin/llm``
  sets the switches.

Every change is written to ``ai.audit_log`` (never a password).
"""

from __future__ import annotations

from typing import Annotated

import fastapi

from ai_api import admin as admin_lib
from ai_api import deps
from ai_api import passwords
from ai_api import schemas
from ai_api import users as users_lib

router = fastapi.APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[fastapi.Depends(deps.require_role("ADMIN"))],
    responses={401: {}, 403: {}},
)
_OFF = "Administration is not configured"
_NOT_FOUND = "Not found"
_MIN_PASSWORD_CHARS = 12


def _admin(services: deps.Services) -> admin_lib.PostgresAdmin:
    if services.admin is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    return services.admin


def _user_admin(services: deps.Services) -> users_lib.UserAdmin:
    if services.user_admin is None:
        raise fastapi.HTTPException(status_code=503, detail=_OFF)
    return services.user_admin


def _hash(password: str) -> str:
    if not _MIN_PASSWORD_CHARS <= len(password) <= passwords.MAX_PASSWORD_CHARS:
        raise fastapi.HTTPException(
            status_code=422,
            detail=f"A password has {_MIN_PASSWORD_CHARS} to"
            f" {passwords.MAX_PASSWORD_CHARS} characters",
        )
    return passwords.hash_password(password)


def _user_out(row: users_lib.UserRow) -> schemas.AdminUserOut:
    return schemas.AdminUserOut(
        username=row.username,
        role=row.role,
        disabled=row.disabled,
        created_at=schemas.utc_z(row.created_at),
        updated_at=schemas.utc_z(row.updated_at),
    )


@router.get("/users")
async def list_users(services: deps.ServicesDep) -> schemas.AdminUserListOut:
    """Every user (no password hashes)."""
    found = await _user_admin(services).list_all()
    items = [_user_out(row) for row in found]
    return schemas.AdminUserListOut(count=len(items), items=items)


@router.post("/users", status_code=201, responses={409: {}, 422: {}, 503: {}})
async def create_user(
    body: schemas.AdminUserIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.AdminUserOut:
    """Creates a user.

    Raises:
        fastapi.HTTPException: 409 when the name is taken.
    """
    store = _user_admin(services)
    try:
        await store.create(body.username, body.role, _hash(body.password))
    except users_lib.DuplicateUserError as e:
        raise fastapi.HTTPException(
            status_code=409, detail="The username is taken"
        ) from e
    await services.users.audit(
        "admin_user_create",
        user.username,
        deps.client_ip(request),
        {"username": body.username, "role": body.role},
    )
    created = next(
        r for r in await store.list_all() if r.username == body.username
    )
    return _user_out(created)


@router.post(
    "/users/{username}", responses={404: {}, 409: {}, 422: {}, 503: {}}
)
async def update_user(
    body: schemas.AdminUserUpdateIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
    username: Annotated[str, fastapi.Path(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")],
) -> schemas.AdminUserOut:
    """Changes a user's role, status or password.

    Raises:
        fastapi.HTTPException: 404 for an unknown user; 409 when an admin
            would disable or demote themselves.
    """
    store = _user_admin(services)
    if username == user.username and (
        body.disabled or (body.role is not None and body.role != "ADMIN")
    ):
        raise fastapi.HTTPException(
            status_code=409,
            detail="You can't disable or demote your own account",
        )
    password_hash = None if body.password is None else _hash(body.password)
    changed = await store.update(
        username,
        role=body.role,
        disabled=body.disabled,
        password_hash=password_hash,
    )
    if changed is None:
        raise fastapi.HTTPException(status_code=404, detail=_NOT_FOUND)
    ended = 0
    if body.disabled or password_hash is not None:
        ended = await services.sessions.revoke_user(username)
    await services.users.audit(
        "admin_user_update",
        user.username,
        deps.client_ip(request),
        {
            "username": username,
            "role": body.role,
            "disabled": body.disabled,
            "password_reset": password_hash is not None,
            "sessions_ended": ended,
        },
    )
    return _user_out(changed)


def _source_out(row: admin_lib.SourceRow) -> schemas.AdminSourceOut:
    return schemas.AdminSourceOut(
        domain=row.domain,
        tier=row.tier,
        reputation=round(float(row.reputation), 3),
        note=row.note,
        updated_at=schemas.utc_z(row.updated_at),
    )


@router.get("/sources")
async def list_sources(
    services: deps.ServicesDep,
    q: Annotated[str, fastapi.Query(max_length=100)] = "",
) -> schemas.AdminSourceListOut:
    """The source reputation list (domains containing ``q``)."""
    found = await _admin(services).sources(q.strip())
    items = [_source_out(row) for row in found]
    return schemas.AdminSourceListOut(count=len(items), items=items)


@router.post("/sources", responses={422: {}, 503: {}})
async def upsert_source(
    body: schemas.AdminSourceIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.AdminSourceOut:
    """Adds a domain or changes its tier, score and note."""
    row = await _admin(services).upsert_source(
        body.domain, body.tier, body.reputation, body.note
    )
    await services.users.audit(
        "admin_source",
        user.username,
        deps.client_ip(request),
        {"domain": body.domain, "tier": body.tier, "score": body.reputation},
    )
    return _source_out(row)


async def _llm_out(services: deps.Services) -> schemas.AdminLlmOut:
    settings = services.settings
    llm = settings.llm
    switches = await _admin(services).cloud_switches()
    spent = 0.0 if services.budget is None else await services.budget.spent()
    return schemas.AdminLlmOut(
        hw_profile="" if llm is None else llm.hw_profile,
        main_model="" if llm is None else llm.main_model,
        embed_model="" if llm is None else llm.embed_model,
        guard_model="" if llm is None else llm.guard_model,
        vector_store="" if settings.rag is None else settings.rag.vector_store,
        judge_cloud_model=settings.judge_cloud_model,
        brief_model=settings.brief_model,
        cloud=schemas.CloudSwitchesOut(**switches),
        budget=schemas.BudgetOut(
            spent_usd=round(spent, 4),
            cap_usd=settings.monthly_budget_usd,
            share=round(spent / settings.monthly_budget_usd, 4)
            if settings.monthly_budget_usd
            else 1.0,
            warning=spent >= 0.8 * settings.monthly_budget_usd,
            reached=spent >= settings.monthly_budget_usd,
        ),
    )


@router.get("/llm", responses={503: {}})
async def llm_settings(services: deps.ServicesDep) -> schemas.AdminLlmOut:
    """The models, the budget and the cloud switches."""
    return await _llm_out(services)


@router.post("/llm", responses={503: {}})
async def set_llm_settings(
    body: schemas.CloudSwitchesIn,
    services: deps.ServicesDep,
    user: deps.CurrentUser,
    request: fastapi.Request,
) -> schemas.AdminLlmOut:
    """Sets the cloud switches (unset fields keep their value)."""
    store = _admin(services)
    current = await store.cloud_switches()
    wanted = {
        name: value
        for name, value in body.model_dump().items()
        if value is not None
    }
    saved = await store.set_cloud_switches({**current, **wanted}, user.username)
    await services.users.audit(
        "admin_llm", user.username, deps.client_ip(request), saved
    )
    return await _llm_out(services)
