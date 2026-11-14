"""Build (or rebuild) the RAG vector index from the shards.

Run with ``python -m rag.indexer``. The index is written atomically to
``RAG_INDEX_PATH`` (default ``data/rag_index.json``).
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.config import get_settings
from rag.embeddings import EmbeddingEngine
from rag.knowledge_base import KnowledgeBase
from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)


def build_index(
    engine: EmbeddingEngine | None = None,
    knowledge_base: KnowledgeBase | None = None,
    index_path: str | None = None,
) -> int:
    """Harvest documents, embed them and save the index. Returns the document count."""
    settings = get_settings()
    engine = engine or EmbeddingEngine(settings.rag_embedding_backend, settings.rag_embedding_model)
    knowledge_base = knowledge_base or KnowledgeBase()
    index_path = index_path or settings.rag_index_path

    docs = knowledge_base.harvest_all()
    if not any(d.metadata.get("source") == "stats" for d in docs):
        logger.warning("No shard statistics harvested; are the shards running and seeded?")

    vectors = engine.embed_batch([d.text for d in docs])
    store = VectorStore(dimension=len(vectors[0]))
    store.embedding_backend = engine.backend
    store.add_documents(docs, vectors)
    store.save(index_path)
    logger.info("Indexed %d documents with %s embeddings", len(docs), engine.backend)
    return len(docs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build (or rebuild) the RAG vector index from the PostgreSQL shards.",
        epilog="Embedding backend and model come from RAG_EMBEDDING_BACKEND / RAG_EMBEDDING_MODEL.",
    )
    parser.add_argument(
        "--output", help="index file to write (default: RAG_INDEX_PATH or data/rag_index.json)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = args.output or get_settings().rag_index_path
    count = build_index(index_path=path)
    print(f"RAG index built with {count} documents at {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
