"""Distributed synchronisation primitives on Redis, plus a wait-for-graph deadlock detector."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import redis

_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

# Atomically: drop expired holders, then join only if below the limit.
_SEMAPHORE_ACQUIRE = """
redis.call('zremrangebyscore', KEYS[1], '-inf', ARGV[1])
if redis.call('zscore', KEYS[1], ARGV[3]) then
    redis.call('zadd', KEYS[1], ARGV[2], ARGV[3])
    return 1
end
if redis.call('zcard', KEYS[1]) < tonumber(ARGV[4]) then
    redis.call('zadd', KEYS[1], ARGV[2], ARGV[3])
    return 1
end
return 0
"""


class DistributedMutex:
    """Single-instance Redis lock: ``SET key token NX PX ttl`` + owner-checked release.

    The lock value is the owner's token, so only the holder can release it.
    """

    def __init__(self, client: redis.Redis, name: str, owner: str | None = None) -> None:
        self.client = client
        self.lock_name = f"lock:mutex:{name}"
        self.owner = owner or str(uuid.uuid4())

    def acquire(self, acquire_timeout: float = 5, lock_ttl: float = 10) -> bool:
        deadline = time.monotonic() + acquire_timeout
        while True:
            if self.client.set(self.lock_name, self.owner, px=int(lock_ttl * 1000), nx=True):
                return True
            if self.get_owner() == self.owner:  # re-entrant for the same owner
                self.client.pexpire(self.lock_name, int(lock_ttl * 1000))
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def release(self) -> bool:
        return bool(self.client.eval(_RELEASE_IF_OWNER, 1, self.lock_name, self.owner))

    def get_owner(self) -> str | None:
        owner = self.client.get(self.lock_name)
        return None if owner is None else str(owner)


class DistributedSemaphore:
    """Counting semaphore on a Redis sorted set (member = holder, score = acquire time).

    Holders that do not release within ``ttl`` seconds are considered expired.
    """

    def __init__(
        self,
        client: redis.Redis,
        name: str,
        limit: int,
        ttl: float = 30,
        owner_id: str | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.client = client
        self.sem_name = f"sem:{name}"
        self.limit = limit
        self.ttl = ttl
        self.owner_id = owner_id or str(uuid.uuid4())

    def acquire(self, timeout: float = 5) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            now = time.time()
            granted = self.client.eval(
                _SEMAPHORE_ACQUIRE, 1, self.sem_name, now - self.ttl, now, self.owner_id, self.limit
            )
            if granted:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def release(self) -> bool:
        return bool(self.client.zrem(self.sem_name, self.owner_id))

    def get_current_count(self) -> int:
        self.client.zremrangebyscore(self.sem_name, "-inf", time.time() - self.ttl)
        return int(self.client.zcard(self.sem_name))


class DeadlockDetector:
    """Deadlock detection on a wait-for graph (edge ``A -> B``: A waits for a lock B holds).

    State lives in memory by default. Pass a Redis client to keep it in two Redis
    hashes instead, so every API replica behind the load balancer sees one graph.
    """

    HELD_KEY = "deadlock:held_by"
    WAITING_KEY = "deadlock:waiting_for"

    def __init__(self, client: redis.Redis | None = None) -> None:
        self.client = client
        self._lock = threading.Lock()
        self._held: dict[str, str] = {}
        self._waiting: dict[str, str] = {}

    @property
    def resource_held_by(self) -> dict[str, str]:
        if self.client is not None:
            return {str(k): str(v) for k, v in self.client.hgetall(self.HELD_KEY).items()}
        with self._lock:
            return dict(self._held)

    @property
    def waiting_for_resource(self) -> dict[str, str]:
        if self.client is not None:
            return {str(k): str(v) for k, v in self.client.hgetall(self.WAITING_KEY).items()}
        with self._lock:
            return dict(self._waiting)

    @property
    def graph(self) -> dict[str, list[str]]:
        held = self.resource_held_by
        graph: dict[str, list[str]] = {}
        for tx, resource in sorted(self.waiting_for_resource.items()):
            holder = held.get(resource)
            if holder and holder != tx:
                graph.setdefault(tx, []).append(holder)
        return graph

    def register_lock_holder(self, transaction_id: str, resource: str) -> None:
        if self.client is not None:
            pipe = self.client.pipeline()
            pipe.hset(self.HELD_KEY, resource, transaction_id)
            if self.client.hget(self.WAITING_KEY, transaction_id) == resource:
                pipe.hdel(self.WAITING_KEY, transaction_id)
            pipe.execute()
            return
        with self._lock:
            self._held[resource] = transaction_id
            if self._waiting.get(transaction_id) == resource:
                del self._waiting[transaction_id]

    def register_lock_request(self, transaction_id: str, resource: str) -> None:
        if self.client is not None:
            self.client.hset(self.WAITING_KEY, transaction_id, resource)
            return
        with self._lock:
            self._waiting[transaction_id] = resource

    def release_lock(self, transaction_id: str, resource: str) -> None:
        if self.client is not None:
            if self.client.hget(self.HELD_KEY, resource) == transaction_id:
                self.client.hdel(self.HELD_KEY, resource)
            if self.client.hget(self.WAITING_KEY, transaction_id) == resource:
                self.client.hdel(self.WAITING_KEY, transaction_id)
            return
        with self._lock:
            if self._held.get(resource) == transaction_id:
                del self._held[resource]
            if self._waiting.get(transaction_id) == resource:
                del self._waiting[transaction_id]

    def reset(self) -> None:
        if self.client is not None:
            self.client.delete(self.HELD_KEY, self.WAITING_KEY)
            return
        with self._lock:
            self._held.clear()
            self._waiting.clear()

    def detect_deadlock(self) -> dict[str, Any]:
        """Iterative DFS cycle search. Returns the cycle and a suggested victim."""
        graph = self.graph
        WHITE, GREY, BLACK = 0, 1, 2
        color: dict[str, int] = {}

        for root in graph:
            if color.get(root, WHITE) != WHITE:
                continue
            path: list[str] = []
            stack: list[tuple[str, int]] = [(root, 0)]
            while stack:
                node, edge_index = stack.pop()
                if edge_index == 0:
                    color[node] = GREY
                    path.append(node)
                neighbours = graph.get(node, [])
                if edge_index < len(neighbours):
                    stack.append((node, edge_index + 1))
                    nxt = neighbours[edge_index]
                    state = color.get(nxt, WHITE)
                    if state == GREY:
                        cycle = path[path.index(nxt) :]
                        return {"deadlock_detected": True, "cycle": cycle, "resolution_victim": cycle[0]}
                    if state == WHITE:
                        stack.append((nxt, 0))
                else:
                    color[node] = BLACK
                    path.pop()
        return {"deadlock_detected": False, "cycle": []}
