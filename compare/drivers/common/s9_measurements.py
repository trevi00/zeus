"""Shared S9 scenario steps (`observation.measurements`): M7 `domain/measurements.py` and `application/measurements.py` (INV-METRIC-001).

Layer: harness (never shipped)

`api.dm` is the side's measurements domain module (`Definition`, `DEFINITIONS`, `TERMINAL`, `Evaluation`, `evaluate`, `timestamp`,
`definition_documents`), `api.Measurements` its use case, `api.MemoryStore` and `api.FileArtifacts` the side's store and artifact adapters (unchanged
by S9). Mirrors `tests/test_measurements.py`: `evaluate` over every population shape (a ratio only from valid evidence, `unknown` and no value for
every missing/stale/future/invalid case, the window bounds, the minimum-sample and capacity thresholds), then `Measurements.collect` over a MemoryStore
and a FileArtifacts under a per-case temporary directory with a fixed `now`: one artifact (body and receipt), one `metric_observations` row per
definition, the byte-equal reproduction, and the refusal of an empty revision. The receipt's wall-clock `at` is never reported (only the file names
and the evidence document); the temporary directory never appears in a result.
"""

from __future__ import annotations

import dataclasses
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)
REVISION = "a" * 40


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def task(key="one", status="succeeded", attempt=1, outcome="succeeded"):
    return {"id": key, "status": status, "attempt": attempt, "created_at": (NOW - timedelta(hours=1)).isoformat(),
            "attempt_outcomes": [{"attempt": 1, "status": outcome, "at": (NOW - timedelta(minutes=1)).isoformat()}]}


def evidence(*rows):
    return {"tasks": list(rows), "decisions": [], "observed_at": NOW.isoformat()}


def ev(api, definition, data, now=NOW):
    return call(lambda: dataclasses.asdict(api.dm.evaluate(definition, data, now)))


