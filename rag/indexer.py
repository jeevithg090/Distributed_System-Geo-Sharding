# rag/indexer.py
# Script to build or refresh the RAG knowledge base vector index

import os
import sys

# Ensure parent directory is in python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.embeddings import EmbeddingEngine
from rag.vector_store import VectorStore
from rag.knowledge_base import KnowledgeBase

RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.environ.get('RUNNING_IN_DOCKER') == 'true'

if RUNNING_IN_DOCKER:
    DB_CONFIGS = {
        "us": {"host": "us-postgres-service", "port": 5432},
        "eu": {"host": "eu-postgres-service", "port": 5432},
        "asia": {"host": "asia-postgres-service", "port": 5432}
    }
else:
    DB_CONFIGS = {
        "us": {"host": "localhost", "port": 5433},
        "eu": {"host": "localhost", "port": 5434},
        "asia": {"host": "localhost", "port": 5435}
    }

INDEX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rag_index.pkl")

def build_index():
    print("==================================================")
    print("Starting RAG Indexer for GeoShardDB")
    print("==================================================")
    
    # 1. Harvest documents
    print("Harvesting documents from database shards...")
    kb = KnowledgeBase(DB_CONFIGS)
    docs = kb.harvest_all()
    
    if not docs:
        print("Error: No documents harvested. Are the database shards running and seeded?")
        print("Please run seed_data.py to populate databases first.")
        return False
        
    print(f"Successfully harvested {len(docs)} knowledge documents:")
    for idx, d in enumerate(docs):
        print(f"  [{idx+1}] Source: {d.metadata.get('source')} | Region: {d.metadata.get('region')} | Preview: {d.text[:60]}...")
        
    # 2. Generate embeddings
    print("\nInitializing Embedding Engine and generating vectors...")
    engine = EmbeddingEngine()
    
    texts = [d.text for d in docs]
    vectors = engine.embed_batch(texts)
    print(f"Generated {len(vectors)} vectors of dimension {len(vectors[0])}")
    
    # 3. Build Vector Store
    print("\nBuilding vector index...")
    store = VectorStore(dimension=len(vectors[0]))
    store.add_documents(docs, vectors)
    
    # 4. Save to disk
    store.save(INDEX_FILE)
    print("RAG Indexer complete!")
    print("==================================================")
    return True

if __name__ == "__main__":
    build_index()
