"""INV-CONTINUATION-001: owned, nonblocking conductor children with REAL processes.

Every child here is a real local process started through the real `ProcessTree` by the real
`ConductorProcesses` and its real child wrapper (`python -m codex_harness.adapters.continuation_process`).
The command the wrapper runs is a LABELLED controlled sleeping Python child, never the conduct
command and never a model: these tests prove process ownership, polling, fencing, restart
reconciliation, timeout and the Fleet runner's accounting, not a conductor decision.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_continuation import LaneLauncher, World, accepted_item, only

import codex_harness
from codex_harness.adapters.continuation_process import (
    CLAIM_FENCED,
    ENTRY_ARGV,
    EXIT_FENCED,
    ConductorProcesses,
    launch_directory,
    observe,
)
from codex_harness.application.fleet import FleetRunner
from codex_harness.domain import continuation as dc

PACKAGE_ROOT = Path(codex_harness.__file__).resolve().parents[1]
HOST = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "fixture/image:1",
        "HARNESS_DATABASE_URL": "postgresql://fixture@127.0.0.1:1/fixture"}


def environment(lane=None, host=None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + ((os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    return env


def sleeper(seconds: float, marker: str | None = None):
    """The LABELLED controlled child: sleeps, optionally appends one line to a marker file."""
    code = f"import time; time.sleep({seconds})"
    if marker is not None:
        code += f"; open({marker!r}, 'a').write('ran\\n')"
    return lambda lane, manifest: [sys.executable, "-c", code]


def processes(world, seconds=60.0, command=None, **kwargs):
    (world.tmp / "repo-a").mkdir(exist_ok=True)  # the child's working directory, as a real lane has
    return ConductorProcesses(world.fleet.registered()["config"], HOST, command=command or sleeper(0.6),
                              environment=environment, seconds=seconds, **kwargs)


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


JOB = {"id": "op-1", "manifest": {"id": "op-1"}}


def test_an_owned_child_is_polled_without_waiting_and_settles_from_its_receipt(tmp_path):
    world = World(tmp_path)
    port = processes(world)
    launch = "1" * 64
    started = time.monotonic()
    assert port.start("a", JOB, launch)["pid"] > 0
    assert time.monotonic() - started < 2.0, "start returns once spawned, not when the child ends"
    assert port.poll("a", launch) == {"state": dc.LAUNCH_RUNNING, "owned": True, "exit_code": None}
    assert port.active() == [launch] and port.available() is False
    assert wait_for(lambda: port.active() == [])
    settled = port.poll("a", launch)
    assert settled["state"] == dc.LAUNCH_EXITED and settled["exit_code"] == 0 and settled["cleanup_confirmed"] is True
    directory = launch_directory(tmp_path / "rt-a", launch)
    assert json.loads((directory / "exit.json").read_text(encoding="utf-8")) == {"exit_code": 0}
    assert (directory / "claim").read_text(encoding="utf-8") == "child"
    assert port.start("a", JOB, launch) == {"pid": None, "cached": True}, "an entered identity never starts again"


def test_a_restarted_owner_reconciles_a_live_child_from_its_evidence_and_never_signals_it(tmp_path):
    world = World(tmp_path)
    first = processes(world, command=sleeper(1.5))
    launch = "2" * 64
    first.start("a", JOB, launch)
    assert wait_for(lambda: (launch_directory(tmp_path / "rt-a", launch) / "claim").exists())
    restarted = processes(world)  # the controller process was recreated: no handle, same evidence
    assert restarted.poll("a", launch) == {"state": dc.LAUNCH_RUNNING, "owned": False, "exit_code": None}
    assert restarted.active() == [], "a child owned elsewhere is unresolved, not this process's work"
    assert wait_for(lambda: restarted.poll("a", launch)["state"] == dc.LAUNCH_EXITED)
    assert restarted.poll("a", launch)["exit_code"] == 0
    # The receipt is written just before the wrapper itself exits, so the original owner's handle may
    # still be alive for a moment; it then reaps its own tree.
    assert wait_for(lambda: first.poll("a", launch)["state"] == dc.LAUNCH_EXITED) and first.active() == []


def test_a_launch_that_never_started_is_fenced_and_a_late_child_does_nothing(tmp_path):
    directory = launch_directory(tmp_path / "rt-a", "3" * 64)
    assert observe(directory) == {"state": dc.LAUNCH_ABSENT, "owned": False, "exit_code": None}
    assert (directory / "claim").read_text(encoding="utf-8") == CLAIM_FENCED
    marker = tmp_path / "late.txt"
    late = subprocess.run([*ENTRY_ARGV, "--launch", str(directory), "--", sys.executable, "-c",
                           f"open({str(marker)!r}, 'w').write('ran')"], env=environment(), timeout=60)
    assert late.returncode == EXIT_FENCED and not marker.exists(), "a fenced launch never enters"
    assert observe(directory)["state"] == dc.LAUNCH_ABSENT


def test_two_owners_of_one_launch_run_the_command_once(tmp_path):
    directory = launch_directory(tmp_path / "rt-a", "4" * 64)
    directory.mkdir(parents=True)
    marker = tmp_path / "ran.txt"
    argv = [*ENTRY_ARGV, "--launch", str(directory), "--", sys.executable, "-c",
            f"import time; open({str(marker)!r}, 'a').write('ran\\n'); time.sleep(1)"]
    children = [subprocess.Popen(argv, env=environment()) for _ in range(2)]
    codes = sorted(child.wait(timeout=60) for child in children)
    assert codes == [0, EXIT_FENCED] and marker.read_text(encoding="utf-8") == "ran\n"


def test_a_failed_spawn_is_reconciled_as_absent_never_retried_by_the_port(tmp_path):
    world = World(tmp_path)

    def broken(argv, **kwargs):
        raise OSError("spawn failed (injected)")
    port = processes(world, spawn=broken)
    launch = "5" * 64
    with pytest.raises(OSError):
        port.start("a", JOB, launch)
    assert port.active() == [] and port.poll("a", launch)["state"] == dc.LAUNCH_ABSENT


def test_a_child_past_its_deadline_is_ended_through_its_tree_and_reported_as_timeout(tmp_path):
    world = World(tmp_path)
    port = processes(world, seconds=0.5, command=sleeper(60))
    launch = "6" * 64
    port.start("a", JOB, launch)
    pid = port.children[launch]["tree"].process.pid
    assert wait_for(lambda: port.poll("a", launch)["state"] != dc.LAUNCH_RUNNING, timeout=30)
    assert port.active() == [] and launch not in port.children
    process = subprocess.run([sys.executable, "-c", f"import os\ntry:\n os.kill({pid}, 0)\nexcept OSError:\n print('gone')"],
                             capture_output=True, text=True, timeout=30) if os.name != "nt" else None
    if process is not None:
        assert process.stdout.strip() == "gone"


def test_fleet_admission_reaping_heartbeat_and_stop_continue_while_a_real_conductor_child_is_pending(tmp_path):
    """A real sleeping child is the pending conductor (LABELLED: it decides nothing). A second
    eligible family is admitted and reaped, heartbeats are written and a graceful stop is observed
    while it runs; the stop then drains it and settles its truthful outcome."""
    world = World(tmp_path)
    port = processes(world, command=sleeper(2.0))
    controller = world.build(conductor=port)
    world.register()
    job_id = accepted_item(world)
    world.enqueue("op-2", "docs/b.md")
    heartbeats, durations, flags = [], [], {"stop": False}

    class Pass:
        def __call__(self):
            started = time.monotonic()
            try:
                return world.tick(controller=controller)
            finally:
                durations.append(time.monotonic() - started)

        def drain(self):
            return controller.drain("policy-1")

        def owned(self):
            return port.active()

        def unresolved(self):
            return controller.unresolved("policy-1", port.active())

    class Control:  # LABELLED fixture of the managed runtime control
        def admission_open(self):
            return True

        def stop_requested(self):
            if world.jobs()["op-2"]["status"] == "accepted" and len(heartbeats) >= 3:
                flags["stop"] = True
            return flags["stop"]

        def heartbeat(self, state):
            heartbeats.append({**state, "conductor_alive": bool(port.active()),
                               "op2": world.jobs()["op-2"]["status"]})

    runner = FleetRunner(world.fleet, LaneLauncher(world, [True]), sleep=time.sleep, interval=0.05,
                         control=Control(), continuation=Pass())
    started = time.monotonic()
    summary = runner.run(once=False)
    assert summary["stopped"] is True and time.monotonic() - started < 30
    alive = [beat for beat in heartbeats if beat["conductor_alive"]]
    assert any(beat["op2"] == "accepted" and beat["admission"] == "open" and beat["active"] >= 1 for beat in alive), \
        "the second family was admitted and reaped while the conductor child was pending"
    assert any(beat["admission"] == "stopping" and beat["active"] == 1 for beat in alive), \
        "stop polling continued and the pending child stayed accounted"
    assert len(alive) >= 3 and max(durations) < 1.0, "no tick waited for the child"
    intent = only(world.intents(), origin_job=job_id, route=dc.CONDUCTOR)
    assert intent["state"] == dc.AWAITING_OWNER and intent["reason_code"] == "conductor_not_claimed"
    assert intent["launch"]["state"] == dc.LAUNCH_EXITED and intent["launch"]["exit_code"] == 0
    assert port.active() == [] and len(list((tmp_path / "rt-a" / "continuation" / "launches").iterdir())) == 1
