import pytest

from core.config import REGION_ID_OFFSETS, USER_ID_BLOCK_SIZE, get_settings, home_region_for_user


@pytest.mark.parametrize(
    ("user_id", "region"),
    [
        (1, "us"),
        (USER_ID_BLOCK_SIZE, "us"),
        (USER_ID_BLOCK_SIZE + 1, "eu"),
        (2 * USER_ID_BLOCK_SIZE, "eu"),
        (2 * USER_ID_BLOCK_SIZE + 1, "asia"),
        (3 * USER_ID_BLOCK_SIZE, "asia"),
    ],
)
def test_home_region_for_user(user_id, region):
    assert home_region_for_user(user_id) == region


@pytest.mark.parametrize("user_id", [0, -5, 3 * USER_ID_BLOCK_SIZE + 1])
def test_home_region_out_of_range(user_id):
    assert home_region_for_user(user_id) is None


def test_offsets_are_consistent_with_home_region():
    for region, offset in REGION_ID_OFFSETS.items():
        assert home_region_for_user(offset + 1) == region


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("SHARD_EU_HOST", "eu-postgres-service")
    monkeypatch.setenv("SHARD_EU_PORT", "5432")
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-env")
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "5")
    monkeypatch.delenv("SHARD_US_PORT", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    eu = settings.shards["eu"]
    assert (eu.host, eu.port, eu.password) == ("eu-postgres-service", 5432, "from-env")
    assert settings.shards["us"].port == 5433  # untouched default
    assert settings.breaker_failure_threshold == 5
    assert eu.connect_kwargs(connect_timeout=2)["connect_timeout"] == 2


def test_invalid_integer_env_is_reported(monkeypatch):
    monkeypatch.setenv("REDIS_PORT", "not-a-port")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="REDIS_PORT"):
        get_settings()
