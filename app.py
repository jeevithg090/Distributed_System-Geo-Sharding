"""GeoShardDB API gateway.

Region-aware user reads over three PostgreSQL shards with Redis cache-aside,
per-region circuit breakers and failover, a retrieval-only RAG assistant, and
interactive OS-concept demos. Run with ``uvicorn app:app``.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any

import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import users as user_store
from core.circuit_breaker import BreakerRegistry
from core.config import REGIONS, Settings, get_settings, home_region_for_user
from core.redis_cache import RedisCache
from core.redis_client import get_redis
from os_concepts.page_replacement import CacheSimulator
from os_concepts.scheduler import RequestScheduler, generate_random_workload, summarize
from os_concepts.sync_primitives import DeadlockDetector, DistributedMutex, DistributedSemaphore
from os_concepts.work_queue import WorkQueue
from rag.embeddings import EmbeddingEngine
from rag.indexer import build_index
from rag.query_engine import RAGQueryEngine

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("geosharddb")

API_VERSION = "2.1.0"
SEMAPHORE_LIMIT = 3
MAX_CONSUMERS = 8
DEFAULT_PAGE_TRACE = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class Region(StrEnum):
    US = "us"
    EU = "eu"
    ASIA = "asia"


assert tuple(r.value for r in Region) == REGIONS, "Region enum out of sync with REGIONS"
RegionQuery = Annotated[Region, Query(description="Shard region")]
ClientId = Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")]


class SchedulingAlgorithm(StrEnum):
    FCFS = "fcfs"
    SJF = "sjf"
    PRIORITY = "priority"
    RR = "rr"
    MLFQ = "mlfq"


class PageAlgorithm(StrEnum):
    FIFO = "fifo"
    LRU = "lru"
    LFU = "lfu"
    CLOCK = "clock"
    OPTIMAL = "optimal"


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)


class JobPayload(BaseModel):
    action: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass
class UserStore:
    """Indirection over shard queries so tests can substitute fakes."""

    fetch_user: Callable[[str, int], dict[str, Any] | None] = user_store.fetch_user
    fetch_recent_users: Callable[[str, int], list[dict[str, Any]]] = user_store.fetch_recent_users
    ping: Callable[[str], bool] = user_store.ping


@dataclass
class Services:
    settings: Settings
    redis: redis.Redis
    users: UserStore = field(default_factory=UserStore)
    cache: RedisCache = field(init=False)
    breakers: BreakerRegistry = field(init=False)
    rag: RAGQueryEngine = field(init=False)
    work_queue: WorkQueue = field(init=False)
    deadlocks: DeadlockDetector = field(init=False)
    embeddings: EmbeddingEngine = field(init=False)

    def __post_init__(self) -> None:
        s = self.settings
        self.cache = RedisCache(self.redis, default_ttl=s.cache_ttl_seconds)
        self.breakers = BreakerRegistry(REGIONS, s.breaker_failure_threshold, s.breaker_recovery_timeout)
        self.embeddings = EmbeddingEngine(s.rag_embedding_backend, s.rag_embedding_model)
        self.rag = RAGQueryEngine(self.embeddings, s.rag_index_path)
        self.work_queue = WorkQueue(self.redis, max_size=50)
        self.deadlocks = DeadlockDetector(self.redis)


def build_services() -> Services:
    return Services(settings=get_settings(), redis=get_redis())


def create_app(
    services_factory: Callable[[], Services] = build_services,
    start_consumers: int = 2,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        services = services_factory()
        app.state.services = services
        if start_consumers:
            services.work_queue.start_consumers(start_consumers)
        if not os.environ.get("ADMIN_API_KEY"):
            logger.warning("ADMIN_API_KEY is not set: admin endpoints are unauthenticated")
        try:
            yield
        finally:
            services.work_queue.stop_consumers()

    app = FastAPI(
        title="GeoShardDB",
        description=(
            "Multi-region distributed database simulator: geo-sharded PostgreSQL, Redis "
            "cache-aside, circuit-breaker failover, a RAG assistant and OS-concept demos."
        ),
        version=API_VERSION,
        lifespan=lifespan,
    )
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    _register_console(app)
    _register_routes(app)
    return app


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _register_console(app: FastAPI) -> None:
    """Serve the browser console (``web/``) at ``/console`` and a friendly HTML 404."""
    app.mount("/console/assets", StaticFiles(directory=WEB_DIR), name="console-assets")

    @app.get("/console", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(os.path.join(WEB_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/console/", include_in_schema=False)
    def console_slash() -> RedirectResponse:
        return RedirectResponse("/console", status_code=308)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(os.path.join(WEB_DIR, "favicon.svg"), media_type="image/svg+xml")

    @app.exception_handler(StarletteHTTPException)
    async def not_found_page(request: Request, exc: StarletteHTTPException) -> Response:
        # Unknown routes requested by a browser get an HTML page; API clients
        # (and 404s raised by handlers, e.g. "User not found") keep JSON.
        if exc.status_code == 404 and exc.detail == "Not Found" and _wants_html(request):
            return FileResponse(os.path.join(WEB_DIR, "404.html"), status_code=404)
        return await http_exception_handler(request, exc)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Protect mutating admin endpoints when ``ADMIN_API_KEY`` is configured."""
    expected = os.environ.get("ADMIN_API_KEY")
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


