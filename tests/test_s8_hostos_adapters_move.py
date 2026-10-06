"""S8 pilot 91 (DESIGN-s8 §13 V18): three small M7 research adapters moved with host_os ports injected: `research.adapters.decision_feedback`
(R-df1), `research.adapters.reverse_source` (R-rs1) and `research.adapters.source_verification` (R-sv2). Everything but the named rules is M7's
(A/evidence/rebuild/s8/hostos-adapters-move/transcribe.py).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the three `research.*` goldens (decision_feedback_registry, reverse_source,
source_verification), where the reference patches the M7 module and the target injects the same doubles. The first-use refusals (the port is not
wired) have no M7 counterpart and are pinned here.
"""
import ast
import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO

from codex_harness.kernel.errors import ContractError
from codex_harness.research import ports

SOURCE = "e38aa722"
NAMES = ("decision_feedback", "reverse_source", "source_verification")
HOMES = {
    "decision_feedback": {"codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["digest"],
                          "codex_harness.research.domain.decision_feedback": ["DecisionFeedbackError", "RegistryError", "registry_pin", "validate_registry"],
                          "codex_harness.research.ports": ["GitBlobSource"]},
    "reverse_source": {"codex_harness.kernel.errors": ["require"], "pathlib": ["Path"]},
    "source_verification": {"codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["canonical"],
                            "codex_harness.research.domain.research": ["InventoryEntry", "SourceIdentity"], "dataclasses": ["asdict"]},
}
REWRITTEN = {"decision_feedback": "load_registry", "reverse_source": "observe_source", "source_verification": "GitSourceVerifier"}
UNWIRED_RUN = "run_process is not wired"
UNWIRED_PROCESSES = "processes is not wired"


def m7_text(name):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/adapters/{name}.py"], check=True, capture_output=True,
                          text=True).stdout


def module(name):
    return importlib.import_module("codex_harness.research.adapters." + name)


def target_text(name):
    return Path(module(name).__file__).read_text()


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


def function(node_or_src, name):
    tree = ast.parse(node_or_src) if isinstance(node_or_src, str) else node_or_src
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)


def dumped(nodes):
    return [ast.dump(n) for n in nodes]


def imported(name):
    found = {}
    for n in ast.parse(target_text(name)).body:
        if isinstance(n, ast.ImportFrom) and n.module != "__future__":
            found[n.module] = [a.name for a in n.names]
        elif isinstance(n, ast.Import):
            found.update({a.name: [a.name] for a in n.names})
    return found


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("name", NAMES)
def test_every_statement_but_the_one_named_rule_is_m7s_in_order(name):
    ref, ours = statements(m7_text(name)), statements(target_text(name))
    assert list(ours) == list(ref), "the same top-level names in the same order"
    for key in ours:
        if key != (REWRITTEN[name],):
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_r_df1_only_the_source_annotation_changed_and_the_body_is_m7s():
    ref = function(m7_text("decision_feedback"), "load_registry")
    ours = function(target_text("decision_feedback"), "load_registry")
    assert ast.unparse(ref.args.args[0].annotation) == "GitSource" and ast.unparse(ours.args.args[0].annotation) == "GitBlobSource"
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["source", "revision", "path"]
    assert dumped(ours.body) == dumped(ref.body) and ast.dump(ours.returns) == ast.dump(ref.returns)
    code = target_text("decision_feedback").split('"""', 2)[2]
    assert "GitSource" not in code.replace("GitBlobSource", ""), "the M7 docstring prose aside, GitSource is gone"
    assert "operation_cli" not in target_text("decision_feedback")


