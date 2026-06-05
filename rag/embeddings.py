# rag/embeddings.py
# Embedding engine using sentence-transformers (local execution)

import os
# Suppress Hugging Face warnings/info logs unless critical
os.environ["TOKENIZERS_PARALLELISM"] = "false"

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Warning: sentence-transformers not installed. RAG features will run with fallback mock embeddings.")

class EmbeddingEngine:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self._init_model()

    def _init_model(self):
        try:
            # This downloads model to cache directory (~120MB)
            self.model = SentenceTransformer(self.model_name)
            print(f"Loaded sentence transformer model: {self.model_name}")
        except Exception as e:
            print(f"Failed to load sentence-transformers model: {e}")
            self.model = None

    def embed_text(self, text):
        if self.model:
            # Return list of floats
            return self.model.encode(text).tolist()
        else:
            # Fallback mock embedding (384-dim vector with deterministic hash values)
            import numpy as np
            print("Using fallback mock embedding for text.")
            rng = np.random.default_rng(hash(text) & 0xffffffff)
            vec = rng.random(384)
            norm = np.linalg.norm(vec)
            vec = vec / norm if norm > 0 else vec
            return vec.tolist()

    def embed_batch(self, texts):
        if self.model:
            return self.model.encode(texts).tolist()
        else:
            return [self.embed_text(t) for t in texts]
