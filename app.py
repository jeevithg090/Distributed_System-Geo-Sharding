from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

import psycopg2
import time
import os

from core.redis_cache import RedisCache
from rag.query_engine import RAGQueryEngine
from rag.indexer import build_index
from os_concepts.scheduler import RequestScheduler, generate_random_workload
from os_concepts.page_replacement import CacheSimulator
from os_concepts.sync_primitives import DistributedMutex, DistributedSemaphore, DeadlockDetector
from os_concepts.work_queue import WorkQueue

app = FastAPI(
    title="GeoShardDB",
    description="Multi-Region Distributed Database Simulator with RAG, Redis & OS Concepts",
    version="2.0"
)

Instrumentator().instrument(app).expose(app)

DATABASES = {
    "us": 5432,
    "eu": 5432,
    "asia": 5432
}

CIRCUIT_BREAKERS = {
    "us": {
        "failures": 0,
        "state": "CLOSED",
        "last_failure_time": 0
    },
    "eu": {
        "failures": 0,
        "state": "CLOSED",
        "last_failure_time": 0
    },
    "asia": {
        "failures": 0,
        "state": "CLOSED",
        "last_failure_time": 0
    }
}

FAILURE_THRESHOLD = 3
RECOVERY_TIMEOUT = 15

# Initialize cache and RAG modules
cache = RedisCache()
rag_engine = RAGQueryEngine()

# Initialize OS Work Queue and Deadlock Detector
work_queue = WorkQueue(max_size=50)
work_queue.start_consumers(2) # Spin up 2 background workers
deadlock_detector = DeadlockDetector()

def get_connection(region):
    if region not in DATABASES:
        return None

    return psycopg2.connect(
        host=f"{region}-postgres-service",
        port=DATABASES[region],
        database="sharddb",
        user="admin",
        password="password"
    )

def get_available_region(preferred_region):
    breaker = CIRCUIT_BREAKERS[preferred_region]
    current_time = time.time()

    if breaker["state"] == "OPEN":
        elapsed = (
            current_time
            - breaker["last_failure_time"]
        )

        if elapsed >= RECOVERY_TIMEOUT:
            breaker["state"] = "HALF-OPEN"
            print(
                f"{preferred_region.upper()} "
                f"breaker HALF-OPEN"
            )
            return preferred_region

        print(
            f"{preferred_region.upper()} "
            f"breaker OPEN"
        )

        for fallback_region in DATABASES.keys():
            if (
                fallback_region != preferred_region
                and
                CIRCUIT_BREAKERS[fallback_region]["state"]
                == "CLOSED"
            ):
                print(
                    f"Failing over to "
                    f"{fallback_region.upper()}"
                )
                return fallback_region

    return preferred_region


@app.get("/")
def root():
    return {
        "project": "GeoShardDB",
        "status": "running",
        "platform": "Kubernetes / AWS EC2",
        "features": {
            "caching": "Redis Distributed Cache (Cache-Aside)",
            "rag": "Retrieval-Augmented Generation Query Assistant",
            "os_concepts": [
                "CPU/Request Scheduling",
                "Memory/Page Replacement Eviction",
                "Synchronization Primitives (Distributed Mutex & Semaphore)",
                "Deadlock Detector & Cycle Finder",
                "Producer-Consumer Bounded Work Queue"
            ]
        }
    }


@app.get("/health")
def health_check():
    health = {}
    for region in DATABASES.keys():
        try:
            conn = psycopg2.connect(
                host=f"{region}-postgres-service",
                port=5432,
                database="sharddb",
                user="admin",
                password="password",
                connect_timeout=3
            )
            conn.close()
            health[region] = {
                "status": "UP",
                "breaker": CIRCUIT_BREAKERS[region]["state"]
            }
        except Exception:
            health[region] = {
                "status": "DOWN",
                "breaker": CIRCUIT_BREAKERS[region]["state"]
            }
    return health


