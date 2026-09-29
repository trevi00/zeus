"""S3b fixture checks (REBUILD-DESIGN-v2 §5.4): Codex native hooks inside a Codex role container.

Characterized first on SOURCE (`compare/goldens/reference/hooks.native_container.json`: M7 refuses any active
hook under isolation, binds the peer-reported hash whatever its trust status, and names host paths). The
declared change is checked here on fixtures only: digest binding, refusal, timeout and container-only
execution. Everything uses the ported M7 fake docker client and a local child process that speaks the App
Server JSON-RPC with a hook registry modelled on the pinned rust-v0.156.1 discovery (untrusted unless the
startup `hooks.state` names the current hash; RESEARCH-S3 R3). DUMMY credentials; no model, provider,
container or network is used, and nothing here observes a real Codex hook run.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "ported"))

from m7_containers import TREES, install_fake, iw, rc  # noqa: E402
from test_role_containers import (  # noqa: E402,F401  `candidate`, `store`, `config` are imported fixtures
    CLAUDE_TOKEN,
    SCHEMA,
    FakeDocker,
    candidate,
    config,
    store,
)

from codex_harness.execution.adapters.providers import native_hooks as nh  # noqa: E402
from codex_harness.kernel.errors import IsolationError  # noqa: E402

HOOK_SERVER = r'''
import hashlib, json, sys, tomllib
mode, args = sys.argv[1], json.loads(sys.argv[2])
config = {}
if "-c" in args:
    literal = args[args.index("-c") + 1]
    assert literal.startswith("hooks=")
    config = tomllib.loads("hooks = " + literal[len("hooks="):])["hooks"]
state = config.pop("state", {})
enabled = "--enable" in args and args[args.index("--enable") + 1] == "hooks"
def send(message):
    sys.stdout.write(json.dumps(message) + "\n"); sys.stdout.flush()
def entries():
    rows = []
    for event, groups in config.items():
        for g, group in enumerate(groups):
            for h, hook in enumerate(group["hooks"]):
                key = "<session-flags>/config.toml:" + event.lower() + ":%d:%d" % (g, h)
                current = "sha256:" + hashlib.sha256(json.dumps([event, group["matcher"], hook], sort_keys=True).encode()).hexdigest()
                if mode == "tamper_after_bind" and state:
                    current = "sha256:" + "0" * 64
                trusted = state.get(key, {}).get("trusted_hash")
                status = "trusted" if trusted == current else ("modified" if trusted else "untrusted")
                if mode == "ignore_state":
                    status = "untrusted"
                rows.append({"key": key, "currentHash": current, "trustStatus": status, "enabled": True,
                             "handler": {"type": "command", "command": hook["command"]}, "timeoutSec": hook["timeout"]})
    if mode == "drop":
        rows = []
    return rows
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"id": message["id"], "result": {"codexHome": "/codex-home"}})
    elif method == "hooks/list":
        send({"id": message["id"], "result": {"data": [{"cwd": message["params"]["cwds"][0], "hooks": entries() if enabled else []}]}})
    elif method in ("thread/start", "thread/resume"):
        send({"id": message["id"], "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        send({"id": message["id"], "result": {"turn": {"id": "turn-1"}}})
        answer = json.dumps({"summary": json.dumps({"hooks": sorted(state)})})
        send({"method": "item/completed", "params": {"threadId": "thread-1", "turnId": "turn-1",
              "item": {"type": "agentMessage", "id": "a1", "text": answer}}})
        send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}}})
'''

SCRIPT = "import sys, json\njson.load(sys.stdin)\nprint('{}')\n"
DIGEST = __import__("hashlib").sha256(SCRIPT.encode()).hexdigest()


def active(event="PreToolUse", digest=DIGEST, status="active", kind="native_hook"):
    return [{"id": "hook-1", "status": status, "revision": "r" * 40,
             "spec": {"kind": kind, "event": event, "matcher": "shell", "script_path": "harness_hooks/h.py",
                      "script_sha256": digest}}]


def reader(text=SCRIPT):
    return lambda revision, path: text


class HookDocker(FakeDocker):
    """The ported M7 fake; the attached child is the hook-aware App Server fixture, given the exact
    entry arguments the container was created with."""

    def __init__(self, tmp_path, mode="ok"):
        super().__init__(tmp_path, mode)
        self.hook_script = tmp_path / "hook_server.py"
        self.hook_script.write_text(HOOK_SERVER, encoding="utf-8")

    def tree(self):
        fake = self

        class Tree:
            @staticmethod
            def spawn(argv, **kwargs):
                container = fake.containers[argv[-1]]
                container["status"] = "running"
                entry = container["args"][container["args"].index(iw_image(container["args"])) + 1:]
                tree = TREES_REAL.spawn([sys.executable, str(fake.hook_script), fake.mode, json.dumps(entry)], **kwargs)
                fake.process = tree.process
                return tree
        return Tree


def iw_image(args):
    return [part for part in args if part.startswith("sha256:")][-1]


TREES_REAL = TREES["current"]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    docker = HookDocker(tmp_path)
    install_fake(monkeypatch, docker)
    return docker


def run_codex(config, tmp_path, store, candidate, fake, *, mode="ok", hooks=None, profile=rc.CODEX_ROLE_RO):  # noqa: F811
    fake.mode = mode
    opened = rc.IsolatedCodexRuntime(config, tmp_path / "runs", profile=profile,
                                     broker=rc.CodexCredentialBroker(store),
                                     environment={**os.environ, iw.TOKEN_NAME: CLAUDE_TOKEN},
                                     state_root=tmp_path / "codex-state", lock_wait_seconds=0.5,
                                     native_hooks=hooks)
    with opened:
        return opened.run("review this", str(candidate), SCHEMA, 30, read_only=profile == rc.CODEX_ROLE_RO)


def records(tmp_path):
    return iw.run_records(tmp_path / "runs")


# ---- digest binding and container-only commands ----------------------------------------------------
def test_the_hook_set_is_digest_addressed_read_only_and_names_only_container_paths(tmp_path):
    hook_set = nh.container_hooks(active(), reader(), tmp_path / "hooks")
    [group] = hook_set.configuration["PreToolUse"]
    [hook] = group["hooks"]
    assert shlex.split(hook["command"]) == [iw.TRUSTED_PYTHON, "-I", nh.HOOK_MOUNT + "/" + DIGEST + ".py"]
    assert hook["timeout"] == nh.HOOK_TIMEOUT_SECONDS == 30 and group["matcher"] == "shell"
    assert str(tmp_path) not in json.dumps(hook_set.configuration) and sys.executable not in hook["command"]
    script = tmp_path / "hooks" / (DIGEST + ".py")
    assert script.read_text() == SCRIPT and oct(script.stat().st_mode & 0o777) == "0o444"
    assert oct((tmp_path / "hooks").stat().st_mode & 0o777) == "0o555"
    assert hook_set.target == nh.HOOK_MOUNT and hook_set.digests == (DIGEST,)
    (tmp_path / "hooks").chmod(0o755)


def test_a_changed_script_is_a_changed_command_so_its_trust_identity_changes(tmp_path):
    other = SCRIPT + "# v2\n"
    digest = __import__("hashlib").sha256(other.encode()).hexdigest()
    first = nh.container_hooks(active(), reader(), tmp_path / "a")
    second = nh.container_hooks(active(digest=digest), reader(other), tmp_path / "b")
    assert first.commands() != second.commands()
    for path in (tmp_path / "a", tmp_path / "b"):
        path.chmod(0o755)


@pytest.mark.parametrize("hooks,reason", [
    (active(digest="0" * 64), "native_hook_digest_mismatch"),
    (active(event="SessionEnd"), "native_hook_event_unsupported"),
])
def test_a_digest_mismatch_or_unsupported_event_refuses_before_any_container(
        hooks, reason, config, tmp_path, store, candidate, fake):  # noqa: F811
    with pytest.raises(IsolationError, match=reason):
        run_codex(config, tmp_path, store, candidate, fake,
                  hooks=lambda destination: nh.container_hooks(hooks, reader(), destination))
    # Refused while preparing, before the credential copy is issued: no container, no ledger entry.
    assert not fake.created() and rc.CodexCredentialBroker(store).entries() == []
    assert [row["state"] for row in records(tmp_path)] == ["refused"]


def test_no_active_native_hook_keeps_the_m7_single_container_run(config, tmp_path, store, candidate, fake):  # noqa: F811
    result = run_codex(config, tmp_path, store, candidate, fake,
                       hooks=lambda destination: nh.container_hooks(active(status="proposed"), reader(), destination))
    [create] = fake.created()
    assert create["args"][-1] == "app-server" and result["isolation"]["outcome"] == "reviewed"


# ---- discover, bind, verify: container-only execution ------------------------------------------------
def test_hooks_are_discovered_in_their_own_container_then_bound_and_verified_in_the_run(
        config, tmp_path, store, candidate, fake):  # noqa: F811
    result = run_codex(config, tmp_path, store, candidate, fake,
                       hooks=lambda destination: nh.container_hooks(active(), reader(), destination))
    discovery, run = fake.created()
    # Both containers mount the verified hook set read-only at the fixed path; nothing else changes.
    for create in (discovery, run):
        assert any(part.endswith("target=" + nh.HOOK_MOUNT + ",readonly=true") for part in create["args"])
        assert "--enable" in create["args"] and "hooks" in create["args"]
    discovery_entry = discovery["args"][discovery["args"].index("-c") + 1]
    run_entry = run["args"][run["args"].index("-c") + 1]
    assert '"state"={}' in discovery_entry and '"trusted_hash"="sha256:' in run_entry
    # The run's answer shows the bound key; the record shows the verification step.
    assert json.loads(result["answer"]["summary"])["hooks"] == ["<session-flags>/config.toml:pretooluse:0:0"]
    states = {tuple(step["state"] for step in row["lifecycle"]) for row in records(tmp_path)}
    assert ("created", "start_requested", "running", "stop_confirmed", "evidence_retained", "removed") in states
    main = [row for row in records(tmp_path) if row.get("purpose") != "native_hook_discovery"][0]
    assert "hooks_verified" in [step["state"] for step in main["lifecycle"]] and main["state"] == "removed"
    assert not fake.containers and all(row["state"] == "removed" for row in records(tmp_path))
    [entry] = rc.CodexCredentialBroker(store).entries()
    assert entry["state"] == "unchanged"


@pytest.mark.parametrize("mode,reason", [("ignore_state", "codex_native_hook_unbound"),
                                         ("tamper_after_bind", "codex_native_hook_unbound")])
def test_a_hook_not_trusted_after_binding_refuses_instead_of_running_without_it(
        mode, reason, config, tmp_path, store, candidate, fake):  # noqa: F811
    with pytest.raises(IsolationError, match=reason):
        run_codex(config, tmp_path, store, candidate, fake, mode=mode,
                  hooks=lambda destination: nh.container_hooks(active(), reader(), destination))
    assert len(fake.created()) == 2 and not fake.containers
    assert all(row["state"] == "removed" for row in records(tmp_path))
    assert rc.CodexCredentialBroker(store).entries()[0]["state"] == "unchanged"


def test_an_undiscovered_hook_refuses_before_the_run_container_exists(config, tmp_path, store, candidate, fake):  # noqa: F811
    with pytest.raises(IsolationError, match="codex_native_hook_undiscovered"):
        run_codex(config, tmp_path, store, candidate, fake, mode="drop",
                  hooks=lambda destination: nh.container_hooks(active(), reader(), destination))
    assert len(fake.created()) == 1 and not fake.containers
    assert rc.CodexCredentialBroker(store).entries()[0]["state"] == "unchanged"
    assert iw.unresolved_runs(tmp_path / "runs") == []
    main = [row for row in records(tmp_path) if row.get("purpose") != "native_hook_discovery"][0]
    assert main["lifecycle"][-1]["reason"] == "hook_discovery_codex_native_hook_undiscovered"


def test_bound_state_and_verification_are_exact(tmp_path):
    hook_set = nh.container_hooks(active(), reader(), tmp_path / "h")
    [command] = hook_set.commands()
    row = {"key": "k", "currentHash": "sha256:1", "trustStatus": "untrusted", "handler": {"command": command}}
    state = nh.bound_state([{"hooks": [row]}], hook_set)
    assert state == {"k": {"enabled": True, "trusted_hash": "sha256:1"}}
    assert nh.verify_bound([{"hooks": [{**row, "trustStatus": "trusted"}]}], hook_set, state) == {"k": "trusted"}
    for bad in ({**row, "trustStatus": "modified"}, {**row, "trustStatus": "trusted", "currentHash": "sha256:2"},
                {**row, "trustStatus": "trusted", "enabled": False}):
        with pytest.raises(IsolationError, match="codex_native_hook_unbound"):
            nh.verify_bound([{"hooks": [bad]}], hook_set, state)
    with pytest.raises(IsolationError, match="codex_native_hook_undiscovered"):
        nh.bound_state([{"hooks": [row, {**row, "key": "k2"}]}], hook_set)
    (tmp_path / "h").chmod(0o755)
