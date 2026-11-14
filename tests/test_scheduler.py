import copy
import itertools

import pytest

from os_concepts.scheduler import ALGORITHMS, Request, RequestScheduler, generate_random_workload, summarize


def textbook_workload():
    # (id, arrival, burst, priority)
    spec = [("P1", 0, 8, 1), ("P2", 1, 4, 3), ("P3", 2, 9, 2), ("P4", 3, 5, 3)]
    return [Request(rid, 1, "us", prio, burst, arrival) for rid, arrival, burst, prio in spec]


def waits(requests):
    return {r.request_id: r.waiting_time for r in requests}


def test_fcfs():
    done, timeline = RequestScheduler().run("fcfs", textbook_workload())
    assert waits(done) == {"P1": 0, "P2": 7, "P3": 10, "P4": 18}
    assert summarize(done)["avg_waiting_time"] == 8.75
    assert [s["request_id"] for s in timeline] == ["P1", "P2", "P3", "P4"]


def test_sjf():
    done, _ = RequestScheduler().run("sjf", textbook_workload())
    assert [r.request_id for r in done] == ["P1", "P2", "P4", "P3"]
    assert summarize(done)["avg_waiting_time"] == 7.75


def test_priority():
    done, _ = RequestScheduler().run("priority", textbook_workload())
    # P1 runs first (only arrival), then priority-3 jobs by arrival, then P3
    assert [r.request_id for r in done] == ["P1", "P2", "P4", "P3"]


def test_round_robin():
    done, timeline = RequestScheduler().run("rr", textbook_workload())
    assert waits(done) == {"P1": 12, "P2": 3, "P3": 15, "P4": 17}
    assert all(s["end"] - s["start"] <= 4 for s in timeline)


def test_mlfq_demotes_long_jobs():
    req = Request("R", 1, "us", 1, cost_units=10, arrival_time=0)
    done, timeline = RequestScheduler().schedule_mlfq([req])
    assert [s["queue"] for s in timeline] == [0, 1, 2, 2]
    assert done[0].completion_time == 10
    assert done[0].waiting_time == 0


def test_idle_gap_is_skipped():
    reqs = [Request("A", 1, "us", 1, 2, 0), Request("B", 1, "eu", 1, 3, 10)]
    for algorithm in ALGORITHMS:
        done, _ = RequestScheduler().run(algorithm, copy.deepcopy(reqs))
        by_id = {r.request_id: r for r in done}
        assert by_id["B"].start_time == 10
        assert by_id["B"].completion_time == 13


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_invariants_on_random_workloads(algorithm):
    for seed in range(10):
        workload = generate_random_workload(25, seed=seed)
        done, timeline = RequestScheduler().run(algorithm, workload)
        assert len(done) == 25
        assert sum(s["end"] - s["start"] for s in timeline) == sum(r.cost_units for r in workload)
        for r in done:
            assert r.waiting_time >= 0
            assert r.turnaround_time == r.waiting_time + r.cost_units
        # the CPU never runs two slices at once
        ordered = sorted(timeline, key=lambda s: s["start"])
        assert all(a["end"] <= b["start"] for a, b in itertools.pairwise(ordered))


def test_workload_is_reproducible_with_seed():
    a = [r.to_dict() for r in generate_random_workload(10, seed=7)]
    b = [r.to_dict() for r in generate_random_workload(10, seed=7)]
    assert a == b


def test_unknown_algorithm():
    with pytest.raises(ValueError):
        RequestScheduler().run("lottery", [])
