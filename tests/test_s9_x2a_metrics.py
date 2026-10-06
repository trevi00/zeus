"""S9 X2a: the metrics projection inline in the Collector's transaction, five families and the 0.0.4 renderer (DESIGN-s9-X §2.2).

Construction is the ported `test_observations.py` pattern over the target homes: a file Observer, the SpoolDirectory,
`Collector(..., validate=validate_observation, observer=o)` and an `Interceptor` fault boundary, over a `MemoryStore`
(the PostgreSQL run is the later S9 units/.pg item). The Collector is unchanged; the store it receives is a
`ProjectingStore`.
"""
import json
import math
from contextlib import contextmanager
from pathlib import Path

from codex_harness.observation.adapters.metrics_exposition import CONTENT_TYPE, render
from codex_harness.observation.adapters.observation_schema import validate_observation
from codex_harness.observation.adapters.observation_spool import FileSpool, SpoolDirectory
from codex_harness.observation.application.metrics_projector import (
    METRICS_BUCKET,
    MetricsProjector,
    ProjectingStore,
)
from codex_harness.observation.application.observations import EVENT_BUCKET, Collector, Observer
from codex_harness.observation.domain.metric_families import DURATION_BUCKETS, FAMILIES, samples
from codex_harness.observation.domain.observation import new_process_run_id
from codex_harness.storage.adapters.memory_store import MemoryStore

CANARY = "CANARY-7e1d9c3b5a2f4e6d8c0b1a2f3e4d5c6b"
PROVIDERS = ("claude-code-cli", "codex-app-server")
FIXTURE = Path(__file__).parent / "fixtures" / "s9_x2a" / "exposition.prom"
LEASE = {"id": "task-1", "generation": 1, "attempt": 1, "agent": "worker:implementation"}
DURATION = "zeus_model_invocation_duration_seconds"


class Interceptor:
    """Store wrapper that fails selected writes; a unit fault boundary (ported pattern)."""

    def __init__(self, store):
        self.store = store
        self.fail_put = None  # predicate(bucket, body) -> bool

    @contextmanager
    def transaction(self):
        with self.store.transaction() as tx:
            yield _Intercepted(tx, self)


class _Intercepted:
    def __init__(self, tx, owner):
        self.tx, self.owner = tx, owner

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if self.owner.fail_put is not None and self.owner.fail_put(bucket, body):
            raise OSError("injected sink failure " + CANARY)
        self.tx.put(bucket, key, body)


def file_observer(root, store):
    return Observer(store, FileSpool(root, new_process_run_id(), max_bytes=1 << 20, fsync=False),
                    component="unit", directory=SpoolDirectory(root), alert_window_seconds=300)


def projecting(base):
    projector = MetricsProjector(providers=PROVIDERS)
    return projector, ProjectingStore(base, projector)


def snapshot(base):
    with base.transaction() as tx:
        return MetricsProjector(providers=PROVIDERS).snapshot(tx)


def series(rows, metric):
    [row] = [r for r in rows if r["metric"] == metric]
    return {tuple(item["labels"]): item["value"] for item in row["series"]}


def emit_workload(o, provider="claude-code-cli"):
    execution = o.for_lease(LEASE, provider=provider)
    for outcome, elapsed in (("accepted", 700.0), ("accepted", 700.0), ("provider_failure", 3.0)):
        assert o.emit("development.provider_finished", "succeeded", execution=execution,
                      attributes={"invocation_outcome": outcome, "elapsed_seconds": elapsed}) is not None
    assert o.emit("development.provider_failed", "failed", execution=execution,
                  attributes={"error_type": "OSError", "elapsed_seconds": 2.0, "provider_entered": True}) is not None
    assert o.emit("general.message_quarantined", "observed",
                  attributes={"outbox_id": "m1", "reason": "bad", "quarantine_id": "q1"}) is not None
    assert o.emit("general.message_rejected", "observed",
                  attributes={"stream_entry_id": "1-0", "error_type": "E", "dead_letter": True}) is not None


