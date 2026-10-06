"""The one-job maintenance executor (INV-FLEET-001 maintenance amendment, INV-HOST-DELIVERY-MAINTENANCE-001).

`FleetRunner.run_preclaimed` and `MaintenanceCanaryExecutor` over MemoryStore with LABELLED fixture
launchers (test_fleet.FakeLauncher): nothing here spawns a process, runs `zeus operate run`, reads the
machine ledger or reaches a model, provider, executor transport or host."""
import os
import threading
from types import SimpleNamespace

import pytest
from test_fleet import GOAL, FakeLauncher, config, manifest
from test_fleet_maintenance import (
    MID,
    Clock,
    admit,
    granted,
    owner_paused_fleet,
    permit_for,
    proof_for,
    put_action,
    refused,
    row_of,
    snapshot,
)

import codex_harness.application.fleet as fleet_module
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet, FleetRunner, MaintenanceCanaryExecutor
from codex_harness.domain.fleet import FleetRefused
from codex_harness.domain.model import digest

ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}}


@pytest.fixture(autouse=True)
def no_signals(monkeypatch):
    """Nothing in the maintenance executor may signal a process; a signal fails the test."""
    def forbidden(*args):
        raise AssertionError("a maintenance canary child is never signalled")
    monkeypatch.setattr(os, "kill", forbidden)
    if hasattr(os, "killpg"):
        monkeypatch.setattr(os, "killpg", forbidden)


@pytest.fixture(autouse=True)
def no_executor_transport(monkeypatch):
    """Stub BOTH executor transports so no test here can make a real provider call: reaching either the
    Codex app-server or the Claude runtime raises (the fleet launcher under test is a labelled fixture)."""
    def forbidden(*args, **kwargs):
        raise AssertionError("an executor transport must never be constructed by a fleet maintenance test")
    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", forbidden)
    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", forbidden)


class Forbidden:
    """A port the one-job executor must never touch: every attribute access or call fails the test."""

    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwargs):
        raise AssertionError(self.name + " must not run in run_preclaimed")

    def __getattr__(self, attribute):
        raise AssertionError(self.name + "." + attribute + " must not run in run_preclaimed")


class CountingLauncher(FakeLauncher):
    """LABELLED fixture launcher that also counts launch ATTEMPTS and ledger reads."""

    def __init__(self, outcomes, **kwargs):
        super().__init__(outcomes, **kwargs)
        self.attempts, self.budgets = [], []

    def budget_exhausted(self, budget):
        self.budgets.append(dict(budget))
        return super().budget_exhausted(budget)

    def launch(self, job):
        self.attempts.append(job["id"])
        return super().launch(job)


def execute(executor, permit, **overrides):
    kwargs = {"permit_sha256": digest(permit), "proof": proof_for(permit), "max_wait_seconds": 30.0, **overrides}
    return executor.execute(permit["maintenance_id"], **kwargs)


def test_run_preclaimed_launches_waits_and_finalizes_exactly_one_job(tmp_path):
    f, permit = granted(tmp_path)
    f.enqueue("b", manifest("op-other", ["docs/other.md"]), GOAL, [])
    job = admit(f, permit)["job"]
    launcher = CountingLauncher({permit["job_id"]: ACCEPTED})
    runner = FleetRunner(f, launcher, sleep=Forbidden("sleep"), interval=0, reconcile=Forbidden("reconcile"),
                         backlog=Forbidden("backlog"), control=Forbidden("control"),
                         continuation=Forbidden("continuation"))
    result = runner.run_preclaimed(job, max_wait_seconds=30)
    assert result == {"job_id": permit["job_id"], "state": "finished",
                      "finalized": [{"id": permit["job_id"], "status": "accepted", "reason_code": "lead_accepted"}],
                      "finalize_failures": []}
    assert launcher.attempts == [permit["job_id"]] and launcher.budgets == [], "one launch; the ledger is the caller's"
    assert runner.children == {} and runner.hold_state is None, "no activation-hold release pass ran"
    assert row_of(f.store, "fleet_jobs", permit["job_id"])["status"] == "accepted"
    assert row_of(f.store, "fleet_jobs", "op-other")["status"] == "queued", "nothing else is admitted"
    assert row_of(f.store, "fleet_control", "admission")["paused"] is True


