"""PostgreSQL shard connection helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2

from core.config import REGION_ID_OFFSETS, ShardConfig, get_settings


class UnknownRegionError(ValueError):
    """Raised when a caller asks for a region that has no configured shard."""


def shard_config(region: str) -> ShardConfig:
    try:
        return get_settings().shards[region]
    except KeyError as exc:
        raise UnknownRegionError(f"Unknown region: {region!r}") from exc


def connect(region: str, connect_timeout: int | None = None) -> Any:
    """Open a new psycopg2 connection to the shard for ``region``."""
    settings = get_settings()
    timeout = settings.db_connect_timeout if connect_timeout is None else connect_timeout
    return psycopg2.connect(**shard_config(region).connect_kwargs(connect_timeout=timeout))


@contextmanager
def shard_cursor(region: str, connect_timeout: int | None = None) -> Iterator[Any]:
    """Yield a cursor on ``region``'s shard; commits on success and always closes."""
    conn = connect(region, connect_timeout=connect_timeout)
    try:
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_user_id_sequence(cursor: Any, region: str) -> None:
    """Point ``users.user_id`` at the start of ``region``'s global ID block."""
    start = REGION_ID_OFFSETS[region] + 1
    cursor.execute("SELECT setval('users_user_id_seq', %s, false)", (start,))
