"""Login, refresh rotation, logout, lockout and CSRF checks."""

import asyncio

import conftest

from ai_api.routes import auth


def _cookie_header(response) -> str:
    return response.headers["set-cookie"].lower()


def test_login_returns_token_user_and_hardened_cookie(harness):
    response = harness.client.post(
        "/auth/login",
        data={"username": "Trader1", "password": conftest.PASSWORD},
        headers={"Origin": conftest.ORIGIN, "Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["user"] == {"username": "trader1", "role": "TRADER"}
    cookie = _cookie_header(response)
    assert cookie.startswith(auth.REFRESH_COOKIE.lower() + "=")
    for attribute in ("httponly", "secure", "samesite=strict", "path=/"):
        assert attribute in cookie
    assert "domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert harness.users.events == [("login", "trader1")]


def test_wrong_password_and_unknown_user_get_the_same_401(harness):
    wrong = harness.client.post(
        "/auth/login", data={"username": "trader1", "password": "nope"}
    )
    unknown = harness.client.post(
        "/auth/login", data={"username": "nobody", "password": "nope"}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert (
        wrong.json()
        == unknown.json()
        == {"detail": "Incorrect username or password"}
    )
    assert "set-cookie" not in wrong.headers


def test_disabled_user_cannot_log_in(harness):
    response = harness.client.post(
        "/auth/login",
        data={"username": "gone1", "password": conftest.PASSWORD},
    )
    assert response.status_code == 401


def test_too_long_password_is_rejected_before_hashing(harness):
    response = harness.client.post(
        "/auth/login", data={"username": "trader1", "password": "x" * 300}
    )
    assert response.status_code == 422


def test_lockout_after_max_failures_even_with_right_password(harness):
    for _ in range(3):
        harness.client.post(
            "/auth/login", data={"username": "trader1", "password": "bad"}
        )

    response = harness.client.post(
        "/auth/login",
        data={"username": "trader1", "password": conftest.PASSWORD},
    )

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    assert ("login_locked", "trader1") in harness.users.events


def test_success_resets_the_failure_count(harness):
    for _ in range(2):
        harness.client.post(
            "/auth/login", data={"username": "trader1", "password": "bad"}
        )
    harness.login()
    for _ in range(2):
        harness.client.post(
            "/auth/login", data={"username": "trader1", "password": "bad"}
        )
    harness.login()


def test_cross_site_login_is_forbidden(harness):
    evil_origin = harness.client.post(
        "/auth/login",
        data={"username": "trader1", "password": conftest.PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    cross_site = harness.client.post(
        "/auth/refresh", headers={"Sec-Fetch-Site": "cross-site"}
    )

    assert evil_origin.status_code == 403
    assert cross_site.status_code == 403
    assert evil_origin.json() == {"detail": "Forbidden"}


def test_refresh_without_cookie_is_401(harness):
    response = harness.client.post("/auth/refresh")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_refresh_rotates_the_cookie(harness):
    harness.login()
    first = harness.client.cookies.get(auth.REFRESH_COOKIE)

    response = harness.client.post("/auth/refresh")

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "TRADER"
    second = harness.client.cookies.get(auth.REFRESH_COOKIE)
    assert second and second != first


def _refresh_with(harness, value: str):
    # Another tab or an attacker: send exactly this cookie, nothing else.
    harness.client.cookies.clear()
    return harness.client.post(
        "/auth/refresh", headers={"Cookie": f"{auth.REFRESH_COOKIE}={value}"}
    )


def test_old_cookie_within_grace_returns_the_same_new_token(harness):
    harness.login()
    old = harness.client.cookies.get(auth.REFRESH_COOKIE)
    first = harness.client.post("/auth/refresh")
    new = first.cookies.get(auth.REFRESH_COOKIE)

    # A second tab sends the old cookie a moment later.
    again = _refresh_with(harness, old)

    assert again.status_code == 200
    assert again.cookies.get(auth.REFRESH_COOKIE) == new


def test_reused_cookie_after_grace_revokes_the_session(harness):
    token = harness.login()
    old = harness.client.cookies.get(auth.REFRESH_COOKIE)
    new = harness.client.post("/auth/refresh").cookies.get(auth.REFRESH_COOKIE)
    sid = old.split(".")[0]

    async def expire_grace():
        async for key in harness.redis.scan_iter(f"session:{sid}:grace:*"):
            await harness.redis.delete(key)

    asyncio.run(expire_grace())
    stolen = _refresh_with(harness, old)

    assert stolen.status_code == 401
    assert "max-age=0" in _cookie_header(stolen)
    assert ("refresh_reuse", None) in harness.users.events
    # The legitimate holder is logged out too, and so is its access token.
    assert _refresh_with(harness, new).status_code == 401
    news = harness.client.get(
        "/news", headers={"Authorization": f"Bearer {token}"}
    )
    assert news.status_code == 401


def test_refresh_of_a_disabled_user_fails(harness):
    harness.login()
    user = harness.users.users["trader1"]
    harness.users.users["trader1"] = type(user)(
        user.username, user.role, user.password_hash, disabled=True
    )
    assert harness.client.post("/auth/refresh").status_code == 401


def test_logout_revokes_access_token_and_clears_cookie(harness):
    token = harness.login()
    bearer = {"Authorization": f"Bearer {token}"}
    assert harness.client.get("/news", headers=bearer).status_code == 200

    response = harness.client.post("/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in _cookie_header(response)
    assert harness.client.get("/news", headers=bearer).status_code == 401
    assert harness.client.post("/auth/refresh").status_code == 401


def test_logout_without_session_is_still_204(harness):
    assert harness.client.post("/auth/logout").status_code == 204
