"""Users (``ai.app_user``) and the audit log (``ai.audit_log``).

The API's database role can only read users and append audit rows. Users
are created and their passwords set by ``ai-api init`` (as the owner role).
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
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


class PostgresUserStore:
    """UserStore over PostgreSQL."""

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
