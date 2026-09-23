"""INV-CONTINUATION-001: the production adapter and `zeus continuation` commands.

The policy is read from a REAL temporary Git repository through the existing `GitSource`; stores
are real MemoryStores; the conductor child's process runner and the lane executor are LABELLED
fixtures (no model, provider, Docker, PostgreSQL or network). Nothing here qualifies a live host.
"""
from __future__ import annotations

import hashlib
import json
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


def test_the_runner_pass_keeps_its_port_across_ticks_and_an_unreadable_pin_only_drains(tmp_path):
    world = World(tmp_path)
    world.conductor.pending = True
    root, revision = policy_repository(world)
    config = world.fleet.registered()["config"]
    adapter.register_policy(world.control, config, "a", revision, "ops/continuation.json")
    world.enqueue("op-1")
    tick = adapter.ContinuationPass(world.control, config, HOST, "policy-1", processes=world.conductor,
                                    lanes=world.lanes, runtime=world.runtime)
    assert tick()["actions"] == [{"subject": "op-1", "effect": "session_bound"}]
    job_id, _ = world.run_next(verdict=True)
    tick()
    launch = world.conductor.active()
    assert len(launch) == 1 and tick.owned() == launch and tick.unresolved() == []
    # The pinned commit disappears while the child runs: no new effect, but the child is settled.
    with world.control.transaction() as tx:
        row = tx.get("continuation_policies", "policy-1")
        tx.put("continuation_policies", "policy-1", {**row, "pin": {**row["pin"], "revision": "0" * 40}})
    world.conductor.finish(launch[0])
    refused = tick()
    assert refused["outcome"] == "refused" and refused["reason_code"] == "policy_unavailable"
    assert [action["effect"] for action in refused["actions"]] == ["conductor_decided"]
    assert tick.owned() == [] and tick.drain()["actions"] == [] and world.conductor.calls == [job_id]


def test_a_standalone_tick_reserves_through_the_same_fleet_authority_as_the_runner(tmp_path):
    world = World(tmp_path, max_parallel=1)
    root, revision = policy_repository(world)
    config = world.fleet.registered()["config"]
    adapter.register_policy(world.control, config, "a", revision, "ops/continuation.json")
    owner = adapter.coordinator(world.control, config, HOST, lanes=world.lanes, conductor=world.conductor)
    assert owner.fleet.store is world.control, "the standalone coordinator uses the control store's Fleet"
    world.enqueue("op-1")
    adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes, conductor=world.conductor,
                        runtime=world.runtime)
    job_id, _ = world.run_next(verdict=True)
    world.enqueue("op-2", "docs/b.md")
    job = world.fleet.admit_one()["job"]  # another controller's worker holds the only slot
    full = adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes,
                               conductor=world.conductor, runtime=world.runtime)
    assert {"subject": job_id, "reason_code": "conductor_capacity", "next_owner": "fleet"} in full["skipped"]
    assert world.conductor.calls == [] and world.fleet.held_units() == []
    world.fleet.finalize(job["id"], job["owner_token"], {"status": "failed", "reason_code": "child_refused"})
    adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes, conductor=world.conductor,
                        runtime=world.runtime)
    assert world.conductor.calls == [job_id] and world.fleet.units()[0]["state"] == "released"


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


def test_conductor_processes_spawn_one_guardian_for_the_existing_command_in_the_lane_environment(tmp_path):
    world = World(tmp_path)
    config = world.fleet.registered()["config"]
    seen = []

    def spawn(argv, **kwargs):  # LABELLED fixture of the guardian spawn: records, starts nothing, stays running
        seen.append((argv, kwargs))
        return SimpleNamespace(pid=4242, poll=lambda: None, breakaway=None)
    job = {"id": "op-1", "manifest": manifest("op-1")}
    launch = "a" * 64
    port = adapter.ConductorProcesses(config, HOST, argv=("python", "-m", "codex_harness.cli"),
                                      entry=("python", "-m", "entry"), spawn=spawn, seconds=30)
    assert not hasattr(port, "available"), "the port holds no capacity: the Fleet unit is the slot"
    with pytest.raises(ValueError):
        port.start("a", job, launch, None)  # never without the reserved unit's token
    assert port.start("a", job, launch, "tok-1") == {"pid": 4242, "cached": False, "breakaway": None}
    assert port.active() == [launch]
    argv, kwargs = seen[0]
    directory = tmp_path / "rt-a" / "continuation" / "launches" / launch
    assert argv[:7] == ["python", "-m", "entry", "--launch", str(directory), "--seconds", "30.0"]
    assert argv[7:13] == ["--", "python", "-m", "codex_harness.cli", "--repository", str(tmp_path / "repo-a")]
    assert argv[13:16] == ["continuation", "conduct", "--file"]
    assert json.loads(Path(argv[16]).read_text(encoding="utf-8")) == job["manifest"]
    assert json.loads((directory / "launch.json").read_text(encoding="utf-8")) == {
        "schema": "urn:zeus:conductor-guardian:1", "launch": launch, "token": "tok-1", "seconds": 30}
    assert "search_path=lane_a" in kwargs["env"]["ZEUS_DATABASE_URL"] and kwargs["cwd"] == str(tmp_path / "repo-a")
    assert port.poll("a", launch) == {"state": "running", "owned": True, "exit_code": None}
    assert port.start("a", job, launch, "tok-1")["cached"] is True and len(seen) == 1, "one identity, one start"
    restarted = adapter.ConductorProcesses(config, HOST, spawn=spawn)
    assert restarted.start("a", job, launch, "tok-1") == {"pid": None, "cached": True} and len(seen) == 1, \
        "the one-shot spawn marker holds across a controller restart"
    with pytest.raises(ValueError):
        port.start("a", job, "../escape", "tok-1")


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


