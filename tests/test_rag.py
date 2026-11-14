import json
import os
import time

import numpy as np
import pytest

from rag.embeddings import DIMENSION, EmbeddingEngine, hash_embedding
from rag.query_engine import RAGQueryEngine
from rag.vector_store import FAISS_AVAILABLE, Document, VectorStore

DOCS = [
    Document("Redis cache-aside layer with a 300 second TTL", {"type": "cache"}),
    Document("Circuit breaker opens after three failures and fails over", {"type": "routing"}),
    Document("Asynchronous replication copies users between shards", {"type": "replication"}),
]


def test_hash_embedding_is_deterministic_and_normalised():
    a = hash_embedding("How does replication work?")
    assert a == hash_embedding("How does replication work?")
    assert len(a) == DIMENSION
    assert np.isclose(np.linalg.norm(a), 1.0)
    assert not np.any(hash_embedding(""))


def test_hash_embedding_reflects_lexical_overlap():
    q = np.array(hash_embedding("cache ttl"))
    near = np.array(hash_embedding("redis cache with a ttl"))
    far = np.array(hash_embedding("gpu cluster pricing"))
    assert q @ near > q @ far


def test_engine_rejects_unknown_backend():
    with pytest.raises(ValueError):
        EmbeddingEngine("magic")
    assert EmbeddingEngine("hash").backend == "hash"


def _store(use_faiss):
    engine = EmbeddingEngine("hash")
    store = VectorStore(use_faiss=use_faiss)
    store.add_documents(DOCS, engine.embed_batch([d.text for d in DOCS]))
    return store, engine


@pytest.mark.parametrize(
    "use_faiss",
    [False, pytest.param(True, marks=pytest.mark.skipif(not FAISS_AVAILABLE, reason="faiss not installed"))],
)
def test_search_ranks_relevant_document_first(use_faiss):
    store, engine = _store(use_faiss)
    results = store.search(engine.embed_text("what happens when the circuit breaker opens"), top_k=2)
    assert results[0]["document"].metadata["type"] == "routing"
    assert len(results) == 2
    assert results[0]["similarity"] >= results[1]["similarity"]


def test_numpy_and_faiss_agree():
    if not FAISS_AVAILABLE:
        pytest.skip("faiss not installed")
    (np_store, engine), (faiss_store, _) = _store(False), _store(True)
    q = engine.embed_text("replication between shards")
    a = [(r["document"].text, round(r["similarity"], 5)) for r in np_store.search(q, 3)]
    b = [(r["document"].text, round(r["similarity"], 5)) for r in faiss_store.search(q, 3)]
    assert a == b


def test_vector_validation():
    store = VectorStore(dimension=4)
    with pytest.raises(ValueError):
        store.add_documents(DOCS[:1], [])
    with pytest.raises(ValueError):
        store.add_documents(DOCS[:1], [[1.0, 2.0]])
    assert store.search([1, 0, 0, 0]) == []


def test_save_and_load_round_trip(tmp_path):
    store, engine = _store(False)
    store.embedding_backend = "hash"
    path = str(tmp_path / "idx" / "index.json")
    store.save(path)
    with open(path) as fh:
        assert json.load(fh)["embedding_backend"] == "hash"
    loaded = VectorStore()
    assert loaded.load(path)
    assert len(loaded) == 3
    assert loaded.embedding_backend == "hash"
    q = engine.embed_text("cache ttl")
    assert loaded.search(q, 1)[0]["document"].text == store.search(q, 1)[0]["document"].text


def test_load_rejects_missing_or_corrupt_files(tmp_path):
    assert not VectorStore().load(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    assert not VectorStore().load(str(bad))


def test_query_engine_without_index(tmp_path):
    engine = RAGQueryEngine(EmbeddingEngine("hash"), str(tmp_path / "none.json"))
    result = engine.ask("anything")
    assert result["index_initialized"] is False
    assert result["retrieved_documents"] == []


def test_query_engine_answers_and_hot_reloads(tmp_path):
    path = str(tmp_path / "index.json")
    store, _ = _store(False)
    store.embedding_backend = "hash"
    store.save(path)

    engine = RAGQueryEngine(EmbeddingEngine("hash"), path)
    result = engine.ask("how does the redis cache ttl work", top_k=1)
    assert result["retrieved_documents"][0]["metadata"]["type"] == "cache"
    assert "top similarity" in result["answer"]
    assert engine.status()["document_count"] == 3

    bigger = VectorStore()
    bigger.embedding_backend = "hash"
    docs = [*DOCS, Document("Sharding by region with user ID blocks", {"type": "sharding"})]
    bigger.add_documents(docs, EmbeddingEngine("hash").embed_batch([d.text for d in docs]))
    bigger.save(path)
    future = time.time() + 5
    os.utime(path, (future, future))  # make sure the mtime visibly changes
    assert engine.status()["document_count"] == 4


def test_query_engine_detects_backend_mismatch(tmp_path):
    path = str(tmp_path / "index.json")
    store, _ = _store(False)
    store.embedding_backend = "model:all-MiniLM-L6-v2"
    store.save(path)
    result = RAGQueryEngine(EmbeddingEngine("hash"), path).ask("cache")
    assert "Rebuild the index" in result["answer"]
