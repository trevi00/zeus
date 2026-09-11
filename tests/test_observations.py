"""Observer and collector against memory and real isolated PostgreSQL (U001 L02, L06, L07, L08, L09)."""
import json
import time
from contextlib import contextmanager

import pytest
from test_workflow import assignment

from codex_harness.adapters.contracts import validate_observation
from codex_harness.adapters.observation_spool import (
    FileSpool,
    MemorySpool,
    SpoolDirectory,
    encode_record,
)
from codex_harness.adapters.store import MemoryStore, PostgresStore
from codex_harness.application.invocation_ledger import InvocationLedger
from codex_harness.application.observations import (
    Collector,
    MemoryDirectory,
    Observer,
    orphan_report,
    status_report,
)
from codex_harness.application.workflow import Workflow
from codex_harness.bootstrap import organization
from codex_harness.domain.invocation import parse_request
from codex_harness.domain.observation import new_process_run_id

CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"


class Interceptor:
    """Store wrapper that fails selected writes or whole transactions; a unit fault boundary."""

    def __init__(self, store):
        self.store = store
        self.fail_put = None       # predicate(bucket, body) -> bool
        self.fail_transaction = None  # exception instance to raise on entry
        self.fail_scan = None      # predicate(bucket) -> bool; True raises once per matching scan

    @contextmanager
    def transaction(self):
        if self.fail_transaction is not None:
            raise self.fail_transaction
        with self.store.transaction() as tx:
            yield _Interceptedtx(tx, self)


class _Interceptedtx:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if self.owner.fail_put is not None and self.owner.fail_put(bucket, body):
            raise OSError("injected sink failure " + CANARY)
        self.tx.put(bucket, key, body)

    def scan(self, bucket):
        if self.owner.fail_scan is not None and self.owner.fail_scan(bucket):
            raise OSError("transient marker read outage " + CANARY)
        return self.tx.scan(bucket)


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    return MemoryStore() if request.param == "memory" else request.getfixturevalue("isolated_pgstore")


def file_observer(tmp_path, store, **kwargs):
    root = tmp_path / "obs"
    kwargs.setdefault("alert_window_seconds", 300)
    return Observer(store, FileSpool(root, new_process_run_id(), max_bytes=1 << 20, fsync=False),
                    component="unit", directory=SpoolDirectory(root), **kwargs)


def test_audit_same_id_same_content_is_one_row_and_different_content_is_isolated(store):
    """L02 for mandatory audits."""
    o = Observer(store, MemorySpool(new_process_run_id()), component="unit", directory=MemoryDirectory())
    attributes = {"outbox_id": "m1", "attempt_id": "a1", "attempt_number": 1, "stream_entry_id": "1-0"}
    with store.transaction() as tx:
        first = o.audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", "a1"], attributes=attributes)
        again = o.audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", "a1"], attributes=attributes)
        assert again["event_id"] == first["event_id"] and o.counters["audit_redelivered"] == 1
        conflict = o.audit(tx, "general.message_published", "succeeded", identity=["outbox_attempt", "a1"],
                           attributes={**attributes, "stream_entry_id": "2-0"})
        assert conflict["status"] == "quarantined"
    with store.transaction() as tx:
        assert len(tx.scan("observation_audit")) == 1
        assert tx.get("observation_audit", first["event_id"])["attributes"]["stream_entry_id"] == "1-0"
        [quarantine] = tx.scan("observation_quarantine")
        assert quarantine["reason"] == "conflicting_content" and quarantine["event_id"] == first["event_id"]
        [alert] = tx.scan("observation_alerts")
        assert alert["event_type"] == "operations.observation_conflict"
        assert alert["attributes"]["quarantine_id"] == quarantine["id"]


def test_collector_deduplicates_redelivery_and_isolates_conflicting_redelivery(tmp_path, store):
    """L02 for spooled events: a re-collected record is one logical record; altered bytes are quarantined."""
    o = file_observer(tmp_path, store)
    event = o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 5})
    directory = SpoolDirectory(tmp_path / "obs")
    [path] = directory.spool_files()
    collector = Collector(store, directory, validate=validate_observation, observer=o)
    assert collector.collect()["inserted"] == 1
    altered = {**event, "attributes": {"idle_seconds": 6}}
    with path.open("ab") as stream:
        stream.write(encode_record("event", event))
        stream.write(encode_record("event", altered))
    result = collector.collect()
    # The one insertion is the previous pass's own collection_completed event, spooled after its ack.
    assert result["duplicates"] == 1 and result["conflicts"] == 1 and result["inserted"] == 1
    with store.transaction() as tx:
        rows = {r["event_type"] for r in tx.scan("observations")}
        assert rows == {"general.process_idle_exit", "operations.collection_completed"}
        assert tx.get("observations", event["event_id"])["attributes"]["idle_seconds"] == 5
        assert [q["reason"] for q in tx.scan("observation_quarantine")] == ["conflicting_content"]
        assert any(a["event_type"] == "operations.observation_conflict" for a in tx.scan("observation_alerts"))


