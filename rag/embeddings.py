"""Text embedding backends.

* ``model`` – sentence-transformers (``all-MiniLM-L6-v2`` by default, 384 dims).
* ``hash``  – a dependency-free feature-hashing bag-of-words embedding. It is
  deterministic across processes, so an index built by one process can be
  queried by another, and lexical overlap still yields meaningful similarity.
* ``auto``  – use the model when sentence-transformers is importable and the
  model loads, otherwise fall back to ``hash``.

The model is loaded lazily on first use so importing the API stays fast.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import os
import re
import threading
from typing import Any

import numpy as np

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

logger = logging.getLogger(__name__)

DIMENSION = 384
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def hash_embedding(text: str, dimension: int = DIMENSION) -> list[float]:
    """Embed ``text`` by hashing unigrams and bigrams into ``dimension`` signed buckets."""
    tokens = _TOKEN_RE.findall(text.lower())
    features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
    vec = np.zeros(dimension, dtype=np.float32)
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return [float(x) for x in vec]


class EmbeddingEngine:
    def __init__(self, backend: str = "auto", model_name: str = "all-MiniLM-L6-v2") -> None:
        if backend not in {"auto", "model", "hash"}:
            raise ValueError(f"Unknown embedding backend: {backend}")
        self.requested_backend = backend
        self.model_name = model_name
        self._model: Any = None
        self._resolved: str | None = "hash" if backend == "hash" else None
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        """Return the backend in use (``model:<name>`` or ``hash``), loading the model if needed."""
        self._ensure_loaded()
        assert self._resolved is not None
        return self._resolved

    def _ensure_loaded(self) -> None:
        if self._resolved is not None:
            return
        with self._lock:
            if self._resolved is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
                self._resolved = f"model:{self.model_name}"
                logger.info("Loaded sentence-transformers model %s", self.model_name)
            except Exception as exc:
                if self.requested_backend == "model":
                    raise RuntimeError(f"Could not load embedding model {self.model_name}") from exc
                logger.warning("Embedding model unavailable (%s); using hash embeddings", exc)
                self._resolved = "hash"

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._ensure_loaded()
        if self._model is not None:
            return [list(map(float, v)) for v in self._model.encode(texts)]
        return [hash_embedding(t) for t in texts]
