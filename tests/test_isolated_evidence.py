"""INV-ISOLATED-WORKER-001 replay backend. The Docker client and the attached capture are INJECTED
fakes (one labelled test runs the REAL capture over a real local child instead of a docker client);
no container, model or live service runs here, and nothing below is a real-container result."""
import json
import sys
import time

import pytest
from test_evidence_inspection import HOLDER, WATCHDOG_SECONDS, interrupt_first_wait
from test_isolated_worker import IMAGE, TOKEN, FakeDocker

from codex_harness.adapters import evidence_inspection as ei
from codex_harness.adapters import isolated_evidence as ie
from codex_harness.adapters import isolated_worker as iw


class Artifacts:
    def put(self, body, kind):
        return {"ref": "sha256:" + kind}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake, captured = FakeDocker(tmp_path), []
    monkeypatch.setattr(iw, "_docker", fake)
    monkeypatch.setenv(iw.TOKEN_NAME, TOKEN)

    def capture(argv, cwd, timeout, max_bytes, env):  # injected: the container "ran" and exited 0
        captured.append({"argv": argv, "env": env})
        fake.containers[argv[-1]]["status"] = "exited" if getattr(fake, "exit_on_capture", True) else "running"
        return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.1}
    monkeypatch.setattr(ie, "_capture", capture)
    workspace = tmp_path / "candidate"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "mod.py").write_text("X = 1\n")
    (workspace / ".git").write_text("gitdir: elsewhere\n")
    config = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE})
    return ie.DockerEvidenceInspector(Artifacts(), config, tmp_path / "replays"), fake, captured, workspace


def inspect(inspector, workspace, claims):
    snapshot = inspector.snapshot(workspace)
    return inspector.inspect(claims, workspace, {"task_id": "t"}, environment=snapshot["environment"],
                             interpreter=snapshot["identity"]["interpreter"]), snapshot


def test_unauthorized_argv_never_reaches_docker_or_the_host(setup):
    inspector, fake, captured, workspace = setup
    report, _ = inspect(inspector, workspace, [{"kind": "command", "argv": ["python", "-c", "print(1)"], "expected_exit": 0}])
    assert report["findings"][0]["state"] == "not_checked" and fake.calls == [] and captured == []


def test_authorized_replay_runs_in_fresh_credential_free_network_none_containers(setup):
    inspector, fake, captured, workspace = setup
    report, snapshot = inspect(inspector, workspace, ["python -m pytest -q"])
    finding = report["findings"][0]
    assert finding["state"] == "checked" and finding["replay_argv"][0] == iw.TRUSTED_PYTHON
    creates = [call for call in fake.calls if call["args"][0] == "create"]
    assert len(creates) == 2 and len({call["args"][call["args"].index("--name") + 1] for call in creates}) == 2
    for call in creates:
        args = call["args"]
        assert args[args.index("--network") + 1] == "none" and iw.TOKEN_NAME not in args and "--read-only" in args
        assert args[args.index("--entrypoint") + 1] == iw.TRUSTED_PYTHON and args[-3:] == ["-m", "pytest", "-q"]
        assert "PYTHONPATH=/workspace/src" in args
    assert all(iw.TOKEN_NAME not in call["env"] for call in fake.calls) and all(iw.TOKEN_NAME not in c["env"] for c in captured)
    assert TOKEN not in json.dumps(fake.calls) + json.dumps(report)
    assert report["context"]["python"] == "container:" + IMAGE and report["context"]["interpreter"] == iw.TRUSTED_PYTHON
    assert list(fake.containers) == ["f" * 64] and not any(inspector.root.glob("*/workspace"))  # own containers, copies removed
    assert [run["container"]["network"] for run in finding["runs"]] == ["none", "none"]
    # Normal replay: each run keeps its durable record, with the observed output written BEFORE removal.
    records = iw.run_records(inspector.root)
    assert len(records) == 2 and iw.unresolved_runs(inspector.root) == []
    for saved in records:
        assert [step["state"] for step in saved["lifecycle"]] == ["prepared", "created", "start_requested", "stop_confirmed",
                                                                  "evidence_retained", "removed"]
        assert saved["role"] == "verifier" and saved["label"] == iw.LABEL + "=" + saved["run_id"]
        assert saved["container_name"] == "zeus-verifier-" + saved["run_id"] and iw.CONTAINER_ID.fullmatch(saved["container"])
        assert saved["lifecycle"][2]["recovery"]["container"] == saved["container"]  # exact id durable before start
        assert saved["result"]["returncode"] == 0 and saved["result"]["container"]["stop"]["confirmed"]
    order = [call["args"][0] for call in fake.calls]
    assert order.index("rm") > order.index("create")


