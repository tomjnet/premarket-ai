"""Users (``ai.app_user``) and the audit log (``ai.audit_log``).

The API's database role reads users and appends audit rows. The demo users
are created by ``ai-api init`` (as the owner). From increment 6 an ADMIN
also creates users, changes roles, disables users and resets passwords
(``/admin/users``), so the role can insert and update ``ai.app_user``
(never delete: a user is disabled, and the audit log keeps the name).
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import datetime
import json
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool


@dataclasses.dataclass(frozen=True)
class User:
    """A user who may log in.

    Attributes:
        username: Lower-case login name.
        role: TRADER, ANALYST or ADMIN.
        password_hash: argon2id hash.
        disabled: Disabled users can't log in or refresh.
    """

    username: str
    role: str
    password_hash: str = dataclasses.field(repr=False)
    disabled: bool = False


@dataclasses.dataclass(frozen=True)
class UserRow:
    """A user as the admin page lists it (no password hash).

    Attributes:
        username: Login name.
        role: TRADER, ANALYST or ADMIN.
        disabled: Can't log in.
        created_at: When it was created.
        updated_at: Its last change.
    """

    username: str
    role: str
    disabled: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DuplicateUserError(ValueError):
    """The username is taken."""


class UserStore(Protocol):
    """Reads users and writes audit events."""

    async def get(self, username: str) -> User | None:
        """Returns the user, or None if there is no such user."""
        ...

    async def audit(
        self,
        action: str,
        actor: str | None,
        client_ip: str | None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Appends one audit event."""
        ...


class UserAdmin(Protocol):
    """What ``/admin/users`` needs (ADMIN only)."""

    async def list_all(self) -> list[UserRow]:
        """Every user, by name."""
        ...

    async def create(
        self, username: str, role: str, password_hash: str
    ) -> None:
        """Adds a user.

        Raises:
            DuplicateUserError: The name is taken.
        """
        ...

    async def update(
        self,
        username: str,
        role: str | None = None,
        disabled: bool | None = None,
        password_hash: str | None = None,
    ) -> UserRow | None:
        """Changes a user; returns it, or None when there is no such user."""
        ...


class PostgresUserStore:
    """UserStore and UserAdmin over PostgreSQL."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Uses connections from ``pool``."""
        self._pool = pool

    async def get(self, username: str) -> User | None:
        """Returns the user, or None if there is no such user."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT username, role, password_hash, disabled"
                " FROM ai.app_user WHERE username = %s",
                (username,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return User(row[0], row[1], row[2], row[3])

    async def list_all(self) -> list[UserRow]:
        """Every user, by name."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT username, role, disabled, created_at, updated_at"
                " FROM ai.app_user ORDER BY username"
            )
            found = await cur.fetchall()
        return [UserRow(*row) for row in found]

    async def create(
        self, username: str, role: str, password_hash: str
    ) -> None:
        """Adds a user.

        Raises:
            DuplicateUserError: The name is taken.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO ai.app_user (username, role, password_hash)"
                " VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING",
                (username, role, password_hash),
            )
            if cur.rowcount == 0:
                raise DuplicateUserError(username)

    async def update(
        self,
        username: str,
        role: str | None = None,
        disabled: bool | None = None,
        password_hash: str | None = None,
    ) -> UserRow | None:
        """Changes a user; returns it, or None when there is no such user."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE ai.app_user SET role = coalesce(%s, role),"
                " disabled = coalesce(%s, disabled),"
                " password_hash = coalesce(%s, password_hash),"
                " updated_at = now() WHERE username = %s"
                " RETURNING username, role, disabled, created_at, updated_at",
                (role, disabled, password_hash, username),
            )
            row = await cur.fetchone()
        return None if row is None else UserRow(*row)

    async def audit(
        self,
        action: str,
        actor: str | None,
        client_ip: str | None,
        detail: Mapping[str, Any] | None = None,
    ) -> None:
        """Appends one audit event."""
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO ai.audit_log (action, actor, client_ip, detail)"
                " VALUES (%s, %s, %s, %s::jsonb)",
                (
                    action,
                    actor,
                    client_ip,
                    json.dumps({} if detail is None else dict(detail)),
                ),
            )