@pytest.mark.parametrize("change", [
    {"status": "queued"}, {"status": "unknown"}, {"owner_token": None}, {"owner_token": ""}, {"owner_token": 7},
    None,
])
def test_run_preclaimed_refuses_a_job_not_dispatching_or_without_owner(tmp_path, change):
    f, permit = granted(tmp_path)
    job = admit(f, permit)["job"]
    before = snapshot(f.store)
    launcher = CountingLauncher({})
    candidate = None if change is None else {**job, **change}
    refused(lambda: FleetRunner(f, launcher, interval=0).run_preclaimed(candidate, max_wait_seconds=30),
            "maintenance_admission_refused", "job")
    assert launcher.attempts == [] and snapshot(f.store) == before


@pytest.mark.parametrize("fault, status", [("refuse", "failed"), ("explode", "unknown")])
def test_refused_launch_fails_and_uncertain_spawn_stays_unknown_never_relaunched(tmp_path, fault, status):
    f, permit = granted(tmp_path)
    launcher = CountingLauncher({}, **{fault: {permit["job_id"]}})
    result = execute(MaintenanceCanaryExecutor(f, launcher, interval=0), permit)
    assert result == {"schema": "urn:zeus:fleet-maintenance-execution:1", "maintenance_id": MID,
                      "job_id": permit["job_id"], "admitted": True, "state": "not_launched", "job_status": status}
    assert launcher.attempts == [permit["job_id"]] and launcher.launched == []
    job = row_of(f.store, "fleet_jobs", permit["job_id"])
    reason = {"refuse": "isolation_required", "explode": "spawn_uncertain"}[fault]
    assert (job["status"], job["reason_code"]) == (status, reason)
    # A replay (a second arm, a restarted command) never launches again.
    after = snapshot(f.store)
    refused(lambda: execute(MaintenanceCanaryExecutor(f, launcher, interval=0), permit),
            "maintenance_already_used", "state")
    assert launcher.attempts == [permit["job_id"]] and snapshot(f.store) == after
    if status == "unknown":
        assert f.maintenance_readiness()["reserving"] == [permit["job_id"]]
        refused(lambda: f.close_maintenance_canary(permit, "maintenance_settled"),
                "maintenance_reconciliation_required", "job")
    else:
        assert f.close_maintenance_canary(permit, "maintenance_settled")["job_status"] == "failed"


def test_wait_bound_leaves_the_child_reserving_and_never_kills(tmp_path, monkeypatch):
    now = {"t": 0.0}
    monkeypatch.setattr(fleet_module, "time", SimpleNamespace(monotonic=lambda: now["t"], sleep=Forbidden("sleep")))

    class Hanging(CountingLauncher):
        """LABELLED: a child that never finishes within the bound; each wait advances the fake clock."""

        def __init__(self):
            super().__init__({})
            self.waits = []

        def wait(self, handles, seconds):
            self.waits.append(seconds)
            if len(self.waits) > 10:
                raise AssertionError("the wait bound was not honoured")
            now["t"] += 4.0
            return []

        def outcome(self, handle, job):
            raise AssertionError("an unfinished child has no outcome")

        def kill(self, *args):
            raise AssertionError("a maintenance canary child is never killed")

        terminate = kill

    f, permit = granted(tmp_path)
    launcher = Hanging()
    result = execute(MaintenanceCanaryExecutor(f, launcher, interval=5.0), permit, max_wait_seconds=10.0)
    assert (result["state"], result["job_status"]) == ("running", "dispatching")
    assert launcher.waits == [5.0, 5.0, 5.0] and launcher.attempts == [permit["job_id"]]
    job = row_of(f.store, "fleet_jobs", permit["job_id"])
    assert job["status"] == "dispatching" and job["owner_token"], "the reservation is kept for reconciliation"
    assert f.reconciliation_required() == [permit["job_id"]]
    for reason in ("maintenance_expired", "maintenance_cancelled", "maintenance_settled"):
        refused(lambda reason=reason: f.close_maintenance_canary(permit, reason),
                "maintenance_reconciliation_required", "job")
    # A zero bound launches and returns at once, still without killing anything.
    other, permit = granted(tmp_path)
    assert execute(MaintenanceCanaryExecutor(other, Hanging(), interval=5.0), permit,
                   max_wait_seconds=0)["state"] == "running"


