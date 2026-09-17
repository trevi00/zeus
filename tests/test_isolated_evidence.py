"""INV-ISOLATED-WORKER-001 replay backend. The Docker client and the attached capture are INJECTED
fakes; no container, model or live service runs here, and nothing below is a real-container result."""
import json

import pytest

from codex_harness.adapters import isolated_evidence as ie
from codex_harness.adapters import isolated_worker as iw
from tests.test_isolated_worker import IMAGE, TOKEN, FakeDocker


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
        fake.containers[argv[-1]]["status"] = "exited"
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
    assert list(fake.containers) == ["f" * 64] and not any((inspector.root).glob("*"))  # own containers and copies removed
    assert [run["container"]["network"] for run in finding["runs"]] == ["none", "none"]


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