@app.get("/users/{user_id}")
def get_user(user_id: int, region: str):
    start = time.time()
    region = get_available_region(region)

    # 1. Check Redis Cache
    cached_user = cache.get(region, str(user_id))
    if cached_user:
        end = time.time()
        latency_ms = (end - start) * 1000
        cached_user["served_from_cache"] = True
        cached_user["latency_ms"] = round(latency_ms, 2)
        return cached_user

    # 2. Cache Miss -> Query database shard
    try:
        conn = get_connection(region)
        if conn is None:
            return {"error": "Invalid region"}

        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                user_id,
                username,
                email,
                region,
                subscription_type,
                department,
                status,
                login_count,
                last_login
            FROM users
            WHERE user_id = %s
        """, (user_id,))

        user = cursor.fetchone()
        end = time.time()
        latency_ms = (end - start) * 1000
        cursor.close()
        conn.close()

        CIRCUIT_BREAKERS[region]["failures"] = 0
        CIRCUIT_BREAKERS[region]["state"] = "CLOSED"
        CIRCUIT_BREAKERS[region]["last_failure_time"] = 0

        if not user:
            return {"error": "User not found"}

        user_data = {
            "served_from": region,
            "user_id": user[0],
            "username": user[1],
            "email": user[2],
            "region": user[3],
            "subscription_type": user[4],
            "department": user[5],
            "status": user[6],
            "login_count": user[7],
            "last_login": str(user[8]) if user[8] else None,
            "served_from_cache": False
        }

        # 3. Write Back to Cache
        cache.set(region, str(user_id), user_data)

        user_data["latency_ms"] = round(latency_ms, 2)
        return user_data

    except Exception as e:
        CIRCUIT_BREAKERS[region]["failures"] += 1
        if (
            CIRCUIT_BREAKERS[region]["failures"]
            >= FAILURE_THRESHOLD
        ):
            CIRCUIT_BREAKERS[region]["state"] = "OPEN"
            CIRCUIT_BREAKERS[region]["last_failure_time"] = time.time()

        return {
            "error": str(e),
            "region": region,
            "breaker_state": CIRCUIT_BREAKERS[region]["state"],
            "failures": CIRCUIT_BREAKERS[region]["failures"]
        }


@app.get("/users/recent/all")
def recent_users():
    all_users = []
    start = time.time()

    for region in DATABASES.keys():
        try:
            conn = psycopg2.connect(
                host=f"{region}-postgres-service",
                port=5432,
                database="sharddb",
                user="admin",
                password="password"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    user_id,
                    username,
                    region
                FROM users
                ORDER BY created_at DESC
                LIMIT 5
            """)
            users = cursor.fetchall()
            for user in users:
                all_users.append({
                    "user_id": user[0],
                    "username": user[1],
                    "region": user[2]
                })
            cursor.close()
            conn.close()
        except Exception as e:
            all_users.append({
                "region": region,
                "error": str(e)
            })

    end = time.time()
    return {
        "total_results": len(all_users),
        "latency_ms": round((end - start) * 1000, 2),
        "results": all_users
    }


@app.get("/breaker-status")
def breaker_status():
    return CIRCUIT_BREAKERS


# ==================================================
# REDIS CACHE ENDPOINTS
# ==================================================

@app.get("/cache/stats")
def get_cache_stats():
    return cache.get_stats()

@app.delete("/cache/{region}")
def invalidate_region_cache(region: str):
    if region not in DATABASES:
        return {"error": "Invalid region"}
    cache.invalidate_region(region)
    return {"message": f"Cache invalidated for region: {region}"}

@app.delete("/cache")
def flush_all_cache():
    cache.flush_all()
    return {"message": "All caches flushed"}


# ==================================================
# RAG ENDPOINTS
# ==================================================

class QueryRequest(BaseModel):
    question: str

@app.post("/rag/ask")
def rag_ask(req: QueryRequest):
    return rag_engine.ask(req.question)

@app.post("/rag/index")
def rag_reindex():
    success = build_index()
    # Reload newly generated index file into memory
    rag_engine.reload_index()
    return {
        "success": success,
        "message": "RAG index rebuilt successfully." if success else "Failed to rebuild RAG index."
    }

@app.get("/rag/status")
def rag_status():
    index_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag", "rag_index.pkl")
    exists = os.path.exists(index_file)
    doc_count = len(rag_engine.store.documents) if (exists and rag_engine.index_loaded) else 0
    return {
        "index_initialized": exists and rag_engine.index_loaded,
        "document_count": doc_count,
        "index_file_path": index_file,
        "embedding_model": "all-MiniLM-L6-v2 (384 dimensions)",
        "fallback_numpy_mode": not exists
    }


# ==================================================
# OS CONCEPTS ENDPOINTS
# ==================================================

@app.get("/os/schedule")
def run_scheduler_demo(algorithm: str = "fcfs", count: int = 10):
    """Simulate request scheduling using various OS algorithms: fcfs, sjf, priority, rr, mlfq"""
    scheduler = RequestScheduler()
    workload = generate_random_workload(count)
    
    # Reset workload attributes for accurate run
    for r in workload:
        r.start_time = None
        r.completion_time = None
        r.remaining_cost = r.cost_units
        
    if algorithm == "fcfs":
        reqs, timeline = scheduler.schedule_fcfs(workload)
    elif algorithm == "sjf":
        reqs, timeline = scheduler.schedule_sjf(workload)
    elif algorithm == "priority":
        reqs, timeline = scheduler.schedule_priority(workload)
    elif algorithm == "rr":
        reqs, timeline = scheduler.schedule_rr(workload, quantum=4)
    elif algorithm == "mlfq":
        reqs, timeline = scheduler.schedule_mlfq(workload)
    else:
        return {"error": f"Unknown scheduling algorithm: {algorithm}"}
        
    # Calculate average metrics
    avg_wait = sum(r.waiting_time for r in reqs) / len(reqs) if reqs else 0
    avg_turnaround = sum(r.turnaround_time for r in reqs) / len(reqs) if reqs else 0
    
    # Convert workload output to JSON-serializable
    serialized_workload = []
    for r in reqs:
        serialized_workload.append({
            "request_id": r.request_id,
            "user_id": r.user_id,
            "region": r.region,
            "priority": r.priority,
            "cost_units": r.cost_units,
            "arrival_time": r.arrival_time,
            "start_time": r.start_time,
            "completion_time": r.completion_time,
            "waiting_time": r.waiting_time,
            "turnaround_time": r.turnaround_time
        })
        
    return {
        "algorithm": algorithm,
        "avg_waiting_time": round(avg_wait, 2),
        "avg_turnaround_time": round(avg_turnaround, 2),
        "timeline": timeline,
        "requests": serialized_workload
    }

