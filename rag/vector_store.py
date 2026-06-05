# rag/vector_store.py
# FAISS-based Vector Store with numpy-based cosine similarity fallback

import os
import pickle
import numpy as np

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("Warning: faiss-cpu not installed. RAG features will run with fallback NumPy vector store.")

class VectorStore:
    def __init__(self, dimension=384):
        self.dimension = dimension
        self.documents = []
        self.vectors = []
        self.index = None
        self._init_index()

    def _init_index(self):
        if FAISS_AVAILABLE:
            # L2 distance index (FAISS doesn't directly support Cosine without IP index on normalized vectors)
            # We will normalize vectors upon adding and querying to make IndexFlatIP act as Cosine Similarity
            self.index = faiss.IndexFlatIP(self.dimension)
        else:
            self.index = None

    def add_documents(self, docs, vecs):
        """Adds documents and their corresponding embedding vectors to the index"""
        assert len(docs) == len(vecs), "Documents and vectors size mismatch"
        if not docs:
            return

        # Normalize vectors for Cosine Similarity
        normalized_vecs = []
        for v in vecs:
            arr = np.array(v, dtype='float32')
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            normalized_vecs.append(arr.tolist())

        self.documents.extend(docs)
        self.vectors.extend(normalized_vecs)

        if FAISS_AVAILABLE and self.index:
            np_vecs = np.array(normalized_vecs, dtype='float32')
            self.index.add(np_vecs)

    def search(self, query_vector, top_k=5):
        """Searches top_k closest documents to the query vector"""
        if not self.documents:
            return []

        # Normalize query vector
        q_arr = np.array(query_vector, dtype='float32')
        q_norm = np.linalg.norm(q_arr)
        if q_norm > 0:
            q_arr = q_arr / q_norm

        top_k = min(top_k, len(self.documents))

        if FAISS_AVAILABLE and self.index:
            # Query vector shape needs to be (1, dim)
            q_np = np.array([q_arr], dtype='float32')
            similarities, indices = self.index.search(q_np, top_k)
            
            results = []
            for sim, idx in zip(similarities[0], indices[0]):
                if idx != -1 and idx < len(self.documents):
                    results.append({
                        "document": self.documents[idx],
                        "similarity": float(sim) # FlatIP on normalized vectors gives cosine similarity [-1, 1]
                    })
            return results
        else:
            # Fallback Cosine Similarity using NumPy
            np_vectors = np.array(self.vectors, dtype='float32')
            # Cosine similarity is dot product of normalized vectors
            similarities = np.dot(np_vectors, q_arr)
            
            # Get top_k indices sorted descending by similarity
            top_indices = np.argsort(similarities)[::-1][:top_k]
            
            results = []
            for idx in top_indices:
                results.append({
                    "document": self.documents[idx],
                    "similarity": float(similarities[idx])
                })
            return results

    def save(self, filepath):
        """Saves index and document list to disk"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data = {
            "documents": self.documents,
            "vectors": self.vectors,
            "dimension": self.dimension
        }
        with open(filepath, "wb") as f:
            pickle.dump(data, f)
        print(f"Saved vector store with {len(self.documents)} documents to {filepath}")

    def load(self, filepath):
        """Loads index and document list from disk"""
        if not os.path.exists(filepath):
            print(f"No vector store index found at {filepath}")
            return False
            
        with open(filepath, "rb") as f:
            data = pickle.load(f)
            
        self.documents = data["documents"]
        self.vectors = data["vectors"]
        self.dimension = data["dimension"]
        self._init_index()

        if FAISS_AVAILABLE and self.index and self.vectors:
            np_vecs = np.array(self.vectors, dtype='float32')
            self.index.add(np_vecs)
            
        print(f"Loaded vector store with {len(self.documents)} documents from {filepath}")
        return True