def evaluations(api) -> dict:
    d0, d1, d2 = api.dm.DEFINITIONS
    out = {}
    data = evidence(task(), task("retry", attempt=2, outcome="failed"), task("cancel", "cancelled", 0), task("expired", "expired", 0))
    data["tasks"][2]["attempt_outcomes"] = []
    data["tasks"][3]["attempt_outcomes"] = []
    out["retries_do_not_improve_first_attempt"] = [ev(api, d, data) for d in (d0, d1)]
    out["freshness"] = {}
    for offset in (121, 120, 0, -1):
        fresh = evidence(task())
        fresh["observed_at"] = (NOW - timedelta(seconds=offset)).isoformat()
        out["freshness"][str(offset)] = [ev(api, d, fresh) for d in api.dm.DEFINITIONS]
    out["evidence_shapes"] = {name: ev(api, d0, data) for name, data in (
        ("none", None), ("empty", {}), ("no_rows", evidence()), ("two_same_id", evidence(task(), task())),
        ("tasks_not_list", {"tasks": {}, "decisions": [], "observed_at": NOW.isoformat()}),
        ("empty_id", evidence({**task(), "id": ""})), ("int_id", evidence({**task(), "id": 5})),
        ("naive_observed", {**evidence(task()), "observed_at": "2026-09-07T00:00:00"}),
        ("bad_observed", {**evidence(task()), "observed_at": "nope"}), ("no_decisions", {"tasks": [], "observed_at": NOW.isoformat()}))}
    out["minimum_samples"] = [ev(api, dataclasses.replace(d0, minimum_samples=m), evidence(task())) for m in (0, 1, 2)]
    row = task(attempt=2)
    row.pop("attempt_outcomes")
    out["legacy_history"] = ev(api, d0, evidence(row))
    row = task()
    row["created_at"] = "not-a-time"
    out["bad_created"] = ev(api, d1, evidence(row))
    out["task_changes"] = {}
    for name, change in (("future_created", {"created_at": (NOW + timedelta(seconds=1)).isoformat()}),
                         ("future_completed", {"completed_at": (NOW + timedelta(seconds=1)).isoformat()}),
                         ("completed_before_created", {"completed_at": (NOW - timedelta(hours=2)).isoformat()}),
                         ("completed_ok", {"completed_at": (NOW - timedelta(minutes=5)).isoformat()}),
                         ("completed_null", {"completed_at": None}),
                         ("attempt_true", {"attempt": True}), ("attempt_zero", {"attempt": 0}), ("attempt_negative", {"attempt": -1}),
                         ("attempt_str", {"attempt": "1"}), ("status_made_up", {"status": "made_up"}),
                         ("queued", {"status": "queued", "attempt": 0}), ("running", {"status": "running"}),
                         ("failed", {"status": "failed", "attempt_outcomes": [{"attempt": 1, "status": "failed", "at": NOW.isoformat()}]}),
                         ("lease_expired_outcome", {"status": "retry", "attempt_outcomes": [
                             {"attempt": 1, "status": "lease_expired", "at": NOW.isoformat()}]}),
                         ("duplicate_attempt", {"attempt_outcomes": [{"attempt": 1, "status": "failed", "at": NOW.isoformat()}] * 2}),
                         ("outcome_attempt_beyond", {"attempt_outcomes": [{"attempt": 2, "status": "failed", "at": NOW.isoformat()}]}),
                         ("outcome_before_created", {"attempt_outcomes": [{"attempt": 1, "status": "failed",
                                                                           "at": (NOW - timedelta(hours=2)).isoformat()}]}),
                         ("outcome_future", {"attempt_outcomes": [{"attempt": 1, "status": "failed",
                                                                   "at": (NOW + timedelta(seconds=1)).isoformat()}]}),
                         ("outcome_bad_status", {"attempt_outcomes": [{"attempt": 1, "status": "bogus", "at": NOW.isoformat()}]}),
                         ("outcome_missing_key", {"attempt_outcomes": [{"attempt": 1, "status": "failed"}]}),
                         ("no_outcomes_running_attempt1", {"status": "running", "attempt_outcomes": []}),
                         ("no_outcomes_succeeded", {"attempt_outcomes": []}),
                         ("success_without_attempt", {"status": "succeeded", "attempt": 0}),
                         ("missing_status", {"status": None}),
                         ("not_in_window", {"created_at": (NOW - timedelta(hours=25)).isoformat()}),
                         ("window_start_inclusive", {"created_at": (NOW - timedelta(seconds=86400)).isoformat(), "attempt_outcomes": [
                             {"attempt": 1, "status": "succeeded", "at": (NOW - timedelta(seconds=86399)).isoformat()}]}),
                         ("created_at_observed", {"created_at": NOW.isoformat(), "attempt_outcomes": [
                             {"attempt": 1, "status": "succeeded", "at": NOW.isoformat()}]})):
        base = task()
        base.update(change)
        out["task_changes"][name] = [ev(api, d, evidence(base)) for d in (d0, d1)]
    mixed = evidence(task("a"), task("b", "failed", 1, "failed"), task("c", "queued", 0), task("d", "running", 1, "succeeded"))
    mixed["tasks"][2]["attempt_outcomes"] = []
    mixed["tasks"][3]["attempt_outcomes"] = []
    mixed["tasks"][3]["attempt"] = 1
    out["mixed_population"] = [ev(api, d, mixed) for d in (d0, d1)]
    out["short_window"] = [ev(api, dataclasses.replace(d, window_seconds=60), evidence(task())) for d in (d0, d1)]

    cap = evidence()
    for i in range(3):
        cap["decisions"].append({"id": str(i), "status": "running", "lease_until": (NOW + timedelta(seconds=1)).isoformat()})
    capacity = {"three_leased": ev(api, d2, cap)}
    cap["decisions"][0]["lease_until"] = NOW.isoformat()
    capacity["one_expired"] = ev(api, d2, cap)
    capacity["empty"] = ev(api, d2, evidence())
    cap["decisions"][0]["lease_until"] = None
    capacity["null_lease"] = ev(api, d2, cap)
    capacity["invalid_status"] = ev(api, d2, evidence({"id": "bad", "status": "made_up"}))
    capacity["decision_status_blocked"] = ev(api, d2, {"tasks": [], "decisions": [{"id": "x", "status": "blocked"}], "observed_at": NOW.isoformat()})
    capacity["task_status_pending_invalid"] = ev(api, d2, evidence({"id": "x", "status": "pending"}))
    capacity["tasks_and_decisions"] = ev(api, d2, {
        "tasks": [{"id": "t", "status": "running", "lease_until": (NOW + timedelta(minutes=1)).isoformat()}],
        "decisions": [{"id": "d", "status": "running", "lease_until": (NOW + timedelta(minutes=1)).isoformat()}] * 1,
        "observed_at": NOW.isoformat()})
    capacity["at_target"] = ev(api, d2, {
        "tasks": [{"id": f"t{i}", "status": "running", "lease_until": (NOW + timedelta(minutes=1)).isoformat()} for i in range(d2.target)],
        "decisions": [], "observed_at": NOW.isoformat()})
    capacity["over_target"] = ev(api, d2, {
        "tasks": [{"id": f"t{i}", "status": "running", "lease_until": (NOW + timedelta(minutes=1)).isoformat()} for i in range(d2.target + 1)],
        "decisions": [], "observed_at": NOW.isoformat()})
    capacity["duplicate_ids"] = ev(api, d2, {"tasks": [{"id": "x", "status": "queued"}], "decisions": [{"id": "x", "status": "queued"}],
                                             "observed_at": NOW.isoformat()})
    capacity["lease_at_observed"] = ev(api, d2, evidence({"id": "x", "status": "running", "lease_until": NOW.isoformat()}))
    out["capacity"] = capacity
    return out


