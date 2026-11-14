"""Per-shard point-query latency over a connection pool.

Compare with ``benchmarks.benchmark`` to see the cost of per-request
connections. Run with ``python -m benchmarks.pooled_benchmark``.
"""

from __future__ import annotations

import argparse
import random
import time

from psycopg2 import pool

from benchmarks._common import POINT_QUERY, random_user_id
from benchmarks.stats import format_summary
from core.config import REGIONS, get_settings


def run(iterations: int, seed: int | None = None) -> dict[str, list[float]]:
    rng = random.Random(seed)
    settings = get_settings()
    results: dict[str, list[float]] = {}
    for region in REGIONS:
        conn_pool = pool.SimpleConnectionPool(
            1, 10, **settings.shards[region].connect_kwargs(settings.db_connect_timeout)
        )
        try:
            samples = []
            for _ in range(iterations):
                start = time.perf_counter()
                conn = conn_pool.getconn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(POINT_QUERY, (random_user_id(region, rng),))
                        cur.fetchone()
                    conn.rollback()  # end the implicit transaction before returning it
                finally:
                    conn_pool.putconn(conn)
                samples.append((time.perf_counter() - start) * 1000)
            results[region] = samples
        finally:
            conn_pool.closeall()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--iterations", type=int, default=50)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    print(f"Pooled point queries ({args.iterations} per shard, getconn + query + putconn)")
    for region, samples in run(args.iterations, args.seed).items():
        print(format_summary(region.upper(), samples))


if __name__ == "__main__":
    main()
