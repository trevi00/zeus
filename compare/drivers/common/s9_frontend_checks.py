"""Shared S9 scenario steps (`observation.frontend_checks`): M7 `adapters/monitor_frontend_checks.py` (U9), the one fixed monitor frontend capability.

Layer: harness (never shipped)

`api.module` is the side's module (the source scan, the constants and `CHECK_IDS`); `api.observe(cwd, node=None, dependencies=None, capture=None)` and `api.main(argv)` are the
SIDE-NEUTRAL callables. `capture=None` means "the real bounded capture":
- reference: M7's `observe` default (`evidence_inspection._capture`, imported at module level) and M7's `main`;
- target: the composition's capture (OWNER-DECISIONS-S9 D3/D3.1: `functools.partial(_capture, process_tree=ProcessTree)`) injected into `observe(capture=)` and `main(capture=)`.
A non-None `capture` is passed through unchanged on both sides (the injected-record cases).
Mirrors `tests/test_monitor_frontend_checks.py` (14 tests) and adds the bounded source scan (file, size and count caps, excluded directories, special files, dangling and
escaping links), every refusal kind, every outcome class of `_classify` (through injected capture records, the labelled fixture of M7's cleanup-debt test), the dependency binding,
the unchanged-checkout verification and `main` with an argument.

LABELLED FIXTURE (as in M7's tests): node and the image's frozen store are not installed here; the host Python interpreter stands in for `/usr/local/bin/node` and three Python
files stand in for the eslint/tsc/vite entrypoints. No npm, node, network or container runs; every real run is a real child process over real temporary files, so the copy, the
dependency binding, the digests, the bounded capture and the cleanup are the production ones.

Declared nondeterministic fields, normalized HERE and never by the mask list (`compare/masks.json` is untouched): the per-run temporary directories (`zeus-monitor-checks-*`),
this driver's own work directory, the interpreter path (it differs between the two venvs), the OS process and group ids of the capture's cleanup proof (`pid`, `group`, proven positive integers) and every `duration_seconds` (replaced by `<duration>` after being PROVEN to lie between
the wall-clock bounds around the call; a value outside them is `<out-of-bounds>` and cannot equal the golden).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

PY = sys.executable
PACKAGE = b'{\n  "name": "monitor",\n  "private": true\n}\n'
LOCK = b'{\n  "name": "monitor",\n  "lockfileVersion": 3\n}\n'
TOOLS = {"eslint": ("eslint", "bin", "eslint.js"), "typecheck": ("typescript", "bin", "tsc"), "build": ("vite", "bin", "vite.js")}
BODY = """import json, os, sys
entries = []
for base, directories, names in os.walk('.'):
    if 'node_modules' in directories:
        directories.remove('node_modules')
    for name in names:
        entries.append(os.path.relpath(os.path.join(base, name), '.').replace(os.sep, '/'))
json.dump({{'argv': sys.argv, 'cwd': os.getcwd(), 'entries': sorted(entries),
            'dependency_linked': os.path.islink('node_modules/vite'),
            'build_info_writable': os.path.isdir('node_modules/.tmp'),
            'environment': dict(os.environ)}}, open({record!r}, 'w'))
