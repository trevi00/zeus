"""S10 unit C5c-1: `composition.isolation` and `composition.processes` build the IsolatedWorker as M7 host_isolation did (R-c15).

Every docker call goes through `owned_container.docker_call` (as `m7_containers.install_docker` does) to a recording
fake: the real client is never run. Environment values are synthetic and never printed.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "ported"))
from m7_containers import iw  # noqa: E402

from codex_harness.composition import isolation, processes  # noqa: E402
from codex_harness.composition.configuration import runtime_dir  # noqa: E402
from codex_harness.context.adapters import worker_profile  # noqa: E402
from codex_harness.credentials.adapters import codex_custody, scrubber  # noqa: E402
from codex_harness.execution.adapters.containers import launcher, owned_container  # noqa: E402
from codex_harness.execution.domain import container_spec  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.kernel.errors import IsolationError  # noqa: E402

IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def config(tmp_path):
    root = tmp_path / "secrets" / "codex-product"
    root.mkdir(parents=True)
    root.chmod(0o700)
    auth = root / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": None, "auth_mode": "chatgpt",
                                "tokens": {"id_token": "idt-DUMMY", "access_token": "at-DUMMY-NOT-A-TOKEN",
                                           "refresh_token": "rt-DUMMY-NOT-A-TOKEN", "account_id": "acct-dummy-0001"},
                                "last_refresh": "2026-09-29T00:00:00Z"}), encoding="utf-8")
    auth.chmod(0o600)
    return iw.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": IMAGE,
                              "ZEUS_CODEX_CREDENTIAL_STORE": str(root)})


def install(monkeypatch, *, daemon=True, image=IMAGE):
    calls = []

    def fake(runner, docker, args, *, timeout, env=None):
        calls.append(list(args))
        if args[0] == "version":
            return subprocess.CompletedProcess(args, 0 if daemon else 1, "27.0.1\n" if daemon else "", "")
        return subprocess.CompletedProcess(args, 0, image + "\n", "")

    monkeypatch.setattr(owned_container, "docker_call", fake)
    return calls


def test_daemon_down_refuses_and_builds_nothing(monkeypatch, config):
    calls = install(monkeypatch, daemon=False)
    built = []
    monkeypatch.setattr(launcher.IsolatedWorker, "__init__", lambda self, *a, **k: built.append(1))
    with pytest.raises(IsolationError, match="docker_unavailable"):
        isolation.isolated_worker(config, environment={container_spec.TOKEN_NAME: "synthetic"})
    assert built == [] and [c[0] for c in calls] == ["version"]


def test_image_mismatch_refuses(monkeypatch, config):
    install(monkeypatch, image="sha256:" + "b" * 64)
    with pytest.raises(IsolationError, match="worker_image_unavailable"):
        isolation.isolated_worker(config, environment={container_spec.TOKEN_NAME: "synthetic"})


def test_missing_token_refuses(monkeypatch, config):
    install(monkeypatch)
    with pytest.raises(IsolationError, match="worker_token_missing"):
        isolation.isolated_worker(config, environment={})


def test_success_composes_the_worker(monkeypatch, tmp_path, config):
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path / "runtime"))
    calls = install(monkeypatch)
    worker = isolation.isolated_worker(config, environment={container_spec.TOKEN_NAME: "synthetic"})
    assert isinstance(worker, launcher.IsolatedWorker)
    assert worker.root == runtime_dir() / "isolated-worker" == (tmp_path / "runtime").resolve() / "isolated-worker"
    assert worker.config is config
    host = worker.host
    assert isinstance(host, launcher.ContainerHost)
    assert host.runner is process_groups.run_process
    assert isinstance(host.processes, process_groups.ChokepointProcesses)
    assert host.trees is ProcessTree
    assert host.worker_profiles is worker_profile
    assert worker.broker_factory is codex_custody.CodexCredentialBroker
    assert worker.credentials.scrubber is scrubber.CredentialScrubber
    assert worker.credentials.OutputUnsanitizable is scrubber.OutputUnsanitizable
    assert worker.summary() == container_spec.summary(config)
    assert worker.review_context(tmp_path) == owned_container.isolated_review_context(tmp_path, config)
    assert [c[:2] for c in calls] == [["version", "--format"], ["image", "inspect"]]
    assert all(c[0] != "run" for c in calls)


def test_credential_boundary_and_container_host_are_the_shim_wiring():
    boundary = isolation.credential_boundary()
    assert boundary.scrubber is scrubber.CredentialScrubber
    host = processes.container_host()
    assert host.worker_profiles is worker_profile
    assert {"load_profile", "profile_digest", "hook_receipts"} <= set(dir(host.worker_profiles))


def test_composition_modules_import_nothing_from_tests():
    for module in (isolation, processes):
        tree = ast.parse(Path(module.__file__).read_text("utf-8"))
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not [n for n in names if n.split(".")[0] in {"tests", "m7_containers"}]
