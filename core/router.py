"""CLI: look up a user on a single shard and report query latency.

Usage: ``python -m core.router --user-id 1 --region us`` (prompts if omitted).
The region may be omitted entirely; it is then derived from the user ID block.
"""

from __future__ import annotations

import argparse
import sys
import time

from core.config import REGIONS, home_region_for_user
from core.users import fetch_user


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--region", choices=REGIONS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    user_id = args.user_id if args.user_id is not None else int(input("Enter user ID: "))
    region = args.region or home_region_for_user(user_id)
    if region is None:
        print(f"User ID {user_id} is outside every region's ID range", file=sys.stderr)
        return 2

    start = time.perf_counter()
    user = fetch_user(region, user_id)
    latency_ms = (time.perf_counter() - start) * 1000

    print("\n--- QUERY RESULT ---")
    print(user if user else f"User {user_id} not found on {region.upper()} shard")
    print(f"\nShard: {region.upper()}  Query time: {latency_ms:.2f} ms")
    return 0 if user else 1


if __name__ == "__main__":
    sys.exit(main())