def test_r_rs1_run_process_is_a_keyword_only_port_checked_once_before_the_try():
    ref = function(m7_text("reverse_source"), "observe_source")
    ours = function(target_text("reverse_source"), "observe_source")
    assert [a.arg for a in ours.args.args] == ["path"] and [a.arg for a in ours.args.kwonlyargs] == ["run_process"]
    assert [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"]
    assert ast.dump(ours.body[0]) == ast.dump(ast.parse(f"require(run_process is not None, {UNWIRED_RUN!r})").body[0])
    assert dumped(ours.body[1:]) == dumped(ref.body), "every other statement is M7's"
    assert isinstance(ours.body[2], ast.FunctionDef) and isinstance(ours.body[3], ast.Try), "the require is outside the try that swallows exceptions"
    assert "run_process" not in imported("reverse_source").get("codex_harness.adapters.commands", [])


def test_r_sv2_processes_is_a_keyword_only_port_checked_once_in_git():
    ref = function(m7_text("source_verification"), "GitSourceVerifier")
    ours = function(target_text("source_verification"), "GitSourceVerifier")
    init_m, init_t = function(ours, "__init__"), function(ref, "__init__")
    assert [a.arg for a in init_m.args.args] == ["self", "repository", "artifacts"] and [a.arg for a in init_m.args.kwonlyargs] == ["processes"]
    assert [ast.unparse(d) for d in init_m.args.kw_defaults] == ["None"]
    assert dumped(init_m.body[:1]) == dumped(init_t.body) and ast.unparse(init_m.body[1]) == "self.processes = processes"
    git_m, git_t = function(ours, "git"), function(ref, "git")
    assert ast.dump(git_m.body[0]) == ast.dump(ast.parse(f"require(self.processes is not None, {UNWIRED_PROCESSES!r})").body[0])
    assert [ast.unparse(n) for n in git_m.body[1:]] == [
        ast.unparse(n).replace("subprocess.run(", "self.processes.run(").replace(", **no_console_kwargs()", "") for n in git_t.body]
    for method in ("inventory", "verify"):
        assert ast.dump(function(ours, method)) == ast.dump(function(ref, method)), method
    names = {n.id for n in ast.walk(ast.parse(target_text("source_verification"))) if isinstance(n, ast.Name)}
    assert "no_console_kwargs" not in names
    # the chokepoint rule: no direct process creation outside host_os
    assert not any(isinstance(n, ast.Call) and ast.unparse(n.func) == "subprocess.run" for n in ast.walk(ast.parse(target_text("source_verification"))))


STDLIB = {"decision_feedback": {"hashlib": ["hashlib"], "json": ["json"]}, "reverse_source": {},
          "source_verification": {"base64": ["base64"], "hashlib": ["hashlib"], "json": ["json"], "subprocess": ["subprocess"]}}


@pytest.mark.parametrize("name", NAMES)
def test_imports_are_only_the_v18_homes_and_nothing_reaches_m7_or_host_os(name):
    found = {k: sorted(v) for k, v in imported(name).items()}
    assert found == {k: sorted(v) for k, v in {**HOMES[name], **STDLIB[name]}.items()}
    for module_name in found:
        assert not module_name.startswith(("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.bootstrap",
                                           "codex_harness.host_os", "codex_harness.composition")), module_name


@pytest.mark.parametrize("name", NAMES)
def test_headers_name_context_layer_the_move_and_the_rules(name):
    header = target_text(name).split('"""')[1]
    for needle in ("Layer: adapters", "Context: research", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-", "Moved from M7 `adapters/" + name + ".py`",
                   "SOURCE e38aa722", "V18", "A/evidence/rebuild/s8/hostos-adapters-move/transcribe.py"):
        assert needle in header, needle
    assert {"decision_feedback": "R-df1", "reverse_source": "R-rs1", "source_verification": "R-sv2"}[name] in header


def test_the_module_surface_is_m7s():
    assert module("decision_feedback").__all__ == ["MAX_REGISTRY_BYTES", "load_registry"]
    assert module("decision_feedback").MAX_REGISTRY_BYTES == 256 * 1024 and module("decision_feedback").REGULAR_BLOB == "100644"
    assert [n for n in dir(module("reverse_source")) if not n.startswith("_")] == ["Path", "annotations", "observe_source", "require"]
    assert hasattr(module("source_verification"), "GitSourceVerifier")


# ---- the ports -----------------------------------------------------------------------------------------------------------
def test_git_blob_source_is_the_consumer_shape_of_host_os_git_source():
    assert sorted(n for n in vars(ports.GitBlobSource) if not n.startswith("_")) == ["blob", "commit_exists"]
    from codex_harness.host_os.adapters.git_source import GitSource
    for method in ("commit_exists", "blob"):
        assert list(inspect.signature(getattr(GitSource, method)).parameters) == list(inspect.signature(getattr(ports.GitBlobSource, method)).parameters)
    assert "GitBlobSource" in ports.__doc__.split("Entry points:", 1)[1].split("Contracts:", 1)[0]


def test_load_registry_takes_any_structural_blob_source():
    class Source:
        def commit_exists(self, revision):
            return False

        def blob(self, revision, path):
            raise AssertionError("the missing commit is refused before any blob is read")

    with pytest.raises(Exception) as info:
        module("decision_feedback").load_registry(Source(), "a" * 40, "docs/zeus/procedures.json")
    assert info.value.reason_code == "registry_revision_missing"


def completed(argv, stdout=""):
    return SimpleNamespace(argv=argv, returncode=0, stdout=stdout + "\n", stderr="")


def test_observe_source_uses_the_injected_run_process_keyword_only(tmp_path):
    calls = []
    answers = {"--show-toplevel": str(tmp_path), "HEAD": "a" * 40, "a" * 40 + "^{tree}": "b" * 40}

    def run(argv, timeout):
        calls.append((argv[:argv.index("-C")], timeout))
        return completed(argv, answers.get(argv[-1], ""))

    observed = module("reverse_source").observe_source(tmp_path, run_process=run)
    assert observed == {"status": "clean", "repository": str(tmp_path.resolve()), "commit": "a" * 40, "tree": "b" * 40}
    assert calls and all(prefix == ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false"] and timeout == 15
                         for prefix, timeout in calls)
    with pytest.raises(TypeError):
        module("reverse_source").observe_source(tmp_path, run)


def test_r_rs1_observe_source_without_run_process_is_refused_not_an_unknown_observation(tmp_path):
    """The M7 module imported `run_process`; a missing port must not be reported as a failed observation (the `except Exception` would)."""
    with pytest.raises(ContractError, match=UNWIRED_RUN):
        module("reverse_source").observe_source(tmp_path)
    with pytest.raises(ContractError, match=UNWIRED_RUN):
        module("reverse_source").observe_source(tmp_path / "missing", run_process=None)


def test_a_failing_injected_run_process_is_still_an_unknown_observation(tmp_path):
    def run(argv, timeout):
        raise OSError("no git")

    assert module("reverse_source").observe_source(tmp_path, run_process=run) == {"status": "unknown", "repository": str(tmp_path.resolve()),
                                                                                    "reason": "OSError"}


def test_source_verifier_spawns_through_the_injected_processes_port_only(tmp_path, monkeypatch):
    calls = []

    class Processes:
        def run(self, argv, *, process_group=False, **kwargs):
            calls.append((argv, process_group, kwargs))
            return SimpleNamespace(returncode=0, stdout=b"out", stderr=b"")

    def spawn(*args, **kwargs):
        raise AssertionError("the verifier must not create a process itself")

    monkeypatch.setattr(subprocess, "run", spawn)
    verifier = module("source_verification").GitSourceVerifier(tmp_path, "artifacts", processes=Processes())
    assert verifier.repository == str(tmp_path) and verifier.artifacts == "artifacts"
    assert verifier.git("rev-parse", "HEAD") == b"out"
    (argv, process_group, kwargs), = calls
    assert argv == ["git", "--no-replace-objects", "-C", str(tmp_path), "rev-parse", "HEAD"] and process_group is False
    assert kwargs == {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": 60}
    with pytest.raises(TypeError):
        module("source_verification").GitSourceVerifier(tmp_path, "artifacts", Processes())


def test_r_sv2_git_without_processes_is_refused_before_any_process_is_spawned(tmp_path, monkeypatch):
    def spawn(*args, **kwargs):
        raise AssertionError("no process may start without the processes port")

    monkeypatch.setattr(subprocess, "run", spawn)
    verifier = module("source_verification").GitSourceVerifier(tmp_path, None)
    assert verifier.processes is None
    with pytest.raises(ContractError, match=UNWIRED_PROCESSES):
        verifier.git("rev-parse", "HEAD")
    with pytest.raises(ContractError, match=UNWIRED_PROCESSES):
        verifier.inventory(SimpleNamespace(validate=lambda: None))


def test_the_host_os_ports_the_composition_will_pass_exist_with_the_injected_shapes():
    from codex_harness.host_os.adapters import process_groups
    from codex_harness.host_os.ports import ChildProcesses
    assert list(inspect.signature(process_groups.run_process).parameters)[:3] == ["argv", "cwd", "timeout"]
    assert list(inspect.signature(ChildProcesses.run).parameters) == ["self", "argv", "process_group", "kwargs"]
    assert list(inspect.signature(process_groups.ChokepointProcesses.run).parameters) == ["self", "argv", "process_group", "kwargs"]