def test_research_accept_reads_the_owner_file_and_stores_one_verified_receipt(tmp_path):
    from test_continuation_research import held, receipt_for, receipts

    args = parser().parse_args(["continuation", "research-accept", "--file", "r.json"])
    assert args.continuation_command == "research-accept" and args.file == Path("r.json")
    world = World(tmp_path)
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt_for(world, research, investigation, dispatch)), encoding="utf-8")
    config = world.fleet.registered()["config"]
    stored = adapter.accept_research(world.control, config, HOST, adapter.read_receipt(path), lanes=world.lanes,
                                     evidence=world.evidence)
    assert stored["accepted"] is True and stored["cached"] is False
    assert stored["covered_jobs"] == sorted([root, successor]) and stored["intent_id"] == research["id"]
    again = adapter.accept_research(world.control, config, HOST, adapter.read_receipt(path), lanes=world.lanes,
                                    evidence=world.evidence)
    assert again["cached"] is True and len(receipts(world)) == 1
    # A malformed or unreadable file refuses by code before any store or lane access.
    path.write_text("{not json " + str(tmp_path), encoding="utf-8")
    for target in (path, tmp_path / "missing.json"):
        with pytest.raises(dc.ContinuationRefused) as info:
            adapter.read_receipt(target)
        refusal = continuation_cli.refusal(info.value)
        assert refusal["reason_code"] in {"research_receipt_invalid", "research_receipt_unreadable"}
        assert str(tmp_path) not in json.dumps(refusal)


def test_both_production_paths_read_research_evidence_from_the_configured_runtime_store(tmp_path, monkeypatch):
    """No evidence port is injected: `accept_research`, `tick_policy` and `ContinuationPass` must
    build their own over `<HARNESS_RUNTIME_DIR>/artifacts`, where the World's store also writes."""
    from test_continuation_research import EVIDENCE, held, receipt_for, receipts

    for name in ("HARNESS_RUNTIME_DIR", "ZEUS_RUNTIME_DIR"):
        monkeypatch.setenv(name, str(tmp_path / "runtime"))
    world = World(tmp_path)
    repo, revision = policy_repository(world)
    world.pin = {"revision": revision, "path": "ops/continuation.json", "lane": "a",
                 "sha256": hashlib.sha256((repo / "ops" / "continuation.json").read_bytes()).hexdigest()}
    root, successor, research, investigation, dispatch = held(world, tmp_path)
    document = receipt_for(world, research, investigation, dispatch)
    config = world.fleet.registered()["config"]
    path = tmp_path / "runtime" / "artifacts" / (EVIDENCE[0].partition(":")[2] + ".txt")
    body = path.read_bytes()
    # Owner acceptance: the file is absent from the configured store, so nothing is stored.
    path.unlink()
    with pytest.raises(dc.ContinuationRefused) as info:
        adapter.accept_research(world.control, config, HOST, document, lanes=world.lanes)
    assert info.value.reason_code == "research_evidence_missing" and receipts(world) == {}
    assert str(tmp_path) not in json.dumps(continuation_cli.refusal(info.value))
    path.write_bytes(body)
    assert adapter.accept_research(world.control, config, HOST, document, lanes=world.lanes)["cached"] is False
    # Runtime consumption: tampered after acceptance, the production tick keeps the hold.
    path.write_bytes(body + b"tampered")
    ticked = adapter.tick_policy(world.control, config, HOST, "policy-1", lanes=world.lanes,
                                 conductor=world.conductor, runtime=world.runtime)
    assert {"subject": research["id"], "reason_code": "research_evidence_corrupt",
            "next_owner": "portfolio_research"} in ticked["skipped"]
    assert world.intents()[research["id"]]["state"] == dc.RESEARCH_REQUIRED and len(world.jobs()) == 2
    # The runner pass holds the same configured store; once the bytes verify it releases once.
    path.write_bytes(body)
    runner = adapter.ContinuationPass(world.control, config, HOST, "policy-1", processes=world.conductor,
                                      lanes=world.lanes, runtime=world.runtime)
    assert runner.evidence.root.resolve() == (tmp_path / "runtime" / "artifacts").resolve()
    assert {"subject": research["id"], "effect": "research_resolved", "route": dc.RESEARCH} in runner()["actions"]
    assert world.intents()[research["id"]]["state"] == dc.COMPLETED and len(world.jobs()) == 3
