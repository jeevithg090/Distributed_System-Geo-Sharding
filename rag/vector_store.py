"""In-memory vector store using FAISS when available and NumPy otherwise.

Vectors are L2-normalised, so inner product equals cosine similarity. The index
is persisted as JSON (documents, vectors and the embedding backend that
produced them); it is never unpickled, so loading an index cannot execute code.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:
    import faiss

    FAISS_AVAILABLE = True
except ImportError:  # optional dependency
    faiss = None  # type: ignore[assignment]
    FAISS_AVAILABLE = False

logger = logging.getLogger(__name__)

INDEX_FORMAT_VERSION = 2


@dataclass
class Document:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class VectorStore:
    def __init__(self, dimension: int = 384, use_faiss: bool | None = None) -> None:
        self.dimension = dimension
        self.use_faiss = FAISS_AVAILABLE if use_faiss is None else (use_faiss and FAISS_AVAILABLE)
        self.embedding_backend: str | None = None
        self.documents: list[Document] = []
        self._vectors = np.zeros((0, dimension), dtype=np.float32)
        self._index: Any = None
        self._reset_index()

    def _reset_index(self) -> None:
        self._index = faiss.IndexFlatIP(self.dimension) if self.use_faiss else None

    def __len__(self) -> int:
        return len(self.documents)

    def add_documents(self, docs: list[Document], vectors: list[list[float]]) -> None:
        if len(docs) != len(vectors):
            raise ValueError("documents and vectors must have the same length")
        if not docs:
            return
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != self.dimension:
            raise ValueError(f"expected vectors of dimension {self.dimension}, got {arr.shape}")
        arr = _normalise(arr)
        self.documents.extend(docs)
        self._vectors = np.vstack([self._vectors, arr])
        if self._index is not None:
            self._index.add(arr)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        if not self.documents or top_k < 1:
            return []
        query = _normalise(np.asarray([query_vector], dtype=np.float32))
        top_k = min(top_k, len(self.documents))
        if self._index is not None:
            scores, indices = self._index.search(query, top_k)
            pairs = [(int(i), float(s)) for i, s in zip(indices[0], scores[0], strict=True) if i != -1]
        else:
            sims = self._vectors @ query[0]
            order = np.argsort(-sims, kind="stable")[:top_k]
            pairs = [(int(i), float(sims[i])) for i in order]
        return [{"document": self.documents[i], "similarity": s} for i, s in pairs]

    def save(self, filepath: str) -> None:
        directory = os.path.dirname(filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "format_version": INDEX_FORMAT_VERSION,
            "dimension": self.dimension,
            "embedding_backend": self.embedding_backend,
            "documents": [{"text": d.text, "metadata": d.metadata} for d in self.documents],
            "vectors": self._vectors.round(6).tolist(),
        }
        tmp_path = f"{filepath}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp_path, filepath)  # atomic swap so readers never see a partial file
        logger.info("Saved vector store with %d documents to %s", len(self), filepath)

    def load(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            logger.info("No vector store index found at %s", filepath)
            return False
        try:
            with open(filepath, encoding="utf-8") as fh:
                payload = json.load(fh)
            if payload.get("format_version") != INDEX_FORMAT_VERSION:
                logger.warning("Ignoring index %s with unsupported format", filepath)
                return False
            dimension = int(payload["dimension"])
            documents = [Document(d["text"], d.get("metadata", {})) for d in payload["documents"]]
            vectors = payload["vectors"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Failed to load index %s: %s", filepath, exc)
            return False

        self.dimension = dimension
        self.embedding_backend = payload.get("embedding_backend")
        self.documents = []
        self._vectors = np.zeros((0, dimension), dtype=np.float32)
        self._reset_index()
        self.add_documents(documents, vectors)
        logger.info("Loaded vector store with %d documents from %s", len(self), filepath)
        return True
