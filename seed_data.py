"""Seed every shard with region-specific demo data.

Truncates and repopulates ``users``, ``products``, ``support_tickets`` and
``audit_logs`` on each shard. Distributions differ per region so RAG answers
are interesting (e.g. EU skews to billing tickets and GDPR data exports).

Users get IDs from their region's ID block (US from 1, EU from 1,000,001,
ASIA from 2,000,001) and start with ``replicated = FALSE``, so the replication
worker can later copy them to the other shards.

Usage: ``python seed_data.py [--region us|eu|asia] [--users N] [--seed N]``
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from typing import Any

from faker import Faker

from core.config import REGIONS, shard_label
from core.db import reset_user_id_sequence, shard_cursor

DEPARTMENTS = ["engineering", "sales", "marketing", "support", "hr", "finance"]
SUBSCRIPTION_TYPES = ["free", "premium", "enterprise"]
STATUS_OPTIONS = ["active", "active", "active", "inactive", "suspended"]  # active is more common

# Regional characteristics for RAG differentiation
REGIONAL_DATA: dict[str, dict[str, Any]] = {
    "us": {
        "departments_weights": [0.40, 0.15, 0.10, 0.15, 0.10, 0.10],  # High engineering
        "subscriptions_weights": [0.20, 0.40, 0.40],  # High enterprise/premium
        "products": [
            ("US-East Compute Pro", "cloud_compute", 120.00, "High-performance VM instances in N. Virginia"),
            ("US-West Storage Standard", "storage", 45.00, "Highly available object storage in Oregon"),
            ("DataLake Analytics", "analytics", 350.00, "Serverless data analytics and query service"),
            (
                "US Sovereign Key Vault",
                "security",
                99.00,
                "FIPS 140-2 Level 3 compliant encryption keys management",
            ),
            (
                "Enterprise Service Mesh",
                "security",
                150.00,
                "Secure service-to-service communication network",
            ),
            ("US-East ML Training Hub", "ml_ai", 800.00, "Dedicated GPU clusters for model training"),
            (
                "Global CDN - US Edge",
                "cloud_compute",
                75.00,
                "Low-latency content delivery network edge nodes",
            ),
        ],
    },
    "eu": {
        "departments_weights": [0.20, 0.25, 0.15, 0.15, 0.15, 0.10],
        "subscriptions_weights": [0.40, 0.40, 0.20],  # Standard
        "products": [
            (
                "EU-GDPR Compliance Vault",
                "security",
                199.00,
                "GDPR-compliant data storage and sovereignty vault",
            ),
            (
                "Frankfurt Compute Core",
                "cloud_compute",
                110.00,
                "Compute nodes hosted locally in Frankfurt, Germany",
            ),
            (
                "Sovereign Cloud EU",
                "cloud_compute",
                250.00,
                "Fully isolated cloud infrastructure for EU public sector",
            ),
            ("Paris Database Master", "database", 180.00, "Managed HA PostgreSQL instances in Paris"),
            ("Dublin Cold Archive", "storage", 15.00, "Ultra-low-cost archival storage in Dublin"),
            (
                "EU Threat Detection System",
                "security",
                125.00,
                "AI-driven real-time network threat monitoring",
            ),
            ("GDPR Audit Logger", "analytics", 80.00, "Automated compliance log tracking and reporting"),
        ],
    },
    "asia": {
        "departments_weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
        "subscriptions_weights": [0.10, 0.60, 0.30],  # High premium adoption
        "products": [
            ("Tokyo ML Accelerator", "ml_ai", 950.00, "Next-gen GPU cluster optimized for LLM inference"),
            (
                "Singapore DB Cluster",
                "database",
                320.00,
                "Distributed multi-master database with sub-ms local latency",
            ),
            ("Mumbai Edge CDN", "cloud_compute", 60.00, "Edge caching and DNS routing nodes in South Asia"),
            (
                "Seoul Memory Cache",
                "database",
                85.00,
                "Managed in-memory Redis cluster for application caching",
            ),
            ("Sydney Storage Engine", "storage", 50.00, "Scalable file and object storage in Oceania"),
            (
                "Asia Threat Shield",
                "security",
                110.00,
                "DDoS protection and firewall service optimized for Asian routing",
            ),
            (
                "Beijing ML Vision APIs",
                "ml_ai",
                450.00,
                "Real-time computer vision and image processing endpoints",
            ),
        ],
    },
}

TICKET_SUBJECTS = {
    "billing": [
        "Incorrect invoice charge",
        "Update credit card details",
        "Refund request for server downtime",
        "Enterprise contract renewal query",
        "VAT tax exemption document upload",
        "Upgrade plan discount not applied",
    ],
    "technical": [
        "Server timeout during high load",
        "Database connection pool exhausted",
        "CDN cache invalidation delayed",
        "GPU instance out of memory error",
        "SSH permission denied on VM",
        "Object storage access key rotation failure",
    ],
    "account": [
        "Two-factor authentication reset",
        "Add user to organizational billing",
        "Change account owner email",
        "Close account and delete personal data",
        "SSO integration setup help",
        "API token authorization error",
    ],
    "feature_request": [
        "Support for ARM64 instances",
        "Add pgvector extension to Postgres",
        "Auto-scaling triggers based on custom metrics",
        "Integration with external SIEM tool",
        "S3-compatible bucket policy enhancements",
        "Custom domain support for CDN",
    ],
    "bug_report": [
        "Web console UI breaks on mobile",
        "Kubernetes service discovery DNS failure",
        "Metrics export showing wrong timestamp",
        "Cron job replication worker stuck",
        "CLI command returns 500 error",
        "Grafana dashboard panels not loading",
    ],
}


DEFAULT_VOLUMES = {
    "us": {"users": 500, "tickets": 200, "audit_logs": 1000},
    "eu": {"users": 400, "tickets": 150, "audit_logs": 800},
    "asia": {"users": 600, "tickets": 250, "audit_logs": 1200},
}

TICKET_CATEGORY_WEIGHTS = {
    "eu": [0.45, 0.15, 0.15, 0.10, 0.15],  # billing heavy
    "asia": [0.10, 0.50, 0.10, 0.10, 0.20],  # technical heavy
    "us": [0.20, 0.20, 0.20, 0.25, 0.15],  # feature-request heavy
}
PRIORITIES = ["low", "medium", "high", "critical"]
AUDIT_ACTIONS = {
    "login": "auth_service",
    "logout": "auth_service",
    "data_export": "users_database_dump",
    "permission_change": "rbac_policy_manager",
    "config_update": "cluster_config_file",
}


def seed_region(region: str, fake: Faker, rng: random.Random, scale: float = 1.0) -> dict[str, int]:
    """Repopulate ``region``'s shard and return the resulting row counts."""
    volumes = {k: max(1, int(v * scale)) for k, v in DEFAULT_VOLUMES[region].items()}
    profile = REGIONAL_DATA[region]
    now = datetime.now()

    with shard_cursor(region) as cur:
        cur.execute("TRUNCATE TABLE audit_logs, support_tickets, products, users RESTART IDENTITY CASCADE")
        reset_user_id_sequence(cur, region)

        for name, category, price, desc in profile["products"]:
            cur.execute(
                "INSERT INTO products (name, category, price_monthly, region, status, launch_date, "
                "description) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    name,
                    category,
                    price,
                    region,
                    rng.choice(["active", "active", "active", "beta", "deprecated"]),
                    fake.date_between(start_date="-5y", end_date="-1m"),
                    desc,
                ),
            )

        user_ids: list[int] = []
        for _ in range(volumes["users"]):
            login_count = rng.randint(0, 150)
            last_login = (
                now - timedelta(days=rng.randint(0, 30), hours=rng.randint(0, 23)) if login_count else None
            )
            cur.execute(
                "INSERT INTO users (username, email, region, subscription_type, department, status, "
                "login_count, last_login, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING user_id",
                (
                    fake.user_name(),
                    fake.unique.email(),
                    region,
                    rng.choices(SUBSCRIPTION_TYPES, weights=profile["subscriptions_weights"])[0],
                    rng.choices(DEPARTMENTS, weights=profile["departments_weights"])[0],
                    rng.choice(STATUS_OPTIONS),
                    login_count,
                    last_login,
                    fake.date_time_between(start_date="-1y", end_date="-1m"),
                ),
            )
            user_ids.append(cur.fetchone()[0])

        categories = list(TICKET_SUBJECTS)
        priority_weights = [0.10, 0.30, 0.40, 0.20] if region == "asia" else [0.30, 0.40, 0.25, 0.05]
        for _ in range(volumes["tickets"]):
            category = rng.choices(categories, weights=TICKET_CATEGORY_WEIGHTS[region])[0]
            status = rng.choice(["open", "in_progress", "resolved", "closed"])
            created_at = fake.date_time_between(start_date="-30d", end_date="now")
            resolved_at = (
                created_at + timedelta(days=rng.randint(1, 5)) if status in ("resolved", "closed") else None
            )
            cur.execute(
                "INSERT INTO support_tickets (user_id, subject, category, priority, status, region, "
                "created_at, resolved_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    rng.choice(user_ids),
                    rng.choice(TICKET_SUBJECTS[category]),
                    category,
                    rng.choices(PRIORITIES, weights=priority_weights)[0],
                    status,
                    region,
                    created_at,
                    resolved_at,
                ),
            )

        # EU logs more data exports (GDPR subject-access requests)
        action_weights = [0.30, 0.25, 0.35, 0.05, 0.05] if region == "eu" else [0.50, 0.40, 0.05, 0.03, 0.02]
        actions = list(AUDIT_ACTIONS)
        for _ in range(volumes["audit_logs"]):
            action = rng.choices(actions, weights=action_weights)[0]
            cur.execute(
                "INSERT INTO audit_logs (user_id, action, resource, region, ip_address, success, "
                "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    rng.choice(user_ids),
                    action,
                    AUDIT_ACTIONS[action],
                    region,
                    f"192.168.{rng.randint(1, 254)}.{rng.randint(1, 254)}",
                    rng.random() < 0.97,
                    fake.date_time_between(start_date="-30d", end_date="now"),
                ),
            )

        counts = {}
        for table in ("users", "products", "support_tickets", "audit_logs"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # table names are constants
            counts[table] = cur.fetchone()[0]
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed GeoShardDB shards with demo data")
    parser.add_argument("--region", choices=REGIONS, action="append", help="seed only these regions")
    parser.add_argument("--scale", type=float, default=1.0, help="multiply default row volumes")
    parser.add_argument("--seed", type=int, help="random seed for reproducible data")
    args = parser.parse_args(argv)

    fake = Faker()
    if args.seed is not None:
        Faker.seed(args.seed)
    rng = random.Random(args.seed)

    failed = []
    for region in args.region or REGIONS:
        print(f"Seeding {shard_label(region)} ...")
        try:
            counts = seed_region(region, fake, rng, scale=args.scale)
        except Exception as exc:
            print(f"  failed: {exc}", file=sys.stderr)
            failed.append(region)
            continue
        print("  " + ", ".join(f"{table}={n}" for table, n in counts.items()))

    if failed:
        print(f"Could not seed: {', '.join(failed)}. Are the shards running?", file=sys.stderr)
        return 1
    print("All shards seeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
