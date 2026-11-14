import redis

from core.redis_cache import RedisCache


class BrokenRedis:
    """Every command fails as if Redis were down."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise redis.ConnectionError("redis down")

        return fail


def test_cache_aside_round_trip_and_stats(redis_client):
    cache = RedisCache(redis_client, default_ttl=60)
    assert cache.get("us", 1) is None
    assert cache.set("us", 1, {"user_id": 1, "username": "ada"})
    assert cache.get("us", 1) == {"user_id": 1, "username": "ada"}
    assert 0 < redis_client.ttl("us:user:1") <= 60
    stats = cache.get_stats()["stats"]
    assert (stats["hits"], stats["misses"], stats["hit_rate_pct"]) == (1, 1, 50.0)


def test_stats_are_shared_across_instances(redis_client):
    RedisCache(redis_client).get("eu", 5)
    RedisCache(redis_client).get("eu", 6)
    assert RedisCache(redis_client).get_stats()["stats"]["misses"] == 2


def test_invalidate_region_only_touches_that_region(redis_client):
    cache = RedisCache(redis_client)
    for i in range(3):
        cache.set("us", i, {"i": i})
    cache.set("eu", 1, {"i": 1})
    assert cache.invalidate_region("us") == 3
    assert cache.get("eu", 1) == {"i": 1}


def test_flush_all_keeps_locks_and_queues(redis_client):
    cache = RedisCache(redis_client)
    cache.set("asia", 7, {"i": 7})
    redis_client.set("lock:mutex:us", "owner")
    redis_client.lpush("queue:db-jobs", "job")
    assert cache.flush_all() == 1
    assert redis_client.get("lock:mutex:us") == "owner"
    assert redis_client.llen("queue:db-jobs") == 1


def test_corrupt_entry_is_a_miss(redis_client):
    redis_client.set("us:user:9", "{not json")
    assert RedisCache(redis_client).get("us", 9) is None


def test_degrades_gracefully_when_redis_is_down():
    cache = RedisCache(BrokenRedis())
    assert cache.get("us", 1) is None
    assert cache.set("us", 1, {"a": 1}) is False
    assert cache.invalidate("us", 1) is False
    assert cache.flush_all() == 0
    assert cache.get_stats()["cache_connected"] is False
