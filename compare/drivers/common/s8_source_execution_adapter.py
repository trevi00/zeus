"""Shared S8 scenario steps (`research.source_execution_adapter`): M7 `adapters/source_execution.py` (`SourceExecutionClient`, `bounded_command`,
`DockerSourceRunner`), characterized BEFORE the module moves (DESIGN-s8 §13 V18 R-se0..R-se2).

Every group mirrors an M7 test of `tests/test_research_audits.py` (the test name is the group label) plus LABELLED additions that reach every `require`,
`except` and branch of the module:

- **c_client** (`SourceExecutionClient.execute`): the host queue polled until the request succeeds, is cancelled or the budget ends (a scripted queue
  and a scripted clock stand in for `SourceExecutions` and `time`);
- **b_bounded** (`bounded_command`): a completed child, a non-zero exit, bytes that are not UTF-8, oversized output (only the last
  `source_output_bytes` survive), a timeout (the child is killed and waited for 10 s), any other `BaseException` from the wait, a kill that does not
  end the child, and the one spawn call shape (the arguments and the no-console keywords);
- **e1_test_docker_source_runner_uses_only_inert_source_and_immutable_image**: the argv of the run (the M7 test's assertions) and the staged source
  (a regular file, an executable, a symlink-mode entry written as an inert regular file, a nested path, a raw tab/newline path, a skipped submodule);
- **e2_test_host_output_digests_are_not_artifact_edges_but_declared_children_are**: the receipt over the fixture process output (the
  `bounded_command` and `run_process` fakes of that test), the stored document;
- **v_verdicts**: every classification of a run (a failing, passing, empty and all-skipped pytest summary, a non-test command with and without
  output, the runner exit codes 124/125/126/127/137, oversized and lone-surrogate output);
- **f_failures**: every way the client and the rm can fail (`TimeoutExpired`, `OSError`, `ValueError`, `ContractError` from the run: the unavailable
  receipt; an unexpected error propagates after the rm; the rm's own `OSError`/`TimeoutExpired` swallowed);
- **m_materialize**: every refusal while the source is laid out and every refusal before the attempt starts (the image, the command, the source, the
  manifest and its binding);
- **o_other**: the explicit docker binary, the attempt, the temporary directory removed, the container name drawn per execution, `run_one`.

The execution cases that start a real child (M7: `test_real_runner_failure_retains_command_evidence`, `AuditRunner`) are not reachable here: that module
is `adapters.audit_runner` (layer 2). The `os.name == 'nt'` branch cannot run on this host (`NT_BRANCH`).

Documented normalization rules (the only ones; no clock, id, pid or path other than these is masked because none is drawn):

1. `DRIVER_HASH` (the hash of the module file, which differs between M7 and the moved file), `platform` (a host fact) and `uuid4` (the container name) are
   pinned on the module by the driver to the LABELLED constants `DRIVER_HASH`, `PLATFORM` and `Ids`, so the receipt's `environment_revision` and the
   stored document are comparable; the shape of the real hash is recorded separately (`driver_hash_shape`).
2. The temporary source directory is `tempfile.TemporaryDirectory(prefix="source-")`: every recorded string has the run's scratch root replaced by `<root>`
   and each `source-XXXXXXXX` by `source-<tmp>` (`norm`). The receipt's `output_ref` is the hash of a document that names that directory, so it is
   recorded by shape and the stored document is recorded instead.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `runner`, `run_one`, `client_execute`, `bounded`, `real_driver_hash`,
`FileArtifacts`, `SourceIdentity`, `ExecutionReceipt`, `ContractError`, `canonical`, `POLICY`. M7's tests monkeypatch the module's `bounded_command` and
`run_process`; the scenario's `bounded` (the `Bounded` fake) and `rm` (the `Rm` fake) are those fakes."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import subprocess
from dataclasses import asdict
from subprocess import CompletedProcess
from types import SimpleNamespace

import s8_research_program as R

REPOSITORY = "https://github.com/fixture/repo"
OTHER_REPOSITORY = "https://github.com/other/repo"
SHA = "1" * 40
TREE = "2" * 40
IMAGE = "sha256:" + "a" * 64
DRIVER_HASH = "d" * 64
PLATFORM = "fixture-platform"
CONSOLE_MARK = {"fake_console_kwarg": "console"}
PYTEST = ["python", "-m", "pytest", "-q"]
UNSET = object()
DROP = object()
NT_BRANCH = "the os.name == 'nt' path-portability require cannot run on this host"
FILES = [(b"README.md", "100644", b"readme\n"), (b"bin/run.sh", "100755", b"#!/bin/sh\necho ok\n"), (b"link", "120000", b"README.md"),
         (b"sub/dir/mod.py", "100644", b"x = 1\n"), (b"vendor/lib", "160000", None), (b"raw\tname\n", "100644", b"\xff\x00\xfe")]
M7_TESTS = {
    "e1_test_docker_source_runner_uses_only_inert_source_and_immutable_image": "tests/test_research_audits.py::test_docker_source_runner_uses_only_inert_source_and_immutable_image",
    "e2_test_host_output_digests_are_not_artifact_edges_but_declared_children_are":
        "tests/test_research_audits.py::test_host_output_digests_are_not_artifact_edges_but_declared_children_are (the DockerSourceRunner part)",
    "unreachable": ["tests/test_research_audits.py::test_real_runner_failure_retains_command_evidence (adapters.audit_runner, layer 2)",
                    "tests/test_research_audits.py::test_namespace_denial_preserves_evidence_and_never_changes_isolation (adapters.audit_runner)"],
}


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    return value


def norm(ws, value):
    """Normalization rule 2: the scratch root and the random temporary source directory names."""
    if isinstance(value, str):
        return re.sub(r"(?<=/)source-[a-z0-9_]{8}", "source-<tmp>", ws.scrub(value))
    if isinstance(value, dict):
        return {norm(ws, k) if isinstance(k, str) else k: norm(ws, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [norm(ws, v) for v in value]
    return value


def refusal(exc) -> dict:
    return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:300],
            "cause": type(exc.__cause__).__name__ if exc.__cause__ is not None else None}


class Stop(BaseException):
    """LABELLED stand-in for a `BaseException` that is not an `Exception` (an interrupt), which `bounded_command` kills the child for."""


def outcome(fn) -> dict:
    try:
        return {"returned": plain(fn())}
    except (Exception, Stop) as exc:  # the refusal is the characterized result
        return refusal(exc)


class Ids:
    """LABELLED `uuid.uuid4` double (normalization rule 1): a counter, so the container names are scripted."""

    def __init__(self):
        self.count = 0

    def __call__(self):
        self.count += 1
        return SimpleNamespace(hex="%032x" % self.count)


# =====================================================================================================================
# the doubles
# =====================================================================================================================
def staged(argv):
    """The tree the host staged for the container (the `-v root:/source:ro` mount), seen while the fake child 'runs'."""
    if "-v" not in argv:
        return None
    root = argv[argv.index("-v") + 1].rsplit(":/source:ro", 1)[0]
    out = []
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files + dirs):
            path = os.path.join(base, name)
            info = os.lstat(path)
            rel = os.path.relpath(path, root)
            if os.path.islink(path):
                out.append([rel, "symlink"])
            elif os.path.isdir(path):
                out.append([rel, "dir", oct(info.st_mode & 0o777)])
            else:
                data = open(path, "rb").read()
                out.append([rel, "file", oct(info.st_mode & 0o777), hashlib.sha256(data).hexdigest(), len(data)])
    return sorted(out)


class Bounded:
    """LABELLED `bounded_command` double (what M7's tests monkeypatch): the scripted outcome per call, the call recorded with the staged tree."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def __call__(self, argv, timeout, processes=None):
        self.calls.append({"argv": list(argv), "timeout": timeout, "staged": staged(argv)})
        step = self.outcomes[min(len(self.calls), len(self.outcomes)) - 1]
        if isinstance(step, BaseException):
            raise step
        returncode, stdout, stderr = step
        return CompletedProcess(argv, returncode, stdout, stderr)


class Rm:
    """LABELLED `run_process` double: the container removal; its calls are recorded, its outcome scripted."""

    def __init__(self, step=None):
        self.step, self.calls = step, []

    def __call__(self, argv, timeout=None, **kwargs):
        self.calls.append({"argv": list(argv), "timeout": timeout, "kwargs": sorted(kwargs)})
        if isinstance(self.step, BaseException):
            raise self.step
        return CompletedProcess(argv, 0, "", "")


class FakeProcess:
    """LABELLED `Popen` double: bytes streams, the scripted wait steps (None = the child ends, an exception = raised), kill ends it with -9."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0, waits=()):
        self.stdout, self.stderr = io.BytesIO(stdout), io.BytesIO(stderr)
        self.returncode, self.final, self.waits, self.wait_calls, self.kills = None, returncode, list(waits), [], 0

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        step = self.waits.pop(0) if self.waits else None
        if isinstance(step, BaseException):
            raise step
        if self.returncode is None:
            self.returncode = self.final
        return self.returncode

    def kill(self):
        self.kills += 1
        self.returncode = -9


class Popen:
    """The spawn: records the arguments and keywords, hands out the one scripted process."""

    def __init__(self, process):
        self.process, self.calls = process, []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": plain(kwargs)})
        return self.process


class Queue:
    """LABELLED `SourceExecutions` double: `request` answers the one id, `result` the scripted rows in order (the last repeats), `claim` the one row."""

    def __init__(self, rows=(), claim=None):
        self.rows, self.claimed, self.calls = list(rows), claim, []

    def __call__(self, workflow):
        self.calls.append(["queue", workflow])
        return self

    def request(self, task, source, command):
        self.calls.append(["request", task, asdict(source), list(command)])
        return {"id": "req-1"}

    def result(self, task, request_id):
        self.calls.append(["result", task, request_id])
        return self.rows[min(sum(1 for c in self.calls if c[0] == "result"), len(self.rows)) - 1]

    def claim(self):
        self.calls.append(["claim"])
        return self.claimed

    def complete(self, row, receipt):
        self.completed = receipt
        self.calls.append(["complete", row["id"], asdict(receipt)["exit_status"]])


class Clock:
    """LABELLED `time` double: `monotonic` is the scripted time, `sleep` advances it."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def make_source(api, ws, artifacts, files=FILES, entries=None, manifest=None):
    """A `SourceIdentity` whose manifest artifact lists `files` (path bytes, mode, data) as content-addressed envelopes (`entries`: the rows verbatim)."""
    rows = []
    for path, mode, data in files:
        ref = None
        if data is not None:
            envelope = {"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(data).hexdigest(), "data": b64(data)}
            ref = artifacts.put(api.canonical(envelope), "fixture")["ref"]
        rows.append({"path": b64(path), "mode": mode, "artifact_ref": ref})
    document = {"version": 1, "repository": REPOSITORY, "commit": SHA, "tree": TREE, "entries": rows if entries is None else entries}
    for key, value in (manifest or {}).items():
        if value is DROP:
            del document[key]
        else:
            document[key] = value
    return api.SourceIdentity(REPOSITORY, SHA, TREE, artifacts.put(api.canonical(document), "fixture")["ref"])


def bad_envelope(api, artifacts, **over):
    envelope = {"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(b"payload").hexdigest(), "data": b64(b"payload")}
    envelope.update(over)
    return artifacts.put(api.canonical(envelope), "fixture")["ref"]


def receipt_view(receipt, artifacts, ws):
    """The receipt without its `output_ref` (normalization rule 2: recorded by shape) and the stored document."""
    body = asdict(receipt)
    ref = body.pop("output_ref")
    return {"receipt": norm(ws, body), "output_ref_shape": re.fullmatch(r"sha256:[0-9a-f]{64}", ref) is not None,
            "document": norm(ws, artifacts.document(ref))}


# =====================================================================================================================
# DockerSourceRunner
# =====================================================================================================================
def exec_case(api, ws, name, *, files=FILES, entries=None, command=UNSET, image=IMAGE, outcomes=((0, "fixture-only", ""),), rm=None, attempt=None,
              docker=None, source=None, manifest=None, executions=1):
    case = ws.case(name)
    artifacts = api.FileArtifacts(str(case / "artifacts"))
    if source is None:
        source = make_source(api, ws, artifacts, files, entries(artifacts) if callable(entries) else entries, manifest)
    bounded, rm = Bounded(*outcomes), rm if isinstance(rm, Rm) else Rm(rm)
    runner = api.runner(case / "host", artifacts, bounded, rm, docker)
    command = ["python", "--version"] if command is UNSET else command
    results = []
    for _ in range(executions):
        got = {}
        try:
            receipt = runner.execute(source, command, image, attempt)
            got = {"returned": receipt_view(receipt, artifacts, ws)}
        except Exception as exc:  # the refusal is the characterized result
            got = refusal(exc)
        results.append(norm(ws, got))
    host = case / "host"
    return {"results": results, "bounded": norm(ws, plain(bounded.calls)), "rm": norm(ws, plain(rm.calls)),
            "host_after": sorted(p.name for p in host.iterdir()), "host_is_dir": host.is_dir()}


def e1(api, ws) -> dict:
    out = exec_case(api, ws, "inert", attempt=None)
    argv = out["bounded"][0]["argv"]
    out["m7_assertions"] = {
        "exit_status_zero_and_not_blocked": out["results"][0]["returned"]["receipt"]["exit_status"] == 0
        and not out["results"][0]["returned"]["receipt"]["inspection_blocked"],
        "network_none": argv[argv.index("--network") + 1] == "none",
        "read_only_pids_cap": "--read-only" in argv and "--pids-limit" in argv and "--cap-drop" in argv,
        "one_ro_mount": argv.count("-v") == 1 and argv[argv.index("-v") + 1].endswith(":/source:ro"),
        "tail": argv[-5:], "rm_prefix": out["rm"][-1]["argv"][:3]}
    return out


def e2(api, ws) -> dict:
    return exec_case(api, ws, "digests", outcomes=((0, "fixture process; not an actual Docker execution", ""),),
                     rm=None, attempt={"request_id": "req-1", "owner": "host", "task_id": "t-1", "generation": 1, "release_id": "rel-1"})


def v_verdicts(api, ws) -> dict:
    big = "x" * (api.POLICY.source_output_bytes + 100) + "TAIL"
    pytest_failed = "F\n=== 1 failed, 2 passed in 0.12s ==="
    cases = {
        "pytest_failed": dict(command=PYTEST, outcomes=((1, pytest_failed, ""),)),
        "pytest_passed": dict(command=PYTEST, outcomes=((0, "=== 3 passed in 0.10s ===", ""),)),
        "pytest_nothing_collected": dict(command=PYTEST, outcomes=((5, "=== no tests ran in 0.01s ===", ""),)),
        "pytest_all_skipped": dict(command=PYTEST, outcomes=((0, "=== 2 skipped in 0.01s ===", ""),)),
        "pytest_unstructured_output": dict(command=PYTEST, outcomes=((0, "something", ""),)),
        "pytest_exit_zero_with_failures": dict(command=["pytest"], outcomes=((0, "=== 1 failed, 1 passed in 0.1s ===", ""),)),
        "command_exit_zero_with_output": dict(outcomes=((0, "Python 3.11", ""),)),
        "command_exit_zero_empty_output": dict(outcomes=((0, "", ""),)),
        "command_exit_zero_stderr_only": dict(outcomes=((0, "", "Python 3.11"),)),
        "command_exit_two": dict(outcomes=((2, "out", "err"),)),
        "runner_exit_124": dict(outcomes=((124, "", ""),)),
        "runner_exit_137": dict(outcomes=((137, "partial", ""),)),
        "runner_exit_125": dict(outcomes=((125, "", "docker: error"),)),
        "runner_exit_126": dict(outcomes=((126, "", ""),)),
        "runner_exit_127": dict(outcomes=((127, "", "not found"),)),
        "oversized_output_keeps_the_tail": dict(outcomes=((0, big, big),)),
        "lone_surrogate_output": dict(outcomes=((0, "ok\udc80", ""),)),
        "non_integer_exit_status": dict(outcomes=((None, "out", ""),)),
    }
    return {name: exec_case(api, ws, name, **kwargs) for name, kwargs in cases.items()}


def f_failures(api, ws) -> dict:
    timeout = subprocess.TimeoutExpired(["docker", "run"], 130)
    cases = {
        "run_client_timeout": dict(outcomes=(timeout,)),
        "run_oserror": dict(outcomes=(FileNotFoundError(2, "No such file or directory", "docker"),)),
        "run_value_error": dict(outcomes=(ValueError("bad value"),)),
        "run_contract_error": dict(outcomes=(api.ContractError("contract said no"),)),
        "run_unexpected_error_propagates_after_the_rm": dict(outcomes=(RuntimeError("boom"),)),
        "rm_oserror_is_swallowed": dict(rm=OSError("docker gone")),
        "rm_timeout_is_swallowed": dict(rm=subprocess.TimeoutExpired(["docker", "rm"], 20)),
        "rm_unexpected_error_propagates": dict(rm=RuntimeError("rm boom")),
        "rm_runs_after_a_client_timeout": dict(outcomes=(timeout,), rm=OSError("docker gone")),
        "custom_docker_binary_missing": dict(docker="/nonexistent/docker", outcomes=(FileNotFoundError(2, "No such file or directory", "/nonexistent/docker"),)),
    }
    return {name: exec_case(api, ws, name, **kwargs) for name, kwargs in cases.items()}


def m_materialize(api, ws) -> dict:
    def entry(path, mode="100644", ref=None):
        return {"path": b64(path), "mode": mode, "artifact_ref": ref}

    def good(artifacts):
        return bad_envelope(api, artifacts)

    cases = {}
    cases["materialize_invalid_base64_path"] = dict(entries=lambda a: [{"path": "not base64!!", "mode": "100644", "artifact_ref": good(a)}])
    cases["materialize_path_escapes_the_root"] = dict(entries=lambda a: [entry(b"../escape", ref=good(a))])
    cases["materialize_absolute_path"] = dict(entries=lambda a: [entry(b"/etc/absolute", ref=good(a))])
    cases["materialize_path_collision"] = dict(entries=lambda a: [entry(b"same", ref=good(a)), entry(b"same", ref=good(a))])
    cases["materialize_dotdot_inside_the_root"] = dict(entries=lambda a: [entry(b"a/../inside", ref=good(a))])
    cases["materialize_empty_manifest"] = dict(entries=[])
    cases["materialize_only_submodules"] = dict(entries=[entry(b"one", "160000"), entry(b"two", "160000")])
    cases["materialize_entry_without_a_mode_propagates"] = dict(entries=lambda a: [{"path": b64(b"x"), "artifact_ref": good(a)}])
    cases["materialize_entry_without_an_artifact_ref_propagates"] = dict(entries=[{"path": b64(b"x"), "mode": "100644"}])
    cases["materialize_manifest_without_entries_propagates"] = dict(manifest={"entries": None})
    cases["materialize_missing_entry_artifact"] = dict(entries=[entry(b"x", ref="sha256:" + "9" * 64)])
    cases["materialize_wrong_source_bytes_hash"] = dict(entries=lambda a: [entry(b"x", ref=bad_envelope(api, a, bytes_sha256="0" * 64))])
    cases["materialize_invalid_data_base64"] = dict(entries=lambda a: [entry(b"x", ref=bad_envelope(api, a, data="***"))])
    cases["materialize_executable_mode_and_nested_path"] = dict(entries=lambda a: [entry(b"d/e/f", "100755", good(a))])
    cases["materialize_unknown_mode_is_a_regular_file"] = dict(entries=lambda a: [entry(b"odd", "100666", good(a))])
    out = {name: exec_case(api, ws, name, **kwargs) for name, kwargs in cases.items()}
    # the refusals before the attempt starts
    pre = {
        "image_is_a_tag": dict(image="python:3"),
        "image_digest_uppercase": dict(image="sha256:" + "A" * 64),
        "image_digest_short": dict(image="sha256:" + "a" * 63),
        "image_digest_with_trailing_text": dict(image=IMAGE + "\n"),
        "command_empty": dict(command=[]),
        "command_none": dict(command=None),
        "command_with_an_empty_argument": dict(command=["python", ""]),
        "command_with_a_non_text_argument": dict(command=["python", 3]),
        "manifest_commit_mismatch": dict(manifest={"commit": "3" * 40}),
        "manifest_tree_mismatch": dict(manifest={"tree": "4" * 40}),
        "manifest_repository_mismatch": dict(manifest={"repository": OTHER_REPOSITORY}),
        "manifest_binding_value_is_null": dict(manifest={"repository": None}),
        "manifest_without_a_binding_key_propagates": dict(manifest={"tree": DROP}),
    }
    for name, kwargs in pre.items():
        out[name] = exec_case(api, ws, name, **kwargs)
    # an invalid source and an unreadable manifest are refused first
    ws.case("badsource")
    for name, source in {"source_noncanonical_repository": api.SourceIdentity("https://example.com/x", SHA, TREE, "sha256:" + "0" * 64),
                         "source_invalid_commit": api.SourceIdentity(REPOSITORY, "zz", TREE, "sha256:" + "0" * 64),
                         "source_manifest_ref_invalid": api.SourceIdentity(REPOSITORY, SHA, TREE, "not-a-ref"),
                         "source_manifest_artifact_missing": api.SourceIdentity(REPOSITORY, SHA, TREE, "sha256:" + "0" * 64)}.items():
        out[name] = exec_case(api, ws, name, source=source)
    return out


def o_other(api, ws) -> dict:
    out = {}
    out["explicit_docker_binary_and_attempt"] = exec_case(api, ws, "podman", docker="podman", attempt={"request_id": "r", "owner": "o", "task_id": "t",
                                                                                                    "generation": 2, "release_id": None})
    out["two_executions_draw_two_container_names"] = exec_case(api, ws, "twice", executions=2)
    out["empty_source_executes"] = exec_case(api, ws, "empty", files=[], outcomes=((0, "ok", ""),))
    out["fresh_runner_creates_its_nested_root"] = nested_root(api, ws)
    out["driver_hash_shape"] = driver_hash_shape(api.real_driver_hash)
    return out


def nested_root(api, ws) -> dict:
    case = ws.case("nested")
    artifacts = api.FileArtifacts(str(case / "artifacts"))
    root = case / "a" / "b" / "host"
    first = api.runner(root, artifacts, Bounded(), Rm(), None)
    existed = root.is_dir()
    again = api.runner(root, artifacts, Bounded(), Rm(), None)
    return {"created": existed, "again_ok": again.root == first.root, "docker_default": first.docker}


def run_one_cases(api, ws) -> dict:
    out = {}
    # the claimed row is built on the artifacts of one execution case
    case = ws.case("runone")
    artifacts = api.FileArtifacts(str(case / "artifacts"))
    source = make_source(api, ws, artifacts)
    row = {"id": "req-9", "owner": "host-1", "source": asdict(source), "command": ["python", "--version"], "image": IMAGE, "release_id": "rel-1",
           "task": {"id": "task-1", "generation": 3}}

    def go(name, claim):
        queue = Queue(claim=claim)
        bounded, rm = Bounded((0, "fixture-only", "")), Rm()
        runner = api.runner(ws.case(name) / "host", artifacts, bounded, rm, None)
        got = outcome(lambda: api.run_one(runner, object(), queue))
        out[name] = norm(ws, {"returned": got, "queue": plain(queue.calls[1:]), "bounded": len(bounded.calls), "rm": len(rm.calls),
                              "docker_first_arg": bounded.calls[0]["argv"][0] if bounded.calls else None,
                              "completed": receipt_view(queue.completed, artifacts, ws) if hasattr(queue, "completed") else None})

    go("run_one_nothing_claimed", None)
    go("run_one_claimed_row", row)
    go("run_one_invalid_image_refused_before_complete", {**row, "image": "python:3"})
    return out


def c_client(api, ws) -> dict:
    case = ws.case("client")
    artifacts = api.FileArtifacts(str(case / "artifacts"))
    source = make_source(api, ws, artifacts, files=[])
    done = api.ExecutionReceipt(source, "env-1", ["true"], "iso-1", 0, "sha256:" + "e" * 64, "runner-1", False, passed=True, outcome="executed")
    succeeded = {"status": "succeeded", "receipt": asdict(done)}
    pending, cancelled = {"status": "pending"}, {"status": "cancelled"}

    def go(name, rows, timeout=None, step=0.0):
        queue, clock = Queue(rows), Clock()
        clock.now = 0.0
        result = outcome(lambda: asdict(api.client_execute("workflow", "task-1", source, ["true"], timeout, queue, clock)))
        return {"result": norm(ws, result), "calls": norm(ws, plain([c for c in queue.calls if c[0] != "queue"])), "sleeps": clock.sleeps, "now": clock.now}

    return {"succeeded_at_once": go("a", [succeeded]),
            "pending_twice_then_succeeded": go("b", [pending, pending, succeeded]),
            "cancelled": go("c", [cancelled]),
            "pending_then_cancelled": go("d", [pending, cancelled]),
            "budget_ends_with_the_default": go("e", [pending]),
            "budget_ends_with_three_seconds": go("f", [pending], timeout=3),
            "budget_zero_never_polls": go("g", [succeeded], timeout=0),
            "unknown_status_keeps_polling": go("h", [{"status": "running"}, succeeded], timeout=5),
            "row_without_a_status_is_a_key_error": go("i", [{}]),
            "succeeded_without_a_receipt_propagates": go("j", [{"status": "succeeded"}])}


# =====================================================================================================================
# bounded_command
# =====================================================================================================================
def bounded_case(api, name, stdout=b"", stderr=b"", returncode=0, waits=(), timeout=30):
    process = FakeProcess(stdout, stderr, returncode, waits)
    popen = Popen(process)
    argv = ["docker", "run", name]
    got = outcome(lambda: bounded_view(api.bounded(argv, timeout, popen)))
    return {"result": got, "popen_calls": popen.calls, "wait_calls": process.wait_calls, "kills": process.kills, "returncode": process.returncode}


def bounded_view(done):
    return {"args": done.args, "returncode": done.returncode, "stdout": text_view(done.stdout), "stderr": text_view(done.stderr),
            "types": [type(done.stdout).__name__, type(done.stderr).__name__]}


def text_view(text):
    return {"length": len(text), "sha256": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(), "head": text[:12], "tail": text[-12:]}


def b_bounded(api, ws) -> dict:
    limit = api.POLICY.source_output_bytes
    pattern = b"0123456789abcdef"
    big = (pattern * ((3 * limit) // len(pattern) + 1))[:3 * limit + 17]
    expired = subprocess.TimeoutExpired(["docker", "run"], 30)
    return {
        "completed": bounded_case(api, "ok", b"out", b"err"),
        "nonzero_exit": bounded_case(api, "rc3", b"o", b"e", returncode=3),
        "negative_exit": bounded_case(api, "signal", b"", b"", returncode=-15),
        "empty_output": bounded_case(api, "empty"),
        "output_that_is_not_utf8": bounded_case(api, "binary", b"a\xff\xfeb", b"\xc3("),
        "oversized_output_keeps_the_last_bytes": bounded_case(api, "big", big, big[::-1]),
        "output_of_exactly_the_limit": bounded_case(api, "limit", big[:limit], big[:limit]),
        "one_byte_over_the_limit": bounded_case(api, "limit1", big[:limit + 1], b""),
        "timeout_kills_and_waits_ten_seconds": bounded_case(api, "timeout", b"partial", b"", waits=[expired]),
        "timeout_with_a_custom_budget": bounded_case(api, "timeout5", b"", b"", waits=[expired], timeout=5),
        "other_exception_kills_and_reraises": bounded_case(api, "interrupt", b"", b"", waits=[Stop("stop")]),
        "the_kill_does_not_end_the_child": bounded_case(api, "stuck", b"", b"", waits=[expired, subprocess.TimeoutExpired(["docker", "run"], 10)]),
    }


def driver_hash_shape(real_hash) -> dict:
    """The module's own `DRIVER_HASH` (before the pin) is the sha256 hex digest of its file."""
    return {"is_sha256_hex": re.fullmatch(r"[0-9a-f]{64}", real_hash) is not None}


# =====================================================================================================================
def source_execution_adapter(api) -> dict:
    ws = R.Workspace()
    # The golden records staged directory modes; pin the umask (restored below) so the family does not depend on the shell's.
    previous_umask = os.umask(0o022)
    try:
        groups = {"c_client": c_client(api, ws), "b_bounded": b_bounded(api, ws),
                  "e1_test_docker_source_runner_uses_only_inert_source_and_immutable_image": e1(api, ws),
                  "e2_test_host_output_digests_are_not_artifact_edges_but_declared_children_are": e2(api, ws),
                  "v_verdicts": v_verdicts(api, ws), "f_failures": f_failures(api, ws), "m_materialize": m_materialize(api, ws),
                  "o_other": o_other(api, ws), "r_run_one": run_one_cases(api, ws)}
        return {**groups, "m7_tests": M7_TESTS, "nt_branch": NT_BRANCH, "cases_per_group": {k: len(v) for k, v in groups.items()}}
    finally:
        os.umask(previous_umask)
        ws.close()