def test_known_workload_end_to_end(tmp_path):
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    emit_workload(o)
    collector = Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=o)
    assert collector.collect()["inserted"] == 6
    # Pass 1's own operations.collection_completed is spooled after its acknowledgement: pass 2 stores it.
    assert collector.collect()["inserted"] == 1
    rows = snapshot(base)
    assert [r["metric"] for r in rows] == sorted(r["metric"] for r in rows)
    assert series(rows, "zeus_metrics_projected_observations_total") == {
        ("development",): 4, ("general",): 2, ("operations",): 1}
    assert series(rows, "zeus_observation_records_total") == {
        ("inserted",): 6, ("duplicate",): 0, ("conflict",): 0, ("corrupt",): 0, ("refused",): 0}
    slow = series(rows, DURATION)[("claude-code-cli", "accepted")]
    assert slow["count"] == 2 and slow["sum"] == 1400.0
    at = dict(zip(DURATION_BUCKETS, slow["buckets"]))
    assert at[300] == 0 and at[600] == 0 and at[1200] == 2 and at[86400] == 2
    fast = series(rows, DURATION)[("claude-code-cli", "provider_failure")]
    assert fast["count"] == 1 and fast["sum"] == 3.0
    at = dict(zip(DURATION_BUCKETS, fast["buckets"]))
    assert at[1] == 0 and at[5] == 1 and at[600] == 1
    assert series(rows, "zeus_model_invocation_exceptions_total") == {("claude-code-cli", "true"): 1}
    assert series(rows, "zeus_queue_dropped_or_dead_total") == {
        ("outbox", "quarantined"): 1, ("agent_stream", "dead_letter"): 1}
    assert "zeus_metrics_label_rejections_total" not in {r["metric"] for r in rows}
    text = render(rows)
    assert 'zeus_model_invocation_duration_seconds_bucket{provider="claude-code-cli",outcome="accepted",le="600.0"} 0' in text
    assert 'zeus_model_invocation_duration_seconds_bucket{provider="claude-code-cli",outcome="accepted",le="1200.0"} 2' in text
    assert 'zeus_model_invocation_duration_seconds_sum{provider="claude-code-cli",outcome="accepted"} 1400.0' in text
    assert "text/plain" in CONTENT_TYPE


def test_replay_changes_no_count_and_the_collector_reports_duplicates(tmp_path):
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    emit_workload(o)
    directory = SpoolDirectory(tmp_path / "obs")
    collector = Collector(store, directory, validate=validate_observation)
    assert collector.collect()["inserted"] == 6
    before = snapshot(base)
    [path] = directory.spool_files()
    with path.open("rb") as stream:
        lines = stream.read().splitlines(keepends=True)
    with path.open("ab") as stream:
        for line in lines:
            stream.write(line)
    again = collector.collect()
    assert again["duplicates"] == 6 and again["inserted"] == 0
    assert snapshot(base) == before


def test_a_failed_receipt_put_rolls_the_projection_back_and_the_next_pass_counts_once(tmp_path):
    base = MemoryStore()
    _, projected = projecting(base)
    faulty = Interceptor(projected)
    o = file_observer(tmp_path / "obs", base)
    emit_workload(o)
    collector = Collector(faulty, SpoolDirectory(tmp_path / "obs"), validate=validate_observation)
    armed = {"on": True}

    def once(bucket, body):
        if bucket == "observation_collections" and armed["on"]:
            armed["on"] = False
            return True
        return False

    faulty.fail_put = once
    failed = collector.collect()
    assert failed["sink_failures"] == 1 and failed["inserted"] == 0
    assert snapshot(base) == []
    with base.transaction() as tx:
        assert tx.scan(EVENT_BUCKET) == []
    ok = collector.collect()
    assert ok["sink_failures"] == 0 and ok["inserted"] == 6
    rows = snapshot(base)
    assert series(rows, "zeus_metrics_projected_observations_total") == {("development",): 4, ("general",): 2}
    assert collector.collect()["records"] == 0
    assert snapshot(base) == rows


