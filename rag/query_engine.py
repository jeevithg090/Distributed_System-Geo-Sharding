"""Retrieval-only question answering over the GeoShardDB knowledge index."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from rag.embeddings import EmbeddingEngine
from rag.vector_store import FAISS_AVAILABLE, VectorStore

logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = 0.2


class RAGQueryEngine:
    """Loads the on-disk index lazily and reloads it whenever the file changes.

    Reloading on modification time means an index rebuilt by any API replica
    (on a shared volume) or by ``python -m rag.indexer`` is picked up without
    restarting the server.
    """

    def __init__(self, engine: EmbeddingEngine, index_path: str) -> None:
        self.engine = engine
        self.index_path = index_path
        self.store = VectorStore()
        self._loaded_mtime: float | None = None
        self._lock = threading.Lock()

    @property
    def index_loaded(self) -> bool:
        return self._loaded_mtime is not None

    def refresh(self) -> bool:
        """(Re)load the index if the file is new or changed. Returns whether one is loaded."""
        try:
            mtime = os.path.getmtime(self.index_path)
        except OSError:
            return self.index_loaded
        with self._lock:
            if mtime != self._loaded_mtime:
                store = VectorStore()
                if store.load(self.index_path):
                    self.store = store
                    self._loaded_mtime = mtime
        return self.index_loaded

    def status(self) -> dict[str, Any]:
        loaded = self.refresh()
        return {
            "index_initialized": loaded,
            "document_count": len(self.store) if loaded else 0,
            "index_file_path": self.index_path,
            "index_embedding_backend": self.store.embedding_backend if loaded else None,
            "configured_embedding_backend": self.engine.requested_backend,
            "vector_search": "faiss" if FAISS_AVAILABLE else "numpy",
        }

    def ask(self, question: str, top_k: int = 3) -> dict[str, Any]:
        if not self.refresh():
            return {
                "question": question,
                "answer": (
                    "The RAG index is not initialized. Build it with POST /rag/index "
                    "or `python -m rag.indexer`."
                ),
                "retrieved_documents": [],
                "index_initialized": False,
            }

        if self.store.embedding_backend and self.store.embedding_backend != self.engine.backend:
            return {
                "question": question,
                "answer": (
                    f"The index was built with '{self.store.embedding_backend}' embeddings but the "
                    f"server is using '{self.engine.backend}'. Rebuild the index with POST /rag/index."
                ),
                "retrieved_documents": [],
                "index_initialized": True,
            }

        results = self.store.search(self.engine.embed_text(question), top_k=top_k)
        retrieved = [
            {
                "text": r["document"].text,
                "similarity_score": round(r["similarity"], 4),
                "metadata": r["document"].metadata,
            }
            for r in results
        ]
        if not results:
            answer = "No relevant documents were retrieved to answer your question."
        elif results[0]["similarity"] < LOW_CONFIDENCE_THRESHOLD:
            answer = (
                "No document matched your question closely; the nearest (low-relevance) "
                "documents are listed in retrieved_documents."
            )
        else:
            confidence = results[0]["similarity"] * 100
            bullets = "\n".join(f"- {r['document'].text}" for r in results)
            answer = (
                f"Based on retrieved system metadata and database statistics "
                f"(top similarity: {confidence:.1f}%):\n\n{bullets}"
            )
        return {
            "question": question,
            "answer": answer,
            "retrieved_documents": retrieved,
            "index_initialized": True,
        }
