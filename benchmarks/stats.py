"""Latency summary helpers shared by the benchmarks."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def percentile(samples: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (``pct`` in 0..100)."""
    if not samples:
        raise ValueError("percentile of empty sample")
    if not 0 <= pct <= 100:
        raise ValueError("pct must be within 0..100")
    ordered = sorted(samples)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(samples: Sequence[float]) -> dict[str, float]:
    return {
        "min": min(samples),
        "avg": statistics.fmean(samples),
        "p50": percentile(samples, 50),
        "p95": percentile(samples, 95),
        "max": max(samples),
    }


def format_summary(label: str, samples: Sequence[float]) -> str:
    s = summarize(samples)
    return (
        f"{label:<6} min {s['min']:7.2f} ms | avg {s['avg']:7.2f} ms | "
        f"p50 {s['p50']:7.2f} ms | p95 {s['p95']:7.2f} ms | max {s['max']:7.2f} ms"
    )