def _redis_unavailable(exc: redis.RedisError) -> HTTPException:
    logger.warning("Redis unavailable: %s", exc)
    return HTTPException(status_code=503, detail="Redis is unavailable")


def _register_routes(app: FastAPI) -> None:  # noqa: C901 - flat list of route handlers
    admin = [Depends(require_admin)]

    # ------------------------------------------------------------------ core
    @app.get("/", tags=["core"])
    def root() -> dict[str, Any]:
        return {
            "project": "GeoShardDB",
            "version": API_VERSION,
            "status": "running",
            "regions": list(REGIONS),
            "docs": "/docs",
            "console": "/console",
            "features": {
                "sharding": "Geographic sharding with region-owned user ID blocks",
                "caching": "Redis cache-aside",
                "resilience": "Per-region circuit breakers with cross-region failover",
                "rag": "Retrieval-only question answering over shard metadata",
                "os_concepts": [
                    "CPU/request scheduling",
                    "Page replacement / cache eviction",
                    "Distributed mutex and semaphore",
                    "Deadlock detection",
                    "Bounded producer-consumer work queue",
                ],
            },
        }

    @app.get("/health", tags=["core"])
    def health_check(services: ServicesDep) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=len(REGIONS)) as pool:
            up = dict(zip(REGIONS, pool.map(services.users.ping, REGIONS), strict=True))
        try:
            redis_up = bool(services.redis.ping())
        except redis.RedisError:
            redis_up = False
        breakers = services.breakers.snapshot()
        shards = {r: {"status": "UP" if up[r] else "DOWN", "breaker": breakers[r]["state"]} for r in REGIONS}
        healthy = all(up.values()) and redis_up
        return {
            "status": "ok" if healthy else "degraded",
            "shards": shards,
            "redis": "UP" if redis_up else "DOWN",
        }

    @app.get("/users/recent/all", tags=["users"])
    def recent_users(services: ServicesDep, limit: Annotated[int, Query(ge=1, le=50)] = 5) -> dict[str, Any]:
        """Parallel fan-out: newest users from every shard."""
        start = time.perf_counter()

        def query(region: str) -> list[dict[str, Any]]:
            try:
                return services.users.fetch_recent_users(region, limit)
            except Exception as exc:
                logger.warning("Recent-users query failed on %s: %s", region, exc)
                return [{"region": region, "error": "Shard unavailable"}]

        with ThreadPoolExecutor(max_workers=len(REGIONS)) as pool:
            results = [row for rows in pool.map(query, REGIONS) for row in rows]
        return {
            "total_results": sum(1 for r in results if "error" not in r),
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "results": results,
        }

    @app.get("/users/{user_id}", tags=["users"])
    def get_user(
        services: ServicesDep,
        user_id: Annotated[int, Path(ge=1)],
        region: Annotated[
            Region | None, Query(description="Home region; derived from the user ID if omitted")
        ] = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        preferred = region.value if region else home_region_for_user(user_id)
        if preferred is None:
            raise HTTPException(status_code=404, detail="User ID is outside every region's range")

        failed: list[dict[str, Any]] = []
        serving = services.breakers.select_region(preferred)
        while serving is not None:
            cached = services.cache.get(serving, user_id)
            if cached is not None:
                cached.update(
                    served_from=serving,
                    failover=serving != preferred,
                    failed_regions=failed,
                    served_from_cache=True,
                    latency_ms=round((time.perf_counter() - start) * 1000, 2),
                )
                return cached

            breaker = services.breakers[serving]
            try:
                user = services.users.fetch_user(serving, user_id)
            except Exception as exc:
                # Count the failure, then fail over within the same request.
                breaker.record_failure()
                logger.warning("Query on %s failed: %s", serving, exc)
                failed.append(
                    {"region": serving, "breaker_state": breaker.state.value, "failures": breaker.failures}
                )
                serving = services.breakers.select_region(preferred, exclude=[f["region"] for f in failed])
                continue
            breaker.record_success()

            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            services.cache.set(serving, user_id, user)
            return {
                **user,
                "served_from": serving,
                "failover": serving != preferred,
                "failed_regions": failed,
                "served_from_cache": False,
                "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            }

        raise HTTPException(
            status_code=503,
            detail={
                "error": "All regions unavailable",
                "failed_regions": failed,
                "breakers": services.breakers.snapshot(),
            },
        )

    @app.get("/breaker-status", tags=["core"])
    def breaker_status(services: ServicesDep) -> dict[str, Any]:
        return services.breakers.snapshot()

    # ----------------------------------------------------------------- cache
    @app.get("/cache/stats", tags=["cache"])
    def cache_stats(services: ServicesDep) -> dict[str, Any]:
        return services.cache.get_stats()

    @app.delete("/cache/{region}", tags=["cache"], dependencies=admin)
    def invalidate_region_cache(services: ServicesDep, region: Region) -> dict[str, Any]:
        deleted = services.cache.invalidate_region(region.value)
        return {"message": f"Cache invalidated for region: {region.value}", "keys_deleted": deleted}

    @app.delete("/cache", tags=["cache"], dependencies=admin)
    def flush_all_cache(services: ServicesDep) -> dict[str, Any]:
        deleted = services.cache.flush_all()
        return {"message": "All user caches flushed", "keys_deleted": deleted}

    # ------------------------------------------------------------------- rag
    @app.post("/rag/ask", tags=["rag"])
    def rag_ask(services: ServicesDep, req: QueryRequest) -> dict[str, Any]:
        return services.rag.ask(req.question, top_k=req.top_k)

    @app.post("/rag/index", tags=["rag"], dependencies=admin)
    def rag_reindex(services: ServicesDep) -> dict[str, Any]:
        try:
            count = build_index(engine=services.embeddings, index_path=services.rag.index_path)
        except Exception as exc:
            logger.exception("RAG index rebuild failed")
            raise HTTPException(status_code=500, detail="Failed to rebuild RAG index") from exc
        services.rag.refresh()
        return {"success": True, "document_count": count, "message": "RAG index rebuilt"}

    @app.get("/rag/status", tags=["rag"])
    def rag_status(services: ServicesDep) -> dict[str, Any]:
        return services.rag.status()

    # ----------------------------------------------------------- os concepts
    @app.get("/os/schedule", tags=["os"])
    def scheduler_demo(
        algorithm: SchedulingAlgorithm = SchedulingAlgorithm.FCFS,
        count: Annotated[int, Query(ge=1, le=100)] = 10,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Simulate request scheduling (fcfs, sjf, priority, rr, mlfq) on a random workload."""
        completed, timeline = RequestScheduler().run(
            algorithm.value, generate_random_workload(count, seed=seed)
        )
        return {
            "algorithm": algorithm.value,
            **summarize(completed),
            "timeline": timeline,
            "requests": [r.to_dict() for r in completed],
        }

    @app.get("/os/page-replacement", tags=["os"])
    def page_replacement_demo(
        algorithm: PageAlgorithm = PageAlgorithm.LRU,
        capacity: Annotated[int, Query(ge=1, le=64)] = 4,
        trace: Annotated[
            str | None,
            Query(max_length=1000, pattern=r"^\d+(,\d+)*$", description="Comma-separated page IDs"),
        ] = None,
    ) -> dict[str, Any]:
        """Simulate cache eviction (fifo, lru, lfu, clock, optimal) on an access trace."""
        pages = [int(p) for p in trace.split(",")] if trace else DEFAULT_PAGE_TRACE
        result = CacheSimulator(capacity).simulate(algorithm.value, pages)
        return {"trace": pages, "capacity": capacity, **result}

    @app.get("/os/locks", tags=["os"])
    def locks_status(services: ServicesDep) -> dict[str, Any]:
        try:
            owners = {r: DistributedMutex(services.redis, r).get_owner() for r in REGIONS}
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {f"lock_mutex:{r}": {"locked": o is not None, "owner": o} for r, o in owners.items()}

    @app.post("/os/locks/acquire", tags=["os"])
    def acquire_lock(services: ServicesDep, region: RegionQuery, client_id: ClientId) -> dict[str, Any]:
        mutex = DistributedMutex(services.redis, region.value, owner=client_id)
        resource = f"mutex:{region.value}"
        try:
            acquired = mutex.acquire(acquire_timeout=2, lock_ttl=30)
            if acquired:
                services.deadlocks.register_lock_holder(client_id, resource)
            else:
                services.deadlocks.register_lock_request(client_id, resource)
            owner = mutex.get_owner()
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {
            "region": region.value,
            "acquired": acquired,
            "client_id": client_id,
            "owner": owner,
            "lock_key": mutex.lock_name,
        }

    @app.post("/os/locks/release", tags=["os"])
    def release_lock(services: ServicesDep, region: RegionQuery, client_id: ClientId) -> dict[str, Any]:
        mutex = DistributedMutex(services.redis, region.value, owner=client_id)
        try:
            released = mutex.release()  # only succeeds if client_id holds the lock
            services.deadlocks.release_lock(client_id, f"mutex:{region.value}")
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {"region": region.value, "released": released, "client_id": client_id}

    @app.get("/os/deadlocks", tags=["os"])
    def check_deadlocks(services: ServicesDep) -> dict[str, Any]:
        try:
            return {**services.deadlocks.detect_deadlock(), "graph": services.deadlocks.graph}
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc

    @app.post("/os/deadlocks/simulate", tags=["os"], dependencies=admin)
    def simulate_deadlock(services: ServicesDep) -> dict[str, Any]:
        """Reset the wait-for graph and inject a 3-transaction cycle across regions."""
        detector = services.deadlocks
        try:
            detector.reset()
            for tx, held, wanted in (
                ("Tx-1", "us", "eu"),
                ("Tx-2", "eu", "asia"),
                ("Tx-3", "asia", "us"),
            ):
                detector.register_lock_holder(tx, f"mutex:{held}")
                detector.register_lock_request(tx, f"mutex:{wanted}")
            graph = detector.graph
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {
            "status": "Deadlock condition simulated in wait-for graph.",
            "graph": graph,
            "check_endpoint": "/os/deadlocks",
        }

    @app.get("/os/semaphore/status", tags=["os"])
    def semaphore_status(services: ServicesDep, region: RegionQuery) -> dict[str, Any]:
        try:
            count = DistributedSemaphore(services.redis, region.value, SEMAPHORE_LIMIT).get_current_count()
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {"region": region.value, "max_limit": SEMAPHORE_LIMIT, "active_connections": count}

    @app.post("/os/semaphore/acquire", tags=["os"])
    def semaphore_acquire(
        services: ServicesDep, region: RegionQuery, holder_id: ClientId | None = None
    ) -> dict[str, Any]:
        """Take one of the region's connection slots (held for up to 30 s or until released)."""
        sem = DistributedSemaphore(services.redis, region.value, SEMAPHORE_LIMIT, owner_id=holder_id)
        try:
            acquired = sem.acquire(timeout=1)
            count = sem.get_current_count()
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {
            "region": region.value,
            "acquired": acquired,
            "holder_id": sem.owner_id,
            "active_connections": count,
            "max_limit": SEMAPHORE_LIMIT,
        }

    @app.post("/os/semaphore/release", tags=["os"])
    def semaphore_release(services: ServicesDep, region: RegionQuery, holder_id: ClientId) -> dict[str, Any]:
        sem = DistributedSemaphore(services.redis, region.value, SEMAPHORE_LIMIT, owner_id=holder_id)
        try:
            released = sem.release()
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        return {"region": region.value, "released": released, "holder_id": holder_id}

    # ----------------------------------------------------------------- queue
    @app.post("/queue/produce", tags=["queue"])
    def queue_produce(services: ServicesDep, job: JobPayload) -> dict[str, Any]:
        job_id = f"JOB-{uuid.uuid4().hex[:12]}"
        try:
            accepted, status = services.work_queue.produce(
                {"job_id": job_id, "action": job.action, "payload": job.payload}
            )
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc
        if not accepted:
            raise HTTPException(status_code=429, detail={"job_id": job_id, "status": status})
        return {"job_id": job_id, "success": True, "status": status}

    @app.get("/queue/stats", tags=["queue"])
    def queue_stats(services: ServicesDep) -> dict[str, Any]:
        try:
            return services.work_queue.get_stats()
        except redis.RedisError as exc:
            raise _redis_unavailable(exc) from exc

    @app.post("/queue/start-consumers", tags=["queue"], dependencies=admin)
    def start_consumers(
        services: ServicesDep, count: Annotated[int, Query(ge=1, le=MAX_CONSUMERS)] = 2
    ) -> dict[str, Any]:
        available = MAX_CONSUMERS - services.work_queue.active_consumers
        if available <= 0:
            raise HTTPException(status_code=409, detail=f"Already running {MAX_CONSUMERS} consumers")
        active = services.work_queue.start_consumers(min(count, available))
        return {"message": f"This replica now runs {active} consumer threads.", "active_consumers": active}


app = create_app()
