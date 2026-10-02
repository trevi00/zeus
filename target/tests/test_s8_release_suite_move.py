"""S8 pilot 95 (DESIGN-s8 §14 V19): M7 `adapters/release_suite.py` moves to `review.adapters.release_suite`, and `host_os` owns the exception
class its callers catch (`ProcessCancelled`, moved verbatim into `host_os.ports`) and the `LoggedProcessRunner` call shape.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `review.release_suite` golden. The first-use refusals (a callable is not
wired) have no M7 counterpart and are pinned here. The first part holds the V19 host_os identity tests."""

from __future__ import annotations

import ast
import functools
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from codex_harness.host_os import ports
from codex_harness.host_os.adapters import process_groups
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain.observation import redact_text, redact_value
from codex_harness.review.adapters import release_suite as module
from codex_harness.review.adapters.release_suite import ReleaseSuite, bounded_log

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
REWRITTEN = (("bounded_log",), ("ReleaseSuite",))
HOMES = {"__future__": ["annotations"], "hashlib": [], "json": [], "os": [], "tempfile": [], "pathlib": ["Path"],
         "codex_harness.host_os.ports": ["ProcessCancelled"], "codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["canonical"],
         "codex_harness.review.domain.check_results": ["NODE_OUTCOMES", "classify_batch", "classify_collection", "last_event", "node_results",
                                                       "nodes_digest", "plan_batches", "reconcile_nodes"]}
REQUIRES = ["require(self.run_logged_process is not None, 'release suite needs the process runner')",
            "require(self.redact is not None, 'release suite needs the redaction rule')",
            "require(self.redact_value is not None, 'release suite needs the value redaction rule')"]
LOG_REQUIRE = "require(redact is not None, 'bounded log needs the redaction rule')"


def test_process_cancelled_is_one_class_defined_in_host_os_ports():
    assert process_groups.ProcessCancelled is ports.ProcessCancelled
    assert ports.ProcessCancelled.__module__ == "codex_harness.host_os.ports"
    assert issubclass(ports.ProcessCancelled, KeyboardInterrupt) and not issubclass(ports.ProcessCancelled, Exception)
    error = ports.ProcessCancelled({"exit_code": None, "cancelled": True})
    assert error.observation == {"exit_code": None, "cancelled": True} and str(error) == "process cancelled"
    assert error.args == ("process cancelled",)


def test_logged_process_runner_is_the_call_shape_of_run_logged_process():
    wanted = inspect.signature(ports.LoggedProcessRunner.__call__)
    actual = inspect.signature(process_groups.run_logged_process)
    parameters = [(p.name, p.kind, p.default) for p in wanted.parameters.values() if p.name != "self"]
    assert parameters == [(p.name, p.kind, p.default) for p in actual.parameters.values()]
    assert [name for name, *_ in parameters] == ["argv", "stdout_path", "stderr_path", "cwd", "timeout", "env"]
    assert wanted.return_annotation == actual.return_annotation


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/adapters/release_suite.py"], check=True,
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


def method(src, name):
    return next(n for n in statements(src)[("ReleaseSuite",)].body if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, name):
    return [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == name]


def test_every_statement_but_the_class_and_bounded_log_is_m7s_in_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref)
    for key in ref:
        if key not in REWRITTEN:
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    assert ("PLUGIN_SOURCE",) in ours and ("read_events",) in ours and ("_progress",) in ours and ("_file_digest",) in ours


def test_every_method_but_init_and_the_renamed_calls_is_m7s():
    ref, ours = statements(m7_text())[("ReleaseSuite",)], statements(target_text())[("ReleaseSuite",)]
    assert [n.name for n in ours.body if isinstance(n, ast.FunctionDef)] == [n.name for n in ref.body if isinstance(n, ast.FunctionDef)]
    assert ours.bases == ref.bases and ours.name == ref.name
    for name in ("check", "_suite", "_interrupted", "_finish"):
        a, b = ast.unparse(method(target_text(), name)), ast.unparse(method(m7_text(), name))
        assert a == b.replace("redact_text(", "self.redact("), name


