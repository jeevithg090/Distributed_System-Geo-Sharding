"""Request scheduler simulator: FCFS, SJF, Priority, Round Robin and MLFQ.

Each request has an ``arrival_time`` and a ``cost_units`` (simulated execution
time). Every ``schedule_*`` method mutates the requests' timing fields and
returns ``(completed_requests, timeline)`` where ``timeline`` lists the
execution slices in order.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

ALGORITHMS = ("fcfs", "sjf", "priority", "rr", "mlfq")


@dataclass
class Request:
    request_id: str
    user_id: int
    region: str
    priority: int  # 1 = low, 2 = medium, 3 = high
    cost_units: int
    arrival_time: int
    remaining_cost: int = field(init=False)
    start_time: int | None = None
    completion_time: int | None = None
    waiting_time: int = 0
    turnaround_time: int = 0

    def __post_init__(self) -> None:
        if self.cost_units < 1:
            raise ValueError("cost_units must be positive")
        self.remaining_cost = self.cost_units

    def reset(self) -> None:
        self.remaining_cost = self.cost_units
        self.start_time = None
        self.completion_time = None
        self.waiting_time = 0
        self.turnaround_time = 0

    def finish(self, now: int) -> None:
        self.completion_time = now
        self.turnaround_time = now - self.arrival_time
        self.waiting_time = self.turnaround_time - self.cost_units

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "region": self.region,
            "priority": self.priority,
            "cost_units": self.cost_units,
            "arrival_time": self.arrival_time,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "waiting_time": self.waiting_time,
            "turnaround_time": self.turnaround_time,
        }


def _slice(req: Request, start: int, end: int, queue: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "request_id": req.request_id,
        "start": start,
        "end": end,
        "user_id": req.user_id,
        "region": req.region,
    }
    if queue is not None:
        entry["queue"] = queue
    return entry


class RequestScheduler:
    def run(self, algorithm: str, requests: Sequence[Request]) -> tuple[list[Request], list[dict[str, Any]]]:
        """Dispatch by name (``fcfs``, ``sjf``, ``priority``, ``rr``, ``mlfq``)."""
        handlers: dict[str, Callable[[Sequence[Request]], tuple[list[Request], list[dict[str, Any]]]]] = {
            "fcfs": self.schedule_fcfs,
            "sjf": self.schedule_sjf,
            "priority": self.schedule_priority,
            "rr": self.schedule_rr,
            "mlfq": self.schedule_mlfq,
        }
        try:
            handler = handlers[algorithm.lower()]
        except KeyError as exc:
            raise ValueError(f"Unknown scheduling algorithm: {algorithm}") from exc
        for req in requests:
            req.reset()
        return handler(requests)

    def schedule_fcfs(self, requests: Sequence[Request]) -> tuple[list[Request], list[dict[str, Any]]]:
        """First Come First Served."""
        ordered = sorted(requests, key=lambda r: r.arrival_time)
        now = 0
        timeline = []
        for req in ordered:
            now = max(now, req.arrival_time)
            req.start_time = now
            now += req.cost_units
            req.finish(now)
            timeline.append(_slice(req, req.start_time, now))
        return ordered, timeline

    def _non_preemptive(
        self, requests: Sequence[Request], key: Callable[[Request], Any]
    ) -> tuple[list[Request], list[dict[str, Any]]]:
        pending = sorted(requests, key=lambda r: r.arrival_time)
        ready: list[Request] = []
        completed: list[Request] = []
        timeline = []
        now = 0
        i = 0
        while len(completed) < len(pending):
            while i < len(pending) and pending[i].arrival_time <= now:
                ready.append(pending[i])
                i += 1
            if not ready:
                now = pending[i].arrival_time
                continue
            ready.sort(key=key)
            req = ready.pop(0)
            req.start_time = now
            now += req.cost_units
            req.finish(now)
            completed.append(req)
            timeline.append(_slice(req, req.start_time, now))
        return completed, timeline

    def schedule_sjf(self, requests: Sequence[Request]) -> tuple[list[Request], list[dict[str, Any]]]:
        """Shortest Job First (non-preemptive); ties go to the earlier arrival."""
        return self._non_preemptive(requests, key=lambda r: (r.cost_units, r.arrival_time))

    def schedule_priority(self, requests: Sequence[Request]) -> tuple[list[Request], list[dict[str, Any]]]:
        """Non-preemptive priority scheduling (higher number = higher priority)."""
        return self._non_preemptive(requests, key=lambda r: (-r.priority, r.arrival_time))

    def schedule_rr(
        self, requests: Sequence[Request], quantum: int = 4
    ) -> tuple[list[Request], list[dict[str, Any]]]:
        """Round Robin with a fixed time quantum."""
        if quantum < 1:
            raise ValueError("quantum must be positive")
        pending = sorted(requests, key=lambda r: r.arrival_time)
        for req in pending:
            req.remaining_cost = req.cost_units
        ready: deque[Request] = deque()
        completed: list[Request] = []
        timeline = []
        now = 0
        i = 0

        def admit() -> None:
            nonlocal i
            while i < len(pending) and pending[i].arrival_time <= now:
                ready.append(pending[i])
                i += 1

        while ready or i < len(pending):
            if not ready:
                now = max(now, pending[i].arrival_time)
                admit()
            req = ready.popleft()
            if req.start_time is None:
                req.start_time = now
            run_for = min(quantum, req.remaining_cost)
            timeline.append(_slice(req, now, now + run_for))
            now += run_for
            req.remaining_cost -= run_for
            admit()  # arrivals during the slice queue ahead of the preempted request
            if req.remaining_cost > 0:
                ready.append(req)
            else:
                req.finish(now)
                completed.append(req)
        return completed, timeline

    def schedule_mlfq(
        self, requests: Sequence[Request], quantums: tuple[int, int] = (2, 6)
    ) -> tuple[list[Request], list[dict[str, Any]]]:
        """Three-level Multilevel Feedback Queue.

        * Q0: round robin with ``quantums[0]`` (new arrivals land here)
        * Q1: round robin with ``quantums[1]`` (demoted from Q0)
        * Q2: FCFS, run one unit at a time so new arrivals can preempt it
        """
        pending = sorted(requests, key=lambda r: r.arrival_time)
        for req in pending:
            req.remaining_cost = req.cost_units
        queues: tuple[deque[Request], deque[Request], deque[Request]] = (deque(), deque(), deque())
        completed: list[Request] = []
        timeline = []
        now = 0
        i = 0

        def admit() -> None:
            nonlocal i
            while i < len(pending) and pending[i].arrival_time <= now:
                queues[0].append(pending[i])
                i += 1

        while any(queues) or i < len(pending):
            if not any(queues):
                now = max(now, pending[i].arrival_time)
                admit()
            level = next(n for n, q in enumerate(queues) if q)
            req = queues[level].popleft()
            if req.start_time is None:
                req.start_time = now
            run_for = min(quantums[level] if level < 2 else 1, req.remaining_cost)
            timeline.append(_slice(req, now, now + run_for, queue=level))
            now += run_for
            req.remaining_cost -= run_for
            admit()
            if req.remaining_cost == 0:
                req.finish(now)
                completed.append(req)
            elif level < 2:
                queues[level + 1].append(req)  # used its full quantum: demote
            else:
                queues[2].appendleft(req)  # FCFS: keep running unless preempted
        return completed, timeline


def summarize(requests: Sequence[Request]) -> dict[str, float]:
    if not requests:
        return {"avg_waiting_time": 0.0, "avg_turnaround_time": 0.0}
    return {
        "avg_waiting_time": round(sum(r.waiting_time for r in requests) / len(requests), 2),
        "avg_turnaround_time": round(sum(r.turnaround_time for r in requests) / len(requests), 2),
    }


def generate_random_workload(count: int = 15, seed: int | None = None) -> list[Request]:
    """Generate ``count`` requests with random arrival gaps, costs and priorities."""
    rng = random.Random(seed)
    requests = []
    arrival = 0
    for i in range(count):
        arrival += rng.randint(0, 3)
        requests.append(
            Request(
                request_id=f"REQ-{i + 1:02d}",
                user_id=rng.randint(1000, 9999),
                region=rng.choice(["us", "eu", "asia"]),
                priority=rng.choice([1, 2, 3]),
                cost_units=rng.choice([2, 4, 6, 8, 12, 16]),
                arrival_time=arrival,
            )
        )
    return requests
