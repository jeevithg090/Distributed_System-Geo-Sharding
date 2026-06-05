import psycopg2
from psycopg2 import pool
import time
import statistics
import random

DATABASES = {
    "us": 5433,
    "eu": 5434,
    "asia": 5435
}

POOLS = {}

for region, port in DATABASES.items():

    POOLS[region] = pool.SimpleConnectionPool(
        1,
        10,
        host="localhost",
        port=port,
        database="sharddb",
        user="admin",
        password="password"
    )


def run_query(region):

    connection_pool = POOLS[region]

    conn = connection_pool.getconn()

    cursor = conn.cursor()

    user_id = random.randint(1, 500)

    start = time.time()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE user_id = %s
    """, (user_id,))

    cursor.fetchone()

    end = time.time()

    latency_ms = (end - start) * 1000

    cursor.close()

    connection_pool.putconn(conn)

    return latency_ms


for region in DATABASES.keys():

    latencies = []

    print(f"\nBenchmarking {region.upper()} shard...")

    for _ in range(50):

        latency = run_query(region)

        latencies.append(latency)

    min_latency = min(latencies)
    max_latency = max(latencies)
    avg_latency = statistics.mean(latencies)

    p95_latency = statistics.quantiles(
        latencies,
        n=100
    )[94]

    print(f"""
Region: {region.upper()}
-------------------------
Min:  {min_latency:.2f} ms
Avg:  {avg_latency:.2f} ms
P95:  {p95_latency:.2f} ms
Max:  {max_latency:.2f} ms
""")


for connection_pool in POOLS.values():
    connection_pool.closeall()
