"""Opt-in worker profile for the Claude Code CLI transport (INV-WORKER-PROFILE-001).

A profile is a packaged document, a packaged standalone hook and a manifest that pins both by
digest. Selecting one is a configuration act (`runtime.worker_profile`), never something an
assignment message or a model output can do. Loading verifies the manifest against the packaged
bytes before any provider process exists, so a tampered, oversized or unknown profile is a
refusal, not a run.

What travels to the provider and what is recorded are kept apart: the document goes through
`--append-system-prompt`, the hooks through the per-run `--settings` value, and the receipt keeps
identifiers and digests only. Whether the hooks actually ran is read back from the receipt files
the hook wrote, per session, after the run; installing a hook is never reported as its execution,
and a receipt is an observation, not an approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from importlib.resources import files
from pathlib import Path

from codex_harness.domain.model import ContractError, digest, require

RESOURCES = "codex_harness.resources"
PROFILES = {"worker-v1": "worker-profile-v1.json"}
# The user authorized 15000 normalized characters for this common profile. It is a ceiling for
# the packaged document only: per-run project delivery, project-skill admission and research
# budgets keep their own separate limits, and this number sets no model token allowance.
MAX_CHARACTERS = 15000
HOOK_EVENTS = ("SessionStart", "PostToolUse", "PostToolUseFailure")
HOOK_TOOL_MATCHER = "Bash"
# two-strike-001: the failure event is registered for the tools whose failures the hook can
# fingerprint. The matcher is a regular expression the CLI applies to the tool name.
FAILURE_EVENT = "PostToolUseFailure"
FAILURE_TOOL_MATCHER = "Bash|Edit|Glob|Grep|Read|Write"
HOOKS_DECLARED = ("SessionStart", f"PostToolUse({HOOK_TOOL_MATCHER})",
                  f"{FAILURE_EVENT}({FAILURE_TOOL_MATCHER})")
STRIKE_THRESHOLD = 2
# A hook command is one string that a shell parses. It must mean the same thing to POSIX `sh`
# and to `cmd.exe`, so every element is double-quoted and every character either shell treats
# specially inside double quotes is refused rather than escaped differently per host.
UNQUOTABLE = re.compile(r'["$`\\%!^&|<>;\r\n\x00]')


class WorkerProfileError(ContractError):
    """The selected profile cannot be used; nothing was started (a refusal before entry)."""


def _normalized(text: str) -> str:
    return text.replace("\r\n", "\n")


def _sha256(text: str) -> str:
    return hashlib.sha256(_normalized(text).encode("utf-8")).hexdigest()


def _resource_path(name: str) -> Path:
    path = Path(str(files(RESOURCES).joinpath(name)))
    if not path.is_file():
        raise WorkerProfileError("Worker profile resource is not a file: " + name)
    return path


def load_profile(name) -> dict:
    """Load and verify the packaged profile `name`. Every defect is a refusal."""
    if type(name) is not str or name not in PROFILES:
        raise WorkerProfileError("Unknown worker profile: " + repr(name))
    manifest_path = _resource_path(PROFILES[name])
    manifest_text = manifest_path.read_text("utf-8")
    try:
        manifest = json.loads(manifest_text)
    except ValueError as exc:
        raise WorkerProfileError("Worker profile manifest is not JSON: " + name) from exc
    if not isinstance(manifest, dict) or manifest.get("id") != name:
        raise WorkerProfileError("Worker profile manifest does not name the selected profile")
    for key in ("version", "document", "document_sha256", "hook", "hook_sha256", "sources"):
        if key not in manifest:
            raise WorkerProfileError("Worker profile manifest lacks " + key)
    document_path = _resource_path(str(manifest["document"]))
    document = _normalized(document_path.read_text("utf-8"))
    if _sha256(document) != manifest["document_sha256"]:
        raise WorkerProfileError("Worker profile document does not match its manifest digest")
    if len(document) > MAX_CHARACTERS:
        raise WorkerProfileError(f"Worker profile document exceeds {MAX_CHARACTERS} characters; "
                                 "it is refused, not truncated")
    hook_path = _resource_path(str(manifest["hook"]))
    if _sha256(hook_path.read_text("utf-8")) != manifest["hook_sha256"]:
        raise WorkerProfileError("Worker profile hook does not match its manifest digest")
    allow = manifest.get("permissions", {}).get("allow", [])
    if any(not (type(rule) is str and rule.startswith("Bash(")) for rule in allow):
        raise WorkerProfileError("Worker profile may only add Bash allow rules")
    return {"id": name, "version": str(manifest["version"]), "document": document,
            "document_sha256": manifest["document_sha256"], "manifest_sha256": _sha256(manifest_text),
            "hook_path": hook_path, "hook_sha256": manifest["hook_sha256"],
            "sources": list(manifest["sources"]), "permissions_allow": list(allow),
            "characters": len(document)}


def profile_digest(profile: dict) -> str:
    """One identifier for "this document under this manifest", carried by every hook receipt."""
    return digest({"id": profile["id"], "version": profile["version"],
                   "document_sha256": profile["document_sha256"],
                   "manifest_sha256": profile["manifest_sha256"]})


def delivery_receipt(profile: dict, evidence_directory: Path) -> dict:
    """What was selected and how it was passed. Says nothing about whether the model complied."""
    return {"id": profile["id"], "version": profile["version"],
            "profile_digest": profile_digest(profile),
            "document_sha256": profile["document_sha256"],
            "manifest_sha256": profile["manifest_sha256"], "hook_sha256": profile["hook_sha256"],
            "characters": profile["characters"], "character_limit": MAX_CHARACTERS,
            "document_transport": "--append-system-prompt",
            "hooks_transport": "--settings", "hooks": list(HOOKS_DECLARED),
            "permissions_added": list(profile["permissions_allow"]),
            "sources": [{key: source.get(key) for key in ("source", "path", "commit", "blob",
                                                          "pinned_sha256", "scope")}
                        for source in profile["sources"]],
            "evidence_directory": str(evidence_directory),
            "compliance": "not judged here: delivery of the document is recorded, adherence is not"}


# ---- hook command -------------------------------------------------------------------------------
def quote_argument(value: str) -> str:
    """Quote one argv element so that `sh` and `cmd.exe` both read it as the same single word.

    Backslashes are refused rather than doubled, so Windows paths must arrive with forward
    slashes (see `portable_path`); a path that cannot be written that way is a refusal.
    """
    require(type(value) is str and bool(value), "Hook argument must be a non-empty string")
    if UNQUOTABLE.search(value):
        raise WorkerProfileError("Hook argument contains a character that cannot be quoted for "
                                 "both sh and cmd.exe: " + repr(value))
    return '"' + value + '"'


def portable_path(path) -> str:
    """An absolute path spelled with forward slashes, which Windows and POSIX both accept."""
    return str(Path(path).resolve()).replace("\\", "/")


def hook_command(interpreter, hook_path, evidence_directory, profile_digest_value: str) -> str:
    argv = [portable_path(interpreter), portable_path(hook_path), "--directory",
            portable_path(evidence_directory), "--profile-digest", profile_digest_value]
    return " ".join(quote_argument(part) for part in argv)


def hook_settings(command: str) -> dict:
    """The per-run hook configuration: SessionStart, PostToolUse(Bash) and the two-strike
    PostToolUseFailure matcher only. There is still no Stop hook and no other event."""
    return {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": command}]}],
        "PostToolUse": [{"matcher": HOOK_TOOL_MATCHER,
                         "hooks": [{"type": "command", "command": command}]}],
        FAILURE_EVENT: [{"matcher": FAILURE_TOOL_MATCHER,
                         "hooks": [{"type": "command", "command": command}]}]}}


def merge_settings(base: dict | None, profile: dict, hooks: dict) -> dict:
    """Hooks and the profile's Bash rules are added to the run's settings; nothing is removed.

    The permission mode and every deny rule stay exactly as the run had them, so the profile
    widens Bash within the operator's grant and changes no other policy."""
    merged = json.loads(json.dumps(base or {}))
    permissions = merged.setdefault("permissions", {})
    allow = list(permissions.get("allow") or [])
    for rule in profile["permissions_allow"]:
        if rule not in allow:
            allow.append(rule)
    permissions["allow"] = allow
    permissions.setdefault("deny", [])
    if "hooks" in merged:
        raise WorkerProfileError("Run settings already carry hooks; the profile does not merge into them")
    merged["hooks"] = hooks["hooks"]
    return merged


