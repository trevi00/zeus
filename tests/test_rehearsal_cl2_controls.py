"""Cutover RH-2c: the CL2 disposable-copy controls (moved out of the owner-run Phase P runner, D-RH2-RUNNER-GUARD).

Layer: harness tooling tests (never shipped). Real Docker under the pytest provider guard: only the forms the guard admits
(a labelled, network-less fixture copy via `copies.Copies`; no `docker diff`, restart or volume). Expected results come from
the design's CL2 list (`cl2.py`): a clean disposable copy passes the nonce check and all six checks; a copy with a planted
`rh-<run8>` row fails exactly `nonce_rows`. The other five readers are injected equal-to-P0 stubs: they are covered by
tests/test_rehearsal_cl2.py, and only the nonce count reads the real copy here.
Requires ZEUS_TEST_DOCKER=1 (the acceptance run sets it and a skip there is a failure).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import cl2  # noqa: E402
from rehearsal import copies as cp  # noqa: E402
from rehearsal.sweep import sweep  # noqa: E402

guard = cp.provider_guard
needs_docker = pytest.mark.skipif(os.environ.get(guard.DOCKER_OPT_IN_ENV) != "1", reason="needs ZEUS_TEST_DOCKER=1 (real Docker)")
RUN8 = "7c3d9e1f"
FACTS = {"Id": "i1", "StartedAt": "t1", "RestartCount": 0, "diff_sha256": "d1"}
P0 = {"paused": True, "containers": {"pg": dict(FACTS), "redis": dict(FACTS)}}
MANIFEST = {"./appendonlydir/a.manifest": (5, 100, "aa")}


@pytest.fixture(scope="module")
def copy_d(tmp_path_factory):
    import psycopg

    root = tmp_path_factory.mktemp("cl2") / "r"
    copies = cp.Copies(RUN8, root)
    try:
        copy = copies.start("D")
        with psycopg.connect(cp.pg_dsn(copy.pg_socket), autocommit=True) as conn:
            conn.execute("CREATE DATABASE zeus_aibox")
        with psycopg.connect(cp.pg_dsn(copy.pg_socket, "zeus_aibox"), autocommit=True) as conn:
            conn.execute("CREATE TABLE rh_ctl(x text); INSERT INTO rh_ctl VALUES ('seed')")
        yield copy
    finally:
        sweep(RUN8, root)


def post(copy):
    import psycopg

    def count():
        with psycopg.connect(cp.pg_dsn(copy.pg_socket, "zeus_aibox")) as conn:
            return cl2.count_nonce(conn, RUN8)

    return cl2.post(RUN8, p0=P0, p0_redis=MANIFEST, gate_now=lambda: P0, redis_now=lambda: MANIFEST, nonce_count=count,
                    sweep_now=lambda: {"removed": 0, "residue": []},
                    runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""))


@needs_docker
def test_a_clean_disposable_copy_passes_cl2_then_a_planted_nonce_fails_exactly_nonce_rows(copy_d):
    import psycopg

    clean = post(copy_d)
    assert clean["ok"] and clean["failed"] == [] and clean["checks"]["nonce_rows"] == {"count": 0, "ok": True}
    with psycopg.connect(cp.pg_dsn(copy_d.pg_socket, "zeus_aibox"), autocommit=True) as conn:
        conn.execute(f"INSERT INTO rh_ctl VALUES ('{cl2.nonce(RUN8)}-planted')")
    planted = post(copy_d)
    assert not planted["ok"] and planted["failed"] == ["nonce_rows"] and planted["checks"]["nonce_rows"]["count"] == 1
