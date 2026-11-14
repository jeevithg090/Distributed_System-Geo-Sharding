"""Compare request-scheduling algorithms on one random workload.

Run with ``python -m os_concepts.scheduling_benchmark [--seed N] [--count N]``.
"""

from __future__ import annotations

import argparse
import copy

from os_concepts.scheduler import ALGORITHMS, RequestScheduler, generate_random_workload, summarize


def run_benchmark(count: int = 15, seed: int | None = None) -> None:
    workload = generate_random_workload(count=count, seed=seed)
    print("=" * 52)
    print("Request Scheduling Algorithm Benchmark")
    print("=" * 52)
    for r in workload:
        print(f"  {r.request_id}: arrival={r.arrival_time}, cost={r.cost_units}, priority={r.priority}")
    print("-" * 52)
    print(f"{'Algorithm':<15} | {'Avg Wait Time':<15} | {'Avg Turnaround':<15}")
    print("-" * 52)
    scheduler = RequestScheduler()
    for name in ALGORITHMS:
        completed, _ = scheduler.run(name, copy.deepcopy(workload))
        stats = summarize(completed)
        print(
            f"{name.upper():<15} | {stats['avg_waiting_time']:<15.2f} | {stats['avg_turnaround_time']:<15.2f}"
        )
    print("=" * 52)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    run_benchmark(count=args.count, seed=args.seed)
