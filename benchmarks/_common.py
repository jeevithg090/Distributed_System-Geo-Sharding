"""Shared helpers for benchmark scripts."""

from __future__ import annotations

import random

from core.config import REGION_ID_OFFSETS

POINT_QUERY = "SELECT * FROM users WHERE user_id = %s"


def random_user_id(region: str, rng: random.Random, max_local_id: int = 400) -> int:
    """A user ID inside ``region``'s block that the default seed data populates."""
    return REGION_ID_OFFSETS[region] + rng.randint(1, max_local_id)
