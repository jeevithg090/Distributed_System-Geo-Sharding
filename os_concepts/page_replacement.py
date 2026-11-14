"""Cache-eviction simulator built on classic OS page-replacement algorithms.

Supported policies: FIFO, LRU, LFU, Clock (second chance) and Optimal (Bélády).
Every ``simulate_*`` method returns the same shape::

    {"algorithm", "hits", "faults", "hit_rate_pct", "evictions_count", "history"}

where ``history`` records, per access, the item, ``HIT``/``MISS``, the cache
contents afterwards and the evicted item (if any).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable, Sequence
from typing import Any

ALGORITHMS = ("fifo", "lru", "lfu", "clock", "optimal")


class _Run:
    """Accumulates hits, faults and history for one simulation."""

    def __init__(self, algorithm: str, trace: Sequence[Hashable]) -> None:
        self.algorithm = algorithm
        self.trace = trace
        self.hits = 0
        self.faults = 0
        self.evictions: list[Hashable] = []
        self.history: list[dict[str, Any]] = []

    def record(self, item: Hashable, hit: bool, cache: list[Hashable], evicted: Hashable | None) -> None:
        if hit:
            self.hits += 1
        else:
            self.faults += 1
        if evicted is not None:
            self.evictions.append(evicted)
        self.history.append(
            {"item": item, "status": "HIT" if hit else "MISS", "cache": cache, "evicted": evicted}
        )

    def result(self) -> dict[str, Any]:
        total = len(self.trace)
        return {
            "algorithm": self.algorithm,
            "hits": self.hits,
            "faults": self.faults,
            "hit_rate_pct": round(self.hits / total * 100, 2) if total else 0,
            "evictions_count": len(self.evictions),
            "history": self.history,
        }


class CacheSimulator:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity

    def simulate(self, algorithm: str, trace: Sequence[Hashable]) -> dict[str, Any]:
        """Dispatch to ``simulate_<algorithm>``; raises ``ValueError`` for unknown names."""
        name = algorithm.lower()
        if name not in ALGORITHMS:
            raise ValueError(f"Unknown page replacement algorithm: {algorithm}")
        result: dict[str, Any] = getattr(self, f"simulate_{name}")(trace)
        return result

    def simulate_fifo(self, trace: Sequence[Hashable]) -> dict[str, Any]:
        """First-In, First-Out: evict the page that has been resident longest."""
        run = _Run("FIFO", trace)
        cache: list[Hashable] = []
        for item in trace:
            evicted = None
            hit = item in cache
            if not hit:
                if len(cache) >= self.capacity:
                    evicted = cache.pop(0)
                cache.append(item)
            run.record(item, hit, list(cache), evicted)
        return run.result()

    def simulate_lru(self, trace: Sequence[Hashable]) -> dict[str, Any]:
        """Least Recently Used: evict the page whose last access is oldest."""
        run = _Run("LRU", trace)
        cache: OrderedDict[Hashable, None] = OrderedDict()
        for item in trace:
            evicted = None
            hit = item in cache
            if hit:
                cache.move_to_end(item)
            else:
                if len(cache) >= self.capacity:
                    evicted, _ = cache.popitem(last=False)
                cache[item] = None
            run.record(item, hit, list(cache), evicted)
        return run.result()

    def simulate_lfu(self, trace: Sequence[Hashable]) -> dict[str, Any]:
        """Least Frequently Used: evict the resident page with the fewest accesses.

        Frequencies count accesses since the page was (re)loaded; ties are broken
        by least-recent use.
        """
        run = _Run("LFU", trace)
        counts: dict[Hashable, int] = {}
        last_used: dict[Hashable, int] = {}
        for step, item in enumerate(trace):
            evicted = None
            hit = item in counts
            if hit:
                counts[item] += 1
            else:
                if len(counts) >= self.capacity:
                    evicted = min(counts, key=lambda page: (counts[page], last_used[page]))
                    del counts[evicted]
                    del last_used[evicted]
                counts[item] = 1
            last_used[item] = step
            run.record(item, hit, list(counts), evicted)
        return run.result()

    def simulate_clock(self, trace: Sequence[Hashable]) -> dict[str, Any]:
        """Clock / second chance: a circular FIFO that spares recently referenced pages."""
        run = _Run("Clock", trace)
        frames: list[Hashable | None] = [None] * self.capacity
        ref_bits = [0] * self.capacity
        hand = 0
        for item in trace:
            evicted = None
            hit = item in frames
            if hit:
                ref_bits[frames.index(item)] = 1
            else:
                while frames[hand] is not None and ref_bits[hand] == 1:
                    ref_bits[hand] = 0
                    hand = (hand + 1) % self.capacity
                evicted = frames[hand]
                frames[hand] = item
                ref_bits[hand] = 1
                hand = (hand + 1) % self.capacity
            run.record(item, hit, [f for f in frames if f is not None], evicted)
        return run.result()

    def simulate_optimal(self, trace: Sequence[Hashable]) -> dict[str, Any]:
        """Optimal (Bélády): evict the page whose next use is furthest in the future."""
        run = _Run("Optimal", trace)
        cache: list[Hashable] = []
        for step, item in enumerate(trace):
            evicted = None
            hit = item in cache
            if not hit:
                if len(cache) >= self.capacity:
                    future = trace[step + 1 :]

                    def next_use(page: Hashable, future: Sequence[Hashable] = future) -> float:
                        try:
                            return future.index(page)
                        except ValueError:
                            return float("inf")

                    evicted = max(cache, key=next_use)
                    cache.remove(evicted)
                cache.append(item)
            run.record(item, hit, list(cache), evicted)
        return run.result()
