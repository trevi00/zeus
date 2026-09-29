"""Scenario body `context.worker_profile_entry` (REBUILD-DESIGN-v2 §5.2a, §5.3 S2: the exact
worker-profile metadata command; INV-WORKER-PROFILE-001).

Layer: harness (never shipped); standard library only.

`python -m codex_harness.adapters.worker_profile_metadata` is run exactly as AGENTS.md states it:
from the checkout root, no arguments, by the side's own interpreter (the reference from the SOURCE
archive root, the target from `target/`, the root of the target distribution). Refusals: `--help` and
an extra argument (exit 2). Mismatches: copies of the three resource files with a stale document
digest, a stale hook digest, an overlong document, a wrong id and a missing hook (exit 1 with the
computed facts). The packaged hook runs as `-m codex_harness.resources.worker_profile_hook` on
synthetic events. Process-generated values (pid, time_ns, the receipt file name) are reported as
relational facts, never compared by value, so no mask is needed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

RESOURCES = ("src", "codex_harness", "resources")
NAMES = ("worker-profile-v1.json", "worker-profile-v1.md", "worker_profile_hook.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(python: str, cwd: Path, env: dict, argv: list, stdin: bytes = b"") -> dict:
    done = subprocess.run([python, *argv], input=stdin, capture_output=True, timeout=60, cwd=str(cwd), env=env)
    row = {"argv": ["python", *argv[:2], *(["<args>"] if len(argv) > 2 else [])], "exit": done.returncode,
           "stdout_sha256": sha(done.stdout), "stdout_bytes": len(done.stdout),
           "stderr_bytes": len(done.stderr)}
    try:
        row["json"] = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]
    except ValueError:
        row["json"] = None
    return row


def copy_checkout(root: Path, work: Path, name: str, edit) -> Path:
    tree = work / name
    target = tree.joinpath(*RESOURCES)
    target.mkdir(parents=True)
    for file_name in NAMES:
        shutil.copyfile(root.joinpath(*RESOURCES, file_name), target / file_name)
    edit(target)
    return tree


def edit_manifest(key, value):
    def edit(directory: Path):
        path = directory / "worker-profile-v1.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if value is None:
            manifest.pop(key, None)
        else:
            manifest[key] = value
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return edit


def overlong(directory: Path):
    (directory / "worker-profile-v1.md").write_text("x" * 15001, encoding="utf-8")


def run_all(python: str, checkout_root: Path, work: Path, env: dict) -> dict:
    module = ["-m", "codex_harness.adapters.worker_profile_metadata"]
    out = {"metadata": {
        "no_arguments_from_checkout_root": run(python, checkout_root, env, module),
        "help": run(python, checkout_root, env, [*module, "--help"]),
        "extra_argument": run(python, checkout_root, env, [*module, "extra"]),
        "not_a_checkout": run(python, work, env, module),
    }}
    variants = {
        "stale_document_digest": edit_manifest("document_sha256", "0" * 64),
        "stale_hook_digest": edit_manifest("hook_sha256", "1" * 64),
        "hook_not_declared": edit_manifest("hook", None),
        "wrong_hook": edit_manifest("hook", "other_hook.py"),
        "wrong_id": edit_manifest("id", "worker-v2"),
        "wrong_limit": edit_manifest("character_limit", 16000),
        "overlong_document": overlong,
        "manifest_not_json": lambda d: (d / "worker-profile-v1.json").write_text("{", encoding="utf-8"),
        "hook_missing": lambda d: (d / "worker_profile_hook.py").unlink(),
    }
    for name, edit in variants.items():
        tree = copy_checkout(checkout_root, work, name, edit)
        out["metadata"][name] = run(python, tree, env, module)
    hook = ["-m", "codex_harness.resources.worker_profile_hook"]
    directory = work / "hook-receipts"
    events = {
        "allowed_bash": {"hook_event_name": "PostToolUse", "session_id": "s2-session", "tool_name": "Bash",
                         "tool_use_id": "tu-1", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "x"}},
        "session_start": {"hook_event_name": "SessionStart", "session_id": "s2-session", "source": "startup"},
        "denied_write_1": {"hook_event_name": "PostToolUseFailure", "session_id": "s2-session", "tool_name": "Write",
                           "tool_use_id": "tu-2", "tool_input": {"file_path": "/denied/a.txt"},
                           "error": "Permission denied: /denied/a.txt"},
        "denied_write_2": {"hook_event_name": "PostToolUseFailure", "session_id": "s2-session", "tool_name": "Write",
                           "tool_use_id": "tu-3", "tool_input": {"file_path": "/denied/b.txt"},
                           "error": "Permission denied: /denied/b.txt"},
        "malformed_json": None,
    }
    hooks = {"no_arguments": run(python, work, env, hook)}
    for name, event in events.items():
        before = set(directory.glob("*.json")) if directory.exists() else set()
        stdin = b"{not json" if event is None else json.dumps(event).encode()
        row = run(python, work, env, [*hook, "--directory", str(directory), "--profile-digest", "d" * 64], stdin)
        receipts = []
        for path in sorted(set(directory.glob("*.json")) - before):
            body = json.loads(path.read_text(encoding="utf-8"))
            receipts.append({
                **{k: v for k, v in body.items() if k not in {"pid", "recorded_at_ns"}},
                "pid_is_positive_int": type(body.get("pid")) is int and body["pid"] > 0,
                "recorded_at_ns_is_int": type(body.get("recorded_at_ns")) is int,
                "name_embeds_time_and_pid": re.fullmatch(
                    rf"{re.escape(str(body.get('hook_event_name')))}-{re.escape(str(body.get('tool_name') or 'none'))}-"
                    rf"{body.get('recorded_at_ns')}-{body.get('pid')}-[0-9a-f]{{8}}\.json", path.name) is not None})
        row["receipts"] = receipts
        hooks[name] = row
    hooks["state_files"] = sorted(p.name for p in directory.iterdir() if not p.name.endswith(".json"))
    out["hook"] = hooks
    return out
