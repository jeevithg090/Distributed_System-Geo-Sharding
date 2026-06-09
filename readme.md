# GeoShardDB

A hands-on **multi-region distributed database simulator** that models how global backends shard data, route requests, replicate across regions, cache hot paths, and stay available under partial failure.

GeoShardDB runs three PostgreSQL shards (US, EU, Asia) behind a **FastAPI** gateway with **Redis** cache-aside, **circuit breakers**, **Prometheus** metrics, a **RAG** query assistant over project documentation, and interactive **OS concepts** demos (scheduling, paging, locks, deadlocks, work queues).

---

## Architecture

```mermaid
flowchart TB
    Client[Client / Benchmarks]
    LB[NGINX Load Balancer :8000]
    API[FastAPI Gateway Replicas (3)]
    Redis[(Redis :6379)]
    RAG[RAG Index + Embeddings]
    US[(US Shard :5433)]
    EU[(EU Shard :5434)]
    ASIA[(ASIA Shard :5435)]
    Prom[Prometheus :9090]
    Graf[Grafana :3000]

    Client --> LB
    LB --> API
    API --> Redis
    API --> RAG
    API --> US
    API --> EU
    API --> ASIA
    Prom --> API
    Graf --> Prom
```

| Layer | Role |
|-------|------|
| **Load Balancer** | NGINX round-robin proxy distributing traffic to scaled API gateways |
| **Shards** | Region-partitioned PostgreSQL 16 nodes; each stores users local to that geography |
| **Router (API)** | Region-aware reads, cross-shard fan-out, failover via circuit breakers |
| **Cache** | Redis cache-aside per region (`region:user:{id}`), 5-minute TTL |
| **Replication** | Background worker copies unreplicated rows for eventual consistency |
| **Observability** | Prometheus scrapes FastAPI metrics; Grafana for dashboards |

---

## Features

### Distributed database

- **Geographic sharding** — users are stored on the shard matching their region (`us`, `eu`, `asia`)
- **Request routing** — single-shard lookups with measured latency
- **Cross-shard queries** — sequential and parallel fan-out across all regions
- **Async replication** — `replication_worker.py` propagates rows marked `replicated = FALSE`
- **Connection pooling benchmarks** — compare pooled vs. direct connections
- **Fault tolerance** — stop a regional container; resilient router and API circuit breakers degrade gracefully

### API gateway (v2)

- **Cache-aside** — Redis before PostgreSQL on `GET /users/{user_id}`
- **Circuit breaker** — per-region OPEN / HALF-OPEN / CLOSED with cross-region failover
- **Health checks** — `GET /health` reports shard and breaker state
- **Cross-region aggregation** — `GET /users/recent/all`

### RAG assistant

- Embeds project knowledge with `sentence-transformers` + **FAISS**
- `POST /rag/ask` — retrieval-augmented answers about GeoShardDB behavior
- `POST /rag/index` — rebuild the vector index from `rag/knowledge_base.py`

### OS concepts (educational)

Interactive endpoints that map distributed problems to classical OS ideas:

| Endpoint | Concepts |
|----------|----------|
| `GET /os/schedule` | FCFS, SJF, priority, round-robin, MLFQ |
| `GET /os/page-replacement` | FIFO, LRU, LFU, clock, optimal |
| `GET /os/locks` | Distributed mutex (Redis-backed) |
| `GET /os/semaphore/status` | Connection limiting per region |
| `GET /os/deadlocks` | Wait-for graph cycle detection |
| `POST /queue/produce` | Producer–consumer bounded work queue |

### Observability

- **Prometheus** — `http://localhost:9090` (scrapes API at `:8000`)
- **Grafana** — `http://localhost:3000`
- **Redis Commander** — `http://localhost:8081`

---

## Tech stack

| Category | Technologies |
|----------|----------------|
| Runtime | Python 3.12, FastAPI, Uvicorn |
| Data | PostgreSQL 16, psycopg2, Redis 7 |
| ML / RAG | sentence-transformers, FAISS, NumPy |
| Infra | Docker Compose, Kubernetes manifests, AWS EC2 (optional) |
| Metrics | prometheus-fastapi-instrumentator |