def collected(tmp_path, names, order):
    base = MemoryStore()
    _, store = projecting(base)
    collectors = {}
    for name in names:
        root = tmp_path / name
        emit_workload(file_observer(root, base))
        collectors[name] = Collector(store, SpoolDirectory(root), validate=validate_observation)
    for name in order:
        assert collectors[name].collect()["inserted"] == 6
    return base


def test_collection_order_does_not_change_the_counts(tmp_path):
    forward = snapshot(collected(tmp_path / "f", ("a", "b"), ("a", "b")))
    reverse = snapshot(collected(tmp_path / "r", ("a", "b"), ("b", "a")))
    assert forward == reverse
    assert series(forward, "zeus_metrics_projected_observations_total") == {("development",): 8, ("general",): 4}
    assert series(forward, DURATION)[("claude-code-cli", "accepted")]["count"] == 4


def test_pruned_source_and_a_restarted_projector_leave_the_snapshot_unchanged(tmp_path):
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    emit_workload(o)
    directory = SpoolDirectory(tmp_path / "obs")
    o.close()
    assert Collector(store, directory, validate=validate_observation).collect(prune=True)["inserted"] == 6
    directory.prune(now=10 ** 12)
    before = snapshot(base)
    _, restarted = projecting(base)
    again = Collector(restarted, directory, validate=validate_observation).collect()
    assert again["inserted"] == 0 and again["records"] == 0
    assert snapshot(base) == before


def test_a_provider_outside_the_injected_identities_is_rejected_without_leaking(tmp_path):
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    execution = o.for_lease(LEASE, provider="evil-" + CANARY)
    assert o.emit("development.provider_finished", "succeeded", execution=execution,
                  attributes={"invocation_outcome": "accepted", "elapsed_seconds": 5.0}) is not None
    assert Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation).collect()["inserted"] == 1
    rows = snapshot(base)
    assert DURATION not in {r["metric"] for r in rows}
    assert series(rows, "zeus_metrics_label_rejections_total") == {(DURATION,): 1}
    assert series(rows, "zeus_metrics_projected_observations_total") == {("development",): 1}
    assert CANARY not in render(rows) and CANARY not in json.dumps(rows)


def test_pass_through_counts_only_new_observation_rows():
    base = MemoryStore()
    projector, store = projecting(base)
    row = {"category": "general", "event_type": "general.process_idle_exit", "attributes": {}, "execution": {}}
    with base.transaction() as tx:
        tx.put(EVENT_BUCKET, "old", row)
    with store.transaction() as tx:
        tx.put("other_bucket", "k", row)
        tx.put(EVENT_BUCKET, "old", {**row, "category": "operations"})
        tx.put(EVENT_BUCKET, "new", row)
        tx.put(EVENT_BUCKET, "new", row)
        assert tx.get("other_bucket", "k") == row
    assert series(snapshot(base), "zeus_metrics_projected_observations_total") == {("general",): 1}
    try:
        with store.transaction() as tx:
            tx.put(EVENT_BUCKET, "doomed", row)
            raise RuntimeError("body failed")
    except RuntimeError:
        pass
    assert series(snapshot(base), "zeus_metrics_projected_observations_total") == {("general",): 1}
    with base.transaction() as tx:
        assert tx.get(METRICS_BUCKET, "family:zeus_metrics_projected_observations_total") is not None
        assert tx.get(EVENT_BUCKET, "doomed") is None


def fixed_rows():
    family = FAMILIES
    return [
        {"metric": "zeus_zz_gauge", "type": "gauge", "help": "A gauge that X3 will use.", "labels": ["state"],
         "buckets": [], "series": [{"labels": ["up"], "value": 1}, {"labels": ["ratio"], "value": 0.5},
                                   {"labels": ["top"], "value": math.inf}]},
        {"metric": DURATION, "type": "histogram", "help": family[DURATION].help, "labels": ["provider", "outcome"],
         "buckets": list(DURATION_BUCKETS),
         "series": [{"labels": ["claude-code-cli", "accepted"],
                     "value": {"buckets": [0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2], "sum": 1400.0, "count": 2}}]},
        {"metric": "zeus_escapes_total", "type": "counter", "help": "Back\\slash and\nnewline help.",
         "labels": ["name"], "buckets": [],
         "series": [{"labels": ['q"uote\\back\nline'], "value": 3}]},
    ]


