"""Cold (database) vs. warm (Redis) read latency through the running API.

Run with ``python -m benchmarks.cache_benchmark``. Uses ``API_URL``
(default ``http://localhost:8000``) and sends ``ADMIN_API_KEY`` as
``X-API-Key`` when flushing the cache, if it is set.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
if not API_URL.startswith(("http://", "https://")):
    raise SystemExit("API_URL must be an http(s) URL")


def request(path: str, method: str = "GET") -> Any:
    req = urllib.request.Request(f"{API_URL}{path}", method=method)  # noqa: S310 - scheme checked
    api_key = os.environ.get("ADMIN_API_KEY")
    if api_key:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code} for {method} {path}: {exc.read().decode('utf-8', 'replace')}")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Connection error for {method} {path}: {exc}")
    return None


def timed_reads(targets: list[dict[str, Any]], label: str) -> list[float]:
    print(f"{label}:")
    samples = []
    for target in targets:
        start = time.perf_counter()
        res = request(f"/users/{target['user_id']}?region={target['region']}")
        latency = (time.perf_counter() - start) * 1000
        samples.append(latency)
        cached = res.get("served_from_cache") if res else None
        print(f"  user {target['user_id']} ({target['region']}): {latency:7.2f} ms  cache={cached}")
    return samples


def main() -> int:
    if request("/") is None:
        print(f"GeoShardDB API is not reachable at {API_URL}")
        return 1
    request("/cache", method="DELETE")
    recent = request("/users/recent/all") or {}
    targets = [u for u in recent.get("results", []) if "user_id" in u][:5]
    if not targets:
        print("No users found. Seed the shards first (python seed_data.py).")
        return 1

    cold = timed_reads(targets, "Cold reads (cache miss -> PostgreSQL)")
    warm = timed_reads(targets, "Warm reads (cache hit -> Redis)")
    avg_cold, avg_warm = statistics.fmean(cold), statistics.fmean(warm)
    print(f"\nAverage cold: {avg_cold:.2f} ms | average warm: {avg_warm:.2f} ms")
    if avg_warm > 0:
        print(f"Speed-up: {avg_cold / avg_warm:.2f}x")
    stats = request("/cache/stats")
    if stats:
        s = stats["stats"]
        print(f"Cache hits={s['hits']} misses={s['misses']} hit_rate={s['hit_rate_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
