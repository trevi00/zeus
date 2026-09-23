"""INV-CONTINUATION-001: the production adapter and `zeus continuation` commands.

The policy is read from a REAL temporary Git repository through the existing `GitSource`; stores
are real MemoryStores; the conductor child's process runner and the lane executor are LABELLED
fixtures (no model, provider, Docker, PostgreSQL or network). Nothing here qualifies a live host.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_continuation import GOAL, IDENTITY, World, manifest
from test_git_workspace import git
from test_operation import Bus, Collector, FakeBudget, FakeExecutor
from test_worker_sessions import IMAGE

from codex_harness.adapters import continuation as adapter
from codex_harness.adapters import continuation_cli
from codex_harness.application.operation import Operation
from codex_harness.application.workflow import Workflow
from codex_harness.cli import parser
from codex_harness.domain import continuation as dc
from codex_harness.domain.model import envelope

HOST = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
        "HARNESS_DATABASE_URL": "postgresql://fixture@127.0.0.1:1/fixture"}


def policy_repository(world, document=None, enabled=True):
    """The lane repository with the owner's policy committed at a real revision."""
    root = world.tmp / "repo-a"
    root.mkdir(exist_ok=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@localhost")
    (root / "ops").mkdir(exist_ok=True)
    body = {**world.document, "enabled": enabled, **(document or {})}
    (root / "ops" / "continuation.json").write_text(json.dumps(body), encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "owner policy")
    return root, git(root, "rev-parse", "HEAD")


def test_parser_exposes_the_opt_in_commands():
    args = parser().parse_args(["continuation", "tick", "--policy", "policy-1"])
    assert args.command == "continuation" and args.continuation_command == "tick" and args.policy == "policy-1"
    for argv in (["continuation", "register", "--lane", "a", "--revision", "e" * 40, "--path", "p.json"],
                 ["continuation", "status"], ["continuation", "identity", "--lane", "a"],
                 ["continuation", "conduct", "--file", "m.json"]):
        assert parser().parse_args(argv).continuation_command == argv[1]


def test_policy_is_registered_from_a_git_pin_and_a_moved_pin_refuses(tmp_path):
    world = World(tmp_path)
    root, revision = policy_repository(world)
    config = world.fleet.registered()["config"]
    receipt = adapter.register_policy(world.control, config, "a", revision, "ops/continuation.json")
    assert receipt["registered"] is True and receipt["cached"] is False
    assert adapter.register_policy(world.control, config, "a", revision, "ops/continuation.json")["cached"] is True
    with pytest.raises(dc.ContinuationRefused, match="policy_revision_missing"):
        adapter.register_policy(world.control, config, "a", "0" * 40, "ops/continuation.json")
    with pytest.raises(dc.ContinuationRefused, match="repository_foreign"):
        adapter.register_policy(world.control, config, "a", *policy_repository(
            world, {"repository": "0" * 64, "id": "policy-2"})[1:], "ops/continuation.json")
    world.enqueue("op-1")
    ticked = adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes,
                                 conductor=world.conductor, runtime=world.runtime)
    assert ticked["actions"] == [{"subject": "op-1", "effect": "session_bound"}]
    # The pinned blob is re-read on every tick: a pin whose commit disappeared refuses by name.
    with world.control.transaction() as tx:
        row = tx.get("continuation_policies", "policy-1")
        tx.put("continuation_policies", "policy-1", {**row, "pin": {**row["pin"], "revision": "0" * 40}})
    refused = adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes,
                                  conductor=world.conductor, runtime=world.runtime)
    assert refused["outcome"] == "refused" and refused["reason_code"] == "policy_unavailable"
    assert refused["next_owner"] == "operator"


def test_unregistered_policy_reads_no_git_no_lane_and_starts_no_process(tmp_path):
    world = World(tmp_path)

    def no_git(path):
        raise AssertionError("no Git read for an unregistered policy")
    result = adapter.tick_policy(world.control, world.fleet.registered()["config"], HOST, "policy-1",
                                 source_factory=no_git, lanes=world.lanes, conductor=world.conductor)
    assert result["outcome"] == "disabled" and world.lane_reads == 0 and world.conductor.calls == []
    assert adapter.configured_policy({}) is None and adapter.configured_policy({adapter.POLICY_SETTING: " "}) is None
    assert adapter.configured_policy({adapter.POLICY_SETTING: "policy-1"}) == "policy-1"


def test_lane_runtime_reports_the_actual_image_profile_and_archive_identity(tmp_path):
    world = World(tmp_path)
    config = world.fleet.registered()["config"]
    runtime = adapter.lane_runtime(config, HOST)("a")
    assert runtime["image"] == IMAGE and runtime["profile"] == "worker-v1"
    assert runtime["session_archive_sha256"] == adapter.archive_identity(tmp_path / "rt-a")
    assert adapter.lane_runtime(config, {})("a")["image"] is None, "no isolation: never the qualified image"
    identity = continuation_cli.execute(SimpleNamespace(store=world.control), SimpleNamespace(
        continuation_command="identity", lane="a"))
    assert identity["session_archive_sha256"] == runtime["session_archive_sha256"]
    assert identity["repository"] == world.repository and identity["exit_code"] == 0


