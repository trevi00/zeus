"""S3b: Codex native hooks inside a Codex role container, bound to the Git-verified script digest.

Layer: adapters
Context: execution
Owns: `container_hooks` (the active native hooks as a per-run, read-only, digest-addressed script set and
    the Codex hook configuration naming ONLY container paths), `ContainerHookSet`, `bound_state` (the
    trust state of the discovered entries of exactly those commands) and `verify_bound` (every bound
    entry is discovered, trusted and unchanged after binding, else an explicit refusal)
Does not own: the hook lifecycle (proposal, review, canary, activation: service, S5/S8), the host hook
    configuration and its canary (M7 `adapters/hooks.NativeHooks`, moving with RunTask in S4), the
    decision to hand a hook set to a Codex run (RunTask, S4: it removes the M7
    `codex_container_native_hooks_unsupported` refusal when it wires this)
Entry points: container_hooks, ContainerHookSet, bound_state, verify_bound, HOOK_MOUNT, NATIVE_EVENTS,
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
import shlex
from dataclasses import dataclass
from pathlib import Path

from codex_harness.execution.domain.container_spec import TRUSTED_PYTHON
from codex_harness.kernel.errors import IsolationError

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
