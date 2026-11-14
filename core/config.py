"""Centralised, environment-driven configuration for GeoShardDB.

Every host, port and credential is read from environment variables (optionally
loaded from a local ``.env`` file). Defaults target a developer machine running
the Docker Compose stack, where shards are published on ``localhost:5433-5435``.
Inside Compose/Kubernetes the same variables point at service names instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover - dependency is listed in requirements
    pass

REGIONS: tuple[str, ...] = ("us", "eu", "asia")

# Each region owns a disjoint block of user IDs, so the shard that "owns" a
# user can be derived from the ID alone and replicated rows keep their
# identity on every shard (which makes cross-region failover reads correct).
USER_ID_BLOCK_SIZE = 1_000_000
REGION_ID_OFFSETS: dict[str, int] = {
    region: index * USER_ID_BLOCK_SIZE for index, region in enumerate(REGIONS)
}

_DEFAULT_HOST_PORTS: dict[str, int] = {"us": 5433, "eu": 5434, "asia": 5435}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class ShardConfig:
    region: str
    host: str
    port: int
    database: str
    user: str
    password: str

    def connect_kwargs(self, connect_timeout: int | None = None) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }
        if connect_timeout is not None:
            kwargs["connect_timeout"] = connect_timeout
        return kwargs


@dataclass(frozen=True)
class Settings:
    shards: dict[str, ShardConfig]
    redis_host: str
    redis_port: int
    redis_password: str | None
    db_connect_timeout: int
    breaker_failure_threshold: int
    breaker_recovery_timeout: float
    cache_ttl_seconds: int
    rag_index_path: str
    rag_embedding_backend: str
    rag_embedding_model: str


def _shard_from_env(region: str) -> ShardConfig:
    prefix = f"SHARD_{region.upper()}"
    return ShardConfig(
        region=region,
        host=os.environ.get(f"{prefix}_HOST", "localhost"),
        port=_env_int(f"{prefix}_PORT", _DEFAULT_HOST_PORTS[region]),
        database=os.environ.get("POSTGRES_DB", "sharddb"),
        user=os.environ.get("POSTGRES_USER", "admin"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings (cached; call ``get_settings.cache_clear()`` in tests)."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_index = os.path.join(project_root, "data", "rag_index.json")
    return Settings(
        shards={region: _shard_from_env(region) for region in REGIONS},
        redis_host=os.environ.get("REDIS_HOST", "localhost"),
        redis_port=_env_int("REDIS_PORT", 6379),
        redis_password=os.environ.get("REDIS_PASSWORD") or None,
        db_connect_timeout=_env_int("DB_CONNECT_TIMEOUT", 3),
        breaker_failure_threshold=_env_int("BREAKER_FAILURE_THRESHOLD", 3),
        breaker_recovery_timeout=float(_env_int("BREAKER_RECOVERY_TIMEOUT", 15)),
        cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 300),
        rag_index_path=os.environ.get("RAG_INDEX_PATH", default_index),
        rag_embedding_backend=os.environ.get("RAG_EMBEDDING_BACKEND", "auto").lower(),
        rag_embedding_model=os.environ.get("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    )


def is_valid_region(region: str) -> bool:
    return region in REGIONS


def home_region_for_user(user_id: int) -> str | None:
    """Map a global user ID to the region whose ID block contains it."""
    if user_id < 1:
        return None
    index = (user_id - 1) // USER_ID_BLOCK_SIZE
    if index >= len(REGIONS):
        return None
    return REGIONS[index]


def shard_label(region: str) -> str:
    """Human-readable ``REGION (host:port)`` for log and CLI output."""
    shard = get_settings().shards[region]
    return f"{region.upper()} shard ({shard.host}:{shard.port})"
