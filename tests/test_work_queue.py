import pytest

from os_concepts.work_queue import WorkQueue


def test_fifo_order_and_stats(redis_client):
    q = WorkQueue(redis_client, name="t", max_size=10, job_duration=0)
    for i in range(3):
        assert q.produce({"job_id": i, "action": "noop", "payload": {}}) == (True, "JOB_ENQUEUED")
    assert [q.consume(timeout=1)["job_id"] for _ in range(3)] == [0, 1, 2]
    stats = q.get_stats()
    assert stats["queue_depth"] == 0
    assert stats["processed_jobs_total"] == 3


def test_backpressure_when_full(redis_client):
    q = WorkQueue(redis_client, name="t", max_size=2, job_duration=0)
    assert q.produce({"job_id": 1})[0]
    assert q.produce({"job_id": 2})[0]
    assert q.produce({"job_id": 3}) == (False, "BACKPRESSURE_LIMIT_EXCEEDED")
    stats = q.get_stats()
    assert stats["queue_depth"] == 2
    assert stats["backpressure_events_total"] == 1
    assert stats["backpressure_active"]


def test_consumer_threads_drain_queue(redis_client):
    q = WorkQueue(redis_client, name="t", max_size=50, job_duration=0)
    for i in range(10):
        q.produce({"job_id": i})
    assert q.start_consumers(2) == 2
    try:
        import time

        deadline = time.monotonic() + 5
        while q.get_stats()["processed_jobs_total"] < 10 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        q.stop_consumers()
    assert q.get_stats()["processed_jobs_total"] == 10
    assert q.active_consumers == 0


def test_validation(redis_client):
    with pytest.raises(ValueError):
        WorkQueue(redis_client, max_size=0)
