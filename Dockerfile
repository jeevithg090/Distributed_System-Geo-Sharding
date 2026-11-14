# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Set INSTALL_RAG=false for a much smaller image that uses hash embeddings
# and NumPy search instead of sentence-transformers + FAISS.
ARG INSTALL_RAG=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/data/hf-cache \
    RAG_INDEX_PATH=/app/data/rag_index.json

WORKDIR /app

COPY requirements.txt requirements-rag.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_RAG" = "true" ]; then \
        pip install torch --index-url https://download.pytorch.org/whl/cpu \
     && pip install -r requirements-rag.txt; \
    fi

RUN useradd --create-home --uid 10001 geoshard \
 && mkdir -p /app/data \
 && chown geoshard:geoshard /app/data

COPY --chown=geoshard:geoshard . .

USER geoshard

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
