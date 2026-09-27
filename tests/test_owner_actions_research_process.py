"""INV-OWNER-ACTIONS-001 policy v2 research dispatch: the ACTUAL process lifecycle (whole-goal adjudication C3,
T3-1..T3-4), kept apart from the happy-path fixtures of test_owner_actions_recovery.py.

Real: the incumbent DB-free guardian (`continuation_process`, spawned by `ResearchLaunches` through
`spawn_guardian`), its exclusive spawn marker, lock, claim, stop file, cleanup proof and `observe`; the
owner-actions coordinator and the rest of the Chain world of test_owner_actions_recovery. LABELLED: the
guardian's child is `python -c` sleeping (a stand-in for `zeus research-program run`; no council, provider or
network), and when a test needs the child's own store effects it writes them IN-PROCESS through the real
ResearchProgram runner under the launch id as the cycle owner token (a separate process cannot reach the
MemoryStore). The provider probe runs the real `--version` check against this interpreter (LABELLED: it
stands in for codex and node). Nothing reaches a live service or production state.
"""
from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pytest
from test_continuation_research import two_strikes
from test_owner_actions_recovery import PROGRAM, Chain, accepted, registered_plan, released

from codex_harness.adapters import owner_actions as adapter
from codex_harness.adapters.continuation_process import launch_directory, spawn_guardian
from codex_harness.adapters.research_program_cli import add_parser as add_program_parser
from codex_harness.adapters.research_program_cli import run as program_run
from codex_harness.application.research_program import BUCKET_PROGRAMS
from codex_harness.domain import owner_actions as do
from codex_harness.domain.research_program import ProgramRefused


def sleeper(seconds):
    """LABELLED stand-in for `zeus research-program run <program> --ticks 1 --cycle-owner <launch>`."""
    def command(program_id, launch):
        return [sys.executable, "-c", "import sys, time; time.sleep(float(sys.argv[1]))", str(seconds)]
    return command