def interrupting(fake, seen):
    def capture(argv, cwd, timeout, max_bytes, env):  # INJECTED cancellation right after a (fake) docker start
        fake.containers[argv[-1]]["status"] = "running"
        seen.append({"id": argv[-1], "records": iw.run_records(fake.root)})
        raise KeyboardInterrupt
    return capture


def test_injected_interruption_after_start_stops_records_and_removes(setup, monkeypatch):
    inspector, fake, _, workspace = setup
    fake.root, seen = inspector.root, []
    monkeypatch.setattr(ie, "_capture", interrupting(fake, seen))
    with pytest.raises(KeyboardInterrupt):
        inspect(inspector, workspace, ["python -m pytest -q"])
    # Durable owner existed before the start, naming the exact id that was then started.
    assert seen[0]["records"][0]["state"] == "start_requested" and seen[0]["records"][0]["container"] == seen[0]["id"]
    saved = iw.run_records(inspector.root)
    assert len(saved) == 1 and saved[0]["state"] == "removed" and saved[0]["result"]["interrupted"] == "KeyboardInterrupt"
    assert [c["args"] for c in fake.calls if c["args"][0] == "kill"] == [["kill", seen[0]["id"]]]
    assert list(fake.containers) == ["f" * 64] and iw.unresolved_runs(inspector.root) == []


def test_injected_interruption_with_unconfirmed_stop_leaves_a_durable_recovery_record(setup, monkeypatch):
    inspector, fake, _, workspace = setup
    fake.root, seen = inspector.root, []
    fake.kill_works = False  # injected fault: kill changes nothing, the container stays running
    inspector.isolation["limits"] = {**inspector.isolation["limits"], "cleanup_seconds": 1}
    monkeypatch.setattr(ie, "_capture", interrupting(fake, seen))
    with pytest.raises(KeyboardInterrupt):
        inspect(inspector, workspace, ["python -m pytest -q"])
    saved = iw.run_records(inspector.root)[0]
    assert saved["state"] == "stop_unconfirmed" and saved["lifecycle"][-1]["recovery"] == {
        "container": seen[0]["id"], "name": saved["container_name"], "record": saved["record"]}
    assert seen[0]["id"] in fake.containers and not any(c["args"][0] == "rm" for c in fake.calls)
    assert [row["run_id"] for row in iw.unresolved_runs(inspector.root, str(workspace.resolve()))] == [saved["run_id"]]
    # Restart visibility: the next replay is refused by name and creates nothing.
    created = len([c for c in fake.calls if c["args"][0] == "create"])
    report, _ = inspect(inspector, workspace, ["python -m pytest -q"])
    assert report["findings"][0]["state"] == "replay_failed" and "isolation_unresolved_run" in report["findings"][0]["cause"]
    assert len([c for c in fake.calls if c["args"][0] == "create"]) == created
    del fake.containers[seen[0]["id"]]  # the owner removed the exact container
    assert iw.reconcile(inspector.root / saved["run_id"])["reconciled"] and iw.unresolved_runs(inspector.root) == []


def test_real_capture_interrupted_in_wait_reaches_the_container_stop_before_the_watchdog(setup, monkeypatch):
    """The REAL `_capture` and a REAL sleeping child tree stand where the attached docker client would;
    the only injection is KeyboardInterrupt from the real process's first wait (and the fake daemon)."""
    inspector, fake, _, workspace = setup
    monkeypatch.setattr(ie, "_capture", ei._capture)  # undo the fixture's replacement: the real helper
    spawned, fired, stops = [], [], []

    def client(argv):  # the local child in place of `docker start --attach <id>`
        fake.containers[argv[-1]]["status"] = "running"
        return [sys.executable, "-c", HOLDER]
    interrupt_first_wait(monkeypatch, spawned, fired, replace=client)
    stop = iw.OwnedContainer.stop

    def timed_stop(self, seconds):
        stops.append({"at": time.monotonic(), "child_gone": spawned[0][0].process.poll() is not None})
        return stop(self, seconds)
    monkeypatch.setattr(iw.OwnedContainer, "stop", timed_stop)
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        inspect(inspector, workspace, ["python -m pytest -q"])
    (tree, watchdog), = spawned
    watchdog.cancel()
    assert fired == [] and len(stops) == 1 and stops[0]["at"] - started < WATCHDOG_SECONDS / 2
    assert stops[0]["child_gone"] and tree.process.stdout.closed and tree.process.stderr.closed
    saved = iw.run_records(inspector.root)
    assert len(saved) == 1 and saved[0]["state"] == "removed" and saved[0]["result"]["interrupted"] == "KeyboardInterrupt"
    assert saved[0]["result"]["stop"]["capture_cleanup"]["confirmed"] and saved[0]["result"]["stop"]["confirmed"]
    assert list(fake.containers) == ["f" * 64] and iw.unresolved_runs(inspector.root) == []