def test_lane_conductor_runs_the_existing_command_in_the_lane_environment(tmp_path):
    world = World(tmp_path)
    config = world.fleet.registered()["config"]
    seen = []

    def run(argv, **kwargs):  # LABELLED fixture process runner: records, starts nothing
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    job = {"id": "op-1", "manifest": manifest("op-1")}
    assert adapter.LaneConductor(config, HOST, argv=("python", "-m", "codex_harness.cli"), run=run)("a", job) == {
        "exit_code": 0}
    argv, kwargs = seen[0]
    assert argv[:5] == ["python", "-m", "codex_harness.cli", "--repository", str(tmp_path / "repo-a")]
    assert argv[5:8] == ["continuation", "conduct", "--file"]
    assert json.loads(Path(argv[8]).read_text(encoding="utf-8")) == job["manifest"]
    assert "search_path=lane_a" in kwargs["env"]["ZEUS_DATABASE_URL"] and kwargs["timeout"] > 0

    def lost(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    with pytest.raises(subprocess.TimeoutExpired):  # the controller records this as an unknown effect
        adapter.LaneConductor(config, HOST, run=lost)("a", job)


class GuardedDecider:
    """LABELLED fixture of `Executor.decide_one`: honours the expected-row guard exactly like the
    real claim (a row that is no longer in an expected status is not claimed) and records a call
    only for a claimed row."""

    def __init__(self, svc, accepted=True):
        self.svc, self.accepted, self.calls = svc, accepted, []

    def decide_one(self, agent, expected=None):
        with self.svc.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            if row is None or row["status"] not in expected["statuses"] or row["actor"] != agent:
                return None
            self.calls.append(row["id"])
            row.update(status="succeeded", attempt=1, result={"accepted": self.accepted, "reason": "fixture",
                                                              "execution_ref": "sha256:" + "9" * 64})
            tx.put("decisions_pending", row["id"], row)
            return row


def accepted_lane(tmp_path):
    """A lane store holding one accepted operation and the lead's review.result for the conductor,
    shaped as the executor's `_commit_decision` writes it (fixture worker/lead)."""
    world = World(tmp_path)
    frozen = manifest("op-1")
    Operation(world.lane, FakeExecutor(world.lane, verdict=True), Bus(), Workflow(world.lane.store, world.lane.org),
              FakeBudget(), Collector()).run(frozen, IDENTITY, GOAL)
    with world.lane.store.transaction() as tx:
        operation = tx.get("operations", "op-1")
        lead = tx.get("decisions_pending", operation["decision_id"])
        report = envelope("review.result", "lead:improvement", "conductor", "review",
                          {"decision_id": lead["id"], "result": lead["result"]}, operation["correlation_id"])
        tx.put("outbox", report["message_id"], {"message": report, "sent": True})
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(frozen), encoding="utf-8")
    return world, path, report


def test_conduct_claims_exactly_the_pending_conductor_row_once(tmp_path):
    world, path, report = accepted_lane(tmp_path)
    decider, budget = GuardedDecider(world.lane), FakeBudget()
    first = continuation_cli.conduct(world.lane, SimpleNamespace(file=path), executor=decider, budget=budget)
    assert first["claimed"] is True and first["status"] == "succeeded" and first["accepted"] is True
    assert first["decision_id"] == report["message_id"] and first["exit_code"] == 0
    assert first["calls"] == {"reserved": 1, "settled": 1} and budget.reserved[0]["provider"] == "codex"
    with world.lane.store.transaction() as tx:
        row = tx.get("decisions_pending", report["message_id"])
    assert row["phase"] == "review_conductor" and row["actor"] == "conductor"
    again = continuation_cli.conduct(world.lane, SimpleNamespace(file=path), executor=decider, budget=budget)
    assert again["claimed"] is False and decider.calls == [report["message_id"]], "no second decision"


def test_conduct_refuses_an_operation_that_is_not_the_accepted_one_named(tmp_path):
    world, path, _ = accepted_lane(tmp_path)
    other = tmp_path / "other.json"
    other.write_text(json.dumps(manifest("op-1", objective="a different plan")), encoding="utf-8")
    decider = GuardedDecider(world.lane)
    with pytest.raises(Exception, match="not the accepted one"):
        continuation_cli.conduct(world.lane, SimpleNamespace(file=other), executor=decider, budget=FakeBudget())
    assert decider.calls == []


def test_status_and_refusal_print_codes_only(tmp_path):
    world = World(tmp_path)
    world.register()
    status = continuation_cli.execute(SimpleNamespace(store=world.control),
                                      SimpleNamespace(continuation_command="status", policy="policy-1"))
    assert status["exit_code"] == 0 and status["policies"][0]["id"] == "policy-1" and status["intents"] == []
    refusal = continuation_cli.refusal(dc.ContinuationRefused("goal_changed", "operator", "goal"))
    assert refusal == {"status": "refused", "reason_code": "goal_changed", "next_owner": "operator",
                       "error_type": "ContinuationRefused", "exit_code": 1}
    assert continuation_cli.refusal(RuntimeError("postgresql://secret"))["reason_code"] == "error"
    assert "postgresql" not in json.dumps(continuation_cli.refusal(RuntimeError("postgresql://secret")))