def test_golden_exposition_and_format_properties():
    text = render(fixed_rows())
    assert text == FIXTURE.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert text.endswith("\n") and not text.endswith("\n\n")
    for name in ("zeus_zz_gauge", DURATION, "zeus_escapes_total"):
        help_at, type_at = lines.index(next(x for x in lines if x.startswith(f"# HELP {name} "))), \
            lines.index(next(x for x in lines if x.startswith(f"# TYPE {name} ")))
        first = next(i for i, x in enumerate(lines) if x.startswith(name) and not x.startswith("#"))
        assert help_at + 1 == type_at < first
    inf = next(x for x in lines if 'le="+Inf"' in x)
    count = next(x for x in lines if x.startswith(DURATION + "_count"))
    assert inf.rsplit(" ", 1)[1] == count.rsplit(" ", 1)[1] == "2"
    assert "# HELP zeus_escapes_total Back\\\\slash and\\nnewline help." in lines
    assert 'zeus_escapes_total{name="q\\"uote\\\\back\\nline"} 3' in lines
    assert 'zeus_zz_gauge{state="top"} +Inf' in lines
    for line in lines:
        if not line.startswith("#"):
            assert len(line.rsplit(" ", 1)) == 2 and line.count(" ") == 1, line  # `name{labels} value`, no timestamp
    try:
        render([{**fixed_rows()[0], "type": "summary"}])
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown type must raise")


def test_samples_is_total_over_malformed_rows():
    bad = [None, 1, "x", [], {}, {"category": 3}, {"category": "nope"},
           {"category": "development", "event_type": "development.provider_finished"},
           {"category": "development", "event_type": "development.provider_finished", "attributes": [],
            "execution": "x"},
           {"category": "development", "event_type": "development.provider_finished", "execution": {"provider": []},
            "attributes": {"invocation_outcome": {}, "elapsed_seconds": "5"}},
           {"category": "development", "event_type": "development.provider_finished",
            "execution": {"provider": "claude-code-cli"},
            "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": float("nan")}},
           {"category": "development", "event_type": "development.provider_finished",
            "execution": {"provider": "claude-code-cli"},
            "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": -1}},
           {"category": "development", "event_type": "development.provider_finished",
            "execution": {"provider": "claude-code-cli"},
            "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": True}},
           {"category": "development", "event_type": "development.provider_failed",
            "execution": {"provider": "codex-app-server"}, "attributes": {"provider_entered": "yes"}},
           {"category": "operations", "event_type": "operations.collection_completed",
            "attributes": {"records": 1, "inserted": 5, "duplicates": 0, "conflicts": 0, "corrupt": 0}},
           {"category": "operations", "event_type": "operations.collection_completed",
            "attributes": {"records": -1, "inserted": 0, "duplicates": 0, "conflicts": 0, "corrupt": 0}},
           {"category": "general", "event_type": "general.message_rejected", "attributes": {"dead_letter": "no"}},
           {"category": "general", "event_type": 7, "attributes": None}]
    for row in bad:
        made, refused = samples(row, providers=PROVIDERS)
        assert isinstance(made, list) and isinstance(refused, list)
        assert not [s for s in made if s[0] in refused]
    assert samples({"category": "operations", "event_type": "operations.collection_completed",
                    "attributes": {"records": 5, "inserted": 3, "duplicates": 1, "conflicts": 0, "corrupt": 0}},
                   providers=PROVIDERS)[0][-1] == ("zeus_observation_records_total", ("refused",), 1)


# ----- S9 round 1 F1 (FLEET-REBUILD-S9-ACCEPT): numeric totality of the duration histogram -------------------------
REJECTED = "zeus_metrics_label_rejections_total"


