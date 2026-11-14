"""CLI: user lookup that survives a shard outage.

Tries the user's home shard first (short connect timeout) and, if it is
unreachable, falls back to the replicas on the other shards. Combine with
``docker stop eu-node`` to watch failover happen.

Usage: ``python -m core.resilient_router --user-id 1000001``
"""

from __future__ import annotations

import argparse
import sys
import time

from core.config import REGIONS, home_region_for_user
from core.users import fetch_user


def lookup_with_failover(user_id: int, preferred: str) -> tuple[str | None, dict | None, list[str]]:
    """Return ``(served_region, user, errors)`` trying ``preferred`` then the others."""
    errors: list[str] = []
    for region in (preferred, *[r for r in REGIONS if r != preferred]):
        try:
            user = fetch_user(region, user_id)
        except Exception as exc:  # connection refused, timeout, ...
            errors.append(f"{region.upper()} unavailable: {str(exc).strip()}")
            continue
        if user is not None:
            return region, user, errors
    return None, None, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resilient cross-region user lookup")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--region", choices=REGIONS)
    args = parser.parse_args(argv)

    user_id = args.user_id if args.user_id is not None else int(input("Enter user ID: "))
    preferred = args.region or home_region_for_user(user_id) or REGIONS[0]

    start = time.perf_counter()
    region, user, errors = lookup_with_failover(user_id, preferred)
    latency_ms = (time.perf_counter() - start) * 1000

    for error in errors:
        print(error)
    if user is None:
        print(f"\nUser {user_id} could not be served by any region")
        return 1
    if region is not None and region != preferred:
        print(f"\nFailover: served from {region.upper()} replica instead of {preferred.upper()}")
    print("\n--- RESULT ---")
    print(user)
    print(f"\nLatency: {latency_ms:.2f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