sys.stdout.write('fixture {check} stdout\\n')
sys.stderr.write('fixture {check} stderr\\n')
{extra}
sys.exit({exit_code})
"""
TEMPORARY = re.compile(r"(?:/[^/\"\s:]+)*/zeus-monitor-checks-[A-Za-z0-9_]+")
ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else True


class World:
    """One disposable work directory with the stand-ins; every path in the results is rewritten to a symbolic root."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="s9-frontend-checks-")).resolve()
        self.count = 0
        self.floor, self.ceiling = time.time(), time.time()

    def fresh(self, name):
        self.count += 1
        directory = self.root / f"{self.count:03d}-{name}"
        directory.mkdir()
        return directory

    def close(self):
        for path in sorted(self.root.rglob("*"), reverse=True):
            with contextlib.suppress(OSError):
                if path.is_dir() and not path.is_symlink():
                    path.chmod(0o755)
        shutil.rmtree(self.root, ignore_errors=True)

    def scrub(self, value):
        """JSON-normalize `value` and rewrite the declared nondeterministic strings and durations."""
        text = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
        text = TEMPORARY.sub("<temp>", text)
        text = text.replace(str(self.root), "<work>").replace(PY, "<python>").replace(str(Path(PY).parent), "<python-dir>")
        return self._durations(json.loads(text))

    def _durations(self, node):
        if isinstance(node, dict):
            return {key: ("<pid>" if key in ("pid", "group") and isinstance(item, int) and not isinstance(item, bool) and item > 0
                          else "<not-a-pid>" if key in ("pid", "group") and isinstance(item, int) and not isinstance(item, bool)
                          else "<duration>" if key == "duration_seconds" and isinstance(item, (int, float)) and not isinstance(item, bool) and self._bounded(item)
                          else "<out-of-bounds>" if key == "duration_seconds" and isinstance(item, (int, float)) and not isinstance(item, bool)
                          else self._durations(item)) for key, item in node.items()}
        if isinstance(node, list):
            return [self._durations(item) for item in node]
        return node

    def _bounded(self, seconds):
        return 0 <= seconds <= (time.time() - self.floor) + 1


def candidate_tree(world, name="candidate", observatory=True, excluded=True, manifests=True):
    root = world.fresh(name)
    project = root / "frontend" / "monitor"
    (project / "src" / "views").mkdir(parents=True)
    if manifests:
        (project / "package.json").write_bytes(PACKAGE)
        (project / "package-lock.json").write_bytes(LOCK)
    (project / "eslint.config.js").write_text("export default []\n", encoding="utf-8")
    (project / "src" / "App.tsx").write_text("export const App = () => null\n", encoding="utf-8")
    (project / "src" / "views" / "projects.tsx").write_text("export const P = () => null\n", encoding="utf-8")
    if excluded:
        for directory, file in (("node_modules", "left-over.js"), ("dist", "index.html"), (".git", "HEAD")):
            (project / directory).mkdir()
            (project / directory / file).write_text("never copied", encoding="utf-8")
    if observatory:
        packaged = root.joinpath("src", "codex_harness", "resources", "observatory")
        packaged.mkdir(parents=True)
        (packaged / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    return root


def store_tree(world, name="image-store", manifests=True):
    root = world.fresh(name)
    (root / "node_modules").mkdir()
    if manifests:
        root.joinpath("package.json").write_bytes(PACKAGE)
        root.joinpath("package-lock.json").write_bytes(LOCK)
    return root


def install(store, records, exits=None, extras=None, skip=()):
    exits, extras = exits or {}, extras or {}
    for check, parts in TOOLS.items():
        if check in skip:
            continue
        entrypoint = store.joinpath("node_modules", *parts)
        entrypoint.parent.mkdir(parents=True, exist_ok=True)
        extra = extras.get(check, "")
        if check == "build":
            extra = "os.makedirs(sys.argv[sys.argv.index('--outDir') + 1], exist_ok=True)\n" + extra
        entrypoint.write_text(BODY.format(record=str(records / (check + ".json")), check=check, extra=extra, exit_code=exits.get(check, 0)), encoding="utf-8")
    return store


def observed(records, check):
    path = records / (check + ".json")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@contextlib.contextmanager
def patched(module, **values):
    saved = {name: getattr(module, name) for name in values}
    for name, value in values.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def entry(check):
    return {key: check.get(key) for key in ("id", "status", "reason", "exit_code", "failure", "cleanup_confirmed")}


def brief(report):
    """The observation without its fixed prose: status, refusal, defects, per-check outcome, source/packages/cleanup facts."""
    return {"status": report.get("status"), "refusal": report.get("refusal"), "defects": report.get("defects"),
            "checks": [entry(check) for check in report.get("checks", [])], "packages": report.get("packages"), "source": report.get("source"),
            "dependencies": report.get("dependencies"), "packaged_observatory": report.get("packaged_observatory"),
            "has_temporary_directory": "temporary_directory" in report, "cleanup": report.get("cleanup")}


def run_observe(api, world, name, builder=None, *, node=PY, patches=None, capture=None, setup=None, full=False, tool_records=("eslint", "typecheck", "build"), **install_args):
    """One observation over a fresh candidate/store/records: returns the scrubbed report (full or brief) plus what each fixture tool saw."""
    candidate = candidate_tree(world, name + "-candidate")
    store = store_tree(world, name + "-store")
    records = world.fresh(name + "-records")
    install(store, records, **install_args)
    if setup:
        setup(candidate, store, records)
    nodeargument = node(store) if callable(node) else node
    start = time.time()
    with patched(api.module, **(patches or {})):
        report = api.observe(candidate, node=nodeargument, dependencies=store, capture=capture)
    world.floor = start
    out = {"report": world.scrub(report if full else brief(report)),
           "tools_saw": {check: world.scrub(observed(records, check)) for check in tool_records},
           "candidate_after": sorted(str(p.relative_to(candidate)) for p in candidate.rglob("*") if p.is_file())}
    for retained in report.get("temporary_directory", None), report.get("cleanup", {}).get("directory"):
        if retained and Path(retained).exists():
            out["retained_directory_exists"] = True
            force_remove(Path(retained))
    return out


def force_remove(path):
    """Test hygiene for a retained directory (a debt that was injected, or a subdirectory a fixture tool locked)."""
    pending = [path]
    while pending:
        directory = pending.pop()
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)
            pending.extend(directory.iterdir())
    shutil.rmtree(path)


