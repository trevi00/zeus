"""S10 A5-4: the remaining S9-accept producer seams of DESIGN-s10 §17c (R-a54): `ci_observed`, `queue_item_waited`,
`cleanup_recorded`.

MemoryStore, a recording observer behind the catalog-checking wrapper (a non-catalog attribute refuses and fails the test); no
provider, process, Git or PostgreSQL. Wired: `ci_observed` (DeliveryState.emit_check) and the release_queue `queue_item_waited`
(the controller tick's claim). S10 F2 wired the cleanup ledger (test_s10_r1_f2a.py: the executor's container path and the
`isolated_worker_runs reconcile` step), and the frontdesk and research-dispatch claims through composition wrappers
(composition.queue_waits, tests in test_s10_r1_f2b.py), not through the S8-pinned owners.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_s10_a5_2_seams import observed, only

from codex_harness.delivery.application.host_delivery.controller import DeliveryController
from codex_harness.delivery.application.host_delivery.stages.ci import CiObservation
from codex_harness.delivery.application.host_delivery.state import DeliveryState
from codex_harness.delivery.domain.host_delivery import AWAITING_CI, AWAITING_CONSUMPTION, ci_verdict
from codex_harness.execution.adapters.containers import cleanup_ledger
from codex_harness.observation.domain.feature_registry import FEATURES
from codex_harness.storage.adapters.memory_store import MemoryStore


def ref(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


# ----- ci_observed ------------------------------------------------------------------------------------------------------
REQUIRED = ["build (linux)", "lint", "tests", "docs"]
PLAN = {"plan_id": "p1", "release_id": "r1", "required_checks": REQUIRED}


def ci(observer):
    return DeliveryState(MemoryStore(), observer=observer)


def checks(*states):
    return [{"name": name, "state": state} for name, state in zip(REQUIRED, states)]


def ci_events(recorder):
    return [attrs for kind, _, attrs in recorder.events if kind == "operations.ci_observed"]


def test_one_event_per_required_check_with_the_adapters_normalized_conclusion():
    recorder, observer = observed()
    verdict = ci_verdict(REQUIRED, checks("success", "failure", "pending")[:3], "h")  # `docs` is absent
    ci(observer).emit_check(PLAN, {}, AWAITING_CI, verdict, claim={"attempt": 3})
    assert recorder.types == ["development.delivery_check_observed"] + ["operations.ci_observed"] * 4
    assert ci_events(recorder) == [
        {"check": ref(name), "conclusion": conclusion, "duration_seconds": None, "attempt": 3}
        for name, conclusion in zip(REQUIRED, ("success", "failure", "pending", "other"))]
    assert all(" " not in attrs["check"] for attrs in ci_events(recorder))  # names carry spaces: only the digest leaves


def test_a_passed_verdict_is_success_for_every_check_and_a_repeat_poll_emits_nothing():
    recorder, observer = observed()
    state = ci(observer)
    verdict = ci_verdict(REQUIRED, checks("success", "success", "success", "success"), "h")
    state.emit_check(PLAN, {"last_check_state": "pending"}, AWAITING_CI, verdict, claim={"attempt": 1})
    assert [a["conclusion"] for a in ci_events(recorder)] == ["success"] * 4
    count = len(recorder.events)
    state.emit_check(PLAN, {"last_check_state": verdict["state"]}, AWAITING_CI, verdict, claim={"attempt": 1})
    assert len(recorder.events) == count


def test_a_canary_transition_and_a_moved_head_are_not_ci_observations():
    recorder, observer = observed()
    state = ci(observer)
    state.emit_check(PLAN, {}, AWAITING_CONSUMPTION, {"state": "canary_passed", "reason_code": None, "missing": [],
                                                     "failed": [], "pending": []}, canary_passed=True)
    state.emit_check(PLAN, {}, AWAITING_CI, ci_verdict(REQUIRED, [], "h", observed_head="moved"))
    assert ci_events(recorder) == [] and len(recorder.events) == 2  # the existing delivery_check_observed events only


def test_without_an_observer_nothing_is_emitted_and_a_missing_claim_is_attempt_zero():
    ci(None).emit_check(PLAN, {}, AWAITING_CI, ci_verdict(REQUIRED, [], "h"), claim={"attempt": 1})  # no observer: no-op
    recorder, observer = observed()
    ci(observer).emit_check(PLAN, {}, AWAITING_CI, ci_verdict(REQUIRED, [], "h"))
    assert {a["attempt"] for a in ci_events(recorder)} == {0}


def test_the_ci_stage_hands_emit_check_its_claim():
    seen = []
    state = SimpleNamespace(
        candidate=lambda plan: {}, emit_check=lambda *args, **kwargs: seen.append((args, kwargs)),
        enter=lambda *args, **kwargs: {"entered": True})
    github = SimpleNamespace(observe=lambda candidate: {"head": "h", "checks": checks(*(["success"] * 4))})
    claim = {"id": "r1", "attempt": 2}
    CiObservation(MemoryStore(), github=github, state=state).observe_ci(PLAN, {"head": "h"}, claim)
    assert seen[0][1] == {"claim": claim, "durations": None} and seen[0][0][2] == AWAITING_CI  # S10 F2: the adapter's timing mapping (None: this port reports none)


# ----- queue_item_waited (release_queue) --------------------------------------------------------------------------------
NOW = datetime(2026, 10, 4, 12, 0, 42, tzinfo=timezone.utc)


def clocked(observer):
    return DeliveryState(MemoryStore(), observer=observer, clock=lambda: NOW.isoformat())


def waits(recorder):
    return [attrs for kind, _, attrs in recorder.events if kind == "operations.queue_item_waited"]


def test_a_release_queue_claim_emits_the_wait_since_the_rows_own_enqueue_time():
    recorder, observer = observed()
    clocked(observer).emit_queue_wait({"id": "r1", "at": (NOW - timedelta(seconds=42)).isoformat(), "attempt": 1})
    assert only(recorder) == ("operations.queue_item_waited", "observed",
                              {"queue": "release_queue", "item_ref": ref("r1"), "wait_seconds": 42.0, "outcome": "started"})


@pytest.mark.parametrize("row", [{"id": "r1"}, {"id": "r1", "at": None}, {"id": "r1", "at": "yesterday"},
                                 {"id": "r1", "at": "2026-10-04T12:00:00"},  # no timezone: not guessed
                                 {"id": "r1", "at": (NOW + timedelta(seconds=5)).isoformat()}])  # enqueued after the claim
def test_a_row_without_a_usable_enqueue_time_emits_nothing(row):
    recorder, observer = observed()
    clocked(observer).emit_queue_wait(row)
    assert recorder.events == []


def test_without_an_observer_a_claim_emits_nothing():
    clocked(None).emit_queue_wait({"id": "r1", "at": (NOW - timedelta(seconds=1)).isoformat()})


def test_the_controller_tick_emits_once_per_claim_and_nothing_for_a_busy_release():
    row = {"id": "r1", "at": (NOW - timedelta(seconds=42)).isoformat(), "attempt": 1}

    def tick(claim, observer):
        state = clocked(observer)
        state.gate = lambda plan: {"state": "ready"}
        claims = SimpleNamespace(enqueue=lambda *args: row, claim=lambda **kwargs: claim)
        controller = DeliveryController(MemoryStore(), enabled=True, claims=claims, state=state)
        controller._advance = lambda *args: {"claim": "unsettled", "outcome": "progressed"}
        state.unclaimed = lambda plan: "controller_lease_held"
        state.result = lambda *args, **kwargs: {"outcome": kwargs.get("reason_code") or args[2]}
        return controller._act({"plan": {"plan": {"plan_id": "p1", "release_id": "r1"}}, "intent": {"stage": "x"}})

    recorder, observer = observed()
    claimed = tick(row, observer)
    assert waits(recorder) == [{"queue": "release_queue", "item_ref": ref("r1"), "wait_seconds": 42.0, "outcome": "started"}]
    assert tick(row, None) == claimed  # no observer: the same outcome
    assert tick(None, observer) == {"outcome": "controller_lease_held"} and len(waits(recorder)) == 1  # busy: no claim, no event


# ----- cleanup_recorded (the ledger seam; its callers are wired since S10 F2) -------------------------------------------------
class Container:
    id, name = "c1", "zeus-worker-r1"
    config = {"limits": {"cleanup_seconds": 1}}

    def __init__(self, removed=True, confirmed=True):
        self.removed, self.confirmed = removed, confirmed

    def remove(self):
        return {"removed": self.removed}

    def stop(self, seconds):
        return {"confirmed": self.confirmed}


def record(tmp_path, role="worker", client=True):
    path = tmp_path / "run.json"
    stop = {"confirmed": True, "client_confirmed": client}
    return {"run_id": "r1", "role": role, "record": str(path), "container": "c1", "state": "stop_confirmed",
            "lifecycle": [{"state": "stop_confirmed", "stop": stop}], "workspace": "w"}


def cleanup(recorder):
    return [attrs for kind, _, attrs in recorder.events if kind == "operations.cleanup_recorded"]


@pytest.mark.parametrize("role,resource", [("worker", "container"), ("codex", "container"), ("verifier", "verification_stack")])
def test_retire_emits_removed_completed_once_with_the_resource_of_the_record_kind(tmp_path, role, resource):
    recorder, observer = observed()
    out = cleanup_ledger.retire(Container(), record(tmp_path, role), {}, "done", observer=observer)
    assert out["removed"] is True and cleanup(recorder) == [
        {"resource": resource, "cleanup_outcome": "removed", "cleanup_reason": "completed"}]


def test_retire_that_cannot_remove_the_container_records_a_failure_and_a_refusal_emits_nothing(tmp_path):
    recorder, observer = observed()
    out = cleanup_ledger.retire(Container(removed=False), record(tmp_path), {}, "done", observer=observer)
    assert out["removed"] is False and cleanup(recorder) == [
        {"resource": "container", "cleanup_outcome": "failed", "cleanup_reason": "removal_failed"}]
    refused = cleanup_ledger.retire(Container(), record(tmp_path, client=False), {}, "done", observer=observer)
    assert refused["refused"] == "client_cleanup_unconfirmed" and len(cleanup(recorder)) == 1


def test_hold_with_an_unconfirmed_stop_is_held_and_still_in_use(tmp_path):
    recorder, observer = observed()
    value, stopped = cleanup_ledger.hold(Container(confirmed=False), record(tmp_path), lambda: 7, observer=observer)
    assert value == 7 and stopped["confirmed"] is False and cleanup(recorder) == [
        {"resource": "container", "cleanup_outcome": "held", "cleanup_reason": "still_in_use"}]


def test_the_ledger_outcomes_are_unchanged_without_an_observer(tmp_path):
    left, right = tmp_path / "a", tmp_path / "b"
    left.mkdir(), right.mkdir()
    _, observer = observed()
    assert cleanup_ledger.retire(Container(), record(left), {}, "done", observer=observer).keys() == \
        cleanup_ledger.retire(Container(), record(right), {}, "done").keys()
    assert cleanup_ledger.hold(Container(confirmed=False), record(left), lambda: 7)[0] == 7  # None: no emit, no raise


def test_reconcile_emits_per_record(tmp_path):
    def runner(listing):
        return lambda argv, timeout, env=None: SimpleNamespace(returncode=0, stdout=listing, stderr="")

    def reconcile(listing, **row):
        directory = tmp_path / ("run" + str(len(list(tmp_path.iterdir()))))
        directory.mkdir()
        body = {**record(directory), "image": "i", "state": "stop_unconfirmed", **row}
        (directory / "run.json").write_text(json.dumps(body))
        recorder, observer = observed()
        out = cleanup_ledger.reconcile(directory, runner=runner(listing), observer=observer)
        return out, cleanup(recorder)

    out, events = reconcile("")
    assert out["reconciled"] is True and events == [
        {"resource": "container", "cleanup_outcome": "removed", "cleanup_reason": "completed"}]
    out, events = reconcile("abc")
    assert out["reason"] == "container_still_present" and events == [
        {"resource": "container", "cleanup_outcome": "held", "cleanup_reason": "still_in_use"}]
    out, events = reconcile("", lifecycle=[{"state": "stop_unconfirmed", "stop": {"confirmed": False, "client_confirmed": False}}])
    assert out["reason"] == "client_cleanup_unconfirmed" and events == [
        {"resource": "container", "cleanup_outcome": "debt_recorded", "cleanup_reason": "other"}]
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "run.json").write_text(json.dumps({**record(plain), "image": "i", "role": "worker"}))
    assert cleanup_ledger.reconcile(plain, runner=runner(""))["reconciled"] is True  # no observer: same outcome


# ----- the registry -----------------------------------------------------------------------------------------------------
def test_the_wired_features_are_instrumented():
    for feature in ("ci_checks", "queue_wait", "cleanup"):  # S10 F2: cleanup is wired (it named its seam before)
        assert FEATURES[feature].instrumented is True and FEATURES[feature].seam is None
