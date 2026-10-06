"""Integration fixtures never require a pre-populated production schema."""
import os
from contextlib import nullcontext
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from codex_harness.adapters.store import PostgresStore
from codex_harness.bootstrap import database_url


@pytest.fixture
def fake_verification_services(monkeypatch):
    """Unit release orchestration must not launch real infrastructure."""
    monkeypatch.setattr("codex_harness.adapters.deployment.VerificationServices",
        lambda *args: nullcontext({"database_url": "postgresql://fixture/isolated",
                                   "redis_url": "redis://fixture/0"}))


@pytest.fixture
def isolated_pgstore():
    if os.environ.get("HARNESS_INTEGRATION") != "1":
        pytest.skip("Integration environment required")
    dsn = database_url()
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
        store.migrate()
        yield store
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