def refused(call):
    try:
        return {"value": call()}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "kind": getattr(exc, "kind", None), "detail": getattr(exc, "detail", None)}


# ----------------------------------------------------------------------------------------------------------------------------- injected capture records


def stream(raw: bytes, truncated=False, decoding="utf-8"):
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "truncated": truncated, "decoding": decoding, "raw": raw.decode("latin-1")}


def record(**fields):
    base = {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.25, "stdout": stream(b"out\n"), "stderr": stream(b""),
            "cleanup": {"reason": "exited", "confirmed": True, "readers_alive": [], "streams_closed": ["stdout", "stderr"], "error": None, "tree": None}}
    base.update(fields)
    return base


class Scripted:
    """An injected capture: one scripted record per call (by check order), logging how it was called."""

    def __init__(self, *records):
        self.records, self.calls = list(records), []

    def __call__(self, *args, **kwargs):
        self.calls.append({"argv_shape": [Path(args[0][0]).name, Path(args[0][1]).name, *args[0][2:]], "cwd_name": Path(args[1]).name, "timeout": round(args[2], 0),
                           "max_bytes": args[3], "env_keys": sorted(args[4]), "extra_args": len(args) - 5, "kwargs": sorted(kwargs)})
        item = self.records[min(len(self.calls), len(self.records)) - 1]
        if isinstance(item, Exception):
            raise item
        return dict(item)


def scripted_case(api, world, name, *records, patches=None):
    script = Scripted(*records)
    out = run_observe(api, world, name, capture=script, patches=patches, full=False)
    out["capture_calls"] = world.scrub(script.calls)
    return out


