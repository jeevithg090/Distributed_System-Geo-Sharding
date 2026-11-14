"""Cross-shard fan-out: users created in the last N days, sequential vs. parallel.

Run with ``python -m benchmarks.cross_shard_query [--days 365]``. Sequential
latency is the *sum* of shard latencies; parallel latency approaches the *max*.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from core.config import REGIONS
from core.db import shard_cursor

RECENT_USERS_SQL = (
    "SELECT user_id, username, region, created_at FROM users "
    "WHERE region = %s AND created_at >= NOW() - make_interval(days => %s)"
)


def query_region(region: str, days: int) -> list[tuple[Any, ...]]:
    with shard_cursor(region) as cur:
        cur.execute(RECENT_USERS_SQL, (region, days))
        return list(cur.fetchall())


def sequential(days: int, regions: Iterable[str] = REGIONS) -> tuple[list[tuple[Any, ...]], float]:
    start = time.perf_counter()
    rows: list[tuple[Any, ...]] = []
    for region in regions:
        rows.extend(query_region(region, days))
    return rows, (time.perf_counter() - start) * 1000


def parallel(days: int, regions: Iterable[str] = REGIONS) -> tuple[list[tuple[Any, ...]], float]:
    regions = list(regions)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(regions)) as pool:
        rows = [row for part in pool.map(lambda r: query_region(r, days), regions) for row in part]
    return rows, (time.perf_counter() - start) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    for name, strategy in (("Sequential", sequential), ("Parallel", parallel)):
        rows, latency = strategy(args.days)
        print(f"{name:<10} fan-out: {len(rows)} users in {latency:.2f} ms")


if __name__ == "__main__":
    main()