# ---- environment --------------------------------------------------------------------------------
def verified_interpreter(candidate=None) -> Path:
    """The host interpreter that will stand in front of PATH: it must exist as a file."""
    path = Path(candidate or sys.executable)
    if not (path.is_absolute() and path.is_file()):
        raise WorkerProfileError("Host interpreter for the worker profile is not a file: " + str(path))
    return path.resolve()


def profile_environment(environment: dict, cwd, interpreter: Path) -> tuple[dict, dict]:
    """Put the verified interpreter's directory first on PATH and point PYTHONPATH at
    `<cwd>/src` when it exists. The parent's PYTHONPATH is never inherited (the allow-list in
    `child_environment` already drops it); the report names paths, never secret values."""
    env = dict(environment)
    prefix = str(interpreter.parent)
    existing = env.get("PATH", "")
    parts = [part for part in existing.split(os.pathsep) if part and part != prefix]
    env["PATH"] = os.pathsep.join([prefix, *parts])
    source_root = Path(cwd).resolve() / "src"
    env.pop("PYTHONPATH", None)
    if source_root.is_dir():
        env["PYTHONPATH"] = str(source_root)
    return env, {"path_prefix": prefix, "interpreter": str(interpreter),
                 "pythonpath": env.get("PYTHONPATH"),
                 "note": "PATH is prefixed, not replaced; PYTHONPATH is the candidate's src or unset"}


