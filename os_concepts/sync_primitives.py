# os_concepts/sync_primitives.py
# Distributed Mutex, Semaphore, and Deadlock Detector using Redis.

import time
import uuid
import redis
import os

RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.environ.get('RUNNING_IN_DOCKER') == 'true'
REDIS_HOST = 'redis' if RUNNING_IN_DOCKER else 'localhost'
REDIS_PORT = 6379

class DistributedMutex:
    """Distributed Mutex using Redis SETNX + TTL (Redlock pattern simplified)"""
    def __init__(self, name):
        self.client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.lock_name = f"lock:mutex:{name}"
        self.lock_value = None

    def acquire(self, acquire_timeout=5, lock_ttl=10):
        self.lock_value = str(uuid.uuid4())
        end_time = time.time() + acquire_timeout
        
        while time.time() < end_time:
            # SET with NX (set if not exists) and PX (millisecond TTL)
            if self.client.set(self.lock_name, self.lock_value, px=int(lock_ttl * 1000), nx=True):
                return True
            time.sleep(0.1)
            
        return False

    def release(self):
        if not self.lock_value:
            return False
            
        # Lua script to release lock atomically ONLY if we own it (prevents releasing someone else's lock)
        lua_release = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        try:
            result = self.client.eval(lua_release, 1, self.lock_name, self.lock_value)
            return bool(result)
        except Exception:
            return False

    def get_owner(self):
        return self.client.get(self.lock_name)

class DistributedSemaphore:
    """Distributed Semaphore using Redis sorted sets (limits concurrent access to resources)"""
    def __init__(self, name, limit):
        self.client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.sem_name = f"sem:{name}"
        self.limit = limit
        self.owner_id = str(uuid.uuid4())

    def acquire(self, timeout=5, ttl=10):
        end_time = time.time() + timeout
        now = time.time()
        
        while time.time() < end_time:
            pipe = self.client.pipeline(transaction=True)
            # Remove expired acquisitions
            pipe.zremrangebyscore(self.sem_name, 0, now - ttl)
            # Add our request
            pipe.zadd(self.sem_name, {self.owner_id: now})
            # Check our rank (0-indexed rank tells us if we're under the limit)
            pipe.zrank(self.sem_name, self.owner_id)
            _, _, rank = pipe.execute()
            
            if rank is not None and rank < self.limit:
                return True
                
            # If we didn't get in, clean up our request and wait
            self.client.zrem(self.sem_name, self.owner_id)
            time.sleep(0.1)
            now = time.time()
            
        return False

    def release(self):
        result = self.client.zrem(self.sem_name, self.owner_id)
        return bool(result)

    def get_current_count(self):
        # Remove expired keys first
        now = time.time()
        self.client.zremrangebyscore(self.sem_name, 0, now - 30) # Default 30s expiry
        return self.client.zcard(self.sem_name)

class DeadlockDetector:
    """Deadlock Detector using Wait-For Graphs (Cycle detection)"""
    def __init__(self):
        # Adjacency list representation: transaction_id -> list of transaction_ids it's waiting for
        self.graph = {}
        # Maps transaction to the resource it wants, and resource to transaction holding it
        self.resource_held_by = {}
        self.waiting_for_resource = {}

    def register_lock_holder(self, transaction_id, resource):
        self.resource_held_by[resource] = transaction_id

    def register_lock_request(self, transaction_id, resource):
        self.waiting_for_resource[transaction_id] = resource
        
        # Build wait-for edge
        holder = self.resource_held_by.get(resource)
        if holder and holder != transaction_id:
            if transaction_id not in self.graph:
                self.graph[transaction_id] = []
            if holder not in self.graph[transaction_id]:
                self.graph[transaction_id].append(holder)

    def release_lock(self, transaction_id, resource):
        if self.resource_held_by.get(resource) == transaction_id:
            del self.resource_held_by[resource]
            
        if self.waiting_for_resource.get(transaction_id) == resource:
            del self.waiting_for_resource[transaction_id]
            
        # Rebuild graph
        self.graph = {}
        for tx, res in self.waiting_for_resource.items():
            holder = self.resource_held_by.get(res)
            if holder and holder != tx:
                if tx not in self.graph:
                    self.graph[tx] = []
                self.graph[tx].append(holder)

    def detect_deadlock(self):
        """DFS-based cycle detection"""
        visited = {} # False = visiting, True = visited
        cycle = []

        def dfs(node, path):
            visited[node] = False # Mark as visiting
            path.append(node)
            
            for neighbor in self.graph.get(node, []):
                if neighbor in visited:
                    if not visited[neighbor]: # Neighbor is in visiting state -> cycle found!
                        # Extract cycle
                        cycle_start = path.index(neighbor)
                        cycle.extend(path[cycle_start:])
                        return True
                else:
                    if dfs(neighbor, path):
                        return True
                        
            path.pop()
            visited[node] = True # Mark as fully visited
            return False

        for node in list(self.graph.keys()):
            if node not in visited:
                path = []
                if dfs(node, path):
                    return {
                        "deadlock_detected": True,
                        "cycle": cycle,
                        "resolution_victim": cycle[0] # Select victim (e.g. first transaction in cycle)
                    }
                    
        return {
            "deadlock_detected": False,
            "cycle": []
        }
