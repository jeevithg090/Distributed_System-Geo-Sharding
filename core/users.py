"""Queries against the ``users`` table of a shard."""

from __future__ import annotations

from typing import Any

from core.db import shard_cursor

USER_COLUMNS = (
    "user_id",
    "username",
    "email",
    "region",
    "subscription_type",
    "department",
    "status",
    "login_count",
    "last_login",
)


def _row_to_user(row: tuple[Any, ...]) -> dict[str, Any]:
    user = dict(zip(USER_COLUMNS, row, strict=True))
    if user["last_login"] is not None:
        user["last_login"] = user["last_login"].isoformat(sep=" ")
    return user


def fetch_user(region: str, user_id: int) -> dict[str, Any] | None:
    """Return a single user from ``region``'s shard, or ``None`` if absent."""
    with shard_cursor(region) as cursor:
        cursor.execute(
            f"SELECT {', '.join(USER_COLUMNS)} FROM users WHERE user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
    return _row_to_user(row) if row else None


def fetch_recent_users(region: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return the ``limit`` newest users whose home is ``region`` (replicas excluded)."""
    with shard_cursor(region) as cursor:
        cursor.execute(
            "SELECT user_id, username, region FROM users WHERE region = %s "
            "ORDER BY created_at DESC, user_id DESC LIMIT %s",
            (region, limit),
        )
        rows = cursor.fetchall()
    return [{"user_id": r[0], "username": r[1], "region": r[2]} for r in rows]


def ping(region: str, connect_timeout: int = 2) -> bool:
    """Return True if ``region``'s shard accepts connections and answers ``SELECT 1``."""
    try:
        with shard_cursor(region, connect_timeout=connect_timeout) as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return False
    return True
