"""Compare cache page-replacement algorithms on a fixed access trace.

Run with ``python -m os_concepts.memory_benchmark``.
"""

from __future__ import annotations

from os_concepts.page_replacement import ALGORITHMS, CacheSimulator

TRACE = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5, 6, 1, 2, 3, 7, 8, 9, 1, 2, 3]
CAPACITY = 4


def run_benchmark() -> None:
    print("=" * 57)
    print("Cache Eviction / Page Replacement Benchmark")
    print("=" * 57)
    print(f"Trace ({len(TRACE)} accesses): {TRACE}")
    print(f"Cache capacity: {CAPACITY}")
    print("-" * 57)
    print(f"{'Algorithm':<12} | {'Hits':<8} | {'Faults':<8} | {'Hit Rate %':<12} | {'Evictions':<10}")
    print("-" * 57)
    sim = CacheSimulator(CAPACITY)
    for name in ALGORITHMS:
        res = sim.simulate(name, TRACE)
        print(
            f"{res['algorithm']:<12} | {res['hits']:<8} | {res['faults']:<8} | "
            f"{res['hit_rate_pct']:<12.2f} | {res['evictions_count']:<10}"
        )
    print("=" * 57)


if __name__ == "__main__":
    run_benchmark()