def test_interruption_with_unreclaimed_capture_debt_is_retained_not_retired(setup, monkeypatch):
    inspector, fake, _, workspace = setup
    debt = {"reason": "KeyboardInterrupt", "confirmed": False, "readers_alive": ["stdout"], "injected": True}

    def capture(argv, cwd, timeout, max_bytes, env):  # INJECTED: the capture could not reclaim its client
        fake.containers[argv[-1]]["status"] = "running"
        error = KeyboardInterrupt()
        error.capture_cleanup = debt
        raise error
    monkeypatch.setattr(ie, "_capture", capture)
    with pytest.raises(KeyboardInterrupt):
        inspect(inspector, workspace, ["python -m pytest -q"])
    saved = iw.run_records(inspector.root)[0]
    assert saved["state"] == "stop_unconfirmed" and saved["lifecycle"][-1]["stop"]["capture_cleanup"] == debt
    assert any(c["args"][0] == "kill" for c in fake.calls) and not any(c["args"][0] == "rm" for c in fake.calls)
    assert len(iw.unresolved_runs(inspector.root)) == 1


def test_unconfirmed_stop_after_a_returned_capture_is_never_a_checked_replay(setup):
    inspector, fake, _, workspace = setup
    fake.kill_works = False  # injected fault
    fake.exit_on_capture = False  # injected: the capture returned but the container is still running
    inspector.isolation["limits"] = {**inspector.isolation["limits"], "cleanup_seconds": 1}
    report, _ = inspect(inspector, workspace, ["python -m pytest -q"])
    finding = report["findings"][0]
    assert finding["state"] == "replay_failed" and "container_stop_unconfirmed" in finding["cause"]
    assert iw.run_records(inspector.root)[0]["state"] == "stop_unconfirmed" and len(fake.containers) == 2


def test_evidence_write_failure_keeps_the_stopped_container_and_is_not_success(setup, monkeypatch):
    inspector, fake, _, workspace = setup
    real = iw._write_record

    def failing(path, record):  # injected fault: the observation cannot be written
        if record.get("state") == "evidence_retained":
            raise OSError("injected: disk full")
        return real(path, record)
    monkeypatch.setattr(iw, "_write_record", failing)
    report, _ = inspect(inspector, workspace, ["python -m pytest -q"])
    finding = report["findings"][0]
    assert finding["state"] == "replay_failed" and "replay_evidence_unwritten" in finding["cause"]
    assert not any(c["args"][0] == "rm" for c in fake.calls) and len(fake.containers) == 2
    saved = iw.run_records(inspector.root)[0]
    assert saved["state"] == "stop_confirmed" and len(iw.unresolved_runs(inspector.root)) == 1


def test_image_or_configuration_change_invalidates_the_replay_identity(setup, tmp_path):
    inspector, _, _, workspace = setup
    other = iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "b" * 64})
    changed = ie.DockerEvidenceInspector(Artifacts(), other, tmp_path / "replays")
    first, second = inspector.identity(workspace), changed.identity(workspace)
    assert first["container"]["image"] == IMAGE and first != second and first["platform"] == "linux-container"
    assert first["container"]["credentials"] == "none" and first["container"]["network"] == "none"


def test_unavailable_container_is_a_named_failure_never_a_host_replay(setup, monkeypatch):
    inspector, fake, captured, workspace = setup

    def unavailable(self, args, env):  # injected fault: the daemon creates nothing
        raise iw.IsolationError("container_create_failed")
    monkeypatch.setattr(iw.OwnedContainer, "create", unavailable)
    report, _ = inspect(inspector, workspace, ["python -m pytest -q"])
    finding = report["findings"][0]
    assert finding["state"] == "replay_failed" and "isolated_replay_unavailable" in finding["cause"] and captured == []