@app.get("/os/page-replacement")
def run_page_replacement_demo(algorithm: str = "lru", capacity: int = 4):
    """Simulate page replacement cache eviction algorithms: fifo, lru, lfu, clock, optimal"""
    trace = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
    sim = CacheSimulator(capacity)
    
    if algorithm == "fifo":
        res = sim.simulate_fifo(trace)
    elif algorithm == "lru":
        res = sim.simulate_lru(trace)
    elif algorithm == "lfu":
        res = sim.simulate_lfu(trace)
    elif algorithm == "clock":
        res = sim.simulate_clock(trace)
    elif algorithm == "optimal":
        res = sim.simulate_optimal(trace)
    else:
        return {"error": f"Unknown page replacement algorithm: {algorithm}"}
        
    return {
        "trace": trace,
        "capacity": capacity,
        **res
    }

@app.get("/os/locks")
def get_locks_status():
    us_lock = DistributedMutex("us").get_owner()
    eu_lock = DistributedMutex("eu").get_owner()
    asia_lock = DistributedMutex("asia").get_owner()
    return {
        "lock_mutex:us": {"locked": us_lock is not None, "owner": us_lock},
        "lock_mutex:eu": {"locked": eu_lock is not None, "owner": eu_lock},
        "lock_mutex:asia": {"locked": asia_lock is not None, "owner": asia_lock}
    }

@app.post("/os/locks/acquire")
def acquire_lock_demo(region: str, client_id: str):
    if region not in DATABASES:
        return {"error": "Invalid region"}
    mutex = DistributedMutex(region)
    deadlock_detector.register_lock_holder(client_id, f"mutex:{region}")
    success = mutex.acquire(acquire_timeout=2, lock_ttl=30)
    return {
        "region": region,
        "acquired": success,
        "client_id": client_id,
        "lock_key": mutex.lock_name
    }

@app.post("/os/locks/release")
def release_lock_demo(region: str, client_id: str):
    if region not in DATABASES:
        return {"error": "Invalid region"}
    mutex = DistributedMutex(region)
    mutex.lock_value = mutex.get_owner()
    success = mutex.release()
    deadlock_detector.release_lock(client_id, f"mutex:{region}")
    return {
        "region": region,
        "released": success,
        "client_id": client_id
    }

@app.get("/os/deadlocks")
def check_deadlocks():
    return deadlock_detector.detect_deadlock()

@app.post("/os/deadlocks/simulate")
def simulate_deadlock_condition():
    global deadlock_detector
    deadlock_detector = DeadlockDetector()
    
    deadlock_detector.register_lock_holder("Tx-1", "mutex:us")
    deadlock_detector.register_lock_holder("Tx-2", "mutex:eu")
    deadlock_detector.register_lock_holder("Tx-3", "mutex:asia")
    
    deadlock_detector.register_lock_request("Tx-1", "mutex:eu")
    deadlock_detector.register_lock_request("Tx-2", "mutex:asia")
    deadlock_detector.register_lock_request("Tx-3", "mutex:us")
    
    return {
        "status": "Deadlock condition simulated in wait-for graph.",
        "graph": deadlock_detector.graph,
        "check_endpoint": "/os/deadlocks"
      }

@app.get("/os/semaphore/status")
def get_semaphore_status(region: str):
    if region not in DATABASES:
        return {"error": "Invalid region"}
    sem = DistributedSemaphore(region, limit=3)
    return {
        "region": region,
        "max_limit": 3,
        "active_connections": sem.get_current_count()
    }

class JobPayload(BaseModel):
    action: str
    payload: dict

@app.post("/queue/produce")
def queue_produce(job: JobPayload):
    job_id = f"JOB-{int(time.time() * 1000)}"
    job_data = {
        "job_id": job_id,
        "action": job.action,
        "payload": job.payload
    }
    success, status = work_queue.produce(job_data)
    return {
        "job_id": job_id,
        "success": success,
        "status": status
    }

@app.get("/queue/stats")
def get_queue_stats():
    return work_queue.get_stats()

@app.post("/queue/start-consumers")
def start_queue_consumers(count: int = 2):
    work_queue.start_consumers(count)
    return {"message": f"Started {count} additional consumer worker threads."}