def classify_cases(api, world):
    debt = {"reason": "exited", "confirmed": False, "readers_alive": ["stdout"], "streams_closed": [], "error": None, "tree": None}
    long_text = ("é" * 1500 + "tail-marker").encode("utf-8")
    broken = b"ok \xff\xfe bytes\n"
    cases = {
        "passed_all": [record(), record(), record()],
        "failed_exit_1": [record(returncode=1)],
        "failed_exit_none": [record(returncode=None)],
        "unavailable_executable_missing": [record(failure="executable_missing: [Errno 2] no such file", returncode=None)],
        "unavailable_permission_denied": [record(failure="permission_denied: [Errno 13]", returncode=None)],
        "unavailable_spawn_error": [record(failure="spawn_error: OSError: boom", returncode=None)],
        "timeout_terminated": [record(terminated=True, failure="timeout after 120s; process tree terminated", returncode=-9)],
        "timeout_failure_only": [record(failure="timeout after 120s; elsewhere")],
        "cleanup_debt": [record(failure="capture_cleanup_unconfirmed: readers still own stdout", cleanup=debt)],
        "cleanup_debt_second_check_passes_unconfirmed": [record(), record(cleanup=debt), record()],
        "error_other_failure": [record(failure="something else entirely")],
        "cleanup_unconfirmed_without_failure_on_pass": [record(cleanup=debt)],
        "stream_not_a_mapping": [record(stdout=None, stderr="not a dict"), record(), record()],
        "stream_report_truncated_at_2000_characters": [record(stdout=stream(long_text)), record(), record()],
        "stream_invalid_utf8_decoded_with_replacement": [record(stdout=stream(broken, decoding="invalid_utf8: bad byte")), record(), record()],
        "stream_capture_truncated_is_a_defect": [record(stdout=stream(b"x" * 8, truncated=True), stderr=stream(b"y" * 8, truncated=True)), record(), record()],
        "cleanup_record_absent": [record(cleanup=None), record(), record()],
        "record_without_streams": [{"returncode": 0}, {"returncode": 0}, {"returncode": 0}],
    }
    return {key: scripted_case(api, world, key, *value) for key, value in cases.items()}


# ----------------------------------------------------------------------------------------------------------------------------- scan, refusals, real runs


def scan_cases(api, world):
    module = api.module
    out = {}

    def scan(name, build, **limits):
        root = world.fresh("scan-" + name)
        boundary = root
        build(root)
        with patched(module, **limits):
            result = refused(lambda: module.scan_source(root, boundary))
        if "value" in result:
            result = {"files": sorted(result["value"]), "digests": sorted(result["value"].values()), "count": len(result["value"])}
        out[name] = world.scrub(result)

    def basic(root):
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("a\n", encoding="utf-8")
        (root / "b.ts").write_text("b\n", encoding="utf-8")
        for directory in ("node_modules", "dist", ".git"):
            (root / directory).mkdir()
            (root / directory / "x.js").write_text("x\n", encoding="utf-8")
            (root / "src" / directory).mkdir()
            (root / "src" / directory / "nested.js").write_text("nested excluded\n", encoding="utf-8")
        (root / "src" / "node_modules_like").mkdir()
        (root / "src" / "node_modules_like" / "kept.ts").write_text("kept\n", encoding="utf-8")
        (root / "src" / ".gitkeep").write_text("\n", encoding="utf-8")

    scan("excluded_directories_at_every_depth", basic)
    scan("empty_tree", lambda root: None)
    scan("file_count_cap_reached", basic, MAX_FILES=3)
    scan("file_count_cap_exactly_met", basic, MAX_FILES=4)
    scan("one_file_over_the_per_file_cap", lambda root: (root / "big.bin").write_bytes(b"x" * 11), MAX_FILE_BYTES=10)
    scan("one_file_at_the_per_file_cap", lambda root: (root / "big.bin").write_bytes(b"x" * 10), MAX_FILE_BYTES=10)
    scan("total_bytes_cap", lambda root: [(root / name).write_bytes(b"x" * 6) for name in ("a", "b", "c")], MAX_TOTAL_BYTES=15)
    scan("total_bytes_cap_exactly_met", lambda root: [(root / name).write_bytes(b"x" * 5) for name in ("a", "b", "c")], MAX_TOTAL_BYTES=15)

    def fifo(root):
        (root / "ok.ts").write_text("ok\n", encoding="utf-8")
        os.mkfifo(root / "pipe")

    scan("a_special_file_is_refused", fifo)

    def dangling(root):
        (root / "gone.ts").symlink_to(root / "no-such-target")

    scan("a_dangling_link_is_unreadable", dangling)

    def inside(root):
        (root / "real").mkdir()
        (root / "real" / "f.ts").write_text("f\n", encoding="utf-8")
        (root / "link-file").symlink_to(root / "real" / "f.ts")
        (root / "link-dir").symlink_to(root / "real", target_is_directory=True)
        (root / "real" / "up").symlink_to(root, target_is_directory=True)

    scan("contained_links_and_a_directory_cycle", inside)

    def outside(root):
        elsewhere = world.fresh("scan-outside-target")
        (elsewhere / "secret.txt").write_text("never read\n", encoding="utf-8")
        (root / "escape").symlink_to(elsewhere / "secret.txt")

    scan("a_link_leaving_the_boundary_is_refused", outside)

    def outside_dir(root):
        elsewhere = world.fresh("scan-outside-directory")
        (root / "src").mkdir()
        (root / "src" / "dirlink").symlink_to(elsewhere, target_is_directory=True)

    scan("a_directory_link_leaving_the_boundary_is_refused", outside_dir)
    out["unreadable_directory"] = _unreadable(world, module)
    out["root_directory_missing"] = world.scrub(refused(lambda: module.scan_source(world.root / "no-such-directory", world.root)))
    return out


