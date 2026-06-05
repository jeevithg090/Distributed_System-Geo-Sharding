import psycopg2
import time

DATABASES = {
    "us": 5433,
    "eu": 5434,
    "asia": 5435
}


def get_user(user_id, region):

    if region not in DATABASES:

        print("Invalid region")
        return

    port = DATABASES[region]

    try:

        start = time.time()

        conn = psycopg2.connect(
            host="localhost",
            port=port,
            database="sharddb",
            user="admin",
            password="password",
            connect_timeout=3
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM users
            WHERE user_id = %s
        """, (user_id,))

        result = cursor.fetchone()

        end = time.time()

        latency_ms = (end - start) * 1000

        print("\n--- RESULT ---")
        print(result)

        print(f"\nLatency: {latency_ms:.2f} ms")

        cursor.close()
        conn.close()

    except Exception as e:

        print("\nRegion unavailable")
        print("Error:", e)


user_id = int(input("Enter user ID: "))
region = input("Enter region: ").lower()

get_user(user_id, region)
