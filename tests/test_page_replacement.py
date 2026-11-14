import random

import pytest

from os_concepts.page_replacement import ALGORITHMS, CacheSimulator

BELADY_TRACE = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    ("algorithm", "capacity", "faults"),
    [
        ("fifo", 3, 9),
        ("fifo", 4, 10),  # Bélády's anomaly: more frames, more faults
        ("lru", 3, 10),
        ("lru", 4, 8),
        ("optimal", 3, 7),
        ("optimal", 4, 6),
    ],
)
def test_textbook_fault_counts(algorithm, capacity, faults):
    result = CacheSimulator(capacity).simulate(algorithm, BELADY_TRACE)
    assert result["faults"] == faults
    assert result["hits"] == len(BELADY_TRACE) - faults


def test_lfu_evicts_least_frequent_then_least_recent():
    # 1 is used twice; 2 and 3 once each (2 less recently) -> 2 is evicted for 4
    result = CacheSimulator(3).simulate_lfu([1, 1, 2, 3, 4])
    assert result["history"][-1]["evicted"] == 2
    assert sorted(result["history"][-1]["cache"]) == [1, 3, 4]


def test_clock_gives_second_chance():
    # all frames referenced -> the hand clears bits and evicts the oldest (1)
    result = CacheSimulator(3).simulate_clock([1, 2, 3, 4])
    assert result["history"][-1]["evicted"] == 1
    # 2 referenced again; next miss evicts 3 because 2 got a second chance
    result = CacheSimulator(3).simulate_clock([1, 2, 3, 4, 2, 5])
    assert result["history"][-1]["evicted"] == 3


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_history_is_consistent(algorithm):
    capacity = 3
    result = CacheSimulator(capacity).simulate(algorithm, BELADY_TRACE)
    evictions = [h["evicted"] for h in result["history"] if h["evicted"] is not None]
    assert len(evictions) == result["evictions_count"] == max(0, result["faults"] - capacity)
    for step in result["history"]:
        assert step["item"] in step["cache"]
        assert len(step["cache"]) <= capacity
        if step["status"] == "HIT":
            assert step["evicted"] is None


@pytest.mark.parametrize("seed", range(20))
def test_optimal_is_a_lower_bound(seed):
    rng = random.Random(seed)
    trace = [rng.randint(1, 8) for _ in range(60)]
    capacity = rng.randint(1, 5)
    sim = CacheSimulator(capacity)
    optimal = sim.simulate("optimal", trace)["faults"]
    for algorithm in ALGORITHMS:
        assert sim.simulate(algorithm, trace)["faults"] >= optimal


def test_empty_trace_and_validation():
    assert CacheSimulator(2).simulate("lru", [])["hit_rate_pct"] == 0
    with pytest.raises(ValueError):
        CacheSimulator(0)
    with pytest.raises(ValueError):
        CacheSimulator(2).simulate("random", [1])