def test_ordinary_runner_admission_is_unchanged_by_the_factoring(tmp_path):
    f = Fleet(MemoryStore())
    f.register(config(tmp_path))
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("b", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("a", manifest("op-3", ["docs/z.md"]), GOAL, ["op-1"])
    f.enqueue("b", manifest("op-4", ["docs/w.md"]), GOAL, [])
    f.enqueue("b", manifest("op-5", ["docs/v.md"]), GOAL, [])
    launcher = CountingLauncher({"op-1": ACCEPTED,
                                 "op-2": {"status": "rejected", "reason_code": "lead_rejected", "exit_code": 1},
                                 "op-3": {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0}},
                                refuse={"op-4"}, explode={"op-5"})
    sleeps = []
    summary = FleetRunner(f, launcher, sleep=sleeps.append, interval=0).run(once=True)
    assert launcher.peak == 2 and launcher.launched == ["op-1", "op-2", "op-3"]
    assert launcher.attempts == ["op-1", "op-2", "op-3", "op-4", "op-5"]
    assert summary["admitted"] == ["op-1", "op-2", "op-3", "op-4", "op-5"] and sleeps == []
    assert [(x["id"], x["status"]) for x in summary["finalized"]] == [
        ("op-1", "accepted"), ("op-2", "rejected"), ("op-4", "failed"), ("op-5", "unknown"), ("op-3", "unknown")]
    assert summary["reconciliation_required"] == ["op-3", "op-5"] and summary["finalize_failures"] == []
    assert set(summary) == {"admitted", "finalized", "finalize_failures", "blocked", "stopped", "reconciliation",
                            "backlog", "reconciliation_required"}
    # A paused fleet's ordinary runner admits nothing, even with a permit and its queued canary present.
    paused, permit = granted(tmp_path)
    idle = CountingLauncher({})
    summary = FleetRunner(paused, idle, sleep=sleeps.append, interval=0).run(once=True)
    assert summary["admitted"] == [] and idle.attempts == []
    assert summary["blocked"] == {permit["job_id"]: "paused"}


def test_executor_consults_the_ledger_and_launches_nothing_on_refusal(tmp_path):
    clock = Clock()
    f = owner_paused_fleet(tmp_path, clock)
    f.authorize_budget(8, 16, 8)  # the effective ceilings are what the ledger is asked about
    permit = permit_for()
    f.grant_maintenance_canary(permit)
    put_action(f.store, permit)
    f.enqueue("a", manifest(permit["job_id"], ["canary/probe.md"], {"per_host": 8, "total": 16}), GOAL, [])
    before = snapshot(f.store)
    exhausted = CountingLauncher({}, exhausted=True)
    refused(lambda: execute(MaintenanceCanaryExecutor(f, exhausted, interval=0), permit),
            "maintenance_admission_refused", "budget_exhausted")
    assert exhausted.budgets == [{"per_host": 8, "total": 16}] and exhausted.attempts == []
    assert snapshot(f.store) == before

    class Unreadable(CountingLauncher):
        def budget_exhausted(self, budget):
            raise OSError("LABELLED unreadable ledger /secret/path")

    unreadable = Unreadable({})
    error = refused(lambda: execute(MaintenanceCanaryExecutor(f, unreadable, interval=0), permit),
                    "maintenance_admission_refused", "budget_unknown")
    assert "secret" not in str(error) and unreadable.attempts == [] and snapshot(f.store) == before

    ready = CountingLauncher({permit["job_id"]: ACCEPTED})
    for overrides, code, field in (({"proof": {**proof_for(permit), "acknowledged": False}},
                                    "maintenance_admission_refused", "proof"),
                                   ({"permit_sha256": "0" * 64}, "maintenance_conflict", "permit")):
        refused(lambda overrides=overrides: execute(MaintenanceCanaryExecutor(f, ready, interval=0), permit,
                                                    **overrides), code, field)
    assert ready.attempts == [] and snapshot(f.store) == before
    refused(lambda: execute(MaintenanceCanaryExecutor(Fleet(MemoryStore()), ready, interval=0), permit),
            "unregistered")
    clock.advance(600)
    refused(lambda: execute(MaintenanceCanaryExecutor(f, ready, interval=0), permit),
            "maintenance_expired", "deadline")
    assert ready.attempts == [] and snapshot(f.store) == before


def test_executor_runs_the_admitted_canary_to_its_finalized_status(tmp_path):
    f, permit = granted(tmp_path)
    launcher = CountingLauncher({permit["job_id"]: ACCEPTED})
    result = execute(MaintenanceCanaryExecutor(f, launcher, interval=0), permit)
    assert result == {"schema": "urn:zeus:fleet-maintenance-execution:1", "maintenance_id": MID,
                      "job_id": permit["job_id"], "admitted": True, "state": "finished", "job_status": "accepted"}
    assert "owner_token" not in str(result)
    assert f.close_maintenance_canary(permit, "maintenance_settled")["launched"] is True
    assert f.resume()["paused"] is False and f.admit_one()["job"] is None


def test_two_executors_race_to_one_spawn(tmp_path):
    f, permit = granted(tmp_path)
    launcher = CountingLauncher({permit["job_id"]: ACCEPTED})
    barrier, results = threading.Barrier(2), []

    def arm():
        executor = MaintenanceCanaryExecutor(Fleet(f.store, clock=f.clock), launcher, interval=0)
        barrier.wait()
        try:
            results.append(execute(executor, permit)["state"])
        except FleetRefused as exc:
            results.append((exc.reason_code, exc.field))

    threads = [threading.Thread(target=arm) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results, key=str) == sorted(["finished", ("maintenance_already_used", "state")], key=str)
    assert launcher.attempts == [permit["job_id"]], "exactly one spawn"
    assert row_of(f.store, "fleet_jobs", permit["job_id"])["status"] == "accepted"


class SlowLauncher(CountingLauncher):
    """LABELLED fixture launcher whose child outlives the permit deadline: starting it moves the Fleet clock."""

    def __init__(self, outcomes, clock, seconds, **kwargs):
        super().__init__(outcomes, **kwargs)
        self.clock, self.seconds = clock, seconds

    def launch(self, job):
        handle = super().launch(job)
        self.clock.advance(self.seconds)
        return handle


def test_a_canary_that_settles_after_the_deadline_stays_owned_and_an_unadmitted_one_never_spawns(tmp_path):
    """S2M-13 (G1-03 ruling e, critique #1): admitted before the deadline, the canary is never expired by the
    deadline and closes only by its real settlement; one not admitted by the deadline fails without a spawn
    and no stale job executes on a later normal resume."""
    clock = Clock()
    f, permit = granted(tmp_path, clock)
    slow = SlowLauncher({permit["job_id"]: ACCEPTED}, clock, 700)
    result = execute(MaintenanceCanaryExecutor(f, slow, interval=0), permit)
    assert (result["state"], result["job_status"]) == ("finished", "accepted")
    assert slow.attempts == [permit["job_id"]]
    for reason in ("maintenance_expired", "maintenance_cancelled"):
        refused(lambda reason=reason: f.close_maintenance_canary(permit, reason),
                "maintenance_reconciliation_required", "job")
    closed = f.close_maintenance_canary(permit, "maintenance_settled")
    assert (closed["launched"], closed["job_status"]) == (True, "accepted")
    assert row_of(f.store, "fleet_jobs", permit["job_id"])["status"] == "accepted"

    late_clock = Clock()
    late, permit = granted(tmp_path, late_clock)
    late_clock.advance(600)
    never = CountingLauncher({permit["job_id"]: ACCEPTED})
    refused(lambda: execute(MaintenanceCanaryExecutor(late, never, interval=0), permit),
            "maintenance_expired", "deadline")
    assert never.attempts == []
    assert late.close_maintenance_canary(permit, "maintenance_expired")["launched"] is False
    job = row_of(late.store, "fleet_jobs", permit["job_id"])
    assert (job["status"], job["reason_code"], job["owner_token"]) == ("failed", "maintenance_expired", None)
    assert late.resume()["paused"] is False and late.admit_one()["job"] is None
    assert never.attempts == []
