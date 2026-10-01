"""Shared adaptations for the ported SOURCE M7 suites (REBUILD-DESIGN-v2 §5.3; S1/S2 ported suites).

- `isolated_pgstore`: the M7 tests/conftest.py fixture adapted to a DISPOSABLE PostgreSQL named by
  ZEUS_TEST_DSN (the target conftest refuses production ports, R-X); one fresh schema, dropped after.
- `NATIVE_THRESHOLDS`: stands in for research's native threshold resolution (M7
  `adapters.runtime_thresholds.effective_policy`, moving in S8) over the packaged definition, because
  context receives the definition through `context.ports.ThresholdPolicySource`.
"""

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from codex_harness.kernel.ids import digest
from codex_harness.storage.adapters.postgres_store import PostgresStore

ATTESTED = {}  # the git-attested runtime root of the ported delivery suites, built before the first ported module is imported

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


GIT_FIXED = {"GIT_AUTHOR_NAME": "Zeus Fixture", "GIT_AUTHOR_EMAIL": "fixture@zeus.invalid",
             "GIT_AUTHOR_DATE": "2026-09-22T00:00:00+00:00", "GIT_COMMITTER_NAME": "Zeus Fixture",
             "GIT_COMMITTER_EMAIL": "fixture@zeus.invalid", "GIT_COMMITTER_DATE": "2026-09-22T00:00:00+00:00"}


def pytest_collectstart(collector):
    """LABELLED: `<basetemp>/attested-runtime` is a git repository holding a COPY of the target `src/codex_harness`
    (no bytecode), committed once under a pinned identity, as `compare/drivers/common/s7_host_targets.attested_repository`
    builds its root. The ported delivery suites bind it as their runtime root (m7_delivery.loaded_runtime)."""
    if ATTESTED:
        return
    base = collector.config._tmp_path_factory.getbasetemp()
    root = base / "attested-runtime"
    shutil.copytree(Path(__file__).resolve().parents[2] / "src" / "codex_harness", root / "src" / "codex_harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    empty = base / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    environment = {**os.environ, **GIT_FIXED, "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_SYSTEM": str(empty)}
    for args in (("init", "-q", "-b", "main"), ("add", "--all"),
                 ("commit", "-q", "--no-verify", "-m", "attested runtime fixture")):
        done = subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(root), env=environment,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-500:]
    ATTESTED["root"] = str(root)
