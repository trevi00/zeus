"""S11 XC-6 (TQ-XCUT-PLAN section 9 A6, A7), through the COMPOSED objects of `composition.operation`.

A6: the composed Executor's Transports hands the active native hooks to the Codex role container (REBUILD-DESIGN-v2 S3b;
`hook_units.py` states `Transports.hooks`). A7: the composed host Claude facilities resolve the worker-profile evidence
root to `<runtime_dir>/worker-profile` when the runtime configures none (M7 `adapters/worker_profile.py:209-214`).
Behavioural: no provider is called; isolation is a recording fake and git a recording `_git`."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness import composition
from codex_harness.composition import cli, configuration, operation
from codex_harness.execution.adapters.providers import native_hooks as nh
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

SCRIPT = "import sys, json\njson.load(sys.stdin)\nprint('{}')\n"
DIGEST = hashlib.sha256(SCRIPT.encode()).hexdigest()
REVISION = "r" * 40


@pytest.fixture
def runtime_dir(monkeypatch, tmp_path):
    values = {"HARNESS_RUNTIME_DIR": str(tmp_path / "runtime"), "ZEUS_COMPOSITION_PROFILE": "development"}
    monkeypatch.setattr(configuration, "settings", lambda: values)
    monkeypatch.setattr(configuration, "repository_root", lambda: tmp_path)
    return (tmp_path / "runtime").resolve()


class FakeIsolation:
    def __init__(self):
        self.config = {"codex": {"credential_store": "/store"}}
        self.root, self.docker = Path("/unused-isolation-root"), "docker"
        self.calls = []

    def codex_runtime(self, **kwargs):
        self.calls.append(kwargs)
        return "container-codex"


class FakeUnits:
    def active_hooks(self, **_kwargs):
        return [{"id": "h1", "status": "active", "revision": REVISION,
                 "spec": {"kind": "native_hook", "event": "PreToolUse", "matcher": "shell",
                          "script_path": "harness_hooks/h.py", "script_sha256": DIGEST}}]


def test_a6_the_composed_codex_run_carries_the_active_hooks_read_through_git(tmp_path, runtime_dir, monkeypatch):
    monkeypatch.setattr(cli, "hook_units", lambda service: FakeUnits())
    shows = []

    def _git(*args, strip=True):
        shows.append((args, strip))
        return SCRIPT

    service = composition.ServiceHandle(MemoryStore(), packaged_organization())
    git = SimpleNamespace(_git=_git, repository=tmp_path)
    isolation = FakeIsolation()
    executor = operation.Executor(service, git, FileArtifacts(str(tmp_path / "artifacts")), isolation=isolation)
    assignment = SimpleNamespace(provider="codex", transport="app_server", controls={}, runtime={"tools": []})
    opened = executor.run_task.transports.open(assignment, "m", action="plan", read_only=True, handoff={"refs": []})
    assert opened == "container-codex"
    [kwargs] = isolation.calls
    assert kwargs["native_hooks"] is not None
    hook_set = kwargs["native_hooks"](tmp_path / "hooks")
    assert hook_set.digests == (DIGEST,) and hook_set.target == nh.HOOK_MOUNT
    assert nh.HOOK_MOUNT + "/" + DIGEST + ".py" in hook_set.configuration["PreToolUse"][0]["hooks"][0]["command"]
    assert shows == [(("show", REVISION + ":harness_hooks/h.py"), False)]  # the HostHooks reader: revision:path, no strip
    assert (tmp_path / "hooks" / (DIGEST + ".py")).read_text("utf-8") == SCRIPT


def test_a7_the_composed_claude_host_resolves_the_unconfigured_evidence_root_to_the_runtime_directory(runtime_dir):
    profiles = operation.CLAUDE_HOST.worker_profiles
    assert profiles.evidence_root({}) == runtime_dir / "worker-profile"


def test_a7_a_configured_evidence_root_wins(runtime_dir, tmp_path):
    configured = tmp_path / "elsewhere"
    profiles = operation.CLAUDE_HOST.worker_profiles
    assert profiles.evidence_root({"profile_evidence_root": str(configured)}) == configured.resolve()
