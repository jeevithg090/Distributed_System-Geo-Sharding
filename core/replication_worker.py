"""Asynchronous, eventually consistent replication of users between shards.

Every ``--interval`` seconds the worker looks for rows with ``replicated = FALSE``
on each shard, copies them (keeping their global ``user_id``) to the other
shards with ``ON CONFLICT DO NOTHING``, and only then marks exactly those rows
as replicated. Rows inserted while a pass is running are picked up next pass,
and a pass that cannot reach a target shard leaves the source rows unmarked so
they are retried.

Run with ``python -m core.replication_worker`` (``--once`` for a single pass).
"""

from __future__ import annotations

import argparse
import logging
import time
from typing import Any

from core.config import REGIONS
from core.db import shard_cursor

logger = logging.getLogger(__name__)

REPLICATED_COLUMNS = (
    "user_id",
    "username",
    "email",
    "region",
    "subscription_type",
    "department",
    "status",
    "login_count",
    "last_login",
    "created_at",
)


def fetch_unreplicated_users(region: str, batch_size: int = 1000) -> list[tuple[Any, ...]]:
    with shard_cursor(region) as cursor:
        cursor.execute(
            f"SELECT {', '.join(REPLICATED_COLUMNS)} FROM users "
            "WHERE replicated = FALSE ORDER BY user_id LIMIT %s",
            (batch_size,),
        )
        return list(cursor.fetchall())


def copy_users(target_region: str, users: list[tuple[Any, ...]]) -> int:
    """Insert ``users`` into ``target_region``. Returns how many rows were new."""
    placeholders = ", ".join(["%s"] * len(REPLICATED_COLUMNS))
    inserted = 0
    with shard_cursor(target_region) as cursor:
        for user in users:
            cursor.execute(
                f"INSERT INTO users ({', '.join(REPLICATED_COLUMNS)}, replicated) "
                f"VALUES ({placeholders}, TRUE) ON CONFLICT DO NOTHING",
                user,
            )
            inserted += cursor.rowcount
    return inserted


def mark_as_replicated(region: str, user_ids: list[int]) -> None:
    with shard_cursor(region) as cursor:
        cursor.execute(
            "UPDATE users SET replicated = TRUE WHERE user_id = ANY(%s)",
            (user_ids,),
        )


def replicate_once(regions: tuple[str, ...] = REGIONS) -> dict[str, dict[str, int]]:
    """Run one replication pass. Returns ``{source: {target: rows_inserted}}``."""
    report: dict[str, dict[str, int]] = {}
    for source in regions:
        try:
            users = fetch_unreplicated_users(source)
        except Exception as exc:
            logger.error("Cannot read pending rows from %s: %s", source.upper(), exc)
            continue
        if not users:
            continue

        logger.info("Replicating %d users from %s", len(users), source.upper())
        report[source] = {}
        all_targets_ok = True
        for target in regions:
            if target == source:
                continue
            try:
                report[source][target] = copy_users(target, users)
                logger.info("Copied %d new users to %s", report[source][target], target.upper())
            except Exception as exc:
                all_targets_ok = False
                logger.error("Replication %s -> %s failed: %s", source.upper(), target.upper(), exc)

        if all_targets_ok:
            mark_as_replicated(source, [user[0] for user in users])
        else:
            logger.warning("Leaving %s rows unmarked so they are retried", source.upper())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="GeoShardDB cross-region replication worker")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between passes")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.once:
        replicate_once()
        return
    try:
        while True:
            replicate_once()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Replication worker stopped")


if __name__ == "__main__":
    main()
