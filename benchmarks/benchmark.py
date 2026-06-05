import psycopg2
import time
import statistics
import random

DATABASES = {
    "us": 5433,
    "eu": 5434,
    "asia": 5435
}


def run_query(region, port):

    conn = psycopg2.connect(
        host="localhost",
        port=port,
        database="sharddb",
        user="admin",
        password="password"
    )

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
    conn.close()

    return latency_ms


for region, port in DATABASES.items():

    latencies = []

    print(f"\nRunning benchmark for {region.upper()} shard...")

    for _ in range(50):

        latency = run_query(region, port)

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
