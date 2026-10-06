"""The one fixed monitor frontend capability (operating-portfolio-001, completion batch 2026-09-20).

`python -m codex_harness.adapters.monitor_frontend_checks` takes NO argument, not even `--help`.
It is not a command runner: the project (`frontend/monitor` under the cwd), the toolchain
(`/usr/local/bin/node` plus the frozen dependency store the image put at `/opt/zeus-monitor`) and
the three checks (`eslint .`, `tsc -b`, `vite build` into an explicit temporary outDir) are fixed
here, and nothing in the environment, the argv or the candidate can name another tool, another
path or another check.

What it does: refuse unreadable inputs and a candidate `package.json`/`package-lock.json` that
differ by one byte from the image's, copy the candidate monitor source and config into a uniquely
owned temporary directory (never `node_modules`, `dist` or `.git`, never a symlink that leaves the
candidate), bind the image's frozen dependencies into that copy, run the three checks there through
the existing bounded `_capture`, and print one JSON observation of what actually happened.

What it is not: no installation, no download, no shell, no host credential and no native Windows
fallback; the checkout and the packaged observatory are read, never written. A check failure, a
missing tool, a timeout, truncated output, a mutated source tree or cleanup debt all leave a
nonzero exit and a named defect, and a check that did not run is reported as `not_run` — this
command never claims a check it did not execute. It observes capability only: a green run is
evidence that the pinned toolchain builds this candidate, never human scenario acceptance.

INV-EVIDENCE-001: the exact argv is granted once by the packaged evidence policy and the worker
profile, so the same command replays unchanged in the verifier's fresh, network-free container
(INV-ISOLATED-WORKER-001) and the replayed exit status, not this text, decides the verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from codex_harness.adapters.evidence_inspection import _capture

SCHEMA = "zeus.monitor-frontend-checks/v1"
PROJECT = ("frontend", "monitor")
# Image-bound, not configurable: the node the image installed and the store `npm ci` froze there.
NODE = Path("/usr/local/bin/node")
DEPENDENCY_ROOT = Path("/opt/zeus-monitor")
MANIFESTS = ("package.json", "package-lock.json")
EXCLUDED = frozenset({"node_modules", "dist", ".git"})
OUTPUT_DIRECTORY = ".zeus-build-output"
# Every check is one trusted dependency entrypoint under the image store, run by the fixed node.
CHECKS = (
    {"id": "eslint", "entrypoint": ("eslint", "bin", "eslint.js"), "arguments": (".",)},
    {"id": "typecheck", "entrypoint": ("typescript", "bin", "tsc"), "arguments": ("-b",)},
    {"id": "build", "entrypoint": ("vite", "bin", "vite.js"), "arguments": ("build", "--outDir")},
)
CHECK_IDS = tuple(check["id"] for check in CHECKS)
# Budgets: the outer replay allows 300s per command (resources/evidence-policy.json), so the whole
# observation stays inside that without the policy deadline being raised for anything else.
PER_CHECK_SECONDS = 120
TOTAL_SECONDS = 240
MIN_CHECK_SECONDS = 5
CAPTURE_BYTES = 262144
MAX_STREAM_CHARACTERS = 2000
MAX_FILES = 4000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
OBSERVATORY = ("src", "codex_harness", "resources", "observatory")
EXIT_OK, EXIT_FAILED, EXIT_INVOCATION = 0, 1, 2
LIMITATIONS = (
    "Dependencies are the image's frozen store, bound into the disposable copy; this command "
    "installs nothing and reaches no network.",
    "Only the three named checks run: nothing else about the monitor frontend is asserted.",
    "A passing run is capability evidence for this candidate under the pinned toolchain, not "
    "human scenario acceptance and not a statement about the deployed product.",
)


class _Refusal(Exception):
    """A refusal before or between checks. `kind` and `detail` are fixed words or relative paths."""

    def __init__(self, kind: str, detail: str | None = None):
        super().__init__(kind)
        self.kind, self.detail = kind, detail


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def _tree_digest(files: dict) -> str:
    return hashlib.sha256(json.dumps(sorted(files.items()), sort_keys=True).encode("utf-8")).hexdigest()


def scan_source(root: Path, boundary: Path) -> dict:
    """`{relative path: sha256}` of the monitor sources, or a refusal.

    `node_modules`, `dist` and `.git` are excluded wherever they appear, a symlink that resolves
    outside `boundary` (the candidate) is refused rather than followed, and anything that is
    neither a regular file nor a directory is refused. Bounded in count and bytes so an unexpected
    tree is a named refusal instead of an unbounded read. This is deliberately not
    `isolated_worker.scan_tree`: that one owns Docker snapshotting, refuses every symlink and keeps
    its own exclusion list; the contract here is the monitor project's.
    """
    files: dict[str, str] = {}
    visited: set[str] = set()
    total, stack = 0, [(root, ())]
    while stack:
        directory, parts = stack.pop()
        try:
            with os.scandir(directory) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError as exc:
            raise _Refusal("source_unreadable", "/".join(parts) or ".") from exc
        for entry in entries:
            if entry.name in EXCLUDED:
                continue
            relative = "/".join((*parts, entry.name))
            path = Path(entry.path)
            if entry.is_symlink():
                try:
                    target = path.resolve(strict=True)
                except OSError as exc:
                    raise _Refusal("source_unreadable", relative) from exc
                if target != boundary and boundary not in target.parents:
                    raise _Refusal("source_symlink_escape", relative)
            try:
                is_directory, is_file = entry.is_dir(), entry.is_file()
                size = entry.stat().st_size if is_file else 0
            except OSError as exc:
                raise _Refusal("source_unreadable", relative) from exc
            if is_directory:
                real = str(path.resolve())
                if real in visited:  # a contained directory link never walks its own ancestor twice
                    continue
                visited.add(real)
                stack.append((path, (*parts, entry.name)))
                continue
            if not is_file:
                raise _Refusal("source_special_file", relative)
            if size > MAX_FILE_BYTES:
                raise _Refusal("source_file_too_large", relative)
            total += size
            if len(files) >= MAX_FILES or total > MAX_TOTAL_BYTES:
                raise _Refusal("source_too_large", relative)
            try:
                files[relative] = _file_digest(path)
            except OSError as exc:
                raise _Refusal("source_unreadable", relative) from exc
    return files


def _copy_source(root: Path, files: dict, destination: Path) -> None:
    for relative in sorted(files):
        target = destination.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root.joinpath(*relative.split("/")), target)  # content, never a link


def _bind_dependencies(project: Path, store: Path) -> dict:
    """The image's frozen store, bound entry by entry into the disposable copy.

    One symlink per top-level package keeps `node_modules` itself a real directory of this copy, so
    the tools' own writes (`tsc -b` puts its build info under `node_modules/.tmp`) land in the
    temporary directory and the packaged store stays exactly as the image built it.
    """
    target = project / "node_modules"
    target.mkdir()
    names = sorted(name for name in os.listdir(store) if name != ".tmp")
    for name in names:
        os.symlink(store / name, target / name)
    (target / ".tmp").mkdir()
    return {"root": str(store), "entries": len(names), "binding": "symlink_per_entry",
            "note": "read-only use of the image store; tool writes stay in the temporary copy"}


def _environment(temporary: Path, node: Path) -> dict:
    """A fixed, credential-free child environment. The host environment is never read."""
    for name in ("home", "tmp", "cache"):
        (temporary / name).mkdir(exist_ok=True)
    return {"PATH": os.pathsep.join([str(node.parent), "/usr/local/bin", "/usr/bin", "/bin"]),
            "HOME": str(temporary / "home"), "TMPDIR": str(temporary / "tmp"),
            "XDG_CACHE_HOME": str(temporary / "cache"), "LANG": "C.UTF-8",
            "NO_COLOR": "1", "CI": "1"}


def _stream(record: dict, check_id: str, name: str) -> dict:
    """One captured stream with its fixed identity label; the tail is reported, never invented."""
    raw = record.get(name)
    label = f"monitor_frontend_checks.{check_id}.{name}"
    if not isinstance(raw, dict):
        return {"label": label, "observed": False}
    text = raw["raw"].encode("latin-1").decode("utf-8", "replace")
    tail = text[-MAX_STREAM_CHARACTERS:]
    return {"label": label, "observed": True, "sha256": raw["sha256"], "bytes": raw["bytes"],
            "capture_truncated": bool(raw["truncated"]), "report_truncated": len(tail) < len(text),
            "decoding": raw["decoding"], "text": tail}


def _classify(record: dict) -> str:
    failure = record.get("failure") or ""
    if failure.startswith(("executable_missing", "permission_denied", "spawn_error")):
        return "unavailable"
    if record.get("terminated") or failure.startswith("timeout"):
        return "timeout"
    if "capture_cleanup_unconfirmed" in failure:
        return "cleanup_debt"
    if failure:
        return "error"
    return "passed" if record.get("returncode") == 0 else "failed"


def _not_run(check_id: str, reason: str) -> dict:
    return {"id": check_id, "status": "not_run", "reason": reason, "exit_code": None, "argv": None,
            "duration_seconds": None, "cleanup_confirmed": None}


def _run_checks(project: Path, store: Path, node: Path, environment: dict, capture) -> tuple:
    """The three checks in order, stopping at the first that does not pass; the rest are `not_run`."""
    results, defects = [], []
    deadline = time.monotonic() + TOTAL_SECONDS
    stopped = None
    for check in CHECKS:
        if stopped is not None:
            results.append(_not_run(check["id"], "earlier_check_" + stopped))
            continue
        entrypoint = store.joinpath("node_modules", *check["entrypoint"])
        if not entrypoint.is_file():
            results.append({**_not_run(check["id"], "entrypoint_missing"), "status": "unavailable",
                            "entrypoint": str(entrypoint)})
            defects.append("toolchain_unavailable:" + check["id"])
            stopped = "unavailable"
            continue
        arguments = list(check["arguments"])
        if check["id"] == "build":
            arguments.append(str(project / OUTPUT_DIRECTORY))
        argv = [str(node), str(entrypoint), *arguments]
        remaining = deadline - time.monotonic()
        if remaining < MIN_CHECK_SECONDS:
            results.append(_not_run(check["id"], "budget_exhausted"))
            defects.append("budget_exhausted:" + check["id"])
            stopped = "budget_exhausted"
            continue
        record = capture(argv, str(project), min(PER_CHECK_SECONDS, remaining), CAPTURE_BYTES, dict(environment))
        status = _classify(record)
        cleanup = record.get("cleanup") or {}
        result = {"id": check["id"], "status": status, "exit_code": record.get("returncode"),
                  "argv": argv, "cwd": str(project), "duration_seconds": record.get("duration_seconds"),
                  "failure": record.get("failure"), "cleanup_confirmed": bool(cleanup.get("confirmed")),
                  "cleanup": cleanup,
                  "stdout": _stream(record, check["id"], "stdout"),
                  "stderr": _stream(record, check["id"], "stderr")}
        results.append(result)
        if status != "passed":
            defects.append(("check_" + status) + ":" + check["id"])
            stopped = status
            continue
        for name in ("stdout", "stderr"):
            if result[name].get("capture_truncated"):
                defects.append("output_truncated:" + check["id"] + "." + name)
        if not result["cleanup_confirmed"]:
            defects.append("cleanup_debt:" + check["id"])
    return results, defects


def _cleanup(temporary: Path, results: list) -> dict:
    """Remove only this run's own temporary directory, and only with no live child debt."""
    debt = [result["id"] for result in results if result.get("cleanup_confirmed") is False]
    if debt:
        return {"directory": str(temporary), "removed": False, "reason": "capture_cleanup_unconfirmed",
                "checks_with_debt": debt}
    try:
        shutil.rmtree(temporary)
    except OSError as exc:
        return {"directory": str(temporary), "removed": False, "reason": "rmtree_failed",
                "error": type(exc).__name__}
    return {"directory": str(temporary), "removed": True, "reason": "owned_temporary_directory"}


