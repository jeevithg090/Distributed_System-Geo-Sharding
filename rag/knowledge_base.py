"""Harvest RAG documents: table schemas, per-shard statistics and system metadata."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from core.config import REGIONS, USER_ID_BLOCK_SIZE, get_settings
from core.db import shard_cursor
from rag.vector_store import Document

logger = logging.getLogger(__name__)

TABLES = ("users", "products", "support_tickets", "audit_logs")


def _pairs(rows: Iterable[tuple[Any, ...]], fmt: str = "{0}: {1}") -> str:
    return ", ".join(fmt.format(*row) for row in rows) or "none"


class KnowledgeBase:
    def __init__(self, regions: Iterable[str] = REGIONS) -> None:
        self.regions = tuple(regions)

    def harvest_schema_documents(self) -> list[Document]:
        """Describe each table from ``information_schema`` (shards share one schema)."""
        documents: list[Document] = []
        region = self.regions[0]
        try:
            with shard_cursor(region) as cursor:
                for table in TABLES:
                    cursor.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = %s ORDER BY ordinal_position",
                        (table,),
                    )
                    columns = cursor.fetchall()
                    if not columns:
                        continue
                    text = (
                        f"Database Table Schema for table '{table}': The columns are "
                        f"{_pairs(columns, '{0} ({1})')}. This schema is identical on every "
                        f"regional shard ({', '.join(r.upper() for r in self.regions)})."
                    )
                    documents.append(Document(text, {"source": "schema", "table": table, "region": "all"}))
        except Exception as exc:
            logger.error("Error harvesting schemas from %s: %s", region.upper(), exc)
        return documents

    def _region_stats(self, region: str) -> list[Document]:
        r = region.upper()
        with shard_cursor(region) as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE region = %s", (region,))
            user_count = cur.fetchone()[0]
            cur.execute(
                "SELECT subscription_type, COUNT(*) FROM users WHERE region = %s "
                "GROUP BY subscription_type ORDER BY 1",
                (region,),
            )
            subs = _pairs(cur.fetchall())
            cur.execute(
                "SELECT department, COUNT(*) FROM users WHERE region = %s "
                "GROUP BY department ORDER BY COUNT(*) DESC, department LIMIT 3",
                (region,),
            )
            depts = _pairs(cur.fetchall(), "{0} ({1} users)")

            cur.execute("SELECT COUNT(*) FROM products")
            prod_count = cur.fetchone()[0]
            cur.execute("SELECT category, COUNT(*) FROM products GROUP BY category ORDER BY 1")
            prod_cats = _pairs(cur.fetchall())
            cur.execute("SELECT name, price_monthly FROM products ORDER BY price_monthly DESC LIMIT 3")
            top_prods = _pairs(cur.fetchall(), "{0} (${1}/mo)")

            cur.execute("SELECT COUNT(*) FROM support_tickets")
            ticket_count = cur.fetchone()[0]
            cur.execute("SELECT category, COUNT(*) FROM support_tickets GROUP BY category ORDER BY 1")
            ticket_cats = _pairs(cur.fetchall())
            cur.execute("SELECT priority, COUNT(*) FROM support_tickets GROUP BY priority ORDER BY 1")
            priorities = _pairs(cur.fetchall(), "{0} priority: {1}")
            cur.execute("SELECT status, COUNT(*) FROM support_tickets GROUP BY status ORDER BY 1")
            statuses = _pairs(cur.fetchall(), "{0} tickets: {1}")

            cur.execute("SELECT COUNT(*) FROM audit_logs")
            log_count = cur.fetchone()[0]
            cur.execute(
                "SELECT action, COUNT(*) FROM audit_logs GROUP BY action "
                "ORDER BY COUNT(*) DESC, action LIMIT 3"
            )
            actions = _pairs(cur.fetchall(), "{0} ({1} times)")
            cur.execute("SELECT success, COUNT(*) FROM audit_logs GROUP BY success ORDER BY 1")
            outcomes = (
                ", ".join(f"{'Success' if ok else 'Failure'}: {n}" for ok, n in cur.fetchall()) or "none"
            )

        return [
            Document(
                f"Region {r} Shard User Statistics: Total users = {user_count}. "
                f"Subscription tiers distribution: {subs}. Top departments: {depts}.",
                {"source": "stats", "type": "users", "region": region},
            ),
            Document(
                f"Region {r} Shard Product Catalog: Total cloud products = {prod_count}. "
                f"Categories count: {prod_cats}. Highest priced products in this region: {top_prods}.",
                {"source": "stats", "type": "products", "region": region},
            ),
            Document(
                f"Region {r} Support Ticket Analytics: Total support tickets = {ticket_count}. "
                f"Category breakdowns: {ticket_cats}. Priority distributions: {priorities}. "
                f"Status overview: {statuses}.",
                {"source": "stats", "type": "tickets", "region": region},
            ),
            Document(
                f"Region {r} Security Audit Log Statistics: Total audit log events = {log_count}. "
                f"Top actions recorded: {actions}. Status of actions: {outcomes}.",
                {"source": "stats", "type": "audit_logs", "region": region},
            ),
        ]

    def harvest_stats_documents(self) -> list[Document]:
        documents: list[Document] = []
        for region in self.regions:
            try:
                documents.extend(self._region_stats(region))
            except Exception as exc:
                logger.error("Error harvesting stats for %s: %s", region.upper(), exc)
        return documents

    def harvest_metadata_documents(self) -> list[Document]:
        """Static documents describing how the system itself behaves."""
        settings = get_settings()
        block = f"{USER_ID_BLOCK_SIZE:,}"
        texts = {
            "sharding": (
                "System Sharding Metadata: GeoShardDB partitions users geographically into three "
                "PostgreSQL shards: US, EU and ASIA. Each user lives on the shard of their home region. "
                f"Every region owns a disjoint block of {block} user IDs (US starts at 1, EU at "
                f"{USER_ID_BLOCK_SIZE + 1:,}, ASIA at {2 * USER_ID_BLOCK_SIZE + 1:,}), so the home shard "
                "can be derived from a user ID and replicas keep the same ID on every shard."
            ),
            "replication": (
                "System Replication Metadata: GeoShardDB uses asynchronous, eventually consistent "
                "replication. A background replication worker polls each shard every 10 seconds for "
                "users with replicated = FALSE and copies them, with their global user_id, to the other "
                "two shards using ON CONFLICT DO NOTHING. Rows are marked replicated only after every "
                "target shard accepted them. Replication is multi-directional between US, EU and ASIA."
            ),
            "routing": (
                "System Routing and Failover Metadata: Requests are routed to the user's home region. "
                "Each region has a circuit breaker. After "
                f"{settings.breaker_failure_threshold} consecutive failures the breaker opens for "
                f"{int(settings.breaker_recovery_timeout)} seconds and reads fail over to a healthy "
                "region's replica; then a half-open trial request decides whether it closes again."
            ),
            "cache": (
                "System Caching Layer Metadata: A Redis cache sits in front of the PostgreSQL shards "
                "using the cache-aside pattern. User reads check Redis first; on a miss the shard is "
                f"queried and the result stored in Redis with a {settings.cache_ttl_seconds}-second TTL. "
                "Cache keys use the format '{region}:user:{user_id}'."
            ),
        }
        return [
            Document(text, {"source": "system", "type": kind, "region": "all"})
            for kind, text in texts.items()
        ]

    def harvest_all(self) -> list[Document]:
        return (
            self.harvest_schema_documents()
            + self.harvest_stats_documents()
            + self.harvest_metadata_documents()
        )