def collect_case(api, root: Path) -> dict:
    out = {}
    store, artifacts = api.MemoryStore(), api.FileArtifacts(str(root / "artifacts"))
    with store.transaction() as tx:
        tx.put("tasks", "one", task())
    results = api.Measurements(store, artifacts).collect(REVISION, NOW)
    snapshot = artifacts.document(results[0]["evidence_refs"][0])
    with store.transaction() as tx:
        rows = tx.scan("metric_observations")
        tx.put("tasks", "one", task(status="failed"))
    out["results"] = results
    out["snapshot"] = snapshot
    out["replayed_value"] = dataclasses.asdict(api.dm.evaluate(api.dm.DEFINITIONS[0], snapshot, NOW))
    out["rows"] = sorted(rows, key=lambda r: r["id"])
    out["row_keys_by_metric"] = sorted(r["metric_id"] for r in rows)
    out["artifact_files"] = sorted(p.suffix for p in (root / "artifacts").iterdir())
    out["artifact_file_names_are_the_ref"] = sorted(p.stem for p in (root / "artifacts").iterdir()) == [results[0]["evidence_refs"][0][7:]] * 2
    out["all_refs_equal"] = len({r["evidence_refs"][0] for r in results}) == 1
    out["promotion_approval"] = [r["promotion_approval"] for r in results]
    with store.transaction() as tx:
        out["rows_after_task_change"] = len(tx.scan("metric_observations"))
    out["snapshot_unchanged"] = artifacts.document(results[0]["evidence_refs"][0]) == snapshot
    again = api.Measurements(store, artifacts).collect(REVISION, NOW)
    with store.transaction() as tx:
        out["second_collect_new_rows"] = len(tx.scan("metric_observations"))
    out["second_collect_same_ref"] = again[0]["evidence_refs"] == results[0]["evidence_refs"]
    later = api.Measurements(store, artifacts).collect(REVISION, NOW + timedelta(seconds=1))
    with store.transaction() as tx:
        out["later_collect_rows"] = len(tx.scan("metric_observations"))
    out["later_collect_refs_differ"] = later[0]["evidence_refs"] != results[0]["evidence_refs"]
    return out


def populated_case(api, root: Path) -> dict:
    store, artifacts = api.MemoryStore(), api.FileArtifacts(str(root / "artifacts"))
    lease = (NOW + timedelta(minutes=5)).isoformat()
    with store.transaction() as tx:
        tx.put("tasks", "t1", task("t1"))
        tx.put("tasks", "t2", {**task("t2", "running", 1, "succeeded"), "lease_until": lease})
        tx.put("tasks", "t3", {**task("t3", "failed", 1, "failed")})
        tx.put("decisions_pending", "d1", {"id": "d1", "status": "running", "lease_until": lease})
        tx.put("decisions_pending", "d2", {"id": "d2", "status": "pending"})
    results = api.Measurements(store, artifacts).collect("b" * 40, NOW)
    return {"results": results, "snapshot": artifacts.document(results[0]["evidence_refs"][0])}


def refusals(api, root: Path) -> dict:
    out = {}
    for name, revision in (("empty", ""), ("none", None)):
        store, artifacts = api.MemoryStore(), api.FileArtifacts(str(root / ("refusal-" + name)))
        out[name] = {"outcome": call(api.Measurements(store, artifacts).collect, revision, NOW),
                     "store_data": store.data, "artifact_files": sorted(p.name for p in (root / ("refusal-" + name)).iterdir())}
    return out


def default_now(api, root: Path) -> dict:
    store, artifacts = api.MemoryStore(), api.FileArtifacts(str(root / "default-now"))
    results = api.Measurements(store, artifacts).collect(REVISION)
    parsed = [datetime.fromisoformat(r["observed_at"]) for r in results]
    return {"count": len(results), "aware_utc": all(p.utcoffset() == timedelta(0) for p in parsed),
            "one_instant": len({r["observed_at"] for r in results}) == 1,
            "window_end_is_observed_at": all(r["window_end"] == r["observed_at"] for r in results),
            "window_starts": sorted(
                (r["metric_id"], (datetime.fromisoformat(r["observed_at"]) - datetime.fromisoformat(r["window_start"])).total_seconds())
                for r in results)}


def run(api) -> dict:
    out = {}
    out["definitions"] = {"documents": api.dm.definition_documents(), "terminal": sorted(api.dm.TERMINAL),
                          "count": len(api.dm.DEFINITIONS), "frozen": call(
                              lambda: setattr(api.dm.DEFINITIONS[0], "metric_id", "x"))}
    out["timestamp"] = {"aware": call(lambda: api.dm.timestamp("2026-09-07T00:00:00+00:00").isoformat()),
                        "offset": call(lambda: api.dm.timestamp("2026-09-07T09:00:00+09:00").isoformat()),
                        "naive": call(api.dm.timestamp, "2026-09-07T00:00:00"), "bad": call(api.dm.timestamp, "nope"),
                        "none": call(api.dm.timestamp, None)}
    out["evaluate"] = evaluations(api)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a").mkdir()
        (root / "b").mkdir()
        (root / "c").mkdir()
        (root / "d").mkdir()
        out["collect"] = collect_case(api, root / "a")
        out["collect_populated"] = populated_case(api, root / "b")
        out["collect_refusals"] = refusals(api, root / "c")
        out["collect_default_now"] = default_now(api, root / "d")
    return out
