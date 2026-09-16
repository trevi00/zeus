"""CI scope routing for .github/workflows/validation.yml.

Design: docs/zeus/operations/ci-separation-001/SPEC.md. Standard library only; used by the
`changes` (classify), `docs` (docs-check) and `CI gate` (gate) jobs. Every uncertainty routes to
mode=full, and the gate only passes when the recorded job results match the mode exactly.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DOCS_PREFIX = "docs/zeus/operations/"
REGULAR = "100644"
NO_MODE = "000000"
SHA = re.compile(r"^[0-9a-f]{40}$")
ZERO_SHA = "0" * 40
REQUIRED_JOBS = ("changes", "docs", "test", "integration")
EXPECTED = {
    "docs": {"changes": "success", "docs": "success", "test": "skipped", "integration": "skipped"},
    "full": {"changes": "success", "docs": "skipped", "test": "success", "integration": "success"},
}


class ScopeError(Exception):
    """The change set could not be established; the caller falls back to mode=full."""


@dataclass(frozen=True)
class Change:
    status: str
    old_mode: str
    new_mode: str
    path: str


@dataclass(frozen=True)
class Decision:
    mode: str
    reason: str
    changes: tuple[Change, ...] = ()


def git(args: list[str], repo: Path) -> bytes:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=300)
    if done.returncode:
        detail = done.stderr.decode("utf-8", "replace").strip()[:200]
        raise ScopeError(f"git {args[0]} failed: {detail}")
    return done.stdout


def valid_sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA.match(value)) and value != ZERO_SHA


def load_event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        raise ScopeError("GITHUB_EVENT_PATH is not set")
    try:
        event = json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise ScopeError(f"event payload unreadable: {error}") from None
    if not isinstance(event, dict):
        raise ScopeError("event payload is not a JSON object")
    return event


def select_range(event_name: str, event: dict, repo: Path) -> tuple[str, str]:
    """Return (base, head) commits from trusted SHA fields only; anything else raises."""
    if event_name == "pull_request":
        pull = event.get("pull_request")
        pull = pull if isinstance(pull, dict) else {}
        base, head = pull.get("base"), pull.get("head")
        base = base.get("sha") if isinstance(base, dict) else None
        head = head.get("sha") if isinstance(head, dict) else None
        if not (valid_sha(base) and valid_sha(head)):
            raise ScopeError("pull_request base/head sha missing or invalid")
        merge_base = git(["merge-base", base, head], repo).decode("ascii", "replace").strip()
        if not valid_sha(merge_base):
            raise ScopeError("merge-base did not return one commit")
        return merge_base, head
    if event_name == "push":
        base, head = event.get("before"), event.get("after")
        if not (valid_sha(base) and valid_sha(head)):
            raise ScopeError("push before/after sha missing, zero or invalid")
        return base, head
    raise ScopeError(f"event {event_name!r} has no diff range")


def diff_changes(base: str, head: str, repo: Path) -> list[Change]:
    """Parse `git diff --raw -z` (NUL-delimited, so any path bytes stay one record)."""
    raw = git(["diff", "--no-renames", "--raw", "-z", base, head], repo)
    fields = raw.decode("utf-8", "surrogateescape").split("\0")
    if fields.pop() != "":
        raise ScopeError("diff output is not NUL terminated")
    if len(fields) % 2:
        raise ScopeError("diff output has an odd number of records")
    changes = []
    for header, path in zip(fields[::2], fields[1::2]):
        parts = header.split(" ")
        if not header.startswith(":") or len(parts) != 5 or not path:
            raise ScopeError(f"unexpected diff record {header!r}")
        changes.append(Change(parts[4], parts[0][1:], parts[1], path))
    return changes


def docs_violation(change: Change) -> str | None:
    relative = change.path[len(DOCS_PREFIX):] if change.path.startswith(DOCS_PREFIX) else ""
    if not relative or not relative.endswith(".md") or ".." in relative.split("/"):
        return "path outside the operations Markdown allowlist"
    modes = {"A": (NO_MODE, REGULAR), "M": (REGULAR, REGULAR), "D": (REGULAR, NO_MODE)}
    if modes.get(change.status) != (change.old_mode, change.new_mode):
        return f"status {change.status} {change.old_mode}->{change.new_mode} is not a regular file edit"
    return None


def classify(changes: list[Change]) -> Decision:
    if not changes:
        return Decision("full", "empty diff: no changed paths")
    for change in changes:
        why = docs_violation(change)
        if why:
            return Decision("full", f"{why}: {change.path!r}", tuple(changes))
    return Decision("docs", f"{len(changes)} Markdown change(s) strictly under {DOCS_PREFIX}",
                    tuple(changes))


def decide(repo: Path) -> Decision:
    """Full classification; ScopeError is a routing fact, any other exception is a failure."""
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        base, head = select_range(event_name, load_event(), repo)
        return classify(diff_changes(base, head, repo))
    except ScopeError as error:
        return Decision("full", f"fallback ({event_name or 'no event'}): {error}")


def append(variable: str, text: str) -> None:
    target = os.environ.get(variable)
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)


def run_classify(repo: Path) -> int:
    decision = decide(repo)
    reason = " ".join(decision.reason.split())
    print(f"ci-scope mode={decision.mode} changed={len(decision.changes)} reason={reason}")
    append("GITHUB_OUTPUT", f"mode={decision.mode}\nchanged={len(decision.changes)}\n")
    listing = "".join(f"- `{c.status}` `{c.path!r}`\n" for c in decision.changes[:50])
    append("GITHUB_STEP_SUMMARY", f"## CI scope\n\nmode: **{decision.mode}**\n\nchanged paths: "
           f"{len(decision.changes)}\n\nreason: {reason}\n\n{listing}")
    return 0


def check_markdown(file: Path) -> str | None:
    if file.is_symlink():
        return "symlink"
    if not file.is_file():
        return "not a regular file"
    data = file.read_bytes()
    if b"\0" in data:
        return "contains NUL"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        return f"invalid UTF-8 at byte {error.start}"
    return None


def run_docs_check(repo: Path) -> int:
    decision = decide(repo)
    if decision.mode != "docs":
        print(f"ci-scope docs-check refused: mode={decision.mode} reason={decision.reason}")
        return 1
    failures = 0
    for change in decision.changes:
        if change.status == "D":
            print(f"ci-scope docs-check removed {change.path!r}")
            continue
        problem = check_markdown(repo / change.path)
        failures += problem is not None
        print(f"ci-scope docs-check {'FAIL ' + problem if problem else 'ok'} {change.path!r}")
    print(f"ci-scope docs-check checked={len(decision.changes)} failures={failures}")
    return 1 if failures else 0


def evaluate_gate(needs: object) -> tuple[bool, str, list[str]]:
    """Exact string comparison of every required job result against the mode's expectation."""
    if not isinstance(needs, dict):
        return False, "unknown", ["needs payload is not a JSON object"]
    results = {}
    for job in REQUIRED_JOBS:
        entry = needs.get(job)
        result = entry.get("result") if isinstance(entry, dict) else None
        results[job] = result if isinstance(result, str) else "missing"
    outputs = needs["changes"].get("outputs") if isinstance(needs.get("changes"), dict) else None
    mode = outputs.get("mode") if isinstance(outputs, dict) else None
    lines = [f"{job}={results[job]}" for job in REQUIRED_JOBS]
    if not isinstance(mode, str) or mode not in EXPECTED:
        return False, "unknown", lines + [f"mode {mode!r} is not docs or full"]
    problems = [f"{job}: expected {want}, got {results[job]}"
                for job, want in EXPECTED[mode].items() if results[job] != want]
    return not problems, mode, lines + problems


def run_gate() -> int:
    try:
        needs = json.loads(os.environ.get("CI_NEEDS", ""))
    except ValueError:
        needs = None
    ok, mode, lines = evaluate_gate(needs)
    print(f"ci-scope gate mode={mode} verdict={'pass' if ok else 'FAIL'}")
    for line in lines:
        print(f"  {line}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo = Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd())
    commands = {"classify": lambda: run_classify(repo), "docs-check": lambda: run_docs_check(repo),
                "gate": run_gate}
    if len(argv) != 1 or argv[0] not in commands:
        print(f"usage: ci_scope.py {{{'|'.join(commands)}}}", file=sys.stderr)
        return 2
    return commands[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
