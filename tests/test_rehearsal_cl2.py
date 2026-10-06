"""Cutover RH-2b: CL2 post-checks (`compare/rehearsal/cl2.py`; design "10. CL2", AC11), driven through injected readers.

Layer: harness tooling tests (never shipped). Expected results come from the design's CL2 list: a nonce row, a Redis
manifest difference, a container change, an unpaused Fleet, sweep residue or a leftover rehearsal unit each FAILS
exactly that check; a clean state passes all six. No docker, no production resource.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused, cl2  # noqa: E402

RUN8 = "9a8b7c6d"
FACTS = {"Id": "i1", "StartedAt": "t1", "RestartCount": 0, "diff_sha256": "d1"}
P0 = {"paused": True, "containers": {"pg": dict(FACTS), "redis": dict(FACTS)}}
MANIFEST = {"./appendonlydir/a.manifest": (5, 100, "aa")}
CHECKS = ["nonce_rows", "redis_manifest_equal_p0", "containers_unchanged", "fleet_paused", "no_residue", "no_rehearsal_units"]


def run_post(*, count=0, redis=MANIFEST, now=None, residue=(), units="", unit_exit=0):
    seen = []

    def runner(argv):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, unit_exit, units, "")

    result = cl2.post(RUN8, p0=P0, p0_redis=MANIFEST, gate_now=lambda: now or P0, redis_now=lambda: redis,
                      nonce_count=lambda: count, sweep_now=lambda: {"removed": 2, "residue": list(residue)}, runner=runner)
    return result, seen


def test_a_clean_state_passes_all_six_checks_and_lists_units_through_the_injected_runner():
    result, seen = run_post()
    assert result["ok"] and result["failed"] == [] and list(result["checks"]) == CHECKS
    assert seen == [["systemctl", "list-units", "zeus-rehearsal-*", "--all", "--no-legend", "--plain"]]


def test_a_planted_nonce_row_fails_only_the_nonce_check():
    result, _ = run_post(count=1)
    assert not result["ok"] and result["failed"] == ["nonce_rows"] and result["checks"]["nonce_rows"]["count"] == 1


@pytest.mark.parametrize("mutate,failed", [
    (dict(redis={"./appendonlydir/a.manifest": (6, 100, "aa")}), "redis_manifest_equal_p0"),
    (dict(now={"paused": True, "containers": {"pg": {**FACTS, "StartedAt": "t2"}, "redis": dict(FACTS)}}), "containers_unchanged"),
    (dict(now={"paused": True, "containers": {"pg": dict(FACTS), "redis": {**FACTS, "diff_sha256": "d2"}}}), "containers_unchanged"),
    (dict(now={"paused": True, "containers": {"pg": {**FACTS, "RestartCount": 1}, "redis": dict(FACTS)}}), "containers_unchanged"),
    (dict(now={"paused": True, "containers": {"pg": dict(FACTS)}}), "containers_unchanged"),
    (dict(now={"paused": False, "containers": P0["containers"]}), "fleet_paused"),
    (dict(residue=["abc"]), "no_residue"),
    (dict(units="zeus-rehearsal-x.service loaded active running\n"), "no_rehearsal_units"),
    (dict(unit_exit=1), "no_rehearsal_units"),
])
def test_each_post_check_fails_by_itself(mutate, failed):
    result, _ = run_post(**mutate)
    assert not result["ok"] and result["failed"] == [failed]


class FakeConn:
    def __init__(self, tables, counts):
        self.tables, self.counts, self.queries = tables, counts, []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        rows = self.tables if "pg_tables" in sql else [(self.counts[sql.split(" AS t")[0].split("FROM ")[1]],)]
        return type("Cur", (), {"fetchall": lambda s: rows, "fetchone": lambda s: rows[0]})()


def test_count_nonce_sums_matching_rows_over_every_user_table_and_quotes_identifiers():
    conn = FakeConn([("public", "a"), ("app", 'we"ird')], {'"public"."a"': 0, '"app"."we""ird"': 2})
    assert cl2.count_nonce(conn, RUN8) == 2
    assert [p for sql, p in conn.queries if p] == [(f"rh-{RUN8}",)] * 2
    assert "NOT IN ('pg_catalog', 'information_schema')" in conn.queries[0][0]


def test_a_bad_run8_is_refused():
    with pytest.raises(Refused):
        cl2.nonce("XYZ")