def _unreadable(world, module):
    if ROOT:
        return {"skipped": "root"}
    root = world.fresh("scan-unreadable")
    (root / "locked").mkdir()
    (root / "locked" / "f.ts").write_text("f\n", encoding="utf-8")
    (root / "locked").chmod(0)
    try:
        return world.scrub(refused(lambda: module.scan_source(root, root)))
    finally:
        (root / "locked").chmod(0o755)


def refusal_cases(api, world):
    out = {}

    def case(name, **kwargs):
        out[name] = run_observe(api, world, name, **kwargs)

    # monitor_project_missing
    empty = world.fresh("empty-candidate")
    store = install(store_tree(world, "empty-store"), world.fresh("empty-records"))
    out["monitor_project_missing"] = world.scrub(brief(api.observe(empty, node=PY, dependencies=store)))
    out["monitor_project_missing_for_an_absent_directory"] = world.scrub(brief(api.observe(world.root / "never-created", node=PY, dependencies=store)))
    out["monitor_project_missing_accepts_a_string"] = world.scrub(brief(api.observe(str(empty), node=PY, dependencies=store)))
    out["unsupported_host"] = _unsupported(api, world, store)
    case("node_missing", node=lambda store: store / "no-such-node")
    case("node_is_a_directory", node=lambda store: store)
    case("dependencies_missing", setup=lambda candidate, store, records: shutil.rmtree(store / "node_modules"))
    case("candidate_package_json_missing", setup=lambda candidate, store, records: (candidate / "frontend/monitor/package.json").unlink())
    case("candidate_lock_missing", setup=lambda candidate, store, records: (candidate / "frontend/monitor/package-lock.json").unlink())
    case("image_package_json_missing", setup=lambda candidate, store, records: (store / "package.json").unlink())
    case("image_lock_missing", setup=lambda candidate, store, records: (store / "package-lock.json").unlink())
    case("candidate_lock_differs", setup=lambda candidate, store, records: (candidate / "frontend/monitor/package-lock.json").write_bytes(LOCK + b"\n"), full=True)
    case("candidate_package_differs", setup=lambda candidate, store, records: (candidate / "frontend/monitor/package.json").write_bytes(PACKAGE + b" "))
    case("both_manifests_differ", setup=lambda candidate, store, records: [(candidate / "frontend/monitor" / name).write_bytes(b"{}") for name in ("package.json", "package-lock.json")])
    if ROOT:
        out["manifest_unreadable"] = {"skipped": "root"}
    else:
        case("manifest_unreadable", setup=lambda candidate, store, records: _lock_manifest(candidate))
    case("symlink_escape", setup=lambda candidate, store, records: _escape(world, candidate))
    case("symlink_dangling", setup=lambda candidate, store, records: (candidate / "frontend/monitor/src/gone.ts").symlink_to(candidate / "nope"))
    case("special_file", setup=lambda candidate, store, records: os.mkfifo(candidate / "frontend/monitor/src/pipe"))
    case("source_file_too_large", patches={"MAX_FILE_BYTES": 20})
    case("source_too_many_files", patches={"MAX_FILES": 4})
    case("source_too_many_bytes", patches={"MAX_TOTAL_BYTES": 100})
    case("source_caps_met_exactly", patches={"MAX_FILES": 5}, full=False)
    case("contained_link_is_accepted", setup=lambda candidate, store, records: (candidate / "frontend/monitor/src/inside.ts").symlink_to(candidate / "frontend/monitor/src/App.tsx"))
    case("no_packaged_observatory", setup=lambda candidate, store, records: shutil.rmtree(candidate / "src"))
    case("observatory_symlink_escape", setup=lambda candidate, store, records: _escape(world, candidate, relative="src/codex_harness/resources/observatory/leak.html"))
    return out


