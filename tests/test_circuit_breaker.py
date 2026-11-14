import pytest

from core.circuit_breaker import BreakerRegistry, BreakerState, CircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


def test_opens_after_threshold_and_recovers(clock):
    breaker = CircuitBreaker("us", failure_threshold=3, recovery_timeout=15, clock=clock)
    for _ in range(2):
        breaker.record_failure()
        assert breaker.state is BreakerState.CLOSED
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow_request()

    clock.now += 15
    assert breaker.allow_request()
    assert breaker.state is BreakerState.HALF_OPEN

    breaker.record_success()
    assert breaker.state is BreakerState.CLOSED
    assert breaker.failures == 0


def test_half_open_failure_reopens_immediately(clock):
    breaker = CircuitBreaker("eu", failure_threshold=3, recovery_timeout=10, clock=clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now += 10
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.state is BreakerState.OPEN
    clock.now += 9
    assert not breaker.allow_request()


def test_success_resets_failure_count(clock):
    breaker = CircuitBreaker("asia", failure_threshold=3, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state is BreakerState.CLOSED


def test_invalid_threshold():
    with pytest.raises(ValueError):
        CircuitBreaker("us", failure_threshold=0)


def test_registry_fails_over_to_closed_region(clock):
    registry = BreakerRegistry(["us", "eu", "asia"], failure_threshold=1, recovery_timeout=30, clock=clock)
    assert registry.select_region("us") == "us"
    registry["us"].record_failure()
    assert registry.select_region("us") == "eu"
    registry["eu"].record_failure()
    assert registry.select_region("us") == "asia"
    registry["asia"].record_failure()
    assert registry.select_region("us") is None
    clock.now += 30
    assert registry.select_region("us") == "us"  # half-open trial goes to the home region


def test_registry_respects_exclusions(clock):
    registry = BreakerRegistry(["us", "eu", "asia"], clock=clock)
    assert registry.select_region("us", exclude=["us"]) == "eu"
    assert registry.select_region("us", exclude=["us", "eu"]) == "asia"
    assert registry.select_region("us", exclude=["us", "eu", "asia"]) is None


def test_snapshot_shape(clock):
    registry = BreakerRegistry(["us", "eu"], clock=clock)
    registry["eu"].record_failure()
    assert registry.snapshot() == {
        "us": {"state": "CLOSED", "failures": 0},
        "eu": {"state": "CLOSED", "failures": 1},
    }
