"""Integration-test fixtures: postgres+timescale+age container, redis container."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    """
 Plan 02 will swap this image for the locally-built intellibird-db
 image (Postgres 16 + TimescaleDB + AGE). Until then use the base
 timescaledb-ha image so extension tests can load timescaledb only.
"""
    with PostgresContainer("timescale/timescaledb:latest-pg16") as pg:
        yield pg


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


# fixtures directory accessor used by RSS/TAXII/NVD integration tests.
from pathlib import Path

import pytest as _pytest2


@_pytest2.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to backend/tests/fixtures/."""
    return Path(__file__).resolve().parent.parent / "fixtures"
