from __future__ import annotations

from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import Services, UserStore, create_app
from core.config import get_settings
from rag.vector_store import Document, VectorStore


class FakeShards:
    """In-memory stand-in for the three PostgreSQL shards."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[int, dict[str, Any]]] = {
            "us": {1: {"user_id": 1, "username": "ada", "region": "us"}},
            "eu": {
                1_000_001: {"user_id": 1_000_001, "username": "bo", "region": "eu"},
                1: {"user_id": 1, "username": "ada", "region": "us"},  # replica of a US user
            },
            "asia": {2_000_001: {"user_id": 2_000_001, "username": "chen", "region": "asia"}},
        }
        self.down: set[str] = set()
        self.queries: list[tuple[str, int]] = []

    def fetch_user(self, region: str, user_id: int) -> dict[str, Any] | None:
        self.queries.append((region, user_id))
        if region in self.down:
            raise ConnectionError(f"{region} unreachable")
        row = self.rows[region].get(user_id)
        return dict(row) if row else None

    def fetch_recent_users(self, region: str, limit: int) -> list[dict[str, Any]]:
        if region in self.down:
            raise ConnectionError(f"{region} unreachable")
        return [r for r in self.rows[region].values() if r["region"] == region][:limit]

    def ping(self, region: str) -> bool:
        return region not in self.down


@pytest.fixture
def shards() -> FakeShards:
    return FakeShards()


@pytest.fixture
def services(shards) -> Services:
    return Services(
        settings=get_settings(),
        redis=fakeredis.FakeRedis(decode_responses=True),
        users=UserStore(
            fetch_user=shards.fetch_user,
            fetch_recent_users=shards.fetch_recent_users,
            ping=shards.ping,
        ),
    )


@pytest.fixture
def client(services):
    app = create_app(services_factory=lambda: services, start_consumers=0)
    with TestClient(app) as test_client:
        yield test_client


def test_root_and_openapi(client):
    body = client.get("/").json()
    assert body["project"] == "GeoShardDB"
    assert body["regions"] == ["us", "eu", "asia"]
    assert client.get("/openapi.json").status_code == 200


def test_metrics_endpoint(client):
    client.get("/")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_health_reports_degraded_shard(client, shards):
    assert client.get("/health").json()["status"] == "ok"
    shards.down.add("eu")
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["shards"]["eu"]["status"] == "DOWN"
    assert body["shards"]["us"] == {"status": "UP", "breaker": "CLOSED"}


def test_user_lookup_then_cache_hit(client, shards):
    first = client.get("/users/1", params={"region": "us"}).json()
    assert first["username"] == "ada"
    assert first["served_from"] == "us"
    assert first["served_from_cache"] is False
    second = client.get("/users/1", params={"region": "us"}).json()
    assert second["served_from_cache"] is True
    assert shards.queries == [("us", 1)]
    stats = client.get("/cache/stats").json()["stats"]
    assert (stats["hits"], stats["misses"]) == (1, 1)


def test_region_is_derived_from_user_id(client):
    body = client.get("/users/2000001").json()
    assert body["served_from"] == "asia"
    assert body["username"] == "chen"


def test_user_not_found_and_validation(client):
    assert client.get("/users/42", params={"region": "us"}).status_code == 404
    assert client.get("/users/1", params={"region": "mars"}).status_code == 422
    assert client.get("/users/0").status_code == 422
    assert client.get("/users/9000000").status_code == 404


def test_shard_failure_fails_over_within_the_request(client, shards):
    shards.down.add("us")
    for expected_failures in (1, 2, 3):
        body = client.get("/users/1", params={"region": "us"}).json()
        # served by the EU replica, which holds the same global user ID
        assert (body["served_from"], body["failover"], body["username"]) == ("eu", True, "ada")
        assert body["failed_regions"] == [
            {
                "region": "us",
                "breaker_state": "OPEN" if expected_failures == 3 else "CLOSED",
                "failures": expected_failures,
            }
        ]
        client.delete("/cache")
    assert client.get("/breaker-status").json()["us"]["state"] == "OPEN"

    # Breaker is open: US is skipped without even trying it
    shards.queries.clear()
    body = client.get("/users/1", params={"region": "us"}).json()
    assert body["served_from"] == "eu"
    assert body["failed_regions"] == []
    assert shards.queries == [("eu", 1)]


def test_all_regions_down_returns_503(client, shards):
    shards.down.update({"us", "eu", "asia"})
    response = client.get("/users/1", params={"region": "us"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "All regions unavailable"
    assert [f["region"] for f in detail["failed_regions"]] == ["us", "eu", "asia"]


def test_all_breakers_open_returns_503_without_querying(client, services, shards):
    for region in ("us", "eu", "asia"):
        for _ in range(3):
            services.breakers[region].record_failure()
    assert client.get("/users/1", params={"region": "us"}).status_code == 503
    assert shards.queries == []


def test_recent_users_fan_out_tolerates_failures(client, shards):
    shards.down.add("asia")
    body = client.get("/users/recent/all").json()
    assert body["total_results"] == 2  # replicas are not double-counted
    assert {"region": "asia", "error": "Shard unavailable"} in body["results"]


def test_cache_invalidation_endpoints(client):
    client.get("/users/1", params={"region": "us"})
    assert client.delete("/cache/us").json()["keys_deleted"] == 1
    assert client.delete("/cache/pluto").status_code == 422
    client.get("/users/1", params={"region": "us"})
    assert client.delete("/cache").json()["keys_deleted"] == 1


def test_admin_endpoints_require_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    assert client.delete("/cache").status_code == 401
    assert client.delete("/cache", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.delete("/cache", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.post("/os/deadlocks/simulate").status_code == 401


def test_rag_flow(client, services):
    status = client.get("/rag/status").json()
    assert status["index_initialized"] is False
    assert client.post("/rag/ask", json={"question": "cache?"}).json()["index_initialized"] is False
    assert client.post("/rag/ask", json={"question": ""}).status_code == 422

    store = VectorStore()
    store.embedding_backend = "hash"
    docs = [Document("Redis cache-aside with a TTL", {"type": "cache"})]
    store.add_documents(docs, services.embeddings.embed_batch([d.text for d in docs]))
    store.save(services.rag.index_path)

    body = client.post("/rag/ask", json={"question": "how does the redis cache work", "top_k": 1}).json()
    assert body["retrieved_documents"][0]["metadata"] == {"type": "cache"}


def test_rag_index_rebuild_failure_is_500(client, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("shards down")

    monkeypatch.setattr("app.build_index", boom)
    assert client.post("/rag/index").status_code == 500


@pytest.mark.parametrize("algorithm", ["fcfs", "sjf", "priority", "rr", "mlfq"])
def test_schedule_demo(client, algorithm):
    body = client.get("/os/schedule", params={"algorithm": algorithm, "count": 8, "seed": 3}).json()
    assert body["algorithm"] == algorithm
    assert len(body["requests"]) == 8
    assert body["avg_turnaround_time"] >= body["avg_waiting_time"]


def test_schedule_demo_validation(client):
    assert client.get("/os/schedule", params={"algorithm": "nope"}).status_code == 422
    assert client.get("/os/schedule", params={"count": 0}).status_code == 422
    assert client.get("/os/schedule", params={"count": 10_000}).status_code == 422


def test_page_replacement_demo(client):
    body = client.get("/os/page-replacement", params={"algorithm": "fifo", "capacity": 4}).json()
    assert body["faults"] == 10
    custom = client.get("/os/page-replacement", params={"algorithm": "lru", "trace": "1,2,1,3"}).json()
    assert custom["trace"] == [1, 2, 1, 3]
    assert client.get("/os/page-replacement", params={"capacity": 0}).status_code == 422
    assert client.get("/os/page-replacement", params={"trace": "1;2"}).status_code == 422


def test_lock_lifecycle_and_deadlock_wiring(client):
    acquire = client.post("/os/locks/acquire", params={"region": "us", "client_id": "alice"}).json()
    assert acquire["acquired"] is True
    assert client.get("/os/locks").json()["lock_mutex:us"] == {"locked": True, "owner": "alice"}

    # bob cannot steal or release alice's lock
    assert (
        client.post("/os/locks/release", params={"region": "us", "client_id": "bob"}).json()["released"]
        is False
    )
    assert client.get("/os/locks").json()["lock_mutex:us"]["owner"] == "alice"

    assert (
        client.post("/os/locks/release", params={"region": "us", "client_id": "alice"}).json()["released"]
        is True
    )
    assert client.get("/os/locks").json()["lock_mutex:us"]["locked"] is False
    assert (
        client.post("/os/locks/acquire", params={"region": "us", "client_id": "bad id!"}).status_code == 422
    )


def test_deadlock_simulation(client):
    assert client.get("/os/deadlocks").json()["deadlock_detected"] is False
    graph = client.post("/os/deadlocks/simulate").json()["graph"]
    assert graph == {"Tx-1": ["Tx-2"], "Tx-2": ["Tx-3"], "Tx-3": ["Tx-1"]}
    result = client.get("/os/deadlocks").json()
    assert result["deadlock_detected"] is True
    assert sorted(result["cycle"]) == ["Tx-1", "Tx-2", "Tx-3"]


def test_semaphore_endpoints(client):
    holders = []
    for _ in range(3):
        body = client.post("/os/semaphore/acquire", params={"region": "eu"}).json()
        assert body["acquired"] is True
        holders.append(body["holder_id"])
    assert client.post("/os/semaphore/acquire", params={"region": "eu"}).json()["acquired"] is False
    assert client.get("/os/semaphore/status", params={"region": "eu"}).json()["active_connections"] == 3
    released = client.post("/os/semaphore/release", params={"region": "eu", "holder_id": holders[0]})
    assert released.json()["released"] is True


def test_queue_endpoints(client, services):
    response = client.post("/queue/produce", json={"action": "reindex", "payload": {"region": "us"}})
    assert response.status_code == 200
    assert response.json()["job_id"].startswith("JOB-")
    assert client.get("/queue/stats").json()["queue_depth"] == 1
    assert client.post("/queue/produce", json={"payload": {}}).status_code == 422

    for _ in range(services.work_queue.max_size - 1):
        client.post("/queue/produce", json={"action": "fill"})
    assert client.post("/queue/produce", json={"action": "overflow"}).status_code == 429

    started = client.post("/queue/start-consumers", params={"count": 1}).json()
    assert started["active_consumers"] == 1
    assert client.post("/queue/start-consumers", params={"count": 99}).status_code == 422


def test_redis_outage_on_os_endpoints(services, shards):
    class DownRedis(fakeredis.FakeRedis):
        def execute_command(self, *args, **kwargs):
            import redis

            raise redis.ConnectionError("down")

    broken = Services(settings=services.settings, redis=DownRedis(), users=services.users)
    app = create_app(services_factory=lambda: broken, start_consumers=0)
    with TestClient(app) as c:
        assert c.get("/os/locks").status_code == 503
        assert c.get("/queue/stats").status_code == 503
        # cache failures degrade to a database read
        assert c.get("/users/1", params={"region": "us"}).json()["username"] == "ada"
        assert c.get("/health").json()["redis"] == "DOWN"


def test_console_page_and_assets(client):
    page = client.get("/console")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "<title>GeoShardDB Console</title>" in page.text
    for asset in ("app.js", "styles.css", "favicon.svg"):
        assert client.get(f"/console/assets/{asset}").status_code == 200
    assert client.get("/console/", follow_redirects=False).status_code == 308
    assert client.get("/favicon.ico").headers["content-type"].startswith("image/svg+xml")
    assert client.get("/").json()["console"] == "/console"


def test_unknown_route_is_html_for_browsers_and_json_for_api_clients(client):
    browser = client.get("/no-such-page", headers={"Accept": "text/html,application/xhtml+xml"})
    assert browser.status_code == 404
    assert "Page not found" in browser.text
    api = client.get("/no-such-page")
    assert api.status_code == 404
    assert api.json() == {"detail": "Not Found"}
    # 404s raised by handlers keep their JSON detail even for browsers.
    missing_user = client.get("/users/42", params={"region": "us"}, headers={"Accept": "text/html"})
    assert missing_user.json() == {"detail": "User not found"}
