"""Compare cache page-replacement algorithms on a fixed access trace.

Run with ``python -m os_concepts.memory_benchmark``.
"""

from __future__ import annotations

import argparse

from os_concepts.page_replacement import ALGORITHMS, CacheSimulator

TRACE = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5, 6, 1, 2, 3, 7, 8, 9, 1, 2, 3]
CAPACITY = 4


def run_benchmark(trace: list[int] = TRACE, capacity: int = CAPACITY) -> None:
    print("=" * 57)
    print("Cache Eviction / Page Replacement Benchmark")
    print("=" * 57)
    print(f"Trace ({len(trace)} accesses): {trace}")
    print(f"Cache capacity: {capacity}")
    print("-" * 57)
    print(f"{'Algorithm':<12} | {'Hits':<8} | {'Faults':<8} | {'Hit Rate %':<12} | {'Evictions':<10}")
    print("-" * 57)
    sim = CacheSimulator(capacity)
    for name in ALGORITHMS:
        res = sim.simulate(name, trace)
        print(
            f"{res['algorithm']:<12} | {res['hits']:<8} | {res['faults']:<8} | "
            f"{res['hit_rate_pct']:<12.2f} | {res['evictions_count']:<10}"
        )
    print("=" * 57)


def _trace(value: str) -> list[int]:
    try:
        pages = [int(p) for p in value.split(",") if p.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("trace must be comma-separated integers, e.g. 1,2,3,1") from exc
    if not pages:
        raise argparse.ArgumentTypeError("trace must contain at least one page")
    return pages


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare page-replacement algorithms on one access trace.")
    parser.add_argument("--trace", type=_trace, default=TRACE, help="comma-separated page IDs")
    parser.add_argument("--capacity", type=int, default=CAPACITY, help=f"cache frames (default {CAPACITY})")
    args = parser.parse_args(argv)
    if args.capacity < 1:
        parser.error("--capacity must be at least 1")
    run_benchmark(args.trace, args.capacity)


if __name__ == "__main__":
    main()
