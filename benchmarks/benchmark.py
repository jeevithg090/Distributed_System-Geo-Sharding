"""Per-shard point-query latency, opening a new connection for every query.

The measured time includes the TCP + authentication handshake, which is what
``pooled_benchmark`` removes. Run with ``python -m benchmarks.benchmark``.
"""

from __future__ import annotations

import argparse
import random
import time

from benchmarks._common import POINT_QUERY, random_user_id
from benchmarks.stats import format_summary
from core.config import REGIONS
from core.db import connect


def run(iterations: int, seed: int | None = None) -> dict[str, list[float]]:
    rng = random.Random(seed)
    results: dict[str, list[float]] = {}
    for region in REGIONS:
        samples = []
        for _ in range(iterations):
            start = time.perf_counter()
            conn = connect(region)
            try:
                with conn.cursor() as cur:
                    cur.execute(POINT_QUERY, (random_user_id(region, rng),))
                    cur.fetchone()
            finally:
                conn.close()
            samples.append((time.perf_counter() - start) * 1000)
        results[region] = samples
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--iterations", type=int, default=50)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    print(f"Unpooled point queries ({args.iterations} per shard, connect + query + close)")
    for region, samples in run(args.iterations, args.seed).items():
        print(format_summary(region.upper(), samples))


if __name__ == "__main__":
    main()
