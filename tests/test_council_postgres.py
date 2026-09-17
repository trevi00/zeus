"""INV-COUNCIL-001 read-only snapshot on an isolated PostgreSQL schema: real records including a
missing one, one fixed transaction snapshot, read-only failure on writes, source rows unchanged and
selection bounds. Skipped unless HARNESS_INTEGRATION=1; the owner runs it, not the worker."""
import pytest
from psycopg import errors

from codex_harness.adapters.council_snapshot import ReadOnlySnapshot, SnapshotUnavailable
from codex_harness.domain.council import check_snapshot, snapshot_digest
from codex_harness.domain.model import digest

BASE = "a" * 40
SECRET = "SECRET-row-text-never-emitted"
SELECTION = [{"bucket": "tasks", "id": "t-1"}, {"bucket": "operations", "id": "op-absent"}, {"bucket": "autonomous_runs", "id": "run-1"}]
ROWS = {("tasks", "t-1"): {"id": "t-1", "status": "succeeded", "agent": "worker:implementation", "error": SECRET},
        ("autonomous_runs", "run-1"): {"id": "run-1", "status": "running", "stage": "research"}}


def test_postgres_snapshot_is_one_read_only_repeatable_read_observation(isolated_pgstore):
    with isolated_pgstore.transaction() as tx:
        for (bucket, key), body in ROWS.items():
            tx.put(bucket, key, body)
    port = ReadOnlySnapshot(isolated_pgstore.dsn, clock=lambda: "2029-01-01T00:00:00+00:00")
    envelope = port.observe(SELECTION, topic="pg", run_id="council-pg", base_revision=BASE, max_age_seconds=120)
    assert [r["state"] for r in envelope["records"]] == ["found", "missing", "found"]
    assert envelope["records"][0]["sha256"] == digest(ROWS[("tasks", "t-1")]) and envelope["records"][0]["fields"]["status"] == "succeeded"
    assert envelope["records"][1]["sha256"] is None and SECRET not in str(envelope) and isolated_pgstore.dsn not in str(envelope)
    frozen = snapshot_digest(envelope)
    again = port.observe(SELECTION, topic="pg", run_id="council-pg", base_revision=BASE, max_age_seconds=120)
    assert snapshot_digest(again) == frozen, "same records, same clock: content-addressed"
    with port._session() as conn:
        first = conn.execute("SELECT body FROM documents WHERE bucket='tasks' AND id='t-1'").fetchone()[0]
        with isolated_pgstore.transaction() as tx:  # a concurrent writer commits between two reads
            tx.put("tasks", "t-1", {**ROWS[("tasks", "t-1")], "status": "retry"})
        second = conn.execute("SELECT body FROM documents WHERE bucket='tasks' AND id='t-1'").fetchone()[0]
        assert first == second == ROWS[("tasks", "t-1")], "repeatable read: one snapshot for the whole transaction"
        with pytest.raises(errors.ReadOnlySqlTransaction):
            conn.execute("INSERT INTO documents(bucket,id,body) VALUES ('tasks','t-9','{}')")
    changed = port.observe(SELECTION, topic="pg", run_id="council-pg", base_revision=BASE, max_age_seconds=120)
    assert changed["records"][0]["fields"]["status"] == "retry" and snapshot_digest(changed) != frozen
    with pytest.raises(check_snapshot.__globals__["SnapshotError"], match="snapshot_mismatch"):
        check_snapshot(changed, expected_digest=frozen, topic="pg", run_id="council-pg", base_revision=BASE, selection=SELECTION, now=None)
    with isolated_pgstore.transaction() as tx:
        assert tx.get("tasks", "t-9") is None and tx.get("tasks", "t-1")["status"] == "retry" and tx.get("operations", "op-absent") is None
    with pytest.raises(SnapshotUnavailable) as info:
        ReadOnlySnapshot("postgresql://nobody:" + SECRET + "@127.0.0.1:1/none", connect_timeout=1).observe(
            SELECTION, topic="pg", run_id="council-pg", base_revision=BASE, max_age_seconds=120)
    assert info.value.reason_code == "snapshot_unavailable" and SECRET not in str(info.value)
    with pytest.raises(Exception):
        port.observe([{"bucket": "tasks", "id": "t" + str(i)} for i in range(21)], topic="pg", run_id="council-pg", base_revision=BASE, max_age_seconds=120)
