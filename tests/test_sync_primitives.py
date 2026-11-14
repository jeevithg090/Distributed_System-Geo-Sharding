import fakeredis
import pytest

from os_concepts.sync_primitives import DeadlockDetector, DistributedMutex, DistributedSemaphore


def test_mutex_is_exclusive_and_owner_checked(redis_client):
    a = DistributedMutex(redis_client, "us", owner="client-a")
    b = DistributedMutex(redis_client, "us", owner="client-b")
    assert a.acquire(acquire_timeout=0, lock_ttl=5)
    assert not b.acquire(acquire_timeout=0.1, lock_ttl=5)
    assert b.get_owner() == "client-a"
    assert not b.release(), "a non-owner must not be able to release the lock"
    assert a.release()
    assert b.acquire(acquire_timeout=0)


def test_mutex_is_reentrant_for_same_owner(redis_client):
    m = DistributedMutex(redis_client, "eu", owner="me")
    assert m.acquire(acquire_timeout=0)
    assert DistributedMutex(redis_client, "eu", owner="me").acquire(acquire_timeout=0)


def test_mutex_expires(redis_client):
    m = DistributedMutex(redis_client, "asia", owner="me")
    assert m.acquire(acquire_timeout=0, lock_ttl=5)
    redis_client.delete(m.lock_name)  # simulate TTL expiry
    assert DistributedMutex(redis_client, "asia", owner="other").acquire(acquire_timeout=0)


def test_semaphore_limits_holders(redis_client):
    holders = [DistributedSemaphore(redis_client, "us", limit=2) for _ in range(3)]
    assert holders[0].acquire(timeout=0)
    assert holders[1].acquire(timeout=0)
    assert not holders[2].acquire(timeout=0.1)
    assert holders[0].get_current_count() == 2
    assert holders[0].release()
    assert holders[2].acquire(timeout=0)


def test_semaphore_expires_stale_holders(redis_client):
    stale = DistributedSemaphore(redis_client, "eu", limit=1, ttl=30)
    redis_client.zadd(stale.sem_name, {"ghost": 1.0})  # acquired long ago
    assert stale.acquire(timeout=0)
    assert stale.get_current_count() == 1


def test_semaphore_validation(redis_client):
    with pytest.raises(ValueError):
        DistributedSemaphore(redis_client, "us", limit=0)


@pytest.fixture(params=["memory", "redis"])
def detector(request):
    if request.param == "memory":
        return DeadlockDetector()
    return DeadlockDetector(fakeredis.FakeRedis(decode_responses=True))


def test_detects_three_way_cycle(detector):
    for tx, held, wanted in (("T1", "a", "b"), ("T2", "b", "c"), ("T3", "c", "a")):
        detector.register_lock_holder(tx, held)
        detector.register_lock_request(tx, wanted)
    result = detector.detect_deadlock()
    assert result["deadlock_detected"]
    assert sorted(result["cycle"]) == ["T1", "T2", "T3"]
    assert result["resolution_victim"] in result["cycle"]


def test_chain_without_cycle(detector):
    detector.register_lock_holder("T1", "a")
    detector.register_lock_holder("T2", "b")
    detector.register_lock_request("T1", "b")
    detector.register_lock_request("T3", "a")
    assert detector.graph == {"T1": ["T2"], "T3": ["T1"]}
    assert detector.detect_deadlock() == {"deadlock_detected": False, "cycle": []}


def test_release_breaks_cycle(detector):
    detector.register_lock_holder("T1", "a")
    detector.register_lock_holder("T2", "b")
    detector.register_lock_request("T1", "b")
    detector.register_lock_request("T2", "a")
    assert detector.detect_deadlock()["deadlock_detected"]
    detector.release_lock("T2", "b")
    assert not detector.detect_deadlock()["deadlock_detected"]


def test_acquiring_clears_wait_edge(detector):
    detector.register_lock_request("T1", "a")
    detector.register_lock_holder("T1", "a")
    assert detector.waiting_for_resource == {}
    detector.reset()
    assert detector.resource_held_by == {}


def test_redis_detector_is_shared_between_instances():
    client = fakeredis.FakeRedis(decode_responses=True)
    replica_a, replica_b = DeadlockDetector(client), DeadlockDetector(client)
    replica_a.register_lock_holder("T1", "a")
    replica_a.register_lock_holder("T2", "b")
    replica_b.register_lock_request("T1", "b")
    replica_b.register_lock_request("T2", "a")
    assert replica_a.detect_deadlock()["deadlock_detected"]
