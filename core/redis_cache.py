"""Redis cache-aside layer for user lookups.

Keys are namespaced ``{region}:user:{user_id}``. Hit/miss counters live in
Redis so that stats are shared by every API replica behind the load balancer.
Any Redis failure degrades to a cache miss instead of failing the request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from core.config import REGIONS

logger = logging.getLogger(__name__)

HITS_KEY = "cache:stats:hits"
MISSES_KEY = "cache:stats:misses"


class RedisCache:
    def __init__(self, client: redis.Redis, default_ttl: int = 300) -> None:
        self.client = client
        self.default_ttl = default_ttl

    @staticmethod
    def make_key(region: str, key: str | int) -> str:
        return f"{region}:user:{key}"

    def _incr(self, counter: str) -> None:
        try:
            self.client.incr(counter)
        except redis.RedisError as exc:
            logger.debug("Unable to update cache counter %s: %s", counter, exc)

    def get(self, region: str, key: str | int) -> dict[str, Any] | None:
        try:
            raw = self.client.get(self.make_key(region, key))
        except redis.RedisError as exc:
            logger.warning("Redis GET failed, treating as miss: %s", exc)
            return None
        if raw is None:
            self._incr(MISSES_KEY)
            return None
        self._incr(HITS_KEY)
        try:
            value: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Discarding corrupt cache entry for %s", self.make_key(region, key))
            return None
        return value

    def set(self, region: str, key: str | int, value: dict[str, Any], ttl: int | None = None) -> bool:
        try:
            self.client.set(self.make_key(region, key), json.dumps(value), ex=ttl or self.default_ttl)
        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("Redis SET failed: %s", exc)
            return False
        return True

    def invalidate(self, region: str, key: str | int) -> bool:
        try:
            self.client.delete(self.make_key(region, key))
        except redis.RedisError as exc:
            logger.warning("Redis DELETE failed: %s", exc)
            return False
        return True

    def invalidate_region(self, region: str) -> int:
        """Delete every cached user for ``region``. Returns the number of keys removed."""
        deleted = 0
        try:
            batch: list[str] = []
            for cache_key in self.client.scan_iter(match=f"{region}:user:*", count=500):
                batch.append(cache_key)
                if len(batch) >= 500:
                    deleted += int(self.client.delete(*batch))
                    batch.clear()
            if batch:
                deleted += int(self.client.delete(*batch))
        except redis.RedisError as exc:
            logger.warning("Redis bulk delete failed: %s", exc)
        return deleted

    def flush_all(self) -> int:
        """Remove all cached users (and reset counters) without touching locks or queues."""
        deleted = sum(self.invalidate_region(region) for region in REGIONS)
        try:
            self.client.delete(HITS_KEY, MISSES_KEY)
        except redis.RedisError as exc:
            logger.warning("Unable to reset cache counters: %s", exc)
        return deleted

    def get_stats(self) -> dict[str, Any]:
        connected = True
        try:
            hits = int(self.client.get(HITS_KEY) or 0)
            misses = int(self.client.get(MISSES_KEY) or 0)
        except redis.RedisError:
            hits = misses = 0
            connected = False

        info: dict[str, Any] = {}
        if connected:
            try:
                info = dict(self.client.info())
            except redis.RedisError as exc:  # e.g. INFO disabled by an ACL
                logger.debug("Redis INFO unavailable: %s", exc)

        total = hits + misses
        return {
            "cache_connected": connected,
            "redis_version": info.get("redis_version", "unknown"),
            "used_memory": info.get("used_memory_human", "unknown"),
            "evicted_keys": info.get("evicted_keys", 0),
            "stats": {
                "hits": hits,
                "misses": misses,
                "hit_rate_pct": round(hits / total * 100, 2) if total else 0.0,
                "total_requests": total,
            },
        }