# ---- evidence -----------------------------------------------------------------------------------
def evidence_root(runtime: dict) -> Path:
    configured = runtime.get("profile_evidence_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    from codex_harness.adapters.configuration import runtime_dir
    return (runtime_dir() / "worker-profile").resolve()


def session_directory(root: Path, session_id: str) -> Path:
    """One directory per session so concurrent runs and restarts never share or overwrite."""
    require(re.fullmatch(r"[0-9a-f-]{36}", session_id) is not None, "Session id must be a UUID")
    directory = root / session_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def hook_receipts(directory: Path, expected_digest: str) -> dict:
    """Read what the hook actually wrote for this session. Absence is "not observed"."""
    counts = {event: 0 for event in HOOK_EVENTS}
    records, foreign, unreadable, sessions = 0, 0, 0, set()
    strikes: list[dict] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            try:
                body = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                unreadable += 1
                continue
            if not isinstance(body, dict) or body.get("profile_digest") != expected_digest:
                foreign += 1
                continue
            records += 1
            event = str(body.get("hook_event_name"))
            counts[event] = counts.get(event, 0) + 1
            if body.get("session_id"):
                sessions.add(str(body["session_id"]))
            if isinstance(body.get("two_strike"), dict):
                strikes.append(body["two_strike"])
    return {"observed": records > 0, "records": records, "events": counts,
            "foreign_records": foreign, "unreadable_records": unreadable,
            "sessions_named": sorted(sessions), "directory": str(directory),
            "two_strike": two_strike_facts(strikes),
            "provenance": "files written by the packaged hook into this session's directory, "
                          "read after the run; a missing file is not observed, not absent",
            "authority": "none: a receipt shows the hook ran, it approves and completes nothing"}


def two_strike_facts(strikes: list) -> dict:
    """What the hook counted, read out of the receipts it wrote (two-strike-001).

    This reader never opens or changes the hook's SQLite state: it projects the facts the hook
    already recorded. A fingerprint is a hash of a normalized symptom, so no command, output or
    error text is carried here, and reaching the threshold marks a research candidate only.
    """
    counted = [strike for strike in strikes if strike.get("status") == "counted"]
    required = sorted({str(strike.get("fingerprint")) for strike in counted
                       if strike.get("research_required") and strike.get("fingerprint")})
    return {"observed": bool(strikes), "failure_observations": len(strikes),
            "counted_failures": len(counted),
            "distinct_fingerprints": len({str(strike.get("fingerprint")) for strike in counted}),
            "unknown_observations": sum(strike.get("status") == "unknown" for strike in strikes),
            "unavailable_observations": sum(strike.get("status") == "unavailable"
                                            for strike in strikes),
            "unknown_reasons": sorted({str(strike.get("reason")) for strike in strikes
                                       if strike.get("status") == "unknown"}),
            "research_required_fingerprints": required, "research_required": len(required),
            "contexts_emitted": sum(bool(strike.get("context_emitted")) for strike in strikes),
            "threshold": STRIKE_THRESHOLD,
            "authority": "none: a repeated symptom is a research candidate, not a confirmed cause, "
                         "and an emitted context is not evidence that research was done"}