def emit_duration(o, elapsed, outcome="accepted"):
    execution = o.for_lease(LEASE, provider="claude-code-cli")
    assert o.emit("development.provider_finished", "succeeded", execution=execution,
                  attributes={"invocation_outcome": outcome, "elapsed_seconds": elapsed}) is not None


def all_finite(rows):
    json.dumps(rows, allow_nan=False)  # raises on a non-finite number anywhere in the snapshot
    return True


def test_an_overflowing_integer_duration_is_a_counted_rejection_and_the_batch_still_commits(tmp_path):
    """Codex S9 F1 trigger: a JSON integer 10**309 passes the schema but cannot convert to float. Before the fix,
    `samples` raised OverflowError and every pass rolled the whole sink batch back (sink_failures 1, inserted 0)."""
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    emit_duration(o, 10 ** 309)
    emit_duration(o, 5.0)
    collector = Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=o)
    first = collector.collect()
    assert first["inserted"] == 2 and not first.get("sink_failures")
    rows = snapshot(base)
    assert series(rows, DURATION) == {("claude-code-cli", "accepted"): {
        "buckets": [0, 1] + [1] * (len(DURATION_BUCKETS) - 2), "sum": 5.0, "count": 1}}
    assert series(rows, REJECTED) == {(DURATION,): 1}
    assert series(rows, "zeus_metrics_projected_observations_total") == {("development",): 2}
    collector.collect()   # pass 1's collection_completed; the two duration rows are never recounted
    rows = snapshot(base)
    assert series(rows, REJECTED) == {(DURATION,): 1}
    assert series(rows, DURATION)[("claude-code-cli", "accepted")]["count"] == 1 and all_finite(rows)


def test_finite_durations_whose_sum_would_overflow_are_rejected_without_a_partial_update(tmp_path):
    """Codex S9 F1 discriminator: two individually finite 1e308 durations made the histogram sum infinite. The second
    sample is now refused whole (no bucket, count or sum change) and counted once; the same holds across batches and for
    a restarted projector, and no non-finite number is ever stored."""
    base = MemoryStore()
    _, store = projecting(base)
    o = file_observer(tmp_path / "obs", base)
    emit_duration(o, 1e308)
    emit_duration(o, 1e308)
    collector = Collector(store, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=o)
    assert collector.collect()["inserted"] == 2
    rows = snapshot(base)
    kept = series(rows, DURATION)[("claude-code-cli", "accepted")]
    assert kept["count"] == 1 and kept["sum"] == 1e308 and kept["buckets"] == [0] * len(DURATION_BUCKETS)
    assert series(rows, REJECTED) == {(DURATION,): 1} and all_finite(rows)

    _, restarted = projecting(base)   # a new projector over the same durable aggregates
    emit_duration(o, 1e308)
    emit_duration(o, 2.0, outcome="provider_failure")
    later = Collector(restarted, SpoolDirectory(tmp_path / "obs"), validate=validate_observation, observer=o).collect()
    assert later["inserted"] == 3 and not later.get("sink_failures")   # incl. pass 1's collection_completed
    rows = snapshot(base)
    assert series(rows, DURATION)[("claude-code-cli", "accepted")] == kept
    assert series(rows, DURATION)[("claude-code-cli", "provider_failure")]["sum"] == 2.0
    assert series(rows, REJECTED) == {(DURATION,): 2} and all_finite(rows)


def test_samples_refuses_an_unconvertible_integer_duration_and_keeps_the_positive_controls():
    def row(elapsed):
        return {"category": "development", "event_type": "development.provider_finished",
                "execution": {"provider": "claude-code-cli"},
                "attributes": {"invocation_outcome": "accepted", "elapsed_seconds": elapsed}}
    for bad in (10 ** 309, float("inf"), float("nan"), -1, True):
        made, refused = samples(row(bad), providers=PROVIDERS)
        assert refused == [DURATION] and DURATION not in {s[0] for s in made}
    for good in (0, 3, 2.5, 10 ** 300):
        made, refused = samples(row(good), providers=PROVIDERS)
        assert refused == [] and (DURATION, ("claude-code-cli", "accepted"), good) in made
