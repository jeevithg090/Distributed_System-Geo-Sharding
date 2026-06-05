# rag/knowledge_base.py
# Schema, statistics, and metadata document harvester for RAG

import psycopg2
import os

class Document:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata # e.g. {"source": "schema", "region": "us", "table": "users"}

    def __repr__(self):
        return f"Document(text={self.text[:50]}..., metadata={self.metadata})"

class KnowledgeBase:
    def __init__(self, db_configs):
        self.db_configs = db_configs # Map of region -> {"host": host, "port": port}

    def _get_connection(self, region):
        config = self.db_configs[region]
        return psycopg2.connect(
            host=config["host"],
            port=config["port"],
            database="sharddb",
            user="admin",
            password="password"
        )

    def harvest_schema_documents(self):
        """Extracts table schemas from PostgreSQL information_schema"""
        documents = []
        tables_to_query = ["users", "products", "support_tickets", "audit_logs"]
        
        # We only need to harvest schema from one database because they are identical shards,
        # but we can label it as the master schema description.
        region = list(self.db_configs.keys())[0]
        try:
            conn = self._get_connection(region)
            cursor = conn.cursor()
            
            for table in tables_to_query:
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = %s
                    ORDER BY ordinal_position;
                """, (table,))
                columns = cursor.fetchall()
                
                if columns:
                    col_desc = ", ".join([f"{c[0]} ({c[1]})" for c in columns])
                    text = f"Database Table Schema for table '{table}': The columns are {col_desc}. This schema is synchronized across all regional database shards (US, EU, ASIA)."
                    documents.append(Document(
                        text=text,
                        metadata={
                            "source": "schema",
                            "table": table,
                            "region": "all"
                        }
                    ))
                    
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error harvesting schemas: {e}")
            
        return documents

    def harvest_stats_documents(self):
        """Queries shards to get data aggregates and distributions"""
        documents = []
        
        for region in self.db_configs.keys():
            try:
                conn = self._get_connection(region)
                cursor = conn.cursor()
                
                # 1. User Counts & Subscription distribution
                cursor.execute("""
                    SELECT subscription_type, COUNT(*) 
                    FROM users 
                    GROUP BY subscription_type;
                """)
                subs = cursor.fetchall()
                sub_str = ", ".join([f"{row[0]}: {row[1]}" for row in subs])
                
                cursor.execute("SELECT COUNT(*) FROM users;")
                user_count = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT department, COUNT(*) 
                    FROM users 
                    GROUP BY department 
                    ORDER BY COUNT(*) DESC LIMIT 3;
                """)
                depts = cursor.fetchall()
                dept_str = ", ".join([f"{row[0]} ({row[1]} users)" for row in depts])
                
                text_users = (f"Region {region.upper()} Shard User Statistics: "
                              f"Total users = {user_count}. "
                              f"Subscription tiers distribution: {sub_str}. "
                              f"Top departments: {dept_str}.")
                documents.append(Document(
                    text=text_users,
                    metadata={"source": "stats", "type": "users", "region": region}
                ))
                
                # 2. Product stats
                cursor.execute("SELECT COUNT(*) FROM products;")
                prod_count = cursor.fetchone()[0]
                cursor.execute("SELECT category, COUNT(*) FROM products GROUP BY category;")
                categories = cursor.fetchall()
                cat_str = ", ".join([f"{row[0]}: {row[1]}" for row in categories])
                
                cursor.execute("SELECT name, price_monthly FROM products ORDER BY price_monthly DESC LIMIT 3;")
                exp_prods = cursor.fetchall()
                exp_str = ", ".join([f"{row[0]} (${row[1]}/mo)" for row in exp_prods])
                
                text_prods = (f"Region {region.upper()} Shard Product Catalog: "
                              f"Total cloud products = {prod_count}. "
                              f"Categories count: {cat_str}. "
                              f"Highest priced products in this region: {exp_str}.")
                documents.append(Document(
                    text=text_prods,
                    metadata={"source": "stats", "type": "products", "region": region}
                ))
                
                # 3. Support Tickets stats
                cursor.execute("SELECT COUNT(*) FROM support_tickets;")
                t_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT priority, COUNT(*) FROM support_tickets GROUP BY priority;")
                priorities = cursor.fetchall()
                prio_str = ", ".join([f"{row[0]} priority: {row[1]}" for row in priorities])
                
                cursor.execute("SELECT category, COUNT(*) FROM support_tickets GROUP BY category;")
                t_cats = cursor.fetchall()
                t_cat_str = ", ".join([f"{row[0]}: {row[1]}" for row in t_cats])
                
                cursor.execute("SELECT status, COUNT(*) FROM support_tickets GROUP BY status;")
                statuses = cursor.fetchall()
                stat_str = ", ".join([f"{row[0]} tickets: {row[1]}" for row in statuses])
                
                text_tickets = (f"Region {region.upper()} Support Ticket Analytics: "
                                f"Total support tickets = {t_count}. "
                                f"Category breakdowns: {t_cat_str}. "
                                f"Priority distributions: {prio_str}. "
                                f"Status overview: {stat_str}.")
                documents.append(Document(
                    text=text_tickets,
                    metadata={"source": "stats", "type": "tickets", "region": region}
                ))
                
                # 4. Audit Log analytics
                cursor.execute("SELECT COUNT(*) FROM audit_logs;")
                l_count = cursor.fetchone()[0]
                cursor.execute("SELECT action, COUNT(*) FROM audit_logs GROUP BY action ORDER BY COUNT(*) DESC LIMIT 3;")
                acts = cursor.fetchall()
                act_str = ", ".join([f"{row[0]} ({row[1]} times)" for row in acts])
                
                cursor.execute("SELECT success, COUNT(*) FROM audit_logs GROUP BY success;")
                succs = cursor.fetchall()
                succ_str = ", ".join([f"{'Success' if row[0] else 'Failure'}: {row[1]}" for row in succs])
                
                text_logs = (f"Region {region.upper()} Security Audit Log Statistics: "
                             f"Total audit log events = {l_count}. "
                             f"Top actions recorded: {act_str}. "
                             f"Status of actions: {succ_str}.")
                documents.append(Document(
                    text=text_logs,
                    metadata={"source": "stats", "type": "audit_logs", "region": region}
                ))
                
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Error harvesting stats for region {region}: {e}")
                
        return documents

    def harvest_metadata_documents(self):
        """Compiles system configuration and replication rules metadata"""
        documents = []
        
        # System replication details
        replication_text = (
            "System Replication Metadata: GeoShardDB uses asynchronous eventually consistent replication. "
            "A background replication worker running on a 10-second loop polls database shards for users "
            "with replicated=FALSE, and copies them to the other two shards using ON CONFLICT (email) DO NOTHING. "
            "Replication is multi-directional: US replicates to EU and ASIA, EU replicates to US and ASIA, and ASIA replicates to US and EU."
        )
        documents.append(Document(
            text=replication_text,
            metadata={"source": "system", "type": "replication", "region": "all"}
        ))
        
        # System routing & network latency rules
        routing_text = (
            "System Routing and Latency Metadata: Incoming client user requests are routed by preferred region. "
            "There is a circuit breaker mechanism monitoring failures for each region (US, EU, ASIA). "
            "If failures exceed 3, the circuit breaker opens for 15 seconds, and requests failover to "
            "an alternative available shard. Simulated latencies are: US-EU (80ms), EU-ASIA (120ms), and US-ASIA (160ms)."
        )
        documents.append(Document(
            text=routing_text,
            metadata={"source": "system", "type": "routing", "region": "all"}
        ))
        
        # Caching config
        cache_text = (
            "System Caching Layer Metadata: A distributed Redis cache sits in front of the PostgreSQL shards. "
            "The cache utilizes a Cache-Aside pattern where user reads hit Redis first. "
            "On cache misses, the PostgreSQL shard is queried, and the result is stored in Redis with a 300-second TTL. "
            "Cache keys are stored in the format '{region}:user:{user_id}'."
        )
        documents.append(Document(
            text=cache_text,
            metadata={"source": "system", "type": "cache", "region": "all"}
        ))
        
        return documents

    def harvest_all(self):
        """Harvests all document sources"""
        docs = []
        docs.extend(self.harvest_schema_documents())
        docs.extend(self.harvest_stats_documents())
        docs.extend(self.harvest_metadata_documents())
        return docs
