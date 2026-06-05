# seed_data.py
# Enhanced seed script for GeoShardDB to enable interesting RAG queries

import psycopg2
from faker import Faker
import random
import os
import sys
from datetime import datetime, timedelta

fake = Faker()

# Detect if we are running inside docker or on the host
RUNNING_IN_DOCKER = os.path.exists('/.dockerenv') or os.environ.get('RUNNING_IN_DOCKER') == 'true'

if RUNNING_IN_DOCKER:
    DATABASES = {
        "us": {"host": "us-postgres-service", "port": 5432},
        "eu": {"host": "eu-postgres-service", "port": 5432},
        "asia": {"host": "asia-postgres-service", "port": 5432}
    }
else:
    DATABASES = {
        "us": {"host": "localhost", "port": 5433},
        "eu": {"host": "localhost", "port": 5434},
        "asia": {"host": "localhost", "port": 5435}
    }

DEPARTMENTS = ["engineering", "sales", "marketing", "support", "hr", "finance"]
SUBSCRIPTION_TYPES = ["free", "premium", "enterprise"]
STATUS_OPTIONS = ["active", "active", "active", "inactive", "suspended"] # active is more common

# Regional characteristics for RAG differentiation
REGIONAL_DATA = {
    "us": {
        "departments_weights": [0.40, 0.15, 0.10, 0.15, 0.10, 0.10], # High engineering
        "subscriptions_weights": [0.20, 0.40, 0.40], # High enterprise/premium
        "products": [
            ("US-East Compute Pro", "cloud_compute", 120.00, "High-performance VM instances in N. Virginia"),
            ("US-West Storage Standard", "storage", 45.00, "Highly available object storage in Oregon"),
            ("DataLake Analytics", "analytics", 350.00, "Serverless data analytics and query service"),
            ("US Sovereign Key Vault", "security", 99.00, "FIPS 140-2 Level 3 compliant encryption keys management"),
            ("Enterprise Service Mesh", "security", 150.00, "Secure service-to-service communication network"),
            ("US-East ML Training Hub", "ml_ai", 800.00, "Dedicated GPU clusters for model training"),
            ("Global CDN - US Edge", "cloud_compute", 75.00, "Low-latency content delivery network edge nodes")
        ]
    },
    "eu": {
        "departments_weights": [0.20, 0.25, 0.15, 0.15, 0.15, 0.10],
        "subscriptions_weights": [0.40, 0.40, 0.20], # Standard
        "products": [
            ("EU-GDPR Compliance Vault", "security", 199.00, "GDPR-compliant data storage and sovereignty vault"),
            ("Frankfurt Compute Core", "cloud_compute", 110.00, "Compute nodes hosted locally in Frankfurt, Germany"),
            ("Sovereign Cloud EU", "cloud_compute", 250.00, "Fully isolated cloud infrastructure for EU public sector"),
            ("Paris Database Master", "database", 180.00, "Managed HA PostgreSQL instances in Paris"),
            ("Dublin Cold Archive", "storage", 15.00, "Ultra-low-cost archival storage in Dublin"),
            ("EU Threat Detection System", "security", 125.00, "AI-driven real-time network threat monitoring"),
            ("GDPR Audit Logger", "analytics", 80.00, "Automated compliance log tracking and reporting")
        ]
    },
    "asia": {
        "departments_weights": [0.25, 0.20, 0.15, 0.20, 0.10, 0.10],
        "subscriptions_weights": [0.10, 0.60, 0.30], # High premium adoption
        "products": [
            ("Tokyo ML Accelerator", "ml_ai", 950.00, "Next-gen GPU cluster optimized for LLM inference"),
            ("Singapore DB Cluster", "database", 320.00, "Distributed multi-master database with sub-ms local latency"),
            ("Mumbai Edge CDN", "cloud_compute", 60.00, "Edge caching and DNS routing nodes in South Asia"),
            ("Seoul Memory Cache", "database", 85.00, "Managed in-memory Redis cluster for application caching"),
            ("Sydney Storage Engine", "storage", 50.00, "Scalable file and object storage in Oceania"),
            ("Asia Threat Shield", "security", 110.00, "DDoS protection and firewall service optimized for Asian routing"),
            ("Beijing ML Vision APIs", "ml_ai", 450.00, "Real-time computer vision and image processing endpoints")
        ]
    }
}

