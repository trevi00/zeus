"""INV-CONTINUATION-001 ownership matrix with REAL processes (SPEC "Two-strike ownership design").

Every guardian here is the real `python -m codex_harness.adapters.continuation_process` spawned by
the real `ConductorProcesses` (or the real `guard` in-process), owning a real `ProcessTree`. The
command it supervises is a LABELLED controlled sleeping Python child (sometimes with a grandchild),
never the conduct command and never a model: these tests prove process ownership, the cleanup
proof, the fence and the Fleet unit settlement, not a conductor decision. Faults are LABELLED where
injected (a blocked or failing control store, a terminate that answers False or raises, an unknown
tree, a proof or debt write that fails, a lost spawn response, a killed guardian). Stores are
MemoryStores, not PostgreSQL. POSIX process-group behaviour only; the Windows job-object check is a
separate test that runs only on Windows.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_continuation import LaneLauncher, World, accepted_item, only

import codex_harness
from codex_harness.adapters import continuation_process as cp
from codex_harness.adapters import process_tree
from codex_harness.adapters.continuation_process import (
    CLAIM_FENCED,
    ENTRY_ARGV,
    EXIT_DEBT_UNWRITTEN,
    EXIT_FENCED,
    EXIT_UNRESOLVED,
    ConductorProcesses,
    guard,
    launch_directory,
    observe,
    spawn_guardian,
)
from codex_harness.adapters.process_tree import ProcessTree
from codex_harness.application.continuation import Continuation
from codex_harness.application.fleet import Fleet, FleetRunner
from codex_harness.domain import continuation as dc

PACKAGE_ROOT = Path(codex_harness.__file__).resolve().parents[1]
HOST = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "fixture/image:1",
        "HARNESS_DATABASE_URL": "postgresql://fixture@127.0.0.1:1/fixture"}
POSIX = pytest.mark.skipif(os.name == "nt", reason="POSIX process-group containment only")


def environment(lane=None, host=None) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + ((os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    return env


def sleeper(seconds: float, marker: str | None = None):
    """The LABELLED controlled child: sleeps, optionally appends one line to a marker file."""
    code = f"import time; time.sleep({seconds})"
    if marker is not None:
        code = f"open({marker!r}, 'a').write('ran\\n'); " + code
    return lambda lane, manifest: [sys.executable, "-c", code]


def family(marker, seconds=60):
    """The LABELLED controlled child with a grandchild: records both pids, then sleeps."""
    code = ("import os, subprocess, sys, time\n"
            f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({seconds})'])\n"
            f"open({str(marker)!r}, 'w').write('%d %d' % (os.getpid(), child.pid))\n"
            f"time.sleep({seconds})\n")
    return lambda lane, manifest: [sys.executable, "-c", code]


def processes(world, seconds=60.0, command=None, **kwargs):
    (world.tmp / "repo-a").mkdir(exist_ok=True)  # the guardian's working directory, as a real lane has
    return ConductorProcesses(world.fleet.registered()["config"], HOST, command=command or sleeper(0.6),
                              environment=environment, seconds=seconds, **kwargs)


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def alive(pid: int) -> bool:
    """Signal zero, with a reaped-later zombie counted as gone (no container init may reap it)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def pids(marker: Path) -> list[int]:
    assert wait_for(lambda: marker.exists() and len(marker.read_text().split()) == 2)
    return [int(value) for value in marker.read_text().split()]


