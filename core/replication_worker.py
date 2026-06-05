import psycopg2
import time

DATABASES = {
    "us": 5433,
    "eu": 5434,
    "asia": 5435
}


def get_connection(port):

    return psycopg2.connect(
        host="localhost",
        port=port,
        database="sharddb",
        user="admin",
        password="password"
    )


def fetch_unreplicated_users(region, port):

    conn = get_connection(port)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            username,
            email,
            region,
            subscription_type
        FROM users
        WHERE replicated = FALSE
    """)

    users = cursor.fetchall()

    cursor.close()
    conn.close()

    return users


def mark_as_replicated(port):

    conn = get_connection(port)

    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET replicated = TRUE
        WHERE replicated = FALSE
    """)

    conn.commit()

    cursor.close()
    conn.close()


def replicate():

    for source_region, source_port in DATABASES.items():

        users = fetch_unreplicated_users(
            source_region,
            source_port
        )

        if not users:
            continue

        print(f"\nReplicating from {source_region.upper()}")

        for target_region, target_port in DATABASES.items():

            if source_region == target_region:
                continue

            target_conn = get_connection(target_port)

            target_cursor = target_conn.cursor()

            replicated_count = 0

            for user in users:

                try:

                    target_cursor.execute("""
                        INSERT INTO users
                        (
                            username,
                            email,
                            region,
                            subscription_type,
                            replicated
                        )
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON CONFLICT (email) DO NOTHING
                    """, user)

                    replicated_count += 1

                except Exception as e:

                    print("Replication error:", e)

            target_conn.commit()

            target_cursor.close()
            target_conn.close()

            print(
                f"Copied {replicated_count} users "
                f"to {target_region.upper()}"
            )

        mark_as_replicated(source_port)


while True:

    replicate()

    print("\nSleeping for 10 seconds...\n")

    time.sleep(10)
