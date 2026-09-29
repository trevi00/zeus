"""S4 transport selection (execution.adapters.transports): the S3 container boundary and the active native-hook
set wired into RunTask's runtime opening, with no host fallback (FLEET-REBUILD-S3R2-ACCEPT "S4 entry conditions").

The declared design v2 §5.4 change: M7 refused an isolated `app_server` assignment with active native hooks
(`codex_container_native_hooks_unsupported`, characterized by the reference-only `hooks.native_container`
golden); here the hooks are handed to the Codex role container instead. Both providers are stubbed in every
case and the unexpected transport raises (no real provider, no host process). Fixture proof only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_containers import iw, rc  # noqa: E402
from test_role_containers import (  # noqa: E402,F401  `candidate`, `store`, `config` are imported fixtures
    CLAUDE_TOKEN,
    SCHEMA,
    candidate,
    config,
    store,
)
from test_s3b_native_hooks import (  # noqa: E402,F401  `fake` is a fixture
    DIGEST,
    active,
    fake,
    reader,
    records,
)

from codex_harness.execution.adapters import transports as tr  # noqa: E402
from codex_harness.execution.adapters.providers import native_hooks as nh  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402


class Unexpected:
    """A transport factory that must not be reached in this case (both-provider stub)."""

    def __init__(self, name):
        self.name = name

    def __call__(self, *args, **kwargs):
        raise AssertionError(self.name + " reached")


class FakeIsolation:
    def __init__(self, codex=True):
        self.config = {"codex": {"credential_store": "/store"}} if codex else {}
        self.calls = []

    def codex_runtime(self, **kwargs):
        self.calls.append(("codex_runtime", kwargs))
        return "container-codex"

    def runtime(self, **kwargs):
        self.calls.append(("runtime", kwargs))
        return "container-claude"


class Hooks:
    def __init__(self, rows):
        self.rows = rows

    def active_hooks(self):
        return self.rows

    def read_script(self, revision, path):
        return reader()(revision, path)


def assignment(provider, transport, **controls):
    return SimpleNamespace(provider=provider, transport=transport, controls=controls, runtime={"tools": []})


def isolated(isolation, hooks=None):
    return tr.Transports(isolation=isolation, hooks=hooks, host_app_server=Unexpected("host App Server"),
                         host_hooks=Unexpected("host hook configuration"),
                         claude_runtime=Unexpected("host Claude runtime"), claude_settings=lambda runtime: {})


def test_isolated_codex_with_active_hooks_runs_them_in_the_container_instead_of_refusing(tmp_path):
    isolation = FakeIsolation()
    opened = isolated(isolation, Hooks(active())).open(assignment("codex", "app_server"), "m", action="plan",
                                                       read_only=True, handoff={"refs": []})
    assert opened == "container-codex"
    [(name, kwargs)] = isolation.calls
    assert name == "codex_runtime" and kwargs["profile"] == "codex-role-ro" and kwargs["handoff"] == {"refs": []}
    hook_set = kwargs["native_hooks"](tmp_path / "hooks")
    assert hook_set.digests == (DIGEST,) and hook_set.target == nh.HOOK_MOUNT
    [entry] = hook_set.configuration["PreToolUse"]
    assert nh.HOOK_MOUNT + "/" + DIGEST + ".py" in entry["hooks"][0]["command"]
    assert str(tmp_path) not in json.dumps(hook_set.configuration)  # container paths only, never a host path


def test_isolated_codex_without_active_hooks_keeps_the_single_container_run(tmp_path):
    isolation = FakeIsolation()
    isolated(isolation, Hooks(active(status="proposed"))).open(assignment("codex", "app_server"), "m",
                                                              action="implement", read_only=False)
    [(_, kwargs)] = isolation.calls
    assert kwargs["profile"] == "codex-impl-rw" and kwargs["native_hooks"](tmp_path / "hooks") is None


def test_a_bad_hook_digest_refuses_inside_the_hook_builder_before_any_container(tmp_path):
    isolation = FakeIsolation()
    isolated(isolation, Hooks(active(digest="0" * 64))).open(assignment("codex", "app_server"), "m",
                                                             action="plan", read_only=True)
    [(_, kwargs)] = isolation.calls
    with pytest.raises(IsolationError) as refused:
        kwargs["native_hooks"](tmp_path / "hooks")
    assert refused.value.reason_code == "native_hook_digest_mismatch"


@pytest.mark.parametrize("provider,transport,action,read_only,expected", [
    ("claude", "claude_cli", "implement", False, ("runtime", None)),
    ("claude", "claude_cli", "plan", True, ("runtime", "claude-role-ro")),
])
def test_isolated_claude_never_falls_back_to_the_host(provider, transport, action, read_only, expected):
    isolation = FakeIsolation()
    opened = isolated(isolation).open(assignment(provider, transport), "m", cwd="/w", action=action,
                                      read_only=read_only)
    assert opened == "container-claude"
    [(name, kwargs)] = isolation.calls
    assert name == expected[0] and kwargs.get("profile") == expected[1]


@pytest.mark.parametrize("provider,transport,action,read_only,codex,reason", [
    ("claude", "claude_cli", "plan", False, True, None),        # an unmapped writable shape
    ("codex", "app_server", "plan", True, False, "codex_profile_disabled"),
])
def test_an_unmapped_shape_or_disabled_codex_refuses_before_any_transport(provider, transport, action, read_only,
                                                                           codex, reason):
    isolation = FakeIsolation(codex=codex)
    with pytest.raises(IsolationError) as refused:
        isolated(isolation, Hooks(active())).open(assignment(provider, transport), "m", action=action,
                                                  read_only=read_only)
    assert isolation.calls == [] and (reason is None or refused.value.reason_code == reason)


def test_without_isolation_the_host_paths_are_m7s():
    calls = []
    host = tr.Transports(host_app_server=lambda **kw: calls.append(("app_server", kw)) or "host-codex",
                         host_hooks=lambda: {"Stop": ["host hook"]},
                         claude_runtime=lambda **kw: calls.append(("claude", kw)) or "host-claude",
                         claude_settings=lambda runtime: {"settings": True})
    assert host.profile(assignment("codex", "app_server"), "plan", True) is None
    assert host.open(assignment("codex", "app_server"), "m") == "host-codex"
    assert host.open(assignment("claude", "claude_cli", max_budget_usd=1.0, executable="/x/claude"), "m") == "host-claude"
    assert calls[0] == ("app_server", {"hooks": {"Stop": ["host hook"]}})
    assert calls[1][1] == {"model": "m", "runtime": {"tools": []}, "executable": "/x/claude", "max_budget_usd": 1.0,
                           "settings_document": {"settings": True}}
    with pytest.raises(ContractError, match="Unsupported provider transport: other"):
        host.open(assignment("x", "other"), "m")


class ContainerIsolation:
    """The S3 container runtime behind the fake isolation: the S3b hook-aware peer answers in fixture
    containers (the ported fake Docker client), so the wiring is exercised end to end."""

    def __init__(self, selection, tmp_path, broker_store):
        self.config, self.tmp_path, self.store = selection, tmp_path, broker_store

    def codex_runtime(self, *, profile, handoff=None, native_hooks=None):
        return rc.IsolatedCodexRuntime(self.config, self.tmp_path / "runs", profile=profile,
                                       broker=rc.CodexCredentialBroker(self.store),
                                       environment={**os.environ, iw.TOKEN_NAME: CLAUDE_TOKEN},
                                       state_root=self.tmp_path / "codex-state", lock_wait_seconds=0.5,
                                       native_hooks=native_hooks, handoff=handoff)


def test_the_wired_hook_set_is_discovered_bound_and_verified_in_the_role_container(
        config, tmp_path, store, candidate, fake):  # noqa: F811
    transports = isolated(ContainerIsolation(config, tmp_path, store), Hooks(active()))
    with transports.open(assignment("codex", "app_server"), "m", action="plan", read_only=True) as runtime:
        result = runtime.run("review this", str(candidate), SCHEMA, 30, read_only=True)
    discovery, run = fake.created()
    assert all(any(part.endswith("target=" + nh.HOOK_MOUNT + ",readonly=true") for part in c["args"])
               for c in (discovery, run))
    assert json.loads(result["answer"]["summary"])["hooks"] == ["/<session-flags>/config.toml:pretooluse:0:0"]
    main = [row for row in records(tmp_path) if row.get("purpose") != "native_hook_discovery"][0]
    assert "hooks_verified" in [step["state"] for step in main["lifecycle"]] and main["state"] == "removed"
    [entry] = rc.CodexCredentialBroker(store).entries()
    assert entry["state"] == "unchanged" and not fake.containers


def test_the_isolated_worker_passes_the_hook_builder_to_the_codex_role_container(monkeypatch, tmp_path):
    from codex_harness.execution.adapters.containers import launcher

    seen = {}

    class Recorder:
        def __init__(self, selection, root, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(launcher, "IsolatedCodexRuntime", Recorder)
    worker = launcher.IsolatedWorker({"codex": {"credential_store": "/store"}}, tmp_path, host="host",
                                     broker_factory=lambda path: ("broker", path), credentials="boundary")
    builder = object()
    worker.codex_runtime(profile="codex-role-ro", native_hooks=builder)
    assert seen["native_hooks"] is builder and seen["broker"] == ("broker", "/store")
    assert seen["host"] == "host" and seen["credentials"] == "boundary"


# ---- the host hook configuration equals the SOURCE rows of the hooks.native_container golden --------------
GOLDEN = Path(__file__).resolve().parents[2] / "compare" / "goldens" / "reference" / "hooks.native_container.json"
sys.path.insert(0, str(GOLDEN.parents[2] / "drivers" / "common"))
from s1_common import outcome, relative  # noqa: E402


def test_host_hook_configuration_equals_the_reference_rows(tmp_path):
    """The golden is reference-only as a family (its isolation-refusal rows are the declared §4 change);
    its three host-configuration rows are compared here with the same inputs and the same root masks."""
    import hashlib

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    script = "import sys, json\njson.load(sys.stdin)\nprint('{}')\n"
    spec = {"kind": "native_hook", "event": "PreToolUse", "matcher": "shell", "script_path": "harness_hooks/h.py",
            "script_sha256": hashlib.sha256(script.encode()).hexdigest()}
    active_rows = [
        {"id": "h1", "status": "active", "revision": "r" * 40, "spec": spec},
        {"id": "h2", "status": "active", "revision": "r" * 40, "spec": {**spec, "event": "Stop", "matcher": "*"}},
        {"id": "h3", "status": "proposed", "revision": "r" * 40, "spec": spec},
        {"id": "h4", "status": "active", "revision": "r" * 40, "spec": {**spec, "kind": "prompt_rule"}},
    ]
    base = tmp_path.resolve()

    class Artifacts:
        root = base

        def put(self, text, source):
            ref = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
            (base / (ref[7:] + ".txt")).write_text(text, encoding="utf-8")
            return {"ref": ref}

    def configuration(rows, scripts):
        show = lambda spec_text, strip=True: scripts[spec_text.split(":", 1)[1]]  # noqa: E731
        return nh.HostHooks(SimpleNamespace(active_hooks=lambda: rows), show, Artifacts(), sys.executable).configuration()

    roots = {"ROOT": str(base), "PYTHON": sys.executable}
    assert relative(outcome(lambda: configuration(active_rows, {"harness_hooks/h.py": script})), roots) \
        == golden["configuration"]
    assert relative(outcome(lambda: configuration(active_rows[:1], {"harness_hooks/h.py": script + "#changed\n"})),
                    roots) == golden["configuration_digest_mismatch"]
    assert outcome(lambda: configuration(active_rows[2:], {"harness_hooks/h.py": script})) \
        == golden["configuration_none_active"]