def kill_group(pid: int) -> None:
    """Test-owned teardown of a tree this test deliberately left behind; never production behaviour."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def prepare(directory: Path, launch: str, token: str = "tok") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "launch.json").write_text(json.dumps({"schema": cp.GUARDIAN_SCHEMA, "launch": launch,
                                                       "token": token, "seconds": 1}), encoding="utf-8")
    return directory


def read(directory: Path, name: str):
    path = directory / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


JOB = {"id": "op-1", "manifest": {"id": "op-1"}}


# ---- the guardian owns the tree and proves parent AND tree cleanup -------------------------------
def test_a_guardian_supervises_its_tree_without_blocking_the_controller_and_proves_cleanup(tmp_path):
    world = World(tmp_path)
    port = processes(world)
    launch = "1" * 64
    started = time.monotonic()
    assert port.start("a", JOB, launch, "tok-1")["pid"] > 0
    assert time.monotonic() - started < 2.0, "start returns once the guardian is spawned"
    assert port.poll("a", launch) == {"state": dc.LAUNCH_RUNNING, "owned": True, "exit_code": None}
    assert port.active() == [launch]
    assert wait_for(lambda: port.active() == [])
    settled = port.poll("a", launch)
    directory = launch_directory(tmp_path / "rt-a", launch)
    assert settled["state"] == dc.LAUNCH_EXITED and settled["exit_code"] == 0 and settled["cleanup_confirmed"] is True
    proof = settled["proof"]
    assert proof == read(directory, "cleanup.json") and proof["launch"] == launch and proof["token"] == "tok-1"
    assert proof["parent"]["confirmed"] is True and proof["tree"]["confirmed"] is True and proof["confirmed"] is True
    assert proof["tree"]["method"] == ("job_object" if os.name == "nt" else "process_group")
    debt = read(directory, "debt.json")
    assert debt["state"] == "running" and debt["token"] == "tok-1" and debt["boundary"]["owned_from_spawn"] is True
    assert (directory / "claim").read_text(encoding="utf-8") == "child" and not (directory / "exit.json").exists()
    assert port.start("a", JOB, launch, "tok-1") == {"pid": None, "cached": True}, "one identity, one spawn"


@POSIX
def test_the_guardian_lives_outside_the_controller_session():
    guardian = spawn_guardian([sys.executable, "-c", "import time; time.sleep(5)"], env=environment())
    try:
        assert os.getsid(guardian.pid) == guardian.pid != os.getsid(0), "not in a controller kill boundary"
    finally:
        guardian.kill()
        guardian.wait(timeout=30)


def test_a_restarted_controller_observes_a_guardian_it_did_not_spawn_and_never_signals_it(tmp_path):
    world = World(tmp_path)
    first = processes(world, command=sleeper(1.5))
    launch = "2" * 64
    first.start("a", JOB, launch, "tok-2")
    assert wait_for(lambda: (launch_directory(tmp_path / "rt-a", launch) / "claim").exists())
    restarted = processes(world)  # the controller process was recreated: no handle, same evidence
    assert restarted.poll("a", launch) == {"state": dc.LAUNCH_RUNNING, "owned": False, "exit_code": None}
    assert restarted.active() == [], "a guardian spawned elsewhere is unresolved, not this process's work"
    assert wait_for(lambda: restarted.poll("a", launch)["state"] == dc.LAUNCH_EXITED)
    assert restarted.poll("a", launch)["cleanup_confirmed"] is True
    assert wait_for(lambda: first.poll("a", launch)["state"] == dc.LAUNCH_EXITED)
    assert wait_for(lambda: first.active() == []), "the spawning controller reaps its guardian after the proof"


# ---- fence, one-shot spawn, lost response ---------------------------------------------------------
def test_a_launch_that_never_entered_is_fenced_and_a_late_guardian_executes_zero_conduct(tmp_path):
    launch = "3" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    fenced = observe(directory)
    assert fenced == {"state": dc.LAUNCH_ABSENT, "owned": False, "exit_code": None,
                      "proof": {"kind": "fenced", "launch": launch, "claim": "fenced"}}
    assert (directory / "claim").read_text(encoding="utf-8") == CLAIM_FENCED
    marker = tmp_path / "late.txt"
    late = subprocess.run([*ENTRY_ARGV, "--launch", str(directory), "--seconds", "5", "--", sys.executable, "-c",
                           f"open({str(marker)!r}, 'w').write('ran')"], env=environment(), timeout=60)
    assert late.returncode == EXIT_FENCED and not marker.exists(), "a delayed, fenced guardian runs nothing"
    assert observe(directory)["state"] == dc.LAUNCH_ABSENT


def test_the_guardian_never_loads_the_database_driver(tmp_path):
    """LABELLED: a `psycopg` that raises on import sits first on the guardian's path; supervision,
    cleanup and the proof still complete, so none of them depends on the store."""
    poison = tmp_path / "poison" / "psycopg"
    poison.mkdir(parents=True)
    (poison / "__init__.py").write_text("raise RuntimeError('the guardian imported the database driver')\n",
                                        encoding="utf-8")
    env = environment()
    env["PYTHONPATH"] = str(tmp_path / "poison") + os.pathsep + env["PYTHONPATH"]
    launch = "d" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    done = subprocess.run([*ENTRY_ARGV, "--launch", str(directory), "--seconds", "30", "--", sys.executable, "-c",
                           "pass"], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert observe(directory)["cleanup_confirmed"] is True


def test_two_guardians_of_one_launch_run_the_command_once(tmp_path):
    launch = "4" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    marker = tmp_path / "ran.txt"
    argv = [*ENTRY_ARGV, "--launch", str(directory), "--seconds", "30", "--", sys.executable, "-c",
            f"import time; open({str(marker)!r}, 'a').write('ran\\n'); time.sleep(1)"]
    children = [subprocess.Popen(argv, env=environment()) for _ in range(2)]
    codes = sorted(child.wait(timeout=60) for child in children)
    assert codes == [0, EXIT_FENCED] and marker.read_text(encoding="utf-8") == "ran\n"
    assert observe(directory)["cleanup_confirmed"] is True


def test_a_failed_spawn_is_fenced_as_absent_and_the_identity_is_never_spawned_again(tmp_path):
    world = World(tmp_path)
    attempts = []

    def broken(argv, **kwargs):
        attempts.append(argv)
        raise OSError("guardian spawn failed (injected)")
    port = processes(world, spawn=broken)
    launch = "5" * 64
    with pytest.raises(OSError):
        port.start("a", JOB, launch, "tok-5")
    assert port.active() == [] and port.poll("a", launch)["state"] == dc.LAUNCH_ABSENT
    assert port.start("a", JOB, launch, "tok-5") == {"pid": None, "cached": True} and len(attempts) == 1


def test_a_lost_spawn_response_is_reconciled_from_evidence_and_never_respawned(tmp_path):
    world = World(tmp_path)
    marker = tmp_path / "ran.txt"
    spawned = []

    def lost(argv, **kwargs):  # LABELLED fault: the guardian exists, the response is lost
        spawned.append(spawn_guardian(argv, **kwargs))
        raise TimeoutError("spawn response lost after the guardian started (injected)")
    port = processes(world, command=sleeper(3.0, str(marker)), spawn=lost)
    controller = world.build(conductor=port)
    world.register()
    job_id = accepted_item(world)
    first = world.tick(controller=controller)
    intent = only(world.intents(), route=dc.CONDUCTOR)
    assert {"subject": intent["id"], "effect": "launch_unconfirmed", "route": dc.CONDUCTOR,
            "error_type": "TimeoutError"} in first["actions"]
    assert intent["state"] == dc.DISPATCHED and world.fleet.held_units() == [intent["launch"]["id"]]
    restarted = world.build(conductor=processes(world, command=sleeper(3.0, str(marker)), spawn=lost))
    # This row is the ENTERED branch (a reconciler that wins the lock first fences the launch
    # instead, and that delayed guardian runs nothing: the fence test above).
    directory = launch_directory(tmp_path / "rt-a", intent["launch"]["id"])
    assert wait_for(lambda: (directory / "claim").exists())
    running = world.tick(controller=restarted)
    assert {"subject": intent["id"], "reason_code": "conductor_owner_unknown", "next_owner": "conductor"} \
        in running["skipped"], "alive under a guardian the restarted controller did not spawn: it waits"
    assert wait_for(lambda: spawned[0].poll() is not None)
    world.tick(controller=restarted)
    settled = only(world.intents(), route=dc.CONDUCTOR)
    assert settled["launch"]["id"] == intent["launch"]["id"] and settled["launch"]["state"] == dc.LAUNCH_EXITED
    assert marker.read_text(encoding="utf-8") == "ran\n" and len(spawned) == 1, "one guardian, one command"
    assert world.fleet.units()[0]["settlement"]["kind"] == "cleanup"
    assert job_id


# ---- deadline cleanup needs no database -----------------------------------------------------------
class Blocked:
    """LABELLED fault: every control-store transaction blocks until released (a hung PostgreSQL)."""

    def __init__(self, inner):
        self.inner, self.gate, self.entered = inner, threading.Event(), threading.Event()

    @contextmanager
    def transaction(self):
        self.entered.set()
        self.gate.wait(timeout=120)
        with self.inner.transaction() as tx:
            yield tx


class Down:
    """LABELLED fault: the control store refuses every transaction (PostgreSQL unreachable)."""

    @contextmanager
    def transaction(self):
        raise ConnectionError("control store unreachable (injected)")
        yield  # pragma: no cover


@POSIX
def test_a_real_sleeping_tree_is_deadline_cleaned_while_the_store_is_down_and_while_it_blocks(tmp_path):
    world = World(tmp_path)
    marker = tmp_path / "pids.txt"
    port = processes(world, seconds=1.5, command=family(marker))
    world.register()
    job_id = accepted_item(world)
    world.tick(controller=world.build(conductor=port))
    intent = only(world.intents(), route=dc.CONDUCTOR)
    child, grandchild = pids(marker)
    directory = launch_directory(tmp_path / "rt-a", intent["launch"]["id"])
    blocked = Blocked(world.control)
    held = Continuation(blocked, fleet=Fleet(blocked), lanes=world.lanes, conductor=port)
    stuck = threading.Thread(target=held.drain, args=("policy-1",), daemon=True)
    stuck.start()
    assert blocked.entered.wait(timeout=10), "the controller is inside a blocked store call"
    with pytest.raises(ConnectionError):
        Continuation(Down(), fleet=Fleet(Down()), lanes=world.lanes, conductor=port).drain("policy-1")
    # Nobody polls; the store is blocked and down: the guardian alone enforces the deadline.
    assert wait_for(lambda: (directory / "cleanup.json").exists(), timeout=60)
    proof = read(directory, "cleanup.json")
    assert proof["timed_out"] is True and proof["parent"]["confirmed"] and proof["tree"]["confirmed"]
    assert not alive(child) and not alive(grandchild), "parent AND grandchild gone"
    assert only(world.intents(), route=dc.CONDUCTOR)["state"] == dc.DISPATCHED and world.fleet.held_units(), \
        "cleanup proof alone releases nothing: the unit waits for the Fleet settlement"
    assert wait_for(lambda: port.active() == [])
    blocked.gate.set()
    stuck.join(timeout=60)
    settled = only(world.intents(), route=dc.CONDUCTOR)
    assert settled["state"] == dc.AWAITING_OWNER and settled["reason_code"] == "conductor_not_claimed"
    assert settled["launch"]["state"] == dc.LAUNCH_TIMEOUT and world.fleet.held_units() == []
    assert job_id


@POSIX
def test_controller_exit_leaves_the_guardian_owning_the_tree_until_its_proof(tmp_path):
    world = World(tmp_path)
    (tmp_path / "repo-a").mkdir(exist_ok=True)
    marker = tmp_path / "pids.txt"
    launch = "7" * 64
    command = family(marker)(None, None)
    script = ("import json, os, sys\n"
              "from codex_harness.adapters.continuation_process import ConductorProcesses\n"
              "config, command = json.loads(sys.argv[1]), json.loads(sys.argv[2])\n"
              "port = ConductorProcesses(config, {}, command=lambda lane, manifest: command,\n"
              "                          environment=lambda lane, host: dict(os.environ), seconds=2.0)\n"
              "print(port.start('a', {'id': 'op-1', 'manifest': {'id': 'op-1'}}, sys.argv[3], 'tok-7')['pid'],"
              " flush=True)\n"
              "os._exit(0)\n")
    controller = subprocess.run([sys.executable, "-c", script, json.dumps(world.fleet.registered()["config"]),
                                 json.dumps(command), launch], env=environment(), capture_output=True, text=True,
                                timeout=60)
    assert controller.returncode == 0, controller.stderr
    guardian = int(controller.stdout.strip())
    child, grandchild = pids(marker)
    assert alive(guardian) and alive(child), "the controller exited; its guardian and tree did not"
    directory = launch_directory(tmp_path / "rt-a", launch)
    assert wait_for(lambda: (directory / "cleanup.json").exists(), timeout=60)
    assert not alive(child) and not alive(grandchild)
    observed = processes(world).poll("a", launch)
    assert observed["state"] == dc.LAUNCH_TIMEOUT and observed["cleanup_confirmed"] is True


# ---- guardian death: unknown debt, never a pid kill, never a relaunch -----------------------------
@POSIX
def test_a_killed_guardian_leaves_unknown_debt_that_holds_its_slot_and_is_never_rerun(tmp_path):
    world = World(tmp_path, max_parallel=1)
    marker = tmp_path / "pids.txt"
    port = processes(world, command=family(marker))
    controller = world.build(conductor=port)
    world.register()
    job_id = accepted_item(world)
    world.tick(controller=controller)
    intent = only(world.intents(), route=dc.CONDUCTOR)
    child, grandchild = pids(marker)
    guardian = port.children[intent["launch"]["id"]]["guardian"]
    try:
        guardian.kill()  # LABELLED fault: the guardian is killed outright
        guardian.wait(timeout=30)
        # The conductor DID decide before its guardian died (labelled): success + unknown cleanup.
        with world.lane.store.transaction() as tx:
            operation = tx.get("operations", job_id)
            lead = tx.get("decisions_pending", operation["decision_id"])
            tx.put("decisions_pending", "cond-x", {"id": "cond-x", "actor": "conductor", "phase": "review_conductor",
                                                   "status": "succeeded", "attempt": 1,
                                                   "result": {"accepted": True, "execution_ref": "sha256:" + "9" * 64},
                                                   "message": {"what": {"details": {"decision_id": lead["id"]}}}})
        world.enqueue("op-2", "docs/b.md")
        for _ in range(3):
            result = world.tick(controller=controller)
        held = only(world.intents(), route=dc.CONDUCTOR)
        assert held["state"] == dc.DISPATCHED and held["launch"]["state"] == "cleanup_unknown"
        assert held["hold"]["reason_code"] == "conductor_cleanup_unknown"
        assert {"subject": held["id"], "reason_code": "conductor_cleanup_unknown",
                "next_owner": "execution_recovery"} in result["skipped"]
        assert "no rerun" in dc.view(held)["next_action"]
        assert not [row for row in world.intents().values() if row["route"] == dc.DELIVERY], "not completed"
        assert world.fleet.held_units() == [held["launch"]["id"]]
        admitted = world.fleet.admit_one()
        assert admitted["job"] is None and admitted["blocked"] == {"op-2": "capacity"}, \
            "unknown debt fills the only slot: admission stops honestly"
        launches = list((tmp_path / "rt-a" / "continuation" / "launches").iterdir())
        assert len(launches) == 1, "no replacement launch"
        assert alive(child) and alive(grandchild), "nothing killed a pid recovered from a file"
        assert observe(launches[0])["state"] == dc.LAUNCH_UNKNOWN
    finally:
        kill_group(child)


# ---- terminate false / exception / parent exited but tree unknown ---------------------------------
@POSIX
@pytest.mark.parametrize("fault", ["false", "raises", "tree_unknown"])
def test_unconfirmed_cleanup_retains_handle_and_debt_and_writes_no_proof(tmp_path, monkeypatch, fault):
    launch = "8" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    trees, closed = [], []

    def spawn(argv, **kwargs):
        tree = ProcessTree.spawn(argv, **kwargs)
        trees.append(tree)
        tree.close = lambda: closed.append(True)
        if fault == "false":  # LABELLED: terminate answers unconfirmed and kills nothing
            tree.terminate = lambda reason, **k: {"confirmed": False, "parent": {"confirmed": False},
                                                  "tree": {"confirmed": False}}
        elif fault == "raises":  # LABELLED: terminate raises
            def terminate(reason, **k):
                raise OSError("terminate failed (injected)")
            tree.terminate = terminate
        return tree
    if fault == "tree_unknown":  # LABELLED: the group cannot be read; the parent really exits
        monkeypatch.setattr(process_tree, "_group_state", lambda group, deadline: None)
    seconds = 30.0 if fault == "tree_unknown" else 0.3
    command = [sys.executable, "-c", "import time; time.sleep(%s)" % (0.2 if fault == "tree_unknown" else 60)]
    try:
        code = guard(directory, command, seconds=seconds, spawn=spawn, sleep=lambda s: time.sleep(min(s, 0.05)))
        assert code == EXIT_UNRESOLVED
        assert not (directory / "cleanup.json").exists() and closed == [], "no proof, handle not closed"
        assert read(directory, "debt.json")["state"] == "cleanup_unknown"
        unresolved = read(directory, "unresolved.json")
        assert unresolved["reason_code"] == "cleanup_unconfirmed" and unresolved["attempts"] == cp.CLEANUP_ATTEMPTS
        if fault == "tree_unknown":
            assert unresolved["parent"]["confirmed"] is True and unresolved["tree"]["confirmed"] is False, \
                "parent exit alone is not cleanup"
        assert observe(directory) == {"state": dc.LAUNCH_UNKNOWN, "owned": False, "exit_code": None,
                                      "cleanup_confirmed": False, "reason_code": "cleanup_unresolved"}
    finally:
        for tree in trees:
            kill_group(tree.process.pid)
            tree.process.wait(timeout=30)


# ---- write-ahead debt and proof persistence ------------------------------------------------------
def test_an_unwritable_write_ahead_debt_starts_nothing_and_is_fenced(tmp_path, monkeypatch):
    launch = "9" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    marker = tmp_path / "ran.txt"
    real = cp._write_atomic

    def failing(path, document):  # LABELLED fault: the debt never reaches the disk
        if path.name == "debt.json":
            raise OSError("disk full (injected)")
        return real(path, document)
    monkeypatch.setattr(cp, "_write_atomic", failing)
    code = guard(directory, [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ran')"], seconds=5)
    assert code == EXIT_DEBT_UNWRITTEN and not marker.exists() and not (directory / "claim").exists()
    assert observe(directory)["state"] == dc.LAUNCH_ABSENT


def test_a_proof_that_cannot_be_persisted_after_cleanup_keeps_the_debt(tmp_path, monkeypatch):
    launch = "a" * 64
    directory = prepare(launch_directory(tmp_path / "rt-a", launch), launch)
    real = cp._write_atomic

    def failing(path, document):  # LABELLED fault: the proof write fails every time
        if path.name == "cleanup.json":
            raise OSError("proof write failed (injected)")
        return real(path, document)
    monkeypatch.setattr(cp, "_write_atomic", failing)
    code = guard(directory, [sys.executable, "-c", "pass"], seconds=5, sleep=lambda s: None)
    assert code == EXIT_UNRESOLVED and not (directory / "cleanup.json").exists()
    assert read(directory, "unresolved.json")["reason_code"] == "proof_unwritten"
    assert observe(directory)["state"] == dc.LAUNCH_UNKNOWN


# ---- stop requests: local cleanup without the database --------------------------------------------
@POSIX
@pytest.mark.parametrize("how", ["stop_file", "sigterm"])
def test_a_stop_request_ends_the_tree_locally_and_still_proves_it(tmp_path, how):
    world = World(tmp_path)
    marker = tmp_path / "pids.txt"
    port = processes(world, command=family(marker))
    launch = "b" * 64
    port.start("a", JOB, launch, "tok-b")
    child, grandchild = pids(marker)
    if how == "stop_file":
        assert port.request_stop() == [launch]
    else:
        os.kill(port.children[launch]["guardian"].pid, signal.SIGTERM)
    assert wait_for(lambda: port.active() == [])
    observed = port.poll("a", launch)
    assert observed["cleanup_confirmed"] is True and observed["proof"]["stopped"] is True
    assert not alive(child) and not alive(grandchild)


# ---- the Fleet runner: shared capacity, graceful stop, unrelated work -----------------------------
def test_fleet_admission_reaping_heartbeat_and_stop_continue_while_a_real_guardian_is_pending(tmp_path):
    """A real guardian and sleeping child are the pending conductor (LABELLED: it decides nothing).
    A second eligible family is admitted and reaped, heartbeats are written and a graceful stop is
    observed while it runs; the stop drains it, settles its truthful outcome and releases the unit."""
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
    assert summary["stopped"] is True and time.monotonic() - started < 60
    alive_beats = [beat for beat in heartbeats if beat["conductor_alive"]]
    assert any(beat["op2"] == "accepted" and beat["admission"] == "open" and beat["active"] >= 1
               for beat in alive_beats), "the second family was admitted and reaped while the conductor was pending"
    assert any(beat["admission"] == "stopping" and beat["active"] >= 1 for beat in alive_beats), \
        "stop polling continued and the pending guardian stayed accounted"
    assert len(alive_beats) >= 3 and max(durations) < 1.0, "no tick waited for the child"
    intent = only(world.intents(), origin_job=job_id, route=dc.CONDUCTOR)
    assert intent["state"] == dc.AWAITING_OWNER and intent["reason_code"] == "conductor_not_claimed"
    assert intent["launch"]["state"] == dc.LAUNCH_EXITED and intent["launch"]["exit_code"] == 0
    assert port.active() == [] and summary["units_held"] == [] and world.fleet.held_units() == []


@pytest.mark.skipif(os.name != "nt", reason="Windows job-object containment runs only on a Windows host")
def test_windows_guardian_owns_its_conduct_tree_in_a_job_object(tmp_path):  # pragma: no cover
    world = World(tmp_path)
    port = processes(world, command=sleeper(0.5))
    launch = "c" * 64
    started = port.start("a", JOB, launch, "tok-c")
    assert started["breakaway"] in {True, False}
    assert wait_for(lambda: port.active() == [])
    observed = port.poll("a", launch)
    assert observed["cleanup_confirmed"] is True and observed["proof"]["tree"]["method"] == "job_object"
    assert read(launch_directory(tmp_path / "rt-a", launch), "debt.json")["boundary"]["kind"] == "job_object"
