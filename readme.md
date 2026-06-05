# GeoShardDB

## A Multi-Region Distributed Database Simulator with Sharding, Replication, Latency Simulation, and Fault Tolerance

GeoShardDB is a distributed systems project that simulates a globally distributed database architecture using PostgreSQL, Docker, Python, and Linux traffic control (`tc netem`).

The system demonstrates real-world distributed database concepts including:

* Geographic sharding
* Multi-region request routing
* Cross-shard querying
* Parallel distributed query execution
* Asynchronous replication
* Eventual consistency
* Simulated intercontinental latency
* Connection pooling
* Fault tolerance and failure handling
* Distributed systems benchmarking

This project was built to explore how large-scale distributed databases and cloud-native backend systems operate across geographically separated regions.

---

# Core Features

## Geographic Sharding

Users are partitioned by geographic region:

* US users stored in US shard
* EU users stored in EU shard
* ASIA users stored in ASIA shard

The router intelligently directs requests to the correct regional database.

---

## Distributed Query Routing

The request router:

* Identifies the target shard
* Connects to the correct PostgreSQL node
* Executes region-aware queries
* Measures query latency

---

## Cross-Shard Queries

The system supports distributed fan-out queries across all regions.

Features include:

* Sequential cross-region querying
* Parallel distributed querying using threads
* Result aggregation
* Cross-region latency measurement

---

## Linux Traffic Control Simulation

Using Linux `tc netem`, the project simulates real-world geographic network latency.

Example latency simulation:

| Route     | Simulated Delay |
| --------- | --------------- |
| US ↔ EU   | 80ms            |
| EU ↔ ASIA | 120ms           |
| US ↔ ASIA | 160ms           |

This allows realistic distributed systems experimentation.

---

## Asynchronous Replication

A custom replication worker continuously:

* Detects unreplicated rows
* Replicates data across regions
* Handles duplicate conflicts
* Simulates eventual consistency

Replication demonstrates:

* Cross-region synchronization
* Replication lag
* Eventual consistency
* Distributed propagation delays

---

## Connection Pooling

The project includes optimized database access using PostgreSQL connection pooling.

Benefits:

* Reduced connection overhead
* Lower latency
* Improved throughput
* Better scalability

---

## Fault Tolerance

The system can simulate regional failures by shutting down containers.

The resilient router:

* Detects unavailable regions
* Handles connection failures gracefully
* Demonstrates distributed fault tolerance concepts

---

# Technology Stack

## Backend

* Python 3
* psycopg2
* threading

## Database

* PostgreSQL 16

## Infrastructure

* Docker
* Docker Compose
* AWS EC2 (Ubuntu)

## Networking

* Linux tc/netem
* Docker bridge networking

---

# Project Structure

```text
GeoShardDB/
│
├── docker-compose.yml
├── seed_data.py
├── router.py
├── resilient_router.py
├── cross_shard_query.py
├── parallel_cross_shard.py
├── benchmark.py
├── pooled_benchmark.py
├── replication_worker.py
└── README.md
```

---

# Setup Instructions

## Clone Repository

```bash
git clone https://github.com/jeevithg090/Distributed_System-Geo-Sharding.git
cd Distributed_System-Geo-Sharding
```

---

## Start Containers

```bash
docker compose up -d
```

---

## Verify Running Containers

```bash
docker ps
```

Expected containers:

* us-node
* eu-node
* asia-node

---

## Create Python Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## Install Dependencies

```bash
pip install psycopg2-binary faker
```

---

# Database Ports

| Region | Port |
| ------ | ---- |
| US     | 5433 |
| EU     | 5434 |
| ASIA   | 5435 |

---

# Example Commands

## Run Request Router

```bash
python3 router.py
```

---

## Run Cross-Shard Query

```bash
python3 cross_shard_query.py
```

---

## Run Parallel Distributed Query

```bash
python3 parallel_cross_shard.py
```

---

## Run Benchmarking

```bash
python3 benchmark.py
```

---

## Run Replication Worker

```bash
python3 replication_worker.py
```

---

# Distributed Systems Concepts Demonstrated

This project demonstrates several advanced backend and distributed systems concepts:

* Horizontal database sharding
* Geographic partitioning
* Distributed query coordination
* Eventual consistency
* Asynchronous replication
* Replication lag
* Network latency simulation
* Distributed fault tolerance
* Connection pooling
* Cross-region communication overhead
* Parallel query execution
* Benchmarking and observability

---

# Future Improvements

Potential extensions:

* FastAPI gateway
* Automatic failover
* Read replicas
* Circuit breaker pattern
* Distributed caching
* Monitoring with Prometheus/Grafana
* Kubernetes deployment
* Distributed tracing
* CAP theorem simulations

---

