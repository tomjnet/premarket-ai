"""``/auth/login``, ``/auth/refresh`` and ``/auth/logout``.

The access token goes in the JSON body (the browser keeps it in memory
only). The refresh token goes in an httpOnly cookie that JavaScript can't
read.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

import fastapi
from starlette import concurrency

from ai_api import deps
from ai_api import passwords
from ai_api import schemas
from ai_api import sessions
from ai_api import tokens

_log = logging.getLogger(__name__)

# `__Host-`: the browser only accepts it with Secure, Path=/ and no Domain,
# so no subdomain or plain-HTTP page can set or overwrite it. Browsers treat
# http://localhost as secure, so it works in the local lab too.
REFRESH_COOKIE = "__Host-premarket_refresh"
_USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_WRONG_CREDENTIALS = "Incorrect username or password"

router = fastapi.APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[fastapi.Depends(deps.check_origin)],
)


def _set_refresh_cookie(
    response: fastapi.Response, token: str, max_age: int
) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: fastapi.Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path="/", secure=True, httponly=True, samesite="strict"
    )


def _token_response(
    services: deps.Services, session: sessions.Session
) -> schemas.TokenOut:
    ttl = services.settings.access_token_ttl_s
    access = tokens.issue(
        tokens.Claims(session.username, session.role, session.session_id),
        services.settings.jwt_secret,
        ttl,
    )
    return schemas.TokenOut(
        access_token=access,
        expires_in=ttl,
        user=schemas.UserOut(username=session.username, role=session.role),
    )


@router.post("/login", responses={401: {}, 429: {}})
async def login(
    request: fastapi.Request,
    response: fastapi.Response,
    services: deps.ServicesDep,
    username: Annotated[str, fastapi.Form(max_length=64)],
    password: Annotated[
        str, fastapi.Form(max_length=passwords.MAX_PASSWORD_CHARS)
    ],
) -> schemas.TokenOut:
    """OAuth2 password flow: checks the password and starts a session.

    Every failure answers the same 401, whether the user exists or not, and
    takes the same time. After LOGIN_MAX_FAILURES failures a username is
    locked for LOGIN_LOCKOUT_S (429 with Retry-After).
    """
    ip = deps.client_ip(request)
    name = username.strip().lower()
    wait_s = await services.sessions.locked_for(name)
    if wait_s:
        await services.users.audit("login_locked", name, ip)
        raise fastapi.HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(wait_s)},
        )
    user = await services.users.get(name) if _USERNAME.match(name) else None
    # argon2 takes ~50 ms of CPU: run it off the event loop.
    ok = await concurrency.run_in_threadpool(
        passwords.verify_password,
        None if user is None else user.password_hash,
        password,
    )
    if not ok or user is None or user.disabled:
        await services.sessions.record_failure(name)
        await services.users.audit("login_failed", name, ip)
        raise fastapi.HTTPException(
            status_code=401,
            detail=_WRONG_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    await services.sessions.clear_failures(name)
    session, refresh = await services.sessions.create(user.username, user.role)
    _set_refresh_cookie(
        response, refresh, services.settings.refresh_token_ttl_s
    )
    await services.users.audit("login", user.username, ip)
    _log.info("login %s (%s)", user.username, user.role)
    return _token_response(services, session)


@router.post("/refresh", responses={401: {}})
async def refresh(
    request: fastapi.Request,
    response: fastapi.Response,
    services: deps.ServicesDep,
) -> schemas.TokenOut:
    """Rotates the refresh cookie and returns a new access token.

    The user is read again, so a disabled user or a changed role takes
    effect at the next refresh.
    """
    cookie = request.cookies.get(REFRESH_COOKIE)
    unauthorized = fastapi.HTTPException(
        status_code=401,
        detail=deps.NOT_AUTHENTICATED,
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not cookie:
        raise unauthorized
    rotation = await services.sessions.rotate(cookie)
    if rotation.outcome is sessions.RotateOutcome.REUSED:
        await services.users.audit(
            "refresh_reuse", None, deps.client_ip(request)
        )
        _log.warning("refresh token reuse: session revoked")
    session = rotation.session
    if session is None or rotation.refresh_token is None:
        raise _with_cleared_cookie(unauthorized)
    user = await services.users.get(session.username)
    if user is None or user.disabled:
        await services.sessions.revoke(session.session_id)
        raise _with_cleared_cookie(unauthorized)
    if user.role != session.role:
        # Role changed since login: start over with the current role.
        await services.sessions.revoke(session.session_id)
        session, token = await services.sessions.create(
            user.username, user.role
        )
    else:
        token = rotation.refresh_token
    _set_refresh_cookie(response, token, services.settings.refresh_token_ttl_s)
    return _token_response(services, session)


def _with_cleared_cookie(
    error: fastapi.HTTPException,
) -> fastapi.HTTPException:
    # HTTPException responses don't carry the route's `response` cookies.
    cleared = fastapi.Response()
    _clear_refresh_cookie(cleared)
    headers = dict(error.headers or {})
    headers["set-cookie"] = cleared.headers["set-cookie"]
    return fastapi.HTTPException(
        status_code=error.status_code, detail=error.detail, headers=headers
    )


@router.post("/logout", status_code=204)
async def logout(
    request: fastapi.Request, services: deps.ServicesDep
) -> fastapi.Response:
    """Ends the session (and every access token of it) and clears the cookie."""
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        await services.sessions.revoke_token(cookie)
        await services.users.audit("logout", None, deps.client_ip(request))
    response = fastapi.Response(status_code=204)
    _clear_refresh_cookie(response)
    return response
