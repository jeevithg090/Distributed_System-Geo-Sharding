"""End-to-end tests against live PostgreSQL shards.

These tests TRUNCATE the shard tables. They only run when
``GEOSHARD_INTEGRATION=1`` and the ``SHARD_*``/``POSTGRES_*`` variables point at
disposable databases that already have ``db/init_schema.sql`` applied (CI uses
service containers; locally ``docker compose up -d us-node eu-node asia-node``).
"""

from __future__ import annotations

import os
import random

import fakeredis
import pytest
from faker import Faker
from fastapi.testclient import TestClient

import seed_data
from app import Services, create_app
from core import replication_worker, users
from core.config import REGION_ID_OFFSETS, REGIONS, get_settings
from core.db import shard_cursor
from core.resilient_router import lookup_with_failover
from rag.knowledge_base import KnowledgeBase

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("GEOSHARD_INTEGRATION") != "1", reason="GEOSHARD_INTEGRATION != 1"),
]


@pytest.fixture
def seeded():
    fake = Faker()
    Faker.seed(1234)
    rng = random.Random(1234)
    return {region: seed_data.seed_region(region, fake, rng, scale=0.05) for region in REGIONS}


def test_seed_uses_region_id_blocks(seeded):
    for region in REGIONS:
        assert seeded[region]["users"] > 0
        with shard_cursor(region) as cur:
            cur.execute("SELECT MIN(user_id), MAX(user_id), bool_and(NOT replicated) FROM users")
            low, high, none_replicated = cur.fetchone()
        assert low == REGION_ID_OFFSETS[region] + 1
        assert high < REGION_ID_OFFSETS[region] + 1_000_000
        assert none_replicated


def test_replication_copies_users_with_same_ids(seeded):
    report = replication_worker.replicate_once()
    for source in REGIONS:
        for target in REGIONS:
            if source != target:
                assert report[source][target] == seeded[source]["users"]

    assert replication_worker.replicate_once() == {}, "second pass must be a no-op"

    total = sum(s["users"] for s in seeded.values())
    first_eu_user = REGION_ID_OFFSETS["eu"] + 1
    original = users.fetch_user("eu", first_eu_user)
    for region in REGIONS:
        with shard_cursor(region) as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            assert cur.fetchone()[0] == total
        replica = users.fetch_user(region, first_eu_user)
        assert replica["email"] == original["email"]
        assert replica["region"] == "eu"


def test_new_rows_are_replicated_on_next_pass(seeded):
    replication_worker.replicate_once()
    with shard_cursor("asia") as cur:
        cur.execute(
            "INSERT INTO users (username, email, region, subscription_type) "
            "VALUES ('late', 'late@example.test', 'asia', 'free') RETURNING user_id"
        )
        new_id = cur.fetchone()[0]
    assert new_id > REGION_ID_OFFSETS["asia"]
    report = replication_worker.replicate_once()
    assert report == {"asia": {"us": 1, "eu": 1}}
    assert users.fetch_user("us", new_id)["username"] == "late"


def test_failover_lookup_when_home_shard_is_unreachable(seeded, monkeypatch):
    replication_worker.replicate_once()
    monkeypatch.setenv("SHARD_US_PORT", "1")  # nothing listens here
    get_settings.cache_clear()
    region, user, errors = lookup_with_failover(1, "us")
    assert region == "eu"
    assert user["region"] == "us"
    assert errors and errors[0].startswith("US unavailable")


def test_recent_users_excludes_replicas(seeded):
    replication_worker.replicate_once()
    recent = users.fetch_recent_users("eu", 50)
    assert recent
    assert all(u["region"] == "eu" for u in recent)


def test_knowledge_base_harvest(seeded):
    docs = KnowledgeBase().harvest_all()
    sources = {d.metadata["source"] for d in docs}
    assert sources == {"schema", "stats", "system"}
    us_users = next(d for d in docs if d.metadata.get("type") == "users" and d.metadata.get("region") == "us")
    assert f"Total users = {seeded['us']['users']}" in us_users.text


def test_api_against_live_shards(seeded):
    replication_worker.replicate_once()
    services = Services(settings=get_settings(), redis=fakeredis.FakeRedis(decode_responses=True))
    app = create_app(services_factory=lambda: services, start_consumers=0)
    with TestClient(app) as client:
        assert client.get("/health").json()["shards"]["us"]["status"] == "UP"
        user = client.get(f"/users/{REGION_ID_OFFSETS['asia'] + 1}").json()
        assert user["served_from"] == "asia"
        assert user["served_from_cache"] is False
        assert client.get(f"/users/{REGION_ID_OFFSETS['asia'] + 1}").json()["served_from_cache"]
        recent = client.get("/users/recent/all").json()
        assert recent["total_results"] == 15
        rebuilt = client.post("/rag/index").json()
        assert rebuilt["document_count"] > 10
        answer = client.post("/rag/ask", json={"question": "How many support tickets in EU?"}).json()
        assert answer["retrieved_documents"]