TICKET_SUBJECTS = {
    "billing": [
        "Incorrect invoice charge", "Update credit card details", 
        "Refund request for server downtime", "Enterprise contract renewal query", 
        "VAT tax exemption document upload", "Upgrade plan discount not applied"
    ],
    "technical": [
        "Server timeout during high load", "Database connection pool exhausted", 
        "CDN cache invalidation delayed", "GPU instance out of memory error", 
        "SSH permission denied on VM", "Object storage access key rotation failure"
    ],
    "account": [
        "Two-factor authentication reset", "Add user to organizational billing", 
        "Change account owner email", "Close account and delete personal data", 
        "SSO integration setup help", "API token authorization error"
    ],
    "feature_request": [
        "Support for ARM64 instances", "Add pgvector extension to Postgres", 
        "Auto-scaling triggers based on custom metrics", "Integration with external SIEM tool", 
        "S3-compatible bucket policy enhancements", "Custom domain support for CDN"
    ],
    "bug_report": [
        "Web console UI breaks on mobile", "Kubernetes service discovery DNS failure", 
        "Metrics export showing wrong timestamp", "Cron job replication worker stuck", 
        "CLI command returns 500 error", "Grafana dashboard panels not loading"
    ]
}

def seed_region(region):
    config = DATABASES[region]
    print(f"\nConnecting to {region.upper()} shard ({config['host']}:{config['port']})...")
    
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            database="sharddb",
            user="admin",
            password="password"
        )
    except Exception as e:
        print(f"Error connecting to {region.upper()} shard: {e}")
        print("Make sure your docker containers are running and the ports are correct.")
        return

    cursor = conn.cursor()

    # Clear existing data safely
    print(f"Truncating existing tables in {region.upper()}...")
    cursor.execute("TRUNCATE TABLE audit_logs CASCADE;")
    cursor.execute("TRUNCATE TABLE support_tickets CASCADE;")
    cursor.execute("TRUNCATE TABLE products CASCADE;")
    cursor.execute("TRUNCATE TABLE users CASCADE;")
    conn.commit()

    # Define volumes
    num_users = {"us": 500, "eu": 400, "asia": 600}[region]
    num_tickets = {"us": 200, "eu": 150, "asia": 250}[region]
    num_audit_logs = {"us": 1000, "eu": 800, "asia": 1200}[region]

    reg_config = REGIONAL_DATA[region]

    # 1. Seed Products
    print(f"Seeding products in {region.upper()}...")
    for name, category, price, desc in reg_config["products"]:
        launch_date = fake.date_between(start_date="-5y", end_date="-1m")
        status = random.choice(["active", "active", "active", "beta", "deprecated"])
        cursor.execute("""
            INSERT INTO products (name, category, price_monthly, region, status, launch_date, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, category, price, region, status, launch_date, desc))

    # 2. Seed Users
    print(f"Seeding users in {region.upper()}...")
    user_ids = []
    
    # Custom distributions
    dept_choices = DEPARTMENTS
    dept_weights = reg_config["departments_weights"]
    sub_choices = SUBSCRIPTION_TYPES
    sub_weights = reg_config["subscriptions_weights"]

    for _ in range(num_users):
        username = fake.user_name()
        email = fake.unique.email()
        sub = random.choices(sub_choices, weights=sub_weights, k=1)[0]
        dept = random.choices(dept_choices, weights=dept_weights, k=1)[0]
        status = random.choice(STATUS_OPTIONS)
        
        login_count = random.randint(0, 150)
        last_login = datetime.now() - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23)) if login_count > 0 else None
        created_at = fake.date_time_between(start_date="-1y", end_date="-1m")
        
        cursor.execute("""
            INSERT INTO users (username, email, region, subscription_type, department, status, login_count, last_login, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING user_id
        """, (username, email, region, sub, dept, status, login_count, last_login, created_at))
        
        user_ids.append(cursor.fetchone()[0])

    # 3. Seed Support Tickets
    print(f"Seeding support tickets in {region.upper()}...")
    ticket_categories = list(TICKET_SUBJECTS.keys())
    
    # EU gets more billing tickets, Asia gets more technical tickets
    if region == "eu":
        cat_weights = [0.45, 0.15, 0.15, 0.10, 0.15] # High billing
    elif region == "asia":
        cat_weights = [0.10, 0.50, 0.10, 0.10, 0.20] # High technical
    else:
        cat_weights = [0.20, 0.20, 0.20, 0.25, 0.15] # High feature requests
        
    for _ in range(num_tickets):
        user_id = random.choice(user_ids)
        category = random.choices(ticket_categories, weights=cat_weights, k=1)[0]
        subject = random.choice(TICKET_SUBJECTS[category])
        
        # Priority distribution (Asia gets more critical tickets)
        if region == "asia":
            priority = random.choices(["low", "medium", "high", "critical"], weights=[0.10, 0.30, 0.40, 0.20], k=1)[0]
        else:
            priority = random.choices(["low", "medium", "high", "critical"], weights=[0.30, 0.40, 0.25, 0.05], k=1)[0]
            
        status = random.choice(["open", "in_progress", "resolved", "closed"])
        
        created_at = fake.date_time_between(start_date="-30d", end_date="now")
        resolved_at = created_at + timedelta(days=random.randint(1, 5)) if status in ["resolved", "closed"] else None
        
        cursor.execute("""
            INSERT INTO support_tickets (user_id, subject, category, priority, status, region, created_at, resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, subject, category, priority, status, region, created_at, resolved_at))

    # 4. Seed Audit Logs
    print(f"Seeding audit logs in {region.upper()}...")
    actions = ["login", "logout", "data_export", "permission_change", "config_update"]
    
    # EU has more data_export due to GDPR compliance queries
    if region == "eu":
        action_weights = [0.30, 0.25, 0.35, 0.05, 0.05]
    else:
        action_weights = [0.50, 0.40, 0.05, 0.03, 0.02]

    for _ in range(num_audit_logs):
        user_id = random.choice(user_ids)
        action = random.choices(actions, weights=action_weights, k=1)[0]
        
        resource_map = {
            "login": "auth_service",
            "logout": "auth_service",
            "data_export": "users_database_dump",
            "permission_change": "rbac_policy_manager",
            "config_update": "cluster_config_file"
        }
        resource = resource_map[action]
        
        ip_address = f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"
        success = random.choices([True, False], weights=[0.97, 0.03], k=1)[0]
        
        created_at = fake.date_time_between(start_date="-30d", end_date="now")
        
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, resource, region, ip_address, success, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, action, resource, region, ip_address, success, created_at))

    conn.commit()
    
    # Verify counts
    cursor.execute("SELECT COUNT(*) FROM users;")
    u_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products;")
    p_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM support_tickets;")
    s_cnt = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audit_logs;")
    a_cnt = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()

    print(f"✅ Region {region.upper()} database seeded successfully:")
    print(f"  - Users: {u_cnt}")
    print(f"  - Products: {p_cnt}")
    print(f"  - Support Tickets: {s_cnt}")
    print(f"  - Audit Logs: {a_cnt}")

if __name__ == "__main__":
    print("Starting data seeding process for all shards...")
    for region in DATABASES.keys():
        seed_region(region)
    print("\nAll database shards seeded successfully with rich demo data!")