---

## Project structure

```text
├── app.py                      # FastAPI gateway (main entry point)
├── docker-compose.yml          # Full stack: API, 3 shards, Redis, monitoring
├── init_schema.sql             # Shared schema for all shards
├── seed_data.py                # Populate shards with regional test data
├── requirements.txt
│
├── core/
│   ├── router.py               # CLI: single-shard query
│   ├── resilient_router.py     # CLI: queries with failure handling
│   ├── replication_worker.py   # Async cross-region replication
│   └── redis_cache.py          # Cache-aside layer
│
├── benchmarks/
│   ├── benchmark.py            # Per-shard latency stats
│   ├── pooled_benchmark.py     # Connection pool comparison
│   ├── cross_shard_query.py    # Sequential fan-out
│   ├── parallel_cross_shard.py # Threaded fan-out
│   └── cache_benchmark.py      # Cold vs warm cache latency
│
├── rag/
│   ├── knowledge_base.py       # Source documents for indexing
│   ├── indexer.py              # Build FAISS index (CLI)
│   └── query_engine.py         # Retrieval + answer formatting
│
├── os_concepts/
│   ├── scheduler.py            # CPU-style request scheduling
│   ├── page_replacement.py     # Cache eviction algorithms
│   ├── sync_primitives.py      # Mutex, semaphore, deadlock detection
│   └── work_queue.py           # Background job consumers
│
├── k8s/                        # Kubernetes Postgres + API manifests
├── setup_aws.sh                # Optional AWS VPC / EC2 provisioning
└── prometheus.yml
```

---

## Quick start (Docker — recommended)

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- ~4 GB free disk (API image installs CPU-only PyTorch for embeddings)

### 1. Clone and start the stack

```bash
git clone https://github.com/jeevithg090/Distributed_System-Geo-Sharding.git
cd Distributed_System-Geo-Sharding
docker compose up -d --build
```

Wait until all services are healthy (`docker compose ps`).

### 2. Seed the database

```bash
docker compose exec api python seed_data.py
```

This inserts region-specific users, products, tickets, and audit logs into each shard.

### 3. Build the RAG index (optional)

```bash
docker compose exec api python rag/indexer.py
```

### 4. Try the API

