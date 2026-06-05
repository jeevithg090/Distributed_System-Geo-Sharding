import psycopg2
import time

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


def query_region(region, db_config):

    conn = psycopg2.connect(
        host=db_config["host"],
        port=db_config["port"],
        database="sharddb",
        user="admin",
        password="password"
    )

    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, username, region, created_at
        FROM users
        WHERE created_at >= NOW() - INTERVAL '7 days'
    """)

    results = cursor.fetchall()

    cursor.close()
    conn.close()

    return results


def cross_shard_query():

    all_results = []

    start_time = time.time()

    for region, db in DATABASES.items():

        print(f"\nQuerying {region.upper()} shard...")

        results = query_region(region, db)

        print(f"Found {len(results)} users")

        all_results.extend(results)

    end_time = time.time()

    latency_ms = (end_time - start_time) * 1000

    print("\n============================")
    print(f"TOTAL USERS FOUND: {len(all_results)}")
    print(f"TOTAL QUERY TIME: {latency_ms:.2f} ms")
    print("============================")


cross_shard_query()