def test_sink_outage_is_observed_locally_and_alerts_replay_after_recovery(tmp_path, store):
    """L06: PostgreSQL unavailable → protected local health record, pending alert, no exception, later replay."""
    intercepted = Interceptor(store)
    o = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    intercepted.fail_transaction = OSError("connection refused " + CANARY)
    record = o.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    assert record["notification"] == {"status": "pending", "channel": None}
    assert o.sink_state == "unavailable" and o.counters["alerts_pending"] >= 1
    assert o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": 1}) is not None
    directory = SpoolDirectory(tmp_path / "obs")
    [health] = directory.read_health()
    assert health["sink"] == "unavailable" and health["pending_alerts"]
    collector = Collector(intercepted, directory, validate=validate_observation, observer=o)
    failed = collector.collect()
    assert failed["sink_failures"] == 1 and failed["inserted"] == 0
    [path] = directory.spool_files()
    assert directory.acknowledged(path) == 0, "nothing acknowledged while the sink is down"
    intercepted.fail_transaction = None
    recovered = collector.collect()
    assert recovered["sink_failures"] == 0 and recovered["inserted"] >= 2
    assert o.sink_state == "available" and not o.pending_alerts
    with store.transaction() as tx:
        alerts = tx.scan("observation_alerts")
        kinds = {a["event_type"]: a["notification"]["status"] for a in alerts}
        assert kinds["operations.spool_saturated"] == "recorded_after_recovery"
        assert kinds["operations.sink_unavailable"] == "recorded_after_recovery"
    assert collector.collect()["inserted"] >= 1  # the sink_recovered event emitted after replay
    with store.transaction() as tx:
        assert any(r["event_type"] == "operations.sink_recovered" for r in tx.scan("observations"))
    leaked = CANARY in json.dumps(directory.read_health()) or CANARY in path.read_text("utf-8", "replace")
    assert not leaked


def test_spool_saturation_is_counted_and_alerted_not_silently_dropped(tmp_path, store):
    root = tmp_path / "obs"
    o = Observer(store, FileSpool(root, new_process_run_id(), max_bytes=1500, fsync=False), component="unit",
                 directory=SpoolDirectory(root), alert_window_seconds=0)
    emitted = [o.emit("general.process_idle_exit", "observed", attributes={"idle_seconds": i}) for i in range(20)]
    dropped = sum(1 for e in emitted if e is None)
    assert dropped >= 1 and o.counters["dropped_spool_full"] == dropped
    assert o.counters["alerts_recorded"] + o.counters["alerts_suppressed"] >= 1
    assert SpoolDirectory(root).read_health()[0]["counters"]["dropped_spool_full"] == dropped
    with store.transaction() as tx:
        saturated = [a for a in tx.scan("observation_alerts") if a["event_type"] == "operations.spool_saturated"]
    assert saturated and all(a["notification"]["status"] == "recorded" for a in saturated), "the stored row says recorded"


def test_alert_storms_are_rate_limited_per_kind_and_key(tmp_path, store):
    clock = {"t": 0.0}
    o = file_observer(tmp_path, store, alert_window_seconds=10)
    o.monotonic = lambda: clock["t"]
    first = o.alert("sink_unavailable", "postgres", attributes={"sink": "postgres", "error_type": "E", "pending": 0})
    assert first is not None
    assert all(o.alert("sink_unavailable", "postgres", attributes={"sink": "postgres", "error_type": "E", "pending": 0})
               is None for _ in range(5))
    assert o.counters["alerts_suppressed"] == 5
    clock["t"] = 11.0
    later = o.alert("sink_unavailable", "postgres", attributes={"sink": "postgres", "error_type": "E", "pending": 0})
    assert later is not None and later["suppressed_before"] == 5


def test_stale_observation_after_lease_expiry_is_kept_but_changes_no_task_state(tmp_path, store):
    """L07: late events from an expired lease are evidence, never authority."""
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim("worker:implementation", "old-owner", lease_seconds=1)
    ledger = InvocationLedger(store)
    reservation = ledger.reserve(lease, request=parse_request("app_server", {"model": "m", "timeout": 5}),
                                 budget_seconds=5)
    time.sleep(1.2)
    with store.transaction() as tx:
        before = [r for r in tx.records() if not r["bucket"].startswith("observation")]
    o = file_observer(tmp_path, store)
    o.emit("development.provider_finished", "succeeded",
           execution=o.for_lease(lease, provider="codex-app-server", invocation_id=reservation["id"]),
           attributes={"reservation_id": reservation["id"], "invocation_outcome": "accepted",
                       "elapsed_seconds": 1.0, "event_count": 1, "stream_hash": "sha256:0", "confirmed_model": None,
                       "usage_source": "unknown", "total_tokens": None, "thread_id": None})
    directory = SpoolDirectory(tmp_path / "obs")
    assert Collector(store, directory, validate=validate_observation).collect()["inserted"] == 1
    with store.transaction() as tx:
        after = [r for r in tx.records() if not r["bucket"].startswith("observation")]
        assert after == before
        assert tx.get("tasks", lease["id"])["status"] == "running"
        report = orphan_report(tx)
    assert [row["reason"] for row in report["orphan"]] == ["execution_lease_expired"] and not report["in_progress"]
    assert workflow.claim("worker:implementation", "new-owner") is not None  # a real successor still can


