"""Bounded producer/consumer work queue on a Redis list.

Producers ``LPUSH`` and consumers ``BRPOP`` (FIFO order). The bound is enforced
atomically with a Lua script, so concurrent producers on different API
replicas cannot overshoot ``max_size``; a full queue applies back-pressure by
rejecting the job.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import redis

logger = logging.getLogger(__name__)

_BOUNDED_PUSH = """
if redis.call('llen', KEYS[1]) >= tonumber(ARGV[1]) then
    return -1
end
return redis.call('lpush', KEYS[1], ARGV[2])
"""

BACKPRESSURE_KEY_SUFFIX = ":backpressure_events"
PROCESSED_KEY_SUFFIX = ":processed_jobs"


class WorkQueue:
    def __init__(
        self,
        client: redis.Redis,
        name: str = "db-jobs",
        max_size: int = 50,
        job_duration: float = 0.05,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self.client = client
        self.queue_key = f"queue:{name}"
        self.max_size = max_size
        self.job_duration = job_duration
        self._consumers: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def produce(self, job: dict[str, Any]) -> tuple[bool, str]:
        """Enqueue ``job``. Returns ``(accepted, status)``."""
        serialized = json.dumps(
            {
                "job_id": job.get("job_id"),
                "action": job.get("action"),
                "payload": job.get("payload"),
                "timestamp": time.time(),
            }
        )
        result = self.client.eval(_BOUNDED_PUSH, 1, self.queue_key, self.max_size, serialized)
        if int(result) < 0:
            self.client.incr(self.queue_key + BACKPRESSURE_KEY_SUFFIX)
            return False, "BACKPRESSURE_LIMIT_EXCEEDED"
        return True, "JOB_ENQUEUED"

    def consume(self, timeout: int = 1) -> dict[str, Any] | None:
        """Pop and "process" one job, blocking up to ``timeout`` seconds."""
        item = self.client.brpop([self.queue_key], timeout=timeout)
        if not item:
            return None
        _, raw = item
        job: dict[str, Any] = json.loads(raw)
        time.sleep(self.job_duration)  # simulated work
        self.client.incr(self.queue_key + PROCESSED_KEY_SUFFIX)
        return job

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.consume()
            except redis.RedisError as exc:
                logger.warning("WorkQueue consumer error: %s", exc)
                self._stop_event.wait(1.0)
            except Exception:  # keep the worker alive on bad payloads
                logger.exception("WorkQueue consumer failed to process a job")

    def start_consumers(self, num_threads: int = 2) -> int:
        """Start ``num_threads`` daemon consumer threads. Returns the active count."""
        with self._lock:
            self._stop_event.clear()
            self._consumers = [t for t in self._consumers if t.is_alive()]
            for _ in range(num_threads):
                thread = threading.Thread(
                    target=self._worker,
                    name=f"WorkQueue-Consumer-{len(self._consumers) + 1}",
                    daemon=True,
                )
                thread.start()
                self._consumers.append(thread)
            logger.info("Running %d consumer threads for %s", len(self._consumers), self.queue_key)
            return len(self._consumers)

    def stop_consumers(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._stop_event.set()
            for thread in self._consumers:
                thread.join(timeout=timeout)
            self._consumers = []

    @property
    def active_consumers(self) -> int:
        with self._lock:
            return sum(1 for t in self._consumers if t.is_alive())

    def get_stats(self) -> dict[str, Any]:
        depth = int(self.client.llen(self.queue_key))
        return {
            "queue_name": self.queue_key,
            "queue_depth": depth,
            "max_capacity": self.max_size,
            "processed_jobs_total": int(self.client.get(self.queue_key + PROCESSED_KEY_SUFFIX) or 0),
            "backpressure_events_total": int(self.client.get(self.queue_key + BACKPRESSURE_KEY_SUFFIX) or 0),
            "active_consumers": self.active_consumers,
            "backpressure_active": depth >= self.max_size,
        }