def test_r_rs1_init_gains_three_keyword_only_callables_stored_on_self():
    ref, ours = method(m7_text(), "__init__"), method(target_text(), "__init__")
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["self", "artifacts", "fence", "batch_nodes"]
    assert [ast.unparse(d) for d in ours.args.defaults] == ["BATCH_NODES"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["run_logged_process", "redact", "redact_value"]
    assert [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"] * 3
    assert [ast.unparse(n) for n in ours.body] == [ast.unparse(ref.body[0]), "self.run_logged_process, self.redact, self.redact_value = "
                                                  "(run_logged_process, redact, redact_value)"]


def test_r_rs1_the_runner_call_and_the_redaction_calls_go_through_self():
    ref, ours = method(m7_text(), "_run"), method(target_text(), "_run")
    assert calls(ref, "run_logged_process") != [] and calls(ours, "run_logged_process") == []
    assert len(calls(ours, "self.run_logged_process")) == len(calls(ref, "run_logged_process")) == 1
    rendered = "\n".join(ast.unparse(n) for n in ours.body[3:])
    assert rendered == "\n".join(ast.unparse(n) for n in ref.body).replace("run_logged_process(", "self.run_logged_process(")
    receipt = ast.unparse(method(target_text(), "_receipt"))
    assert ast.unparse(method(m7_text(), "_receipt")).replace("redact_text(", "self.redact(").replace("redact_value(", "self.redact_value(").replace(
        "bounded_log(stdout)", "bounded_log(stdout, redact=self.redact)").replace("bounded_log(stderr)", "bounded_log(stderr, redact=self.redact)") == receipt
    assert len(calls(method(target_text(), "_suite"), "self.redact")) == 1


def test_r_rs2_bounded_log_takes_redact_with_one_require_after_the_docstring():
    ref, ours = statements(m7_text())[("bounded_log",)], statements(target_text())[("bounded_log",)]
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["path", "head", "tail"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["redact"] and [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"]
    assert [ast.unparse(d) for d in ours.args.defaults] == ["LOG_HEAD_BYTES", "LOG_TAIL_BYTES"] and ours.returns is not None
    assert ast.unparse(ours.body[1]) == LOG_REQUIRE
    assert ast.unparse(ours.body[0]) == ast.unparse(ref.body[0]) and ast.unparse(ours.body[2:]) == "\n".join(
        ast.unparse(n) for n in ref.body[1:]).replace("redact_text(", "redact(")


def test_exactly_four_requires_each_before_the_first_use_of_its_callable():
    tree = ast.parse(target_text())
    found = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require"]
    assert sorted(found) == sorted([*REQUIRES, LOG_REQUIRE])
    run = method(target_text(), "_run")
    assert [ast.unparse(n) for n in run.body[:3]] == REQUIRES, "the three requires are the first statements of _run, before any child"
    # `_run` is the first method `check` reaches that starts a child or uses a rule (check -> _suite -> fence, then _run)
    suite = ast.unparse(method(target_text(), "_suite"))
    assert suite.index("self.fence()") < suite.index("self._run(") < suite.index("self.redact(")
    assert not any(isinstance(n, ast.Name) and n.id == "redact_text" for n in ast.walk(tree))


def test_imports_are_only_the_v19_homes():
    found = {}
    for n in ast.parse(target_text()).body:
        if isinstance(n, ast.ImportFrom):
            found[n.module] = sorted(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            found.update({a.name: [] for a in n.names})
    assert {k: sorted(v) for k, v in found.items()} == {k: sorted(v) for k, v in HOMES.items()}


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    for needle in ("Layer: adapters", "Context: review", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-CHECK-002",
                   "Moved from M7 `adapters/release_suite.py`", "SOURCE e38aa722", "V19", "A/evidence/rebuild/s8/release-suite-move/transcribe.py",
                   "R-rs0", "R-rs1", "R-rs2"):
        assert needle in header, needle


def test_the_module_creates_no_process_itself():
    tree = ast.parse(target_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"subprocess", "Popen", "psycopg"}
    assert not any(isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names) for n in ast.walk(tree))


# ---- behaviour on the target: the first-use refusals, the exception identity, the consumer's construction ----------------
class Artifacts:
    def __init__(self):
        self.documents = []

    def put(self, data, kind):
        self.documents.append((kind, json.loads(data)))
        return {"ref": f"ref-{len(self.documents)}"}


def check(suite):
    return suite.check(["python", "-m", "pytest"], cwd="/work", timeout=5, env={"PATH": "/usr/bin"}, binding={})


class Runner:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, argv, *, stdout_path, stderr_path, cwd=None, timeout=120, env=None):
        self.calls.append(argv)
        if self.error is not None:
            raise self.error
        return {"exit_code": 0, "timed_out": False}


@pytest.mark.parametrize("missing, reason", [("run_logged_process", "release suite needs the process runner"),
                                              ("redact", "release suite needs the redaction rule"),
                                              ("redact_value", "release suite needs the value redaction rule")])
def test_an_unwired_callable_is_refused_before_any_child_starts(missing, reason):
    runner, artifacts = Runner(), Artifacts()
    wired = {"run_logged_process": runner, "redact": redact_text, "redact_value": redact_value}
    wired.pop(missing)
    fences = []
    with pytest.raises(ContractError, match=reason):
        check(ReleaseSuite(artifacts, lambda: fences.append(1), **wired))
    assert runner.calls == [] and fences == [1], "the fence ran, no child started"
    assert [(kind, doc["interrupted"]) for kind, doc in artifacts.documents] == [("canary-suite", "ContractError")]


def test_a_suite_with_nothing_wired_refuses_with_the_runner_reason_first():
    with pytest.raises(ContractError, match="process runner"):
        check(ReleaseSuite(Artifacts(), lambda: None))


def test_bounded_log_refuses_without_the_redaction_rule_even_for_a_missing_file(tmp_path):
    with pytest.raises(ContractError, match="bounded log needs the redaction rule"):
        bounded_log(tmp_path / "absent")
    assert bounded_log(tmp_path / "absent", redact=redact_text) == {"text": "", "bytes": 0, "omitted_bytes": 0, "redactions": 0}
    (tmp_path / "log").write_text("a " + "gh" + "p_" + "A" * 24 + "\nmore\n")
    assert bounded_log(tmp_path / "log", redact=redact_text) == {"text": "a [REDACTED token]\nmore\n", "bytes": 36, "omitted_bytes": 0,
                                                                  "redactions": 1}
    assert bounded_log(tmp_path / "log", 4, 4, redact=redact_text) == {"text": "a gh\n...[28 bytes omitted]...\nore\n", "bytes": 36,
                                                                         "omitted_bytes": 28, "redactions": 0}


def test_process_cancelled_is_the_one_host_os_class_the_module_catches():
    assert module.ProcessCancelled is ports.ProcessCancelled is process_groups.ProcessCancelled
    artifacts, cancelled = Artifacts(), ports.ProcessCancelled({"exit_code": None, "cancelled": True, "cleanup": {"reason": "proven"}})
    suite = ReleaseSuite(artifacts, lambda: None, run_logged_process=Runner(cancelled), redact=redact_text, redact_value=redact_value)
    with pytest.raises(ports.ProcessCancelled) as raised:
        check(suite)
    assert raised.value is cancelled and cancelled.receipt == "ref-1", "the receipt was attached to the very exception that was raised"
    kinds = [(kind, doc.get("kind"), doc.get("interrupted")) for kind, doc in artifacts.documents]
    assert kinds == [("canary-suite", "release-suite-process", None), ("canary-suite", "release-suite", "ProcessCancelled")]
    assert artifacts.documents[1][1]["cancelled_process"] == "ref-1"
    assert artifacts.documents[0][1]["verdict"]["reason"] == "cancelled"


def test_the_delivery_consumer_constructs_and_calls_it_positionally():
    # delivery/adapters/deployment.py: `self.release_suite(self.artifacts, self.fence).check(argv, cwd=, timeout=, env=, binding=)`
    init = inspect.signature(ReleaseSuite)
    init.bind(Artifacts(), lambda: None)
    init.bind(Artifacts(), lambda: None, 7)
    assert list(init.parameters) == ["artifacts", "fence", "batch_nodes", "run_logged_process", "redact", "redact_value"]
    inspect.signature(ReleaseSuite.check).bind(None, ["pytest"], cwd="/w", timeout=1, env=None, binding={})
    factory = functools.partial(ReleaseSuite, run_logged_process=Runner(), redact=redact_text, redact_value=redact_value)
    suite = factory(Artifacts(), lambda: None)
    assert isinstance(suite, ReleaseSuite) and suite.batch_nodes == module.BATCH_NODES
    assert factory(Artifacts(), lambda: None, 3).batch_nodes == 3
    consumer = (REPO / "target/src/codex_harness/delivery/adapters/deployment.py").read_text()
    assert "self.release_suite(self.artifacts, self.fence).check(argv, cwd=cwd, timeout=timeout" in consumer


def test_the_runner_the_suite_takes_is_host_os_s_logged_process_runner_shape():
    wanted = [(p.name, p.kind) for p in inspect.signature(ports.LoggedProcessRunner.__call__).parameters.values() if p.name != "self"]
    assert [(p.name, p.kind) for p in inspect.signature(Runner.__call__).parameters.values() if p.name != "self"] == wanted
    assert [(p.name, p.kind) for p in inspect.signature(process_groups.run_logged_process).parameters.values()] == wanted