def observe(cwd, *, node=None, dependencies=None, capture=_capture) -> dict:
    """The complete observation for the candidate at `cwd`. Never raises for an input defect.

    `node`, `dependencies` and `capture` exist so a test can bind a labelled fixture toolchain; the
    command itself always uses the image-bound constants above and reads no setting.
    """
    node = node if node is not None else NODE
    store = dependencies if dependencies is not None else DEPENDENCY_ROOT
    report = {"schema": SCHEMA, "status": "unavailable", "candidate": str(cwd),
              "project": "/".join(PROJECT), "node": str(node), "dependency_root": str(store),
              "checks": [_not_run(check_id, "refused_before_checks") for check_id in CHECK_IDS],
              "defects": [], "limitations": list(LIMITATIONS),
              "authority": "capability observation only: the replayed exit status decides, "
                           "and this command approves, accepts and promotes nothing"}
    # Decided before any path is even constructed: there is no native Windows toolchain here.
    if os.name != "posix":
        return {**report, "refusal": {"kind": "unsupported_host", "detail": os.name},
                "defects": ["unsupported_host"]}
    node, store = Path(node), Path(store)
    candidate = Path(cwd).resolve()
    report["candidate"] = str(candidate)
    temporary = None
    try:
        project = candidate.joinpath(*PROJECT)
        if not project.is_dir():
            raise _Refusal("monitor_project_missing", "/".join(PROJECT))
        if not node.is_file():
            raise _Refusal("node_missing", str(node))
        if not (store / "node_modules").is_dir():
            raise _Refusal("dependencies_missing", str(store / "node_modules"))
        packages = {}
        for name in MANIFESTS:
            for side, root in (("candidate", project), ("image", store)):
                path = root / name
                if not path.is_file():
                    raise _Refusal("manifest_missing", side + ":" + name)
                try:
                    packages[side + ":" + name] = _file_digest(path)
                except OSError as exc:
                    raise _Refusal("manifest_unreadable", side + ":" + name) from exc
        report["packages"] = {**packages, "match": all(
            packages["candidate:" + name] == packages["image:" + name] for name in MANIFESTS)}
        if not report["packages"]["match"]:
            raise _Refusal("package_manifest_mismatch", ",".join(
                name for name in MANIFESTS if packages["candidate:" + name] != packages["image:" + name]))
        before = scan_source(project, candidate)
        observatory = candidate.joinpath(*OBSERVATORY)
        observatory_before = _tree_digest(scan_source(observatory, candidate)) if observatory.is_dir() else None
        report["source"] = {"files": len(before), "sha256": _tree_digest(before),
                            "excluded": sorted(EXCLUDED)}
        temporary = Path(tempfile.mkdtemp(prefix="zeus-monitor-checks-")).resolve()
        report["temporary_directory"] = str(temporary)
        copy = temporary / "source"
        copy.mkdir()
        _copy_source(project, before, copy)
        report["dependencies"] = _bind_dependencies(copy, store / "node_modules")
        results, defects = _run_checks(copy, store, node, _environment(temporary, node), capture)
        report["checks"], report["defects"] = results, defects
        after = scan_source(project, candidate)
        report["source"]["sha256_after_checks"] = _tree_digest(after)
        report["source"]["unchanged"] = after == before
        if not report["source"]["unchanged"]:
            report["defects"].append("source_mutated")
        if observatory_before is not None:
            unchanged = observatory_before == _tree_digest(scan_source(observatory, candidate))
            report["packaged_observatory"] = {"path": "/".join(OBSERVATORY), "unchanged": unchanged}
            if not unchanged:
                report["defects"].append("packaged_observatory_mutated")
        report["cleanup"] = _cleanup(temporary, results)
        if not report["cleanup"]["removed"]:
            report["defects"].append("temporary_directory_retained")
        report["status"] = "failed" if report["defects"] else "ok"
        return report
    except _Refusal as refusal:
        report["refusal"] = {"kind": refusal.kind, "detail": refusal.detail}
        report["defects"] = [refusal.kind]
        if temporary is not None:
            report["cleanup"] = _cleanup(temporary, [])
        return report


def _emit(body: dict) -> None:
    sys.stdout.write(json.dumps(body, ensure_ascii=True, sort_keys=True) + "\n")


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit({"schema": SCHEMA, "status": "error", "error": {"kind": "invalid_invocation"},
               "usage": "python -m codex_harness.adapters.monitor_frontend_checks (no arguments)"})
        return EXIT_INVOCATION
    try:
        body = observe(Path.cwd())
    except Exception:  # noqa: BLE001 - the kind is reported; exception text never is
        _emit({"schema": SCHEMA, "status": "error", "error": {"kind": "internal_error"}})
        return EXIT_FAILED
    _emit(body)
    return EXIT_OK if body["status"] == "ok" else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