def until(predicate, timeout=30.0, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


class Spawns:
    """Counts every guardian actually spawned (the real `spawn_guardian` underneath)."""

    def __init__(self):
        self.argv = []

    def __call__(self, argv, **kwargs):
        self.argv.append(list(argv))
        return spawn_guardian(argv, **kwargs)


def process_chain(tmp_path, seconds=30.0, spawn=None):
    chain = Chain(tmp_path)
    chain.spawns = spawn or Spawns()
    chain.research = launches(tmp_path, seconds, chain.spawns)
    chain.owner = chain.build_owner()
    _, _, intent = two_strikes(chain.world, "op-b2", "docs/a.md")
    released(chain, intent)
    return chain


def launches(tmp_path, seconds, spawn):
    return adapter.ResearchLaunches(tmp_path / "owner-actions" / "research", lambda lane: str(tmp_path),
                                    command=sleeper(seconds), spawn=spawn, seconds=60,
                                    resolve=lambda: {"codex": sys.executable, "node": sys.executable})


def dispatch(chain):
    [row] = chain.actions(do.RESEARCH_DISPATCH)
    return row


def stop(chain, row):
    """The guardian's own stop request (its `stop` file); it terminates the child tree and writes its proof."""
    directory = launch_directory(chain.research.root, row["launch_id"])
    (directory / "stop").write_text("stop", "utf-8")
    assert until(lambda: (directory / "cleanup.json").exists()), "the guardian never proved its cleanup"


def child_records(chain, row):
    """LABELLED: the child's own effects, written in-process by the REAL runner under the launch id."""
    chain.env.programs.token = lambda: row["launch_id"]
    return chain.env.runner.tick(PROGRAM)


# ---- T3-1: the tick never joins the child; the other policy advances meanwhile -----------------------------
def test_ticks_stay_bounded_while_the_real_child_runs_and_the_other_policy_is_delivered(tmp_path):
    chain = process_chain(tmp_path)
    try:
        i1 = accepted(chain, "op-i1", "docs/b.md", "policy-i1")
        durations = []
        for _ in range(3):
            started = time.monotonic()
            chain.owners()
            durations.append(time.monotonic() - started)
        row = dispatch(chain)
        assert row["state"] == do.RUNNING and len(chain.spawns.argv) == 1
        assert chain.research.poll(row["launch_id"])["state"] == "running"
        assert max(durations) < 10.0, durations            # the child sleeps 30 s: nothing waited for it
        plan = registered_plan(chain, i1)
        assert plan["state"] == do.COMPLETED and chain.host.plan(plan["plan_id"]) is not None
        # The child "finishes" its tick (LABELLED in-process effects), then its guardian proves cleanup.
        receipt = child_records(chain, row)
        assert receipt["reserved"] is True
        stop(chain, row)
        chain.owner.tick("owners-002")
        row = dispatch(chain)
        assert row["state"] == do.COMPLETED and row["reason_code"] == "research_dispatch_accepted"
        assert row["outcome"]["launch"]["cleanup_confirmed"] is True and len(chain.spawns.argv) == 1
    finally:
        stop_all(chain)


# ---- T3-2: stop while pending, restart, observe: a proof decides, never a second spawn --------------------
def test_a_stopped_child_seen_by_a_restarted_owner_is_decided_by_its_proof_and_its_rows(tmp_path):
    chain = process_chain(tmp_path)
    try:
        chain.owner.tick("owners-002")
        row = dispatch(chain)
        assert row["state"] == do.RUNNING
        assert until(lambda: (launch_directory(chain.research.root, row["launch_id"]) / "claim").exists())
        # Restart while it runs: a new port (no child handle) observes the held lock and waits. (A guardian
        # that had not yet taken its lock would be fenced here and never execute: that is the one relaunch.)
        chain.research = launches(tmp_path, 30.0, chain.spawns)
        restarted = chain.build_owner()
        restarted.tick("owners-002")
        assert dispatch(chain)["state"] == do.RUNNING and dispatch(chain)["launches"] == 1
        stop(chain, row)
        chain.research = launches(tmp_path, 30.0, chain.spawns)
        chain.build_owner().tick("owners-002")
        row = dispatch(chain)
        # The labelled child reserved nothing: a proven no-effect end is a named outcome, not a relaunch.
        assert row["state"] == do.REFUSED and row["reason_code"] == "research_cycle_not_reserved"
        assert len(chain.spawns.argv) == 1
        with chain.world.control.transaction() as tx:
            assert tx.get(BUCKET_PROGRAMS, PROGRAM)["active_cycle"] is None
    finally:
        stop_all(chain)


@pytest.mark.parametrize("reserved", [False, True])
def test_a_guardian_killed_without_a_proof_is_unknown_keeps_the_debt_and_is_never_relaunched(tmp_path, reserved):
    """T3-2 no proof, and T3-4: an owned cycle of a crashed child keeps the program busy."""
    chain = process_chain(tmp_path, seconds=1.0)
    chain.owner.tick("owners-002")
    row = dispatch(chain)
    directory = launch_directory(chain.research.root, row["launch_id"])
    assert until(lambda: (directory / "claim").exists())
    if reserved:
        chain.env.programs.token = lambda: row["launch_id"]
        chain.env.programs.reserve_cycle(PROGRAM, chain.env.identity)   # LABELLED: reserved, then crashed
    guardian = chain.research.children[row["launch_id"]]
    guardian.kill()                                    # the guardian dies outright: no proof is written
    guardian.wait(10)
    time.sleep(1.5)                                    # the labelled child (1 s) is gone too
    chain.research = launches(tmp_path, 1.0, chain.spawns)
    chain.build_owner().tick("owners-002")
    row = dispatch(chain)
    assert row["state"] == do.UNKNOWN and row["reason_code"] == "research_launch_unknown"
    assert not (directory / "cleanup.json").exists() and len(chain.spawns.argv) == 1
    with chain.world.control.transaction() as tx:
        busy = tx.get(BUCKET_PROGRAMS, PROGRAM)["active_cycle"]
    assert (busy is not None) is reserved, "an owned cycle is never cleared by the owner"
    for _ in range(3):
        chain.build_owner().tick("owners-002")
    assert len(chain.spawns.argv) == 1 and len(chain.actions(do.RESEARCH_DISPATCH)) == 1


# ---- T3-3: a lost start response ---------------------------------------------------------------------------
def test_a_lost_start_response_is_replayed_as_cached_and_one_guardian_runs(tmp_path):
    chain = process_chain(tmp_path)
    real = chain.research
    lost = {"left": 1}

    class LosingStart:
        def __getattr__(self, name):
            return getattr(real, name)

        def start(self, launch, program_id, lane):
            result = real.start(launch, program_id, lane)
            if lost["left"]:
                lost["left"] -= 1
                raise TimeoutError("start response lost after the spawn (labelled injected fault)")
            return result
    try:
        chain.build_owner(research=LosingStart()).tick("owners-002")
        assert dispatch(chain)["state"] == do.LAUNCHING
        # A restarted owner (a new port object, no handle): the exclusive marker answers `cached`.
        chain.research = launches(tmp_path, 30.0, chain.spawns)
        chain.build_owner().tick("owners-002")
        row = dispatch(chain)
        assert row["state"] == do.RUNNING and len(chain.spawns.argv) == 1
        assert chain.research.start(row["launch_id"], PROGRAM, "a")["cached"] is True
    finally:
        stop_all(chain, real)


def stop_all(chain, *ports):
    for port in (chain.research, *ports):
        for launch in list(getattr(port, "children", {})):
            directory = launch_directory(port.root, launch)
            if not (directory / "cleanup.json").exists():
                (directory / "stop").write_text("stop", "utf-8")
        for child in getattr(port, "children", {}).values():
            try:
                child.wait(20)
            except Exception:
                child.kill()


# ---- the ports themselves --------------------------------------------------------------------------------
def test_the_probe_answers_only_for_resolved_executables_that_run(tmp_path):
    def probe(found):
        return adapter.ResearchLaunches(tmp_path, lambda lane: str(tmp_path), resolve=lambda: found).probe()
    assert probe({"codex": sys.executable, "node": sys.executable})["ok"] is True
    assert probe({"codex": None, "node": sys.executable})["reason_code"] == "codex_unresolved"
    assert probe({"codex": sys.executable, "node": None})["reason_code"] == "node_unresolved"
    missing = probe({"codex": str(tmp_path / "missing-codex"), "node": sys.executable})
    assert missing["ok"] is False and missing["reason_code"] == "codex_unavailable"


def test_the_child_argv_is_the_existing_cli_with_the_launch_id_as_cycle_owner_in_the_lane_repository(tmp_path):
    captured = []

    def spawn(argv, **kwargs):
        captured.append((argv, kwargs))
        return SimpleNamespace(pid=1, poll=lambda: 0)
    launch = "a" * 64
    port = adapter.ResearchLaunches(tmp_path / "root", lambda lane: str(tmp_path / ("repo-" + lane)), spawn=spawn,
                                    seconds=5)
    assert port.start(launch, PROGRAM, "harness")["cached"] is False
    assert port.start(launch, PROGRAM, "harness")["cached"] is True
    [(argv, kwargs)] = captured
    assert argv[-9:] == ["--", *adapter.DEFAULT_ARGV[1:], "research-program", "run", PROGRAM, "--ticks", "1",
                         "--cycle-owner", launch][-9:]
    assert kwargs["cwd"] == str(tmp_path / "repo-harness")
    assert kwargs["env"]["ZEUS_REPOSITORY"] == kwargs["env"]["HARNESS_REPOSITORY"] == str(tmp_path / "repo-harness")
    # The guardian bound comes from domain.policy; never restated here.
    from codex_harness.adapters.continuation_process import CONDUCT_MARGIN_SECONDS
    from codex_harness.domain.policy import POLICY
    assert adapter.ResearchLaunches(tmp_path, str).seconds == POLICY.task_seconds + CONDUCT_MARGIN_SECONDS


def test_the_cycle_owner_option_is_one_tick_and_one_exact_token():
    import argparse

    parser = argparse.ArgumentParser()
    add_program_parser(parser.add_subparsers(dest="command"))
    parsed = parser.parse_args(["research-program", "run", PROGRAM, "--ticks", "1", "--cycle-owner", "a" * 64])
    assert parsed.cycle_owner == "a" * 64
    assert parser.parse_args(["research-program", "run", PROGRAM, "--ticks", "2"]).cycle_owner is None
    service = SimpleNamespace(store=None)
    for ticks, owner in ((2, "a" * 64), (1, "A" * 64), (1, "a" * 63), (1, "../x")):
        with pytest.raises(ProgramRefused, match="cycle_owner_invalid"):
            program_run(service, argparse.Namespace(program_id=PROGRAM, ticks=ticks, cycle_owner=owner))


def test_one_owner_process_ticks_every_named_policy_and_one_refusal_never_stops_the_others():
    calls = []

    class Owner:
        store = None

    def tick(owner, config, policy_id, source_factory=None):
        calls.append(policy_id)
        if policy_id == "broken":
            raise OSError("store read failed (labelled injected fault)")
        return {"outcome": "progressed" if policy_id == "busy" else "idle", "policy_id": policy_id}
    original = adapter.tick_policy
    adapter.tick_policy = tick
    try:
        result = adapter.tick_policies(Owner(), {}, ["broken", "busy", "quiet"])
    finally:
        adapter.tick_policy = original
    assert calls == ["broken", "busy", "quiet"] and result["outcome"] == "progressed"
    assert [r["outcome"] for r in result["policies"]] == ["refused", "progressed", "idle"]
    assert result["policies"][0]["error_type"] == "OSError"
    assert adapter.policy_list(["a", "b"]) == ["a", "b"]
    for bad in ([], ["a", "a"], None):
        with pytest.raises(do.OwnerActionRefused, match="policy_list_invalid"):
            adapter.policy_list(bad)
