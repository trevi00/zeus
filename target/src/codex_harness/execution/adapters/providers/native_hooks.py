"""S3b: Codex native hooks inside a Codex role container, bound to the Git-verified script digest.

Layer: adapters
Context: execution
Owns: `HostHooks` (S4: the host App Server's hook configuration, M7 `NativeHooks.materialize/configuration`),
    `HookCandidates` (S4: M7 `NativeHooks.candidate/canary`, with the lifecycle, the validator, Git and the
    runner injected) and the `hook_cases` bucket,
    `container_hooks` (the active native hooks as a per-run, read-only, digest-addressed script set and
    the Codex hook configuration naming ONLY container paths), `ContainerHookSet`, `bound_state` (the
    trust state of the discovered entries of exactly those commands) and `verify_bound` (every bound
    entry is discovered, trusted and unchanged after binding, else an explicit refusal)
Does not own: the hook lifecycle (proposal, review, canary, activation: service, S5/S8; M7
    `NativeHooks.candidate/canary` validate through the research-domain `hook_apply` and propose through the
    lifecycle: here they receive both injected), the decision to hand a hook set to a Codex run
    (execution.adapters.transports, S4: it replaced the M7 `codex_container_native_hooks_unsupported` refusal)
Entry points: HostHooks, HookCandidates, container_hooks, ContainerHookSet, bound_state, verify_bound, HOOK_MOUNT, NATIVE_EVENTS,
    HOOK_TIMEOUT_SECONDS
Contracts: INV-RECURRENCE-001, INV-ROLE-CONTAINER-001

The declared design v2 §5.4 change, characterized first by the `hooks.native_container` golden on SOURCE.
RESEARCH-S3 R3 (Codex hooks at the pinned rust-v0.156.1): Codex's trust hash covers the normalized hook
definition (the command string), not the script bytes, and an untrusted or modified hook is skipped
silently. Therefore (F-R3) the command names a digest-addressed path, so a changed script is a changed
command and a changed trust identity, and the script is re-verified against the reviewed
`script_sha256` before it is copied; (F-R2) after binding, every bound entry must be discovered as
trusted with the bound hash, or the run refuses (`codex_native_hook_unbound`), never runs without it.
Container-only: the command names the image's trusted interpreter and the read-only hook mount; no host
path and no host interpreter appears, and nothing here runs a hook. Timeout: the M7 hook events
(`NATIVE_EVENTS`) are all outside Codex's 1-3 s SessionEnd/Interrupt clamp, so the fixed 30 s applies.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codex_harness.execution.domain.container_spec import TRUSTED_PYTHON
from codex_harness.kernel.errors import IsolationError, require
from codex_harness.kernel.ids import canonical

HOOK_MOUNT = "/zeus-hooks"
HOOK_TIMEOUT_SECONDS = 30
# The events the M7 declarative hook evaluator admits for a native hook (domain.model.hook_apply).
NATIVE_EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SessionStart")


@dataclass(frozen=True)
class ContainerHookSet:
    """A per-run verified hook set: `source` is the host directory mounted read-only at `target`;
    `configuration` is the Codex `hooks` table (container paths only); `digests` names every script."""

    source: str
    target: str
    configuration: dict
    digests: tuple

    def commands(self) -> set:
        return {hook["command"] for groups in self.configuration.values() for group in groups
                for hook in group["hooks"]}


def container_hooks(active_hooks, read_script, destination) -> ContainerHookSet | None:
    """The active native hooks as a container hook set, or None when none is active.

    `read_script(revision, path) -> str` reads the reviewed script at the hook's pinned revision (Git).
    A digest mismatch, an unsupported event or a malformed spec refuses before any container exists."""
    selected = [hook for hook in active_hooks
                if hook.get("status") == "active" and (hook.get("spec") or {}).get("kind") == "native_hook"]
    if not selected:
        return None
    destination = Path(destination)
    destination.mkdir(parents=True)
    configuration, digests = {}, []
    for hook in selected:
        spec = hook["spec"]
        if spec.get("event") not in NATIVE_EVENTS:
            raise IsolationError("native_hook_event_unsupported", str(spec.get("event")))
        if not isinstance(spec.get("matcher"), str) or not isinstance(spec.get("script_sha256"), str):
            raise IsolationError("native_hook_spec_invalid", str(hook.get("id")))
        script = read_script(hook["revision"], spec["script_path"])
        digest = hashlib.sha256(script.encode()).hexdigest()
        if digest != spec["script_sha256"]:
            raise IsolationError("native_hook_digest_mismatch", str(hook.get("id")))
        target = destination / (digest + ".py")
        if not target.exists():
            target.write_bytes(script.encode())
            target.chmod(0o444)
        digests.append(digest)
        command = shlex.join([TRUSTED_PYTHON, "-I", HOOK_MOUNT + "/" + digest + ".py"])
        configuration.setdefault(spec["event"], []).append({
            "matcher": spec["matcher"],
            "hooks": [{"type": "command", "command": command, "timeout": HOOK_TIMEOUT_SECONDS}]})
    destination.chmod(0o555)
    return ContainerHookSet(str(destination.resolve()), HOOK_MOUNT, configuration, tuple(sorted(set(digests))))


def _ours(rows, commands) -> list:
    return [hook for row in rows for hook in row.get("hooks", [])
            if (hook.get("handler") or {}).get("command") in commands or hook.get("command") in commands]


def bound_state(rows, hook_set: ContainerHookSet) -> dict:
    """The `hooks.state` binding of exactly the discovered entries of this set's commands (their
    peer-reported current hash). Every configured hook must be discovered once, else a refusal."""
    entries = _ours(rows, hook_set.commands())
    expected = sum(len(group["hooks"]) for groups in hook_set.configuration.values() for group in groups)
    if len(entries) != expected:
        raise IsolationError("codex_native_hook_undiscovered", f"{len(entries)} of {expected}")
    return {entry["key"]: {"enabled": True, "trusted_hash": entry["currentHash"]} for entry in entries}


def verify_bound(rows, hook_set: ContainerHookSet, state: dict) -> dict:
    """After binding: every bound entry is discovered, trusted and still has the bound hash (Codex skips
    an untrusted or modified hook silently, RESEARCH-S3 F-R2). Returns the per-key trust statuses."""
    entries = {entry.get("key"): entry for entry in _ours(rows, hook_set.commands())}
    statuses = {}
    for key, bound in state.items():
        entry = entries.get(key)
        if entry is None or entry.get("currentHash") != bound["trusted_hash"] \
                or entry.get("trustStatus") != "trusted" or entry.get("enabled") is False:
            raise IsolationError("codex_native_hook_unbound", str(key))
        statuses[key] = entry["trustStatus"]
    if set(entries) != set(state):
        raise IsolationError("codex_native_hook_unbound", "unbound entries of this set were discovered")
    return statuses


class HostHooks:
    """The host App Server's native-hook configuration (M7 `adapters/hooks.NativeHooks.materialize` and
    `.configuration`, moved unchanged; used only WITHOUT isolation, execution.adapters.transports).

    `hooks.active_hooks()` is the hook lifecycle owner's read; `show(spec, strip=True)` is `git show` of
    `revision:path` (M7 `git._git("show", ...)`); `artifacts` is the content-addressed store the script is
    materialized into; `interpreter` is the host interpreter the command names (M7 `sys.executable`)."""

    def __init__(self, hooks, show, artifacts, interpreter: str):
        self.hooks, self.show, self.artifacts, self.interpreter = hooks, show, artifacts, interpreter

    def materialize(self, hook: dict) -> Path:
        spec = hook["spec"]
        script = self.show(hook["revision"] + ":" + spec["script_path"], strip=False)
        require(hashlib.sha256(script.encode()).hexdigest() == spec["script_sha256"], "Reviewed script changed")
        receipt = self.artifacts.put(script, "git:" + hook["revision"] + ":" + spec["script_path"])
        return self.artifacts.root / (receipt["ref"][7:] + ".txt")

    def configuration(self) -> dict:
        output = {}
        for hook in self.hooks.active_hooks():
            if hook["status"] != "active" or hook["spec"].get("kind") != "native_hook":
                continue
            script = self.materialize(hook)
            argv = [self.interpreter, str(script)]
            command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
            spec = hook["spec"]
            output.setdefault(spec["event"], []).append({"matcher": spec["matcher"],
                                                       "hooks": [{"type": "command", "command": command, "timeout": 30}]})
        return output


class HookCandidates:
    """A proposed native hook's candidate validation and its canary (M7 `NativeHooks.candidate/canary`, moved
    unchanged). Injected (§2.4): `lifecycle` (research's HookLifecycle: propose, get_hook), `store`, `show`
    (`git show` of `revision:path`), `host` (HostHooks, for materialize), `validate` (research's `hook_apply`),
    `runner` (host_os ProcessRunner), `channel_environment` (host_os) and the canary `interpreter`."""

    def __init__(self, lifecycle, store, show, host: HostHooks, *, validate, runner, channel_environment,
                 interpreter: str):
        self.lifecycle, self.store, self.show, self.host = lifecycle, store, show, host
        self.validate, self.runner = validate, runner
        self.channel_environment, self.interpreter = channel_environment, interpreter

    def candidate(self, hook_id: str, candidate: dict) -> dict:
        manifest_text = self.show(candidate["revision"] + ":harness_hooks/" + hook_id + ".json")
        manifest = json.loads(manifest_text)
        spec = manifest["spec"]
        self.validate(spec, [], "linux")
        require(spec["kind"] == "native_hook", "Self-improvement hook must include an executable native hook")
        script = self.show(candidate["revision"] + ":" + spec["script_path"], strip=False)
        require(hashlib.sha256(script.encode()).hexdigest() == spec["script_sha256"], "Hook script hash mismatch")
        require(set(manifest["cases"]) == {"reproduction", "normal_case"}, "Hook requires recurrence and negative cases")
        for cases in manifest["cases"].values():
            require(isinstance(cases, list) and bool(cases), "Empty hook case suite")
            for case in cases:
                require(set(case) == {"input", "output", "exit_code"}, "Invalid hook test case")
        self.lifecycle.propose(hook_id, candidate["author"], spec, candidate["revision"])
        with self.store.transaction() as tx:
            tx.put("hook_cases", hook_id, {"id": hook_id, "revision": candidate["revision"], "cases": manifest["cases"]})
        return spec

    def canary(self, hook_id: str) -> dict:
        hook = self.lifecycle.get_hook(hook_id)
        script = self.host.materialize(hook)
        with self.store.transaction() as tx:
            manifest = tx.get("hook_cases", hook_id)
        require(manifest["revision"] == hook["revision"], "Stale hook fixtures")
        checks = {}
        for kind, cases in manifest["cases"].items():
            passed, evidence = True, []
            for case in cases:
                # INV-ENCODING-001: case input/output cross the channel as UTF-8 in both directions.
                result = self.runner([self.interpreter, str(script)], input_text=canonical(case["input"]),
                                     timeout=30, env=self.channel_environment())
                try:
                    output = json.loads(result.stdout) if result.stdout.strip() else None
                except json.JSONDecodeError:
                    output = {"invalid_json": result.stdout}
                passed = passed and result.returncode == case["exit_code"] and output == case["output"]
                evidence.append({"input": case["input"], "output": output, "exit_code": result.returncode,
                                 "stderr": result.stderr})
            checks[kind] = {"passed": passed,
                            "evidence": self.host.artifacts.put(canonical(evidence), "hook-canary:" + hook_id)["ref"]}
        return checks
