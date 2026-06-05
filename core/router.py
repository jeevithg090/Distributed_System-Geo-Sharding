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


def get_user(user_id, region):

    if region not in DATABASES:
        print(f"Invalid region: {region}")
        return

    db = DATABASES[region]

    start_time = time.time()

    conn = psycopg2.connect(
        host=db["host"],
        port=db["port"],
        database="sharddb",
        user="admin",
        password="password"
    )

    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, username, email, region
        FROM users
        WHERE user_id = %s
    """, (user_id,))

    result = cursor.fetchone()

    end_time = time.time()

    latency_ms = (end_time - start_time) * 1000

    print("\n--- QUERY RESULT ---")
    print(result)

    print(f"\nQuery Time: {latency_ms:.2f} ms")

    cursor.close()
    conn.close()


user_id = int(input("Enter user ID: "))
region = input("Enter region (us/eu/asia): ").lower()

get_user(user_id, region)
