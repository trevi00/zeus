"""Shared adaptations for the ported SOURCE M7 suites (REBUILD-DESIGN-v2 §5.3; S1/S2 ported suites).

- `isolated_pgstore`: the M7 tests/conftest.py fixture adapted to a DISPOSABLE PostgreSQL named by
  ZEUS_TEST_DSN (the target conftest refuses production ports, R-X); one fresh schema, dropped after.
- `NATIVE_THRESHOLDS`: stands in for research's native threshold resolution (M7
  `adapters.runtime_thresholds.effective_policy`, moving in S8) over the packaged definition, because
  context receives the definition through `context.ports.ThresholdPolicySource`.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.postgres_store import PostgresStore

RESOURCES = Path(__file__).resolve().parents[2] / "src" / "codex_harness" / "resources"


class NativeThresholds:
    def effective_policy(self):
        text = (RESOURCES / "threshold-policy.json").read_text(encoding="utf-8")
        policy = json.loads(text)
        values = {"skill_match.FULL_BODY_MIN_SCORE": 3, **policy["overrides"]}
        return {"values": values, "definition_hash": digest(text), "definition": policy}


NATIVE_THRESHOLDS = NativeThresholds()


@pytest.fixture
def isolated_pgstore():
    dsn = os.environ.get("ZEUS_TEST_DSN")
    if os.environ.get("HARNESS_INTEGRATION") != "1" or not dsn:
        pytest.skip("Integration environment required (HARNESS_INTEGRATION=1 and a disposable ZEUS_TEST_DSN)")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    schema = "test_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        store = PostgresStore(make_conninfo(dsn, options=f"-c search_path={schema},public"))
        store.migrate()
        yield store
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