def _lock_manifest(candidate):
    (candidate / "frontend/monitor/package.json").chmod(0)


def _escape(world, candidate, relative="frontend/monitor/src/escape.ts"):
    outside = world.fresh("outside")
    (outside / "secret.txt").write_text("never read\n", encoding="utf-8")
    (candidate / relative).symlink_to(outside / "secret.txt")


def _unsupported(api, world, store):
    start = time.time()
    saved = os.name
    candidate = candidate_tree(world, "nt-candidate")
    try:
        os.name = "nt"
        report = api.observe(candidate, node=PY, dependencies=store)
    finally:
        os.name = saved
    world.floor = start
    return world.scrub({"status": report["status"], "refusal": report["refusal"], "defects": report["defects"], "keys": sorted(report),
                        "candidate_unresolved": report["candidate"] == str(candidate)})


def real_cases(api, world):
    out = {}
    out["complete_pass_full_report"] = run_observe(api, world, "pass", full=True)
    out["pass_without_excluded_or_observatory"] = _plain(api, world)
    out["readonly_candidate_and_observatory"] = _readonly(api, world)
    out["injected_write_into_the_checkout"] = _mutation(api, world)
    out["injected_write_into_the_packaged_observatory"] = _observatory_mutation(api, world)
    out["failing_check_typecheck"] = run_observe(api, world, "typecheck-fails", exits={"typecheck": 2})
    out["failing_check_eslint"] = run_observe(api, world, "eslint-fails", exits={"eslint": 1})
    out["failing_check_build"] = run_observe(api, world, "build-fails", exits={"build": 3})
    out["missing_entrypoint_build"] = run_observe(api, world, "no-build", skip=("build",))
    out["missing_entrypoint_eslint"] = run_observe(api, world, "no-eslint", skip=("eslint",))
    out["node_not_executable_is_unavailable"] = run_observe(api, world, "node-not-executable", node=lambda store: _plain_file(store), tool_records=())
    out["timeout_terminates_the_tree"] = run_observe(api, world, "timeout", extras={"eslint": "import time\ntime.sleep(30)\n"}, patches={"PER_CHECK_SECONDS": 1})
    out["output_truncated_is_a_defect"] = run_observe(api, world, "truncated", extras={"eslint": "sys.stdout.write('x' * 200000)\n"}, patches={"CAPTURE_BYTES": 2048})
    out["output_truncated_on_stderr_of_the_last_check"] = run_observe(api, world, "truncated-stderr", extras={"build": "sys.stderr.write('y' * 200000)\n"}, patches={"CAPTURE_BYTES": 2048})
    out["report_truncated_tail_of_long_output"] = run_observe(api, world, "long-tail", extras={"eslint": "sys.stdout.write('z' * 5000 + 'END')\n"}, full=False)
    out["budget_exhausted_before_the_first_check"] = run_observe(api, world, "budget-first", patches={"TOTAL_SECONDS": 3})
    out["budget_exhausted_between_checks"] = run_observe(api, world, "budget-middle", extras={"eslint": "import time\ntime.sleep(2)\n"}, patches={"TOTAL_SECONDS": 6})
    out["rmtree_failure_retains_the_directory"] = _rmtree_failure(api, world)
    out["fixed_credential_free_environment"] = _environment(api, world)
    out["concurrent_runs_own_separate_directories"] = _concurrent(api, world)
    out["bind_dependencies_entries"] = _binding(api, world)
    out["non_string_capture_arguments"] = _capture_arguments(api, world)
    return out


