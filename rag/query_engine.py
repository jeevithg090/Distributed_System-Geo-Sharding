# rag/query_engine.py
# Retrieval-only Query Engine for GeoShardDB RAG

import os
import sys

# Ensure parent directory is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.embeddings import EmbeddingEngine
from rag.vector_store import VectorStore

INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_index.pkl")

class RAGQueryEngine:
    def __init__(self):
        self.engine = EmbeddingEngine()
        self.store = VectorStore()
        self.index_loaded = self.store.load(INDEX_FILE)

    def reload_index(self):
        self.index_loaded = self.store.load(INDEX_FILE)
        return self.index_loaded

    def ask(self, question, top_k=3):
        if not self.index_loaded:
            # Try reloading in case it was built since initialization
            if not self.reload_index():
                return {
                    "question": question,
                    "answer": "Error: RAG index is not initialized. Please build the index first using /rag/index endpoint or running 'python rag/indexer.py'.",
                    "retrieved_documents": []
                }

        # 1. Embed question
        q_vector = self.engine.embed_text(question)
        
        # 2. Vector search
        results = self.store.search(q_vector, top_k=top_k)
        
        # 3. Construct a synthesized answer based on retrieved documents
        if not results:
            return {
                "question": question,
                "answer": "No relevant database metadata or stats documents were retrieved to answer your question.",
                "retrieved_documents": []
            }
            
        # Synthesize direct answer based on the best matched document
        best_match = results[0]["document"]
        similarity = results[0]["similarity"]
        
        # Intelligent direct response template-synthesizer based on similarity
        if similarity < 0.2:
            answer = "I found some database records, but their relevance is quite low. Here is what I retrieved:"
        else:
            answer = f"Based on retrieved system metadata and database statistics (Confidence: {similarity * 100:.1f}%):\n\n"
            # Extract key statements
            sentences = []
            for r in results:
                doc = r["document"]
                sentences.append(doc.text)
            answer += "\n".join([f"- {s}" for s in sentences])
            
        retrieved_docs_formatted = []
        for r in results:
            doc = r["document"]
            retrieved_docs_formatted.append({
                "text": doc.text,
                "similarity_score": round(r["similarity"], 4),
                "metadata": doc.metadata
            })

        return {
            "question": question,
            "answer": answer,
            "retrieved_documents": retrieved_docs_formatted
        }
