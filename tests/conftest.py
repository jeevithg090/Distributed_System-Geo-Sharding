from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import fakeredis
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Never touch the developer's real index or download embedding models in tests.
os.environ.setdefault("RAG_EMBEDDING_BACKEND", "hash")

from core.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("RAG_INDEX_PATH", str(tmp_path / "rag_index.json"))
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hash")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def redis_client() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)
