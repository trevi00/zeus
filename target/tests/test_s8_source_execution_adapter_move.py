"""S8 pilot 96 (DESIGN-s8 §13 V18): M7 `adapters/source_execution.py` moves to `research.adapters.source_execution` with the process creation,
the removal call and the run classification injected (R-se0..R-se2).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `research.source_execution_adapter` golden. The first-use refusals (a port
is not wired) have no M7 counterpart and are pinned here."""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import io
import subprocess
import sys
from pathlib import Path

import pytest
from _layout import REPO

from codex_harness.host_os import ports
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical
from codex_harness.research.adapters import source_execution as module
from codex_harness.research.adapters.source_execution import (
    DockerSourceRunner,
    SourceExecutionClient,
    bounded_command,
)
from codex_harness.research.domain.research import SourceIdentity
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.storage.adapters.file_artifacts import FileArtifacts

SOURCE = "e38aa722"
REWRITTEN = (("bounded_command",), ("DockerSourceRunner",))
HOMES = {"base64": [], "hashlib": [], "os": [], "platform": [], "re": [], "subprocess": [], "tempfile": [], "threading": [], "time": [],
         "pathlib": ["Path"], "uuid": ["uuid4"],
         "codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["canonical", "digest"],
         "codex_harness.kernel.policy": ["POLICY"], "codex_harness.research.application.source_execution": ["SourceExecutions"],
         "codex_harness.research.domain.research": ["ExecutionReceipt", "SourceIdentity"]}
UNWIRED = {"processes": "processes is not wired", "run_process": "run_process is not wired", "classify": "classify is not wired"}
REQUIRES = [f"require(self.{name} is not None, {reason!r})" for name, reason in UNWIRED.items()]
IMAGE = "sha256:" + "a" * 64
REPOSITORY, COMMIT, TREE = "https://github.com/fixture/repo", "1" * 40, "2" * 40


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/adapters/source_execution.py"], check=True,
                          capture_output=True, text=True).stdout