def test_orphan_report_distinguishes_live_heartbeat_from_missing_end(store):
    workflow = Workflow(store, organization())
    workflow.submit(assignment())
    lease = workflow.claim("worker:implementation", "owner", lease_seconds=600)
    ledger = InvocationLedger(store)
    ledger.reserve(lease, request=parse_request("app_server", {"model": "m", "timeout": 5}), budget_seconds=5)
    with store.transaction() as tx:
        live = orphan_report(tx)
    assert len(live["in_progress"]) == 1 and not live["orphan"]
    workflow.fail(lease, "explicit failure")
    with store.transaction() as tx:
        gone = orphan_report(tx)
    assert [row["reason"] for row in gone["orphan"]] == ["execution_retry"]


def test_restart_uses_a_new_namespace_and_status_report_is_informational(tmp_path, store):
    """L08: restart → new process_run_id; same numbers, different ids."""
    first = file_observer(tmp_path, store)
    a = first.emit("general.process_started", "started", attributes={"mode": "one"})
    first.close()
    second = file_observer(tmp_path, store)
    b = second.emit("general.process_started", "started", attributes={"mode": "one"})
    assert a["sequence"]["number"] == b["sequence"]["number"] == 1 and a["event_id"] != b["event_id"]
    directory = SpoolDirectory(tmp_path / "obs")
    collected = Collector(store, directory, validate=validate_observation).collect()
    report = status_report(store, directory, second)
    assert report["buckets"]["observations"] == 2 and report["authority"] == "informational_only"
    # The closed first run's segment was fully acknowledged and reclaimed; the live one stays.
    assert collected["reclaimed_segments"] == 1
    assert len(report["spool_files"]) == 1 and report["observer"]["process_run_id"] == second.process_run_id


def test_canary_secret_never_reaches_spool_sink_health_or_status(tmp_path, store):
    """L09: a credential-shaped canary in nested attributes, reason and errors is absent from every surface."""
    intercepted = Interceptor(store)
    o = file_observer(tmp_path, intercepted, alert_window_seconds=0)
    o.emit("general.message_rejected", "blocked", reason_code="ContractError",
           attributes={"stream_entry_id": f"1-0 password={CANARY}", "error_type": f"token: {CANARY}", "dead_letter": True})
    intercepted.fail_put = lambda bucket, body: bucket == "observation_alerts"
    o.alert("spool_append_failed", "x", attributes={"error_type": f"api_key={CANARY}", "dropped": 1})
    intercepted.fail_put = None
    with store.transaction() as tx:
        o.audit(tx, "general.message_quarantined", "blocked", identity=["q", CANARY],
                attributes={"outbox_id": "m", "reason": f"secret={CANARY}", "quarantine_id": "q"})
    directory = SpoolDirectory(tmp_path / "obs")
    Collector(intercepted, directory, validate=validate_observation, observer=o).collect()
    surfaces = [path.read_text("utf-8", "replace") for path in directory.spool_files()]
    surfaces.append(json.dumps(directory.read_health()))
    surfaces.append(json.dumps(status_report(store, directory, o), default=str))
    with store.transaction() as tx:
        surfaces.append(json.dumps([r for r in tx.records() if r["bucket"].startswith("observation")], default=str))
    leaked = any(CANARY in surface for surface in surfaces)
    assert not leaked
    assert o.counters["alerts_pending"] >= 1 and o.last_defect and "message_sha256=" in o.last_defect


def test_real_postgres_connection_refusal_is_a_sink_outage(tmp_path, isolated_pgstore):
    """L06 with an actual failed connection: the alert path meets psycopg's OperationalError, not a fake."""
    unreachable = PostgresStore("postgresql://harness:x@127.0.0.1:1/harness?connect_timeout=1")
    o = file_observer(tmp_path, unreachable, alert_window_seconds=0)
    record = o.alert("sink_unavailable", "postgres", attributes={"sink": "postgres", "error_type": "probe", "pending": 0})
    assert record["notification"]["status"] == "pending" and o.sink_state == "unavailable"
    assert len(o.pending_alerts) == 2, "the explicit alert plus the observer's own sink_unavailable alert"
    o.store = isolated_pgstore
    later = o.alert("spool_saturated", "k", attributes={"bytes": 1, "limit_bytes": 1, "dropped": 1})
    assert later["notification"]["status"] == "recorded" and not o.pending_alerts
    with isolated_pgstore.transaction() as tx:
        rows = {a["event_id"]: a["notification"]["status"] for a in tx.scan("observation_alerts")}
    assert rows[later["event_id"]] == "recorded"
    assert sorted(rows.values()) == ["recorded", "recorded_after_recovery", "recorded_after_recovery"]
