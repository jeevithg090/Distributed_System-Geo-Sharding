# redis_cache.py
# Redis caching layer for GeoShardDB

import redis
import json
import os
import time

RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.environ.get('RUNNING_IN_DOCKER') == 'true'
REDIS_HOST = 'redis' if RUNNING_IN_DOCKER else 'localhost'
REDIS_PORT = 6379

class RedisCache:
    def __init__(self):
        self.client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True # Decode to unicode strings automatically
        )
        # In-memory counters for fallback stats if Redis stats not used
        self.hits = 0
        self.misses = 0

    def _make_key(self, region, key):
        return f"{region}:user:{key}"

    def get(self, region, key):
        try:
            full_key = self._make_key(region, key)
            val = self.client.get(full_key)
            if val is not None:
                self.hits += 1
                return json.loads(val)
            self.misses += 1
            return None
        except Exception as e:
            print(f"Redis get error: {e}")
            # Degrade gracefully on cache failure (treat as miss)
            return None

    def set(self, region, key, value, ttl=300):
        try:
            full_key = self._make_key(region, key)
            serialized_val = json.dumps(value)
            self.client.setex(full_key, ttl, serialized_val)
            return True
        except Exception as e:
            print(f"Redis set error: {e}")
            return False

    def invalidate(self, region, key):
        try:
            full_key = self._make_key(region, key)
            self.client.delete(full_key)
            return True
        except Exception as e:
            print(f"Redis delete error: {e}")
            return False

    def invalidate_region(self, region):
        try:
            # Find all keys matching region namespace and delete them
            pattern = f"{region}:user:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
            return True
        except Exception as e:
            print(f"Redis bulk delete error: {e}")
            return False

    def flush_all(self):
        try:
            self.client.flushdb()
            return True
        except Exception as e:
            print(f"Redis flush error: {e}")
            return False

    def get_stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0
        
        # Try to get Redis system stats as well
        try:
            info = self.client.info()
            redis_connected = True
            redis_version = info.get('redis_version')
            used_memory_human = info.get('used_memory_human')
            evicted_keys = info.get('evicted_keys', 0)
        except Exception:
            redis_connected = False
            redis_version = "unknown"
            used_memory_human = "0B"
            evicted_keys = 0

        return {
            "cache_connected": redis_connected,
            "redis_version": redis_version,
            "used_memory": used_memory_human,
            "evicted_keys": evicted_keys,
            "stats": {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": round(hit_rate, 2),
                "total_requests": total
            }
        }
