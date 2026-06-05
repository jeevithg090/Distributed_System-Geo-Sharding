import psycopg2
import time
import threading

DATABASES = {
    "us": {
        "host": "localhost",
        "port": 5433
    },
    "eu": {
        "host": "localhost",
        "port": 5434
    },
    "asia": {
        "host": "localhost",
        "port": 5435
    }
}

all_results = []


def query_region(region, db_config):

    global all_results

    conn = psycopg2.connect(
        host=db_config["host"],
        port=db_config["port"],
        database="sharddb",
        user="admin",
        password="password"
    )

    cursor = conn.cursor()

    print(f"Querying {region.upper()} shard...")

    cursor.execute("""
        SELECT user_id, username, region, created_at
        FROM users
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """)

    results = cursor.fetchall()

    print(f"{region.upper()} returned {len(results)} users")

    all_results.extend(results)

    cursor.close()
    conn.close()


threads = []

start_time = time.time()

for region, db in DATABASES.items():

    thread = threading.Thread(
        target=query_region,
        args=(region, db)
    )

    threads.append(thread)

    thread.start()


for thread in threads:
    thread.join()

end_time = time.time()

latency_ms = (end_time - start_time) * 1000

print("\n============================")
print(f"TOTAL USERS FOUND: {len(all_results)}")
print(f"TOTAL QUERY TIME: {latency_ms:.2f} ms")
print("============================")

