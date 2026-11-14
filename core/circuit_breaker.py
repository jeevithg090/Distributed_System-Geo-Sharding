"""Per-region circuit breakers with cross-region failover selection."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from enum import StrEnum

logger = logging.getLogger(__name__)


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF-OPEN"


class CircuitBreaker:
    """Classic three-state circuit breaker.

    * ``CLOSED``: requests flow; consecutive failures are counted.
    * ``OPEN``: after ``failure_threshold`` failures, requests are rejected until
      ``recovery_timeout`` seconds have passed.
    * ``HALF-OPEN``: a trial request is let through; success closes the
      breaker, failure re-opens it immediately.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._state

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    def allow_request(self) -> bool:
        """Return True if a request may be sent to this breaker's backend."""
        with self._lock:
            if self._state is BreakerState.OPEN:
                if self._clock() - self._opened_at >= self.recovery_timeout:
                    self._state = BreakerState.HALF_OPEN
                    logger.info("%s breaker HALF-OPEN", self.name.upper())
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state is not BreakerState.CLOSED:
                logger.info("%s breaker CLOSED", self.name.upper())
            self._state = BreakerState.CLOSED
            self._failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state is BreakerState.HALF_OPEN or self._failures >= self.failure_threshold:
                if self._state is not BreakerState.OPEN:
                    logger.warning("%s breaker OPEN", self.name.upper())
                self._state = BreakerState.OPEN
                self._opened_at = self._clock()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"state": self._state.value, "failures": self._failures}


class BreakerRegistry:
    """Holds one breaker per region and picks a region to serve a request."""

    def __init__(
        self,
        regions: Iterable[str],
        failure_threshold: int = 3,
        recovery_timeout: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.breakers: dict[str, CircuitBreaker] = {
            region: CircuitBreaker(region, failure_threshold, recovery_timeout, clock) for region in regions
        }

    def __getitem__(self, region: str) -> CircuitBreaker:
        return self.breakers[region]

    def select_region(self, preferred: str, exclude: Iterable[str] = ()) -> str | None:
        """Return ``preferred`` if its breaker admits traffic, else a healthy fallback.

        Regions in ``exclude`` (e.g. ones that already failed during this request)
        are skipped. Returns ``None`` when no region can take the request.
        """
        excluded = set(exclude)
        if preferred not in excluded and self.breakers[preferred].allow_request():
            return preferred
        for region, breaker in self.breakers.items():
            if region != preferred and region not in excluded and breaker.state is BreakerState.CLOSED:
                logger.info("Failing over from %s to %s", preferred.upper(), region.upper())
                return region
        return None

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {region: breaker.snapshot() for region, breaker in self.breakers.items()}
