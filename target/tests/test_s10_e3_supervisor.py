"""S10 E3: the `zeus-supervisor` process (R-e3): `composition.supervisor`, `entry.processes.supervisor` and the shim.

MemoryStore, a scripted `run_process`, a fake bus, executor and observer; no Docker, Redis, provider or thread is started. The process runs
Docker, so there is no compare family: these tests are the evidence."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock

from codex_harness.composition import ServiceHandle, supervisor
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.application.catalog_observer import CatalogCheckingObserver
from codex_harness.storage.adapters.memory_store import MemoryStore

TARGET_SRC = Path(__file__).resolve().parent.parent / "src"
SHIM = TARGET_SRC / "codex_harness" / "supervisor.py"
UP = ["docker", "compose", "up", "-d", "--wait", "postgres", "redis"]
PS = ["docker", "compose", "ps", "--all", "--format", "json"]
WAKE = ["docker", "compose", "--profile", "agents", "--profile", "workers", "up", "-d", "--no-build"]


class Observer:
    def __init__(self):
        self.calls, self.store = [], None

    def emit(self, event_type, outcome, **fields):
        self.calls.append((event_type, outcome, fields))

    def audit_system(self, *args, **kwargs):
        return None

    def types(self):
        return [call[0] for call in self.calls]

    def one(self, event_type):
        [match] = [call for call in self.calls if call[0] == event_type]
        return match


class Client:
    def __init__(self, depth):
        self.depth = depth

    def exists(self, key):
        return False

    def xinfo_groups(self, key):
        raise AssertionError("no consumer group in this fake")

    def xlen(self, key):
        return self.depth.get(key.removeprefix("stream:"), 0)


class Bus:
    def __init__(self, depth=None):
        self.client, self.compacted = Client(depth or {}), []

    def stream(self, agent):
        return "stream:" + agent

    def compact(self, agent, retain):
        self.compacted.append((agent, retain))
        return 0


class Thread:
    started: list = []

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args, self.daemon = target, args, daemon

    def start(self):
        Thread.started.append(self)

    def is_alive(self):
        return False

    def join(self):
        return None


class Host:
    """The scripted `run_process`: `ps` answers the rows, every other argv succeeds; each call is recorded."""

    def __init__(self, rows, fail=None):
        self.rows, self.fail, self.calls = rows, fail, []

    def __call__(self, argv, cwd=None, timeout=None, env=None, **_):
        self.calls.append((argv, env))
        if self.fail is not None and argv == self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        if argv == PS:
            return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(r) for r in self.rows) + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def argvs(self):
        return [argv for argv, _ in self.calls]


def up(service, image="zeus:bootstrap"):
    return {"Service": service, "State": "running", "Image": image}


@pytest.fixture
def world(tmp_path, monkeypatch):
    Thread.started = []
    service = ServiceHandle(MemoryStore(), None)
    box = SimpleNamespace(service=service, observer=Observer(), bus=Bus(), host=Host([up("postgres"), up("redis")]),
                          root=tmp_path / "repo", runtime=tmp_path / "runtime", health=None)
    box.root.mkdir()
    monkeypatch.setattr(supervisor, "repository_root", lambda: box.root)
    monkeypatch.setattr(supervisor, "runtime_dir", lambda: box.runtime)
    monkeypatch.setattr(supervisor, "compose_environment", lambda: {"COMPOSE": "env"})
    monkeypatch.setattr(supervisor, "run_process", lambda *a, **k: box.host(*a, **k))
    monkeypatch.setattr(supervisor, "build", lambda: service)
    monkeypatch.setattr(supervisor, "build_observer", lambda store, component: box.observer)
    monkeypatch.setattr(supervisor.cli_bus, "bus", lambda: box.bus)
    monkeypatch.setattr(supervisor.cli_bus, "flusher",
                        lambda handle: SimpleNamespace(flush=lambda bus, audit=None: None))
    monkeypatch.setattr(supervisor, "threading", SimpleNamespace(Thread=Thread))
    monkeypatch.setattr(supervisor, "source_thread", None)
    monkeypatch.setattr(supervisor, "release_thread", None)
    monkeypatch.setattr(supervisor, "maintenance_thread", None)
    monkeypatch.setattr(supervisor, "last_maintenance", time.monotonic())  # not due: the maintenance path has its own test
    return box


def put_task(world, task_id, agent, status, lease_in=0):
    lease = (datetime.now(timezone.utc) + timedelta(seconds=lease_in)).isoformat()
    with world.service.store.transaction() as tx:
        tx.put("tasks", task_id, {"id": task_id, "agent": agent, "status": status, "lease_until": lease})


def test_postgres_or_redis_not_running_brings_both_up(world):
    world.host.rows = [up("postgres"), {"Service": "redis", "State": "exited"}]
    supervisor.tick(observer=world.observer)
    assert world.host.argvs()[:2] == [PS, UP]
    assert world.host.calls[1][1] == {"COMPOSE": "env"}


def test_compose_ps_failure_raises_before_anything_else(world):
    world.host.fail = PS
    with pytest.raises(RuntimeError, match="boom"):
        supervisor.tick(observer=world.observer)
    assert world.host.argvs() == [PS] and not world.observer.calls


def test_a_stopped_worker_with_a_stream_backlog_is_woken_with_the_agent_image(world):
    world.bus = Bus({"worker:implementation": 2})
    supervisor.tick(observer=world.observer)
    argv, env = world.host.calls[-1]
    assert argv == [*WAKE, "implementation-worker"]
    assert env["HARNESS_AGENT_IMAGE"] == "zeus:bootstrap" and env["ZEUS_AGENT_IMAGE"] == "zeus:bootstrap" and env["COMPOSE"] == "env"
    _, outcome, fields = world.observer.one("operations.worker_wake_requested")
    assert outcome == "started" and fields["attributes"] == {
        "agent": "worker:implementation", "service": "implementation-worker", "image": "zeus:bootstrap",
        "stream_backlog": 2, "durable_ready": False}
    assert "operations.worker_replace_requested" not in world.observer.types()


def test_a_durable_ready_task_wakes_a_stopped_worker_without_a_stream_backlog(world):
    put_task(world, "t1", "worker:github", "queued")
    supervisor.tick(observer=world.observer)
    assert world.host.argvs()[-1] == [*WAKE, "github-worker"]
    assert world.observer.one("operations.worker_wake_requested")[2]["attributes"]["durable_ready"] is True


def test_a_running_worker_on_an_old_image_that_is_not_busy_is_replaced(world):
    world.host.rows += [up("implementation-worker", "zeus:old")]
    supervisor.tick(observer=world.observer)
    assert world.host.argvs()[-1] == [*WAKE, "implementation-worker"]
    _, outcome, fields = world.observer.one("operations.worker_replace_requested")
    assert outcome == "started" and fields["attributes"] == {
        "agent": "worker:implementation", "service": "implementation-worker", "image_from": "zeus:old",
        "image_to": "zeus:bootstrap"}
    assert "operations.worker_wake_requested" not in world.observer.types()
    # a replacement ends the pass (M7 `break`): no later agent is observed, and the tick event still closes it
    assert world.observer.types()[-1] == "operations.supervisor_tick"
    assert not [c for c in world.observer.calls if c[2].get("attributes", {}).get("agent") == "worker:geeknews"]


def test_a_busy_worker_is_not_replaced(world):
    world.host.rows += [up("implementation-worker", "zeus:old")]
    put_task(world, "t1", "worker:implementation", "running", lease_in=600)
    supervisor.tick(observer=world.observer)
    assert WAKE not in [argv[:-1] for argv in world.host.argvs()]
    assert "operations.worker_replace_requested" not in world.observer.types()
    seen = [c for c in world.observer.calls if c[0] == "operations.backlog_observed"
            and c[2]["attributes"]["agent"] == "worker:implementation"]
    assert seen[0][2]["attributes"]["busy"] is True


def test_the_active_release_image_is_the_desired_image(world):
    with world.service.store.transaction() as tx:
        tx.put("deployment", "active", {"id": "active", "release_id": "r1"})
        tx.put("images", "r1", {"id": "r1", "image": "zeus:r1"})
    world.host.rows += [up("implementation-worker", "zeus:r1")]
    supervisor.tick(observer=world.observer)
    assert world.observer.one("operations.supervisor_tick")[2]["attributes"]["desired_image"] == "zeus:r1"
    assert "operations.worker_replace_requested" not in world.observer.types()


def test_the_tick_event_carries_the_backlog_total_and_the_running_services(world):
    world.bus = Bus({"conductor": 3, "worker:github": 4})
    world.host.rows += [up("conductor")]
    supervisor.tick(observer=world.observer)
    _, outcome, fields = world.observer.one("operations.supervisor_tick")
    assert outcome == "observed" and fields["severity"] == "debug"
    assert fields["attributes"] == {"services_running": 3, "backlog_total": 7, "desired_image": "zeus:bootstrap"}


def test_the_store_reaches_the_wrapped_observer(world):
    inner = Observer()
    supervisor.tick(observer=CatalogCheckingObserver(inner))
    assert inner.store is world.service.store


def test_the_source_runner_thread_starts_once_and_the_release_thread_only_on_request(world, monkeypatch):
    monkeypatch.setattr(supervisor, "build_executor", lambda service: "executor")
    supervisor.tick(observer=world.observer)
    [source] = Thread.started
    assert source.target.__name__ == "run_one" and source.daemon is True
    assert (world.runtime / "source-executions").is_dir()
    Thread.started.clear()
    supervisor.tick(releases=True, observer=world.observer)
    assert [t.target for t in Thread.started if t.target is supervisor.deploy_queued] == [supervisor.deploy_queued]
    assert Thread.started[-1].args == (world.service, "executor")


def test_a_due_maintenance_pass_records_the_monitor_health_and_starts_the_views_thread(world, monkeypatch):
    monkeypatch.setattr(supervisor, "last_maintenance", 0)
    executor = SimpleNamespace(name="executor")
    monkeypatch.setattr(supervisor, "build_executor", lambda service: executor)
    monkeypatch.setattr(supervisor.cli_executor, "release_runner", lambda service, built: SimpleNamespace(
        monitor=lambda: {"status": "healthy"}))
    supervisor.tick(observer=world.observer)
    with world.service.store.transaction() as tx:
        latest = tx.get("health", "latest")
    assert latest["status"] == "healthy" and latest["id"] == "latest"
    [views] = [t for t in Thread.started if t.target is supervisor.maintain_views]
    assert views.args == (world.service, executor, world.bus, world.root, world.runtime)
    assert supervisor.last_maintenance > 0


# ---- deploy_queued ---------------------------------------------------------------------------------------------------

class Queue:
    def __init__(self, claim, stale=False):
        self.claim_row, self.stale, self.finished, self.beats = claim, stale, [], []

    def claim(self):
        return self.claim_row

    def heartbeat(self, claim):
        self.beats.append(claim)

    def finish(self, claim, result):
        if self.stale:
            raise ContractError("not the owner")
        self.finished.append((claim, result))


class Runner:
    def __init__(self, outcome):
        self.outcome, self.fence = outcome, None

    def run(self, release_id):
        self.fence()
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def deploy(monkeypatch, queue, runner, capsys):
    monkeypatch.setattr(supervisor.cli, "release_queue", lambda service: queue)
    monkeypatch.setattr(supervisor.cli_executor, "release_runner", lambda service, executor: runner)
    supervisor.deploy_queued(SimpleNamespace(), SimpleNamespace())
    out = capsys.readouterr().out
    return json.loads(out) if out else None


def test_deploy_queued_finishes_the_claim_with_the_runner_result_and_fences_with_the_heartbeat(monkeypatch, capsys):
    claim = {"id": "rel-1"}
    queue, runner = Queue(claim), Runner({"status": "passed"})
    assert deploy(monkeypatch, queue, runner, capsys) == {"release": "rel-1", "result": {"status": "passed"}}
    assert queue.finished == [(claim, {"status": "passed"})] and queue.beats == [claim]


def test_deploy_queued_without_a_claim_does_nothing(monkeypatch, capsys):
    assert deploy(monkeypatch, Queue(None), Runner({}), capsys) is None


def test_a_contract_error_is_blocked_and_any_other_error_is_retry(monkeypatch, capsys):
    queue = Queue({"id": "rel-1"})
    assert deploy(monkeypatch, queue, Runner(ContractError("no")), capsys)["result"] == {"status": "blocked", "reason": "no"}
    assert deploy(monkeypatch, queue, Runner(OSError("disk")), capsys)["result"] == {"status": "retry", "reason": "disk"}
    assert [result["status"] for _, result in queue.finished] == ["blocked", "retry"]


def test_a_stale_finish_reports_stale_and_records_nothing(monkeypatch, capsys):
    queue = Queue({"id": "rel-1"}, stale=True)
    out = deploy(monkeypatch, queue, Runner({"status": "passed"}), capsys)
    assert out["result"] == {"status": "stale", "reason": "release controller ownership changed"} and not queue.finished


# ---- run -------------------------------------------------------------------------------------------------------------

def arguments(**kw):
    return SimpleNamespace(**{"once": True, "research": False, "releases": False, "repository": None, **kw})


def test_a_held_lock_prints_supervisor_already_running(world, capsys):
    world.runtime.mkdir()
    with FileLock(str(world.runtime / "supervisor.lock")):
        supervisor.run(arguments())
    assert json.loads(capsys.readouterr().out) == {"status": "supervisor_already_running"}
    assert not world.observer.calls


def test_once_with_a_failing_tick_emits_the_error_and_exits_1(world, monkeypatch, capsys):
    def failing(research, releases, observer):
        raise RuntimeError("compose down")
    monkeypatch.setattr(supervisor, "tick", failing)
    with pytest.raises(SystemExit) as raised:
        supervisor.run(arguments())
    assert raised.value.code == 1
    assert world.observer.types() == ["general.process_started", "operations.supervisor_error"]
    _, outcome, fields = world.observer.calls[1]
    assert outcome == "failed" and fields["severity"] == "error" and fields["reason_code"] == "RuntimeError"
    assert json.loads(capsys.readouterr().out)["supervisor_error"] == "compose down"


def test_once_with_a_passing_tick_returns_and_passes_the_flags(world, monkeypatch):
    seen = []
    monkeypatch.setattr(supervisor, "tick", lambda research, releases, observer: seen.append((research, releases, observer)))
    supervisor.run(arguments(research=True, releases=True))
    assert seen == [(True, True, world.observer)]
    assert world.observer.one("general.process_started")[2]["attributes"]["mode"] == "supervisor"


def test_run_selects_the_requested_repository(world, monkeypatch, tmp_path):
    chosen = []
    monkeypatch.setattr(supervisor, "select_repository", chosen.append)
    monkeypatch.setattr(supervisor, "tick", lambda *a: None)
    supervisor.run(arguments(repository=tmp_path))
    assert chosen == [tmp_path]


# ---- the shim and the entry --------------------------------------------------------------------------------------------

def test_the_shim_imports_only_entry_and_delegates():
    tree = ast.parse(SHIM.read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imported == ["codex_harness.entry.processes.supervisor"]
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import)]
    assert not [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))]


def test_the_entry_parses_the_m7_arguments_and_delegates_to_run(monkeypatch, tmp_path):
    from codex_harness.entry.processes import supervisor as entry
    seen = []
    monkeypatch.setattr(supervisor, "run", seen.append)
    monkeypatch.setattr(sys, "argv", ["zeus-supervisor", "--once", "--research", "--releases", "--repository", str(tmp_path)])
    entry.main()
    [args] = seen
    assert (args.once, args.research, args.releases, args.repository) == (True, True, True, tmp_path)


def test_python_m_codex_harness_supervisor_help_exits_zero(tmp_path):
    environment = {"PYTHONPATH": str(TARGET_SRC), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    done = subprocess.run([sys.executable, "-m", "codex_harness.supervisor", "--help"], cwd=tmp_path, env=environment,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "--once" in done.stdout and "--repository" in done.stdout