def _plain(api, world):
    def build(candidate, store, records):
        shutil.rmtree(candidate / "src")
        for directory in ("node_modules", "dist", ".git"):
            shutil.rmtree(candidate / "frontend/monitor" / directory)
    return run_observe(api, world, "plain", setup=build, full=False)


def _plain_file(store):
    path = store / "not-node"
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def _readonly(api, world):
    candidate = candidate_tree(world, "readonly-candidate")
    store = store_tree(world, "readonly-store")
    records = world.fresh("readonly-records")
    install(store, records)
    before = {str(p.relative_to(candidate)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(candidate.rglob("*")) if p.is_file()}
    report = api.observe(candidate, node=PY, dependencies=store)
    after = {str(p.relative_to(candidate)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(candidate.rglob("*")) if p.is_file()}
    return {"status": report["status"], "checkout_bytes_unchanged": before == after, "files": sorted(before),
            "digests_agree": report["source"]["sha256"] == report["source"]["sha256_after_checks"],
            "observatory": report["packaged_observatory"],
            "observatory_listing": sorted(p.name for p in candidate.joinpath("src/codex_harness/resources/observatory").iterdir()),
            "build_output_in_candidate": any(".zeus-build-output" in name for name in before)}


def _mutation(api, world):
    def script(candidate, store, records):
        target = candidate / "frontend" / "monitor" / "src" / "App.tsx"
        install(store, records, extras={"typecheck": f"open({str(target)!r}, 'a').write('mutated')\n"})
    return run_observe(api, world, "mutation", setup=script)


def _observatory_mutation(api, world):
    def script(candidate, store, records):
        target = candidate / "src" / "codex_harness" / "resources" / "observatory" / "index.html"
        install(store, records, extras={"build": f"open({str(target)!r}, 'a').write('mutated')\n"})
    return run_observe(api, world, "observatory-mutation", setup=script)


def _rmtree_failure(api, world):
    if ROOT:
        return {"skipped": "root"}
    extra = "os.makedirs('locked/inner')\nopen('locked/inner/f', 'w').write('x')\nos.chmod('locked', 0)\n"
    return run_observe(api, world, "rmtree", extras={"build": extra})


def _environment(api, world):
    names = ("ZEUS_SECRET", "ANTHROPIC_API_KEY")
    saved = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = "never-inherited-canary"
        out = run_observe(api, world, "environment", tool_records=("eslint", "typecheck", "build"))
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    environment = out["tools_saw"]["eslint"]["environment"]
    out["canary_absent"] = "never-inherited-canary" not in json.dumps(out)
    out["environment_names"] = sorted(environment)
    return out


def _concurrent(api, world):
    candidate = candidate_tree(world, "concurrent-candidate")
    store = store_tree(world, "concurrent-store")
    records = world.fresh("concurrent-records")
    install(store, records)
    results, lock = [], threading.Lock()

    def run():
        report = api.observe(candidate, node=PY, dependencies=store)
        with lock:
            results.append(report)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    directories = {report["temporary_directory"] for report in results}
    return {"statuses": sorted(report["status"] for report in results), "distinct_directories": len(directories), "all_removed": all(not Path(d).exists() for d in directories),
            "candidate_still_present": candidate.is_dir()}


def _binding(api, world):
    candidate = candidate_tree(world, "binding-candidate")
    store = store_tree(world, "binding-store")
    records = world.fresh("binding-records")
    for name in ("alpha", "vite", ".tmp", "zeta"):
        (store / "node_modules" / name).mkdir(exist_ok=True)
    install(store, records)
    report = api.observe(candidate, node=PY, dependencies=store)
    return world.scrub({"dependencies": report["dependencies"], "status": report["status"], "defects": report["defects"],
                        "tools_saw": {check: (lambda saw: {key: saw[key] for key in ("dependency_linked", "build_info_writable")})(observed(records, check)) for check in TOOLS}})


def _capture_arguments(api, world):
    """What the real capture is handed, seen through a wrapper that forwards to the side's real capture."""
    calls = []
    real = api.real_capture()

    def spy(*args, **kwargs):
        calls.append({"argv_shape": [Path(args[0][0]).name, Path(args[0][1]).name, *[Path(a).name if a.startswith("/") else a for a in args[0][2:]]],
                      "cwd_name": Path(args[1]).name, "timeout": round(args[2], 0), "max_bytes": args[3], "env_keys": sorted(args[4]), "positional": len(args), "kwargs": sorted(kwargs)})
        return real(*args, **kwargs)

    out = run_observe(api, world, "spy", capture=spy)
    out["capture_calls"] = world.scrub(calls)
    return out


# ----------------------------------------------------------------------------------------------------------------------------- main


def main_cases(api, world):
    out = {"refuses_every_argument": {}}
    for arguments in (["--help"], ["frontend/monitor"], [""], ["--json"], ["a", "b"], ["-h"], ["--"]):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = api.main(arguments)
        out["refuses_every_argument"][json.dumps(arguments)] = {"exit": code, "stdout": json.loads(buffer.getvalue()), "single_line": buffer.getvalue().count("\n") == 1}
    empty = world.fresh("main-empty-cwd")
    previous = os.getcwd()
    try:
        os.chdir(empty)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = api.main([])
        out["no_argument_refuses_without_a_project"] = {"exit": code, "stdout": world.scrub(json.loads(buffer.getvalue()))}
        out["no_argument_reads_the_working_directory"] = _main_over_a_tree(api, world, empty)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = api.main(None)
        out["argv_none_reads_sys_argv_which_is_empty_here"] = {"exit": code, "status": json.loads(buffer.getvalue())["status"]}
    finally:
        os.chdir(previous)
    saved = sys.argv
    try:
        sys.argv = ["monitor_frontend_checks", "extra"]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = api.main(None)
        out["argv_none_reads_sys_argv_with_an_argument"] = {"exit": code, "error": json.loads(buffer.getvalue())["error"]}
    finally:
        sys.argv = saved
    out["internal_error_is_a_kind_without_text"] = _internal_error(api)
    return out


def _main_over_a_tree(api, world, empty):
    """`main([])` over a candidate tree as the working directory: the image store is absent, so the node/dependency refusals are the observation."""
    candidate = candidate_tree(world, "main-candidate")
    os.chdir(candidate)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = api.main([])
    os.chdir(empty)
    body = json.loads(buffer.getvalue())
    return world.scrub({"exit": code, "status": body["status"], "refusal": body.get("refusal"), "node": body["node"], "dependency_root": body["dependency_root"],
                        "schema": body["schema"], "keys": sorted(body)})


def _internal_error(api):
    module = api.module
    buffer = io.StringIO()

    def boom(*args, **kwargs):
        raise RuntimeError("secret detail that must never be printed")

    with patched(module, observe=boom), contextlib.redirect_stdout(buffer):
        code = api.main([])
    text = buffer.getvalue()
    return {"exit": code, "stdout": json.loads(text), "secret_printed": "secret detail" in text}


def run(api) -> dict:
    world = World()
    try:
        return {"scan": scan_cases(api, world), "refusals": refusal_cases(api, world), "real": real_cases(api, world), "classify": classify_cases(api, world),
                "main": main_cases(api, world), "constants": constants(api.module)}
    finally:
        world.close()


def constants(module):
    names = ("SCHEMA", "PROJECT", "NODE", "DEPENDENCY_ROOT", "MANIFESTS", "OUTPUT_DIRECTORY", "CHECK_IDS", "PER_CHECK_SECONDS", "TOTAL_SECONDS", "MIN_CHECK_SECONDS",
             "CAPTURE_BYTES", "MAX_STREAM_CHARACTERS", "MAX_FILES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES", "OBSERVATORY", "EXIT_OK", "EXIT_FAILED", "EXIT_INVOCATION", "LIMITATIONS")
    return {name: json.loads(json.dumps(getattr(module, name), default=str)) for name in names} | {"excluded": sorted(module.EXCLUDED),
                                                                                                       "checks": json.loads(json.dumps(module.CHECKS, default=str))}