def target_text():
    return Path(module.__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def method(src, name, klass="DockerSourceRunner"):
    return next(n for n in statements(src)[(klass,)].body if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, name):
    return [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == name]


def test_every_statement_but_bounded_command_and_the_runner_is_m7s_in_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == [("DRIVER_HASH",), ("SourceExecutionClient",), ("bounded_command",), ("_ClientTimeout",), ("DockerSourceRunner",)]
    for key in ref:
        if key not in REWRITTEN:
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_r_se1_bounded_command_takes_processes_requires_it_first_and_spawns_through_popen():
    """Structural: the moved `bounded_command` statements equal M7's but for the `processes` port and its `require`
    (the S8 move rule, R-se1); behaviour is covered by test_bounded_command_without_processes_is_refused_before_any_spawn,
    test_bounded_command_spawns_once_through_popen_with_the_three_standard_streams and
    test_bounded_command_through_the_real_chokepoint_runs_a_real_child_and_bounds_its_output."""
    ref, ours = statements(m7_text())[("bounded_command",)], statements(target_text())[("bounded_command",)]
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["argv", "timeout"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["processes"] and [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"]
    assert ast.unparse(ours.body[0]) == "require(processes is not None, 'processes is not wired')"
    spawn = ast.unparse(ours.body[1])
    assert spawn == ("process = processes.popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)")
    assert ast.unparse(ref.body[0]).startswith("process = subprocess.Popen(argv, stdin=subprocess.DEVNULL") and "no_console_kwargs()" in ast.unparse(ref.body[0])
    assert [ast.dump(n) for n in ours.body[2:]] == [ast.dump(n) for n in ref.body[1:]]


def test_r_se2_the_runner_init_gains_three_keyword_only_ports_stored_on_self():
    ref, ours = method(m7_text(), "__init__"), method(target_text(), "__init__")
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["self", "root", "artifacts", "docker"]
    assert [ast.unparse(d) for d in ours.args.defaults] == ["'docker'"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["processes", "run_process", "classify"]
    assert [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"] * 3
    assert [ast.unparse(n) for n in ours.body] == [*(ast.unparse(n) for n in ref.body),
                                                  "self.processes, self.run_process, self.classify = (processes, run_process, classify)"]


def test_r_se2_the_calls_go_through_the_ports_and_the_rest_of_execute_is_m7s():
    ref, ours = method(m7_text(), "execute"), method(target_text(), "execute")
    assert [ast.unparse(n) for n in ours.body[:3]] == REQUIRES, "the three requires are the first statements of execute"
    rendered = "\n".join(ast.unparse(n) for n in ours.body[3:])
    expected = ("\n".join(ast.unparse(n) for n in ref.body)
                .replace("classify_isolated_run(", "self.classify(").replace("run_process(", "self.run_process(")
                .replace("timeout=POLICY.source_execution_seconds + 10)", "timeout=POLICY.source_execution_seconds + 10, processes=self.processes)"))
    assert rendered == expected
    assert calls(ref, "classify_isolated_run") and calls(ours, "classify_isolated_run") == [] and len(calls(ours, "self.classify")) == 3
    assert calls(ours, "run_process") == [] and len(calls(ours, "self.run_process")) == 1
    assert calls(ours, "bounded_command") == ["bounded_command(argv, timeout=POLICY.source_execution_seconds + 10, processes=self.processes)"]
    for name in ("run_one",):
        assert ast.dump(method(target_text(), name)) == ast.dump(method(m7_text(), name))


def test_exactly_four_port_requires_each_before_the_first_use_of_its_port():
    tree = ast.parse(target_text())
    found = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require"
             and ast.unparse(n.args[0]).endswith("is not None") and ast.unparse(n.args[0]).split(" ")[0] != "re.fullmatch('sha256:[0-9a-f]{64}',"]
    assert sorted(found) == sorted(["require(processes is not None, 'processes is not wired')", *REQUIRES])
    execute = ast.unparse(method(target_text(), "execute"))
    assert execute.index("self.processes is not None") < execute.index("self.classify is not None") < execute.index("source.validate()")
    assert execute.index("self.run_process is not None") < execute.index("self.run_process(") and "try:" in execute
    assert execute.index("self.classify is not None") < execute.index("try:"), "refused outside the try whose ContractError handler would swallow it"
    assert not any(isinstance(n, ast.Name) and n.id in ("no_console_kwargs", "classify_isolated_run") for n in ast.walk(tree))


def test_imports_are_only_the_v18_homes():
    found = {}
    for n in ast.parse(target_text()).body:
        if isinstance(n, ast.ImportFrom):
            found[n.module] = sorted(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            found.update({a.name: [] for a in n.names})
    assert {k: sorted(v) for k, v in found.items()} == {k: sorted(v) for k, v in HOMES.items()}


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    for needle in ("Layer: adapters", "Context: research", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-RUNNER-001",
                   "Moved from M7 `adapters/source_execution.py`", "SOURCE e38aa722", "V18",
                   "A/evidence/rebuild/s8/source-execution-adapter-move/transcribe.py", "R-se0", "R-se1", "R-se2"):
        assert needle in header, needle


def test_the_module_creates_no_process_itself():
    tree = ast.parse(target_text())
    creators = {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
    sites = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id in ("subprocess", "os") and n.func.attr in creators | {"system", "fork"}]
    assert sites == []
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "subprocess"}
    assert used == {"DEVNULL", "PIPE", "CompletedProcess", "TimeoutExpired"}, "subprocess only names constants, a value type and an exception"


def test_the_signatures_match_the_host_os_ports():
    assert list(inspect.signature(ports.ChildProcesses.popen).parameters) == ["self", "argv", "process_group", "kwargs"]
    assert list(inspect.signature(DockerSourceRunner).parameters) == ["root", "artifacts", "docker", "processes", "run_process", "classify"]
    assert [p.kind.name for p in inspect.signature(DockerSourceRunner).parameters.values()][3:] == ["KEYWORD_ONLY"] * 3
    assert inspect.signature(bounded_command).parameters["processes"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(inspect.signature(SourceExecutionClient.execute).parameters) == ["self", "workflow", "task", "source", "command", "timeout"]


# ---- behaviour on the target -------------------------------------------------------------------------------------------
class FakeProcess:
    def __init__(self, stdout=b"fixture-only", stderr=b"", returncode=0):
        self.stdout, self.stderr, self.returncode, self.kills = io.BytesIO(stdout), io.BytesIO(stderr), returncode, 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.kills += 1


class Processes:
    """A `ChildProcesses` double: records each `popen`; no process starts."""

    def __init__(self, process=None):
        self.calls, self.process = [], process or FakeProcess()

    def popen(self, argv, *, process_group=False, **kwargs):
        self.calls.append((list(argv), process_group, kwargs))
        return self.process

    def run(self, argv, *, process_group=False, **kwargs):
        raise AssertionError("bounded_command spawns through popen only")


class Forbidden:
    """Artifacts that fail the test if the runner touches them: the refusal comes first."""

    def document(self, ref):
        raise AssertionError("an unwired runner must not read an artifact")

    def put(self, body, kind):
        raise AssertionError("an unwired runner must not write an artifact")


def source_for(artifacts) -> SourceIdentity:
    data = b"print('x')\n"
    envelope = {"version": 1, "encoding": "base64", "bytes_sha256": hashlib.sha256(data).hexdigest(), "data": base64.b64encode(data).decode()}
    ref = artifacts.put(canonical(envelope), "fixture")["ref"]
    manifest = {"version": 1, "repository": REPOSITORY, "commit": COMMIT, "tree": TREE,
                "entries": [{"path": base64.b64encode(b"mod.py").decode(), "mode": "100644", "artifact_ref": ref}]}
    return SourceIdentity(REPOSITORY, COMMIT, TREE, artifacts.put(canonical(manifest), "fixture")["ref"])


def rm_recorder(calls):
    def run_process(argv, cwd=None, timeout=120, input_text=None, env=None):
        calls.append((list(argv), timeout))
        return subprocess.CompletedProcess(argv, 0, "", "")
    return run_process


@pytest.mark.parametrize("missing", ["processes", "run_process", "classify"])
def test_an_unwired_port_is_refused_before_any_staging_artifact_read_or_child(tmp_path, missing):
    ports_ = {"processes": Processes(), "run_process": rm_recorder([]), "classify": classify_isolated_run}
    ports_.pop(missing)
    runner = DockerSourceRunner(tmp_path / "host", Forbidden(), **ports_)
    source = SourceIdentity(REPOSITORY, COMMIT, TREE, "sha256:" + "0" * 64)
    with pytest.raises(ContractError, match=UNWIRED[missing]):
        runner.execute(source, ["python", "--version"], IMAGE)
    assert list((tmp_path / "host").iterdir()) == [], "nothing was staged"


def test_a_runner_with_nothing_wired_refuses_with_the_processes_reason_first_and_even_for_an_invalid_image(tmp_path):
    runner = DockerSourceRunner(tmp_path / "host", Forbidden())
    assert (runner.processes, runner.run_process, runner.classify, runner.docker) == (None, None, None, "docker")
    with pytest.raises(ContractError, match="processes is not wired"):
        runner.execute(SourceIdentity("https://example.com/x", "bad", "bad", "bad"), [], "python:3")


def test_bounded_command_without_processes_is_refused_before_any_spawn():
    with pytest.raises(ContractError, match="processes is not wired"):
        bounded_command(["true"], 5)


def test_bounded_command_spawns_once_through_popen_with_the_three_standard_streams():
    processes = Processes(FakeProcess(b"out", b"err", 3))
    done = bounded_command(["docker", "run"], 5, processes=processes)
    assert processes.calls == [(["docker", "run"], False, {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE})]
    assert (done.args, done.returncode, done.stdout, done.stderr) == (["docker", "run"], 3, "out", "err")


def test_bounded_command_through_the_real_chokepoint_runs_a_real_child_and_bounds_its_output():
    done = bounded_command([sys.executable, "-c", "import sys; sys.stdout.write('ok'); sys.stderr.write('e')"], 30, processes=ChokepointProcesses())
    assert (done.returncode, done.stdout, done.stderr) == (0, "ok", "e")
    big = bounded_command([sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000 + 'END')"], 30, processes=ChokepointProcesses())
    assert len(big.stdout) == module.POLICY.source_output_bytes and big.stdout.endswith("END")


def test_a_timed_out_child_is_killed_and_the_timeout_propagates():
    class Slow(FakeProcess):
        def wait(self, timeout=None):
            if not self.kills:
                raise subprocess.TimeoutExpired(["docker"], timeout)
            return -9

    process = Slow()
    with pytest.raises(subprocess.TimeoutExpired):
        bounded_command(["docker"], 1, processes=Processes(process))
    assert process.kills == 1


def test_the_runner_hands_its_own_processes_to_bounded_command_and_runs_the_whole_path_through_it(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    source, processes, removals = source_for(artifacts), Processes(), []
    runner = DockerSourceRunner(tmp_path / "host", artifacts, processes=processes, run_process=rm_recorder(removals), classify=classify_isolated_run)
    receipt = runner.execute(source, ["python", "--version"], IMAGE, attempt={"request_id": "r"})
    (argv, group, kwargs), = processes.calls
    assert argv[:3] == ["docker", "run", "--rm"] and argv[argv.index("--network") + 1] == "none" and argv[-5:] == ["--signal=KILL", "--", "120",
                                                                                                                 "python", "--version"]
    assert group is False and kwargs["stdin"] == subprocess.DEVNULL
    assert removals == [(["docker", "rm", "-f", argv[argv.index("--name") + 1]], 20)]
    assert (receipt.exit_status, receipt.passed, receipt.inspection_blocked, receipt.outcome) == (0, True, False, "executed")
    document = artifacts.document(receipt.output_ref)
    assert document["verdict"]["category"] == "executed" and document["attempt"] == {"request_id": "r"} and document["stdout"] == "fixture-only"
    assert list((tmp_path / "host").iterdir()) == [], "the staged source is removed"


def test_a_failing_run_is_classified_by_the_injected_rule_and_a_spawn_failure_is_unavailable_not_executed(tmp_path):
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    source, seen = source_for(artifacts), []

    def classify(**kwargs):
        seen.append(kwargs["stage"])
        return classify_isolated_run(**kwargs)

    failing = Processes(FakeProcess(b"F\n=== 1 failed, 2 passed in 0.1s ===", b"", 1))
    runner = DockerSourceRunner(tmp_path / "host", artifacts, processes=failing, run_process=rm_recorder([]), classify=classify)
    receipt = runner.execute(source, ["python", "-m", "pytest"], IMAGE)
    assert (receipt.exit_status, receipt.passed, receipt.outcome, seen) == (1, False, "executed", ["run"])

    class Missing:
        def popen(self, argv, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", argv[0])

    seen.clear()
    unavailable = DockerSourceRunner(tmp_path / "host", artifacts, processes=Missing(), run_process=rm_recorder([]), classify=classify)
    receipt = unavailable.execute(source, ["python", "--version"], IMAGE)
    assert (receipt.exit_status, receipt.inspection_blocked, receipt.passed, receipt.outcome, seen) == (125, True, False, "isolation_unavailable",
                                                                                                         ["spawn"])


def test_the_client_is_unchanged_and_needs_no_port():
    assert inspect.signature(SourceExecutionClient).parameters == {}
    assert ast.dump(statements(target_text())[("SourceExecutionClient",)]) == ast.dump(statements(m7_text())[("SourceExecutionClient",)])