| Action | Command |
|--------|---------|
| API root | `curl http://localhost:8000/` |
| Interactive docs | Open [http://localhost:8000/docs](http://localhost:8000/docs) |
| Health | `curl http://localhost:8000/health` |
| User lookup | `curl "http://localhost:8000/users/1?region=us"` |
| RAG question | `curl -X POST http://localhost:8000/rag/ask -H "Content-Type: application/json" -d '{"question":"How does sharding work?"}'` |
| Cache stats | `curl http://localhost:8000/cache/stats` |

---

## Local development (without Docker API)

Use this when you want to run Python scripts directly against exposed Postgres ports.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start only databases + Redis
docker compose up -d us-node eu-node asia-node redis

python seed_data.py
python rag/indexer.py   # optional
uvicorn app:app --reload --port 8000
```

### Shard ports (host → container)

| Region | Host port | Service alias (inside Compose network) |
|--------|-----------|----------------------------------------|
| US | 5433 | `us-postgres-service` |
| EU | 5434 | `eu-postgres-service` |
| Asia | 5435 | `asia-postgres-service` |

Default credentials: `admin` / `password`, database `sharddb`.

---

## CLI tools and benchmarks

Run these from the project root with shards reachable on `localhost` (Docker ports above).

```bash
# Interactive single-shard router
python core/router.py

# Resilient router (simulates timeouts / failures)
python core/resilient_router.py

# Cross-shard: sequential vs parallel
python benchmarks/cross_shard_query.py
python benchmarks/parallel_cross_shard.py

# Latency percentiles per region
python benchmarks/benchmark.py
python benchmarks/pooled_benchmark.py

# Replication loop (Ctrl+C to stop)
python core/replication_worker.py

# Cache cold vs warm (requires API on :8000)
python benchmarks/cache_benchmark.py
```

### Fault-injection demo

```bash
docker stop eu-node
python core/resilient_router.py   # or hit the API with region=eu
docker start eu-node
```

---

## API reference (summary)

<details>
<summary><strong>Core</strong></summary>

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info and feature list |
| GET | `/health` | Per-region DB + circuit breaker status |
| GET | `/users/{user_id}?region=` | Cached user lookup |
| GET | `/users/recent/all` | Recent users from every shard |
| GET | `/breaker-status` | Circuit breaker state |

</details>

<details>
<summary><strong>Cache</strong></summary>

| Method | Path | Description |
|--------|------|-------------|
| GET | `/cache/stats` | Hit/miss counters |
| DELETE | `/cache/{region}` | Invalidate one region |
| DELETE | `/cache` | Flush all keys |

</details>

<details>
<summary><strong>RAG</strong></summary>

| Method | Path | Description |
|--------|------|-------------|
| POST | `/rag/ask` | Body: `{"question": "..."}` |
| POST | `/rag/index` | Rebuild vector index |
| GET | `/rag/status` | Index metadata |

</details>

<details>
<summary><strong>OS concepts & queue</strong></summary>

| Method | Path | Description |
|--------|------|-------------|
| GET | `/os/schedule?algorithm=fcfs&count=10` | Scheduling demo |
| GET | `/os/page-replacement?algorithm=lru` | Page replacement demo |
| GET/POST | `/os/locks`, `/os/locks/acquire`, `/os/locks/release` | Distributed mutex |
| GET | `/os/deadlocks` | Deadlock detection |
| POST | `/os/deadlocks/simulate` | Inject a cycle in the wait-for graph |
| POST | `/queue/produce` | Enqueue a background job |
| GET | `/queue/stats` | Queue depth and consumer stats |

</details>

Full OpenAPI schema: **http://localhost:8000/docs**

---

## Optional: AWS and Kubernetes

- **`setup_aws.sh`** — provisions VPC, subnet, security group, and an Ubuntu EC2 instance for remote deployment (requires AWS CLI and credentials).
- **`api-deployment.yaml`**, **`k8s/us-postgres.yaml`**, **`eu-postgres.yaml`**, **`asia-postgres.yaml`** — example manifests; build the API image locally (`docker build -t geoshard-api:latest .`) before applying.

Postgres containers include `NET_ADMIN` so you can add **Linux `tc netem`** rules inside a shard to simulate intercontinental latency (e.g. 80 ms US↔EU). This is manual but matches how production networks are emulated in labs.

---

## Distributed systems concepts

This repo is designed to make the following ideas concrete:

- Horizontal **sharding** and geographic **partitioning**
- **Request routing** and **cross-shard coordination**
- **Cache-aside**, **eventual consistency**, and **replication lag**
- **Circuit breakers** and **graceful degradation**
- **Parallel vs sequential** distributed queries
- **Connection pooling** and throughput tradeoffs
- **Observability** (metrics, latency measurement)
- Mapping to **OS scheduling**, **memory eviction**, **synchronization**, and **deadlocks**

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API can't connect to Postgres | Ensure `docker compose up` finished; check `docker compose logs api` |
| Empty user results | Run `python seed_data.py` (or via `docker compose exec api`) |
| RAG returns "index not initialized" | Run `python rag/indexer.py` or `POST /rag/index` |
| Redis connection errors from host | Use `localhost:6379`; inside Compose the host is `redis` |
| Slow first API start | First build downloads embedding dependencies; subsequent starts are faster |

---

## License

This project is provided for educational and portfolio use. Add a license file if you plan to open-source it formally.

---

## Author

Built by [jeevithg090](https://github.com/jeevithg090) to explore how globally distributed databases and cloud-native backends behave across regions.