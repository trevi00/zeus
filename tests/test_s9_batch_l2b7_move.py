"""S9 batch L2-B7: the frontend checks (U9) move out of M7 `adapters/monitor_frontend_checks.py` into `observation.adapters.monitor_frontend_checks` with the OWNER-DECISIONS-S9
D3/D3.1 seam, and the pinned `-m` argv keeps working through a permanent shim.

The module is M7's except R-f0 (the module-level `_capture` import is removed: observation imports no evidence adapter), R-f1 (`observe(..., capture=None)`, refused first when
unwired) and R-f2 (`main(argv=None, *, capture=None)`, the same refusal first, `observe(Path.cwd(), capture=capture)`). R-f3 is three new files: `composition.monitor_frontend_checks`
binds `functools.partial(_capture, process_tree=ProcessTree)` into `main`, `entry.processes.monitor_frontend_checks.main` delegates and `codex_harness/adapters/
monitor_frontend_checks.py` is the permanent shim of the evidence policy, the worker-profile grant and the S0 scan. M7 is read only as text through `git show e38aa722:...` and
compared by AST, never imported: both packages are named `codex_harness`. Behaviour is compared by the recorded `observation.frontend_checks` golden (target-equal, with the
composition's capture injected); this file pins what a golden cannot: the AST against M7 modulo R-f0..R-f2, the import homes, the refusals (no effect and no output before
them), the composition's binding of the real `_capture` with the host_os `ProcessTree`, the shim, the pinned argv in a subprocess against M7's own `main`, and no new spawn site.

M7 tests this batch does NOT port yet (the S9 ported suite is a later step; every case below has a counterpart in the golden): from `tests/test_monitor_frontend_checks.py`
`test_a_complete_pass_runs_the_three_named_checks_over_a_disposable_copy`, `test_the_candidate_and_the_packaged_observatory_are_read_not_written`,
`test_an_injected_write_into_the_checkout_is_reported_as_source_mutation`, `test_a_failing_check_stops_the_run_and_later_checks_are_reported_not_run`,
`test_a_missing_entrypoint_or_node_is_unavailable_and_nothing_is_invented`, `test_a_package_or_lock_difference_refuses_before_any_check`,
`test_a_symlink_that_leaves_the_candidate_is_refused_and_a_contained_one_is_not`, `test_missing_monitor_project_and_a_non_posix_host_are_explicit_refusals`,
`test_the_command_refuses_every_argument_including_help`, `test_concurrent_runs_own_separate_temporary_directories`, `test_a_timeout_terminates_the_tree_and_is_never_a_pass`,
`test_cleanup_debt_retains_the_temporary_directory_and_fails`, `test_truncated_output_is_a_defect_even_when_the_check_exited_zero` and
`test_the_children_see_a_fixed_credential_free_environment` (all fourteen; their cases are in the golden, and `test_the_command_refuses_every_argument_including_help` is also
run here through the pinned argv).
"""

from __future__ import annotations

import ast
import copy
import functools
import inspect
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import import_rules
import pytest
from _layout import REPO, TARGET

from codex_harness.adapters import monitor_frontend_checks as shim
from codex_harness.composition import monitor_frontend_checks as composition
from codex_harness.entry.processes import monitor_frontend_checks as entry
from codex_harness.evidence.adapters import evidence_inspection
from codex_harness.host_os.adapters import process_tree
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters import monitor_frontend_checks as module

TARGET_SRC = TARGET / "src"
SOURCE = "e38aa722"
M7 = "src/codex_harness/adapters/monitor_frontend_checks.py"
TEXT = Path(module.__file__).read_text(encoding="utf-8")
SHIM_TEXT = Path(shim.__file__).read_text(encoding="utf-8")
FORBIDDEN_HOMES = ("codex_harness.adapters", "codex_harness.domain", "codex_harness.application", "codex_harness.ports", "codex_harness.entry", "codex_harness.intake",
                   "codex_harness.evidence", "codex_harness.delivery", "codex_harness.composition", "codex_harness.host_os")
REQUIRE_MESSAGE = "capture is not wired"
PY = sys.executable
PACKAGE = b'{\n  "name": "monitor",\n  "private": true\n}\n'
LOCK = b'{\n  "name": "monitor",\n  "lockfileVersion": 3\n}\n'


def show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def names_of(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    return {names_of(node)[0]: node for node in ast.parse(src).body if names_of(node)}


def order(src):
    return [name for node in ast.parse(src).body for name in names_of(node)]


def from_imports(tree):
    return {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}


def is_call_to(node, name):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name


M7_TEXT = show(SOURCE, M7)
OURS, THEIRS = statements(TEXT), statements(M7_TEXT)


class InverseOfDecision(ast.NodeTransformer):
    """The inverse of R-f1 and R-f2 on the target's `observe` and `main`, so comparing with M7's AST proves nothing else changed."""

    def __init__(self):
        self.fn, self.removed = None, []

    def visit_FunctionDef(self, node):
        outer, self.fn = self.fn, node.name if self.fn is None else self.fn
        if outer is None and node.name == "observe":
            at = [a.arg for a in node.args.kwonlyargs].index("capture")
            assert isinstance(node.args.kw_defaults[at], ast.Constant) and node.args.kw_defaults[at].value is None
            node.args.kw_defaults[at] = ast.Name("_capture", ast.Load())
        if outer is None and node.name == "main":
            assert [a.arg for a in node.args.kwonlyargs] == ["capture"] and node.args.kw_defaults[0].value is None
            node.args.kwonlyargs, node.args.kw_defaults = [], []
        self.generic_visit(node)
        self.fn = outer
        return node

    def visit_Expr(self, node):
        if is_call_to(node.value, "require"):
            assert ast.unparse(node.value.args[0]) == "capture is not None" and ast.literal_eval(node.value.args[1]) == REQUIRE_MESSAGE
            self.removed.append(self.fn)
            return None
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if self.fn == "main" and isinstance(node.func, ast.Name) and node.func.id == "observe":
            assert [(kw.arg, ast.unparse(kw.value)) for kw in node.keywords] == [("capture", "capture")]
            node.keywords = []
        return node


def stand_in_m7():
    """M7's own module text executed with the one removed import replaced by a name no scenario here uses: M7's `main` and `observe`, not a copy of their behaviour."""
    line = "from codex_harness.adapters.evidence_inspection import _capture\n"
    assert M7_TEXT.count(line) == 1
    namespace = {"__name__": "m7_frontend_checks_text"}
    exec(compile(M7_TEXT.replace(line, "def _capture(*args, **kwargs):\n    raise AssertionError('M7 capture reached')\n"), "m7_frontend_checks.py", "exec"), namespace)
    return SimpleNamespace(**namespace)


# ---- the AST against M7 modulo R-f0..R-f2 --------------------------------------------------------------

def test_the_module_holds_every_m7_definition_in_m7s_order_and_only_observe_and_main_differ():
    assert order(TEXT) == order(M7_TEXT) and len(OURS) == len(THEIRS) == 35 and len(order(M7_TEXT)) == 37
    changed = [name for name in THEIRS if ast.dump(OURS[name]) != ast.dump(THEIRS[name])]
    assert changed == ["observe", "main"]
    for name in THEIRS:
        if name not in changed:
            assert ast.get_source_segment(TEXT, OURS[name]) == ast.get_source_segment(M7_TEXT, THEIRS[name]), name


def test_the_inverse_of_r_f1_and_r_f2_reproduces_m7s_ast_exactly():
    inverse = InverseOfDecision()
    for name in ("observe", "main"):
        back = inverse.visit(copy.deepcopy(OURS[name]))
        ast.fix_missing_locations(back)
        assert ast.dump(back) == ast.dump(THEIRS[name]), name
    assert inverse.removed == ["observe", "main"]


def test_every_changed_line_is_an_r_f_line_and_the_main_guard_stays():
    ours, theirs = TEXT.split("\n"), M7_TEXT.split("\n")
    tail_ours = ours[ours.index("SCHEMA = " + repr("zeus.monitor-frontend-checks/v1").replace("'", '"')):]
    tail_theirs = theirs[theirs.index(tail_ours[0]):]
    removed = [line for line in tail_theirs if line not in tail_ours]
    added = [line for line in tail_ours if line not in tail_theirs]
    assert sorted(removed) == sorted(["def observe(cwd, *, node=None, dependencies=None, capture=_capture) -> dict:", "def main(argv=None) -> int:",
                                      "        body = observe(Path.cwd())"])
    assert sorted(added) == sorted(["def observe(cwd, *, node=None, dependencies=None, capture=None) -> dict:", "def main(argv=None, *, capture=None) -> int:",
                                    "        body = observe(Path.cwd(), capture=capture)",
                                    "    require(capture is not None, 'capture is not wired')", "    require(capture is not None, 'capture is not wired')"])
    assert TEXT.rstrip().endswith('if __name__ == "__main__":\n    sys.exit(main())')


def test_the_header_keeps_m7s_docstring_first_and_names_the_rules():
    doc, m7_doc = ast.get_docstring(ast.parse(TEXT), clean=False), ast.get_docstring(ast.parse(M7_TEXT), clean=False)
    assert doc.startswith(m7_doc) and doc[len(m7_doc):].startswith("\n")
    tail = doc[len(m7_doc):]
    for line in ("Layer: adapters", "Context: observation", "Owns: ", "Does not own: ", "Entry points: ", "Contracts: INV-EVIDENCE-001, INV-ISOLATED-WORKER-001"):
        assert re.search("(?m)^" + re.escape(line), tail), line
    for rule in ("R-f0", "R-f1", "R-f2", "R-ch", "SOURCE e38aa722"):
        assert rule in tail
    entry_points = re.search(r"(?m)^Entry points: (.*)$", tail).group(1).split(", ")
    assert {"observe", "main", "scan_source"} <= set(entry_points) and sorted(entry_points) == sorted(set(entry_points))
    assert set(entry_points) == set(order(TEXT)) - {"_Refusal", "_file_digest", "_tree_digest", "_copy_source", "_bind_dependencies", "_environment", "_stream", "_classify",
                                                    "_not_run", "_run_checks", "_cleanup", "_emit"}


def test_positional_shapes_are_m7s_and_capture_is_keyword_only_with_default_none():
    theirs = {name: THEIRS[name].args for name in ("observe", "main", "scan_source")}
    ours = {name: OURS[name].args for name in ("observe", "main", "scan_source")}
    assert ast.unparse(ours["scan_source"]) == ast.unparse(theirs["scan_source"])
    for name in ("observe", "main"):
        assert [a.arg for a in ours[name].args] == [a.arg for a in theirs[name].args]
        assert [ast.unparse(d) for d in ours[name].defaults] == [ast.unparse(d) for d in theirs[name].defaults]
    assert [a.arg for a in theirs["observe"].args] == ["cwd"] and [a.arg for a in theirs["observe"].kwonlyargs] == ["node", "dependencies", "capture"]
    assert [a.arg for a in theirs["main"].args] == ["argv"] and theirs["main"].kwonlyargs == []
    signature = inspect.signature(module.observe)
    assert [(p.name, p.kind, p.default) for p in signature.parameters.values()] == [
        ("cwd", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty), ("node", inspect.Parameter.KEYWORD_ONLY, None),
        ("dependencies", inspect.Parameter.KEYWORD_ONLY, None), ("capture", inspect.Parameter.KEYWORD_ONLY, None)]
    signature = inspect.signature(module.main)
    assert [(p.name, p.kind, p.default) for p in signature.parameters.values()] == [
        ("argv", inspect.Parameter.POSITIONAL_OR_KEYWORD, None), ("capture", inspect.Parameter.KEYWORD_ONLY, None)]


# ---- the import homes -----------------------------------------------------------------------------------

def test_the_import_homes_resolve_in_the_target_alone_and_observation_imports_no_evidence_adapter():
    tree = ast.parse(TEXT)
    assert from_imports(tree) == {"__future__": ["annotations"], "pathlib": ["Path"], "codex_harness.kernel.errors": ["require"]}
    assert sorted(a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names) == ["hashlib", "json", "os", "shutil", "sys", "tempfile", "time"]
    modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.startswith(FORBIDDEN_HOMES)]
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and n not in tree.body], "no lazy import"
    assert "_capture" not in {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} and not hasattr(module, "_capture")
    assert "evidence" not in " ".join(modules) and "host_os" not in " ".join(modules)
    assert module.require is import_rules.__dict__.get("require", module.require)
    from codex_harness.kernel import errors
    assert module.require is errors.require


def test_no_layer_or_cycle_violation_touches_the_new_files_and_the_shim_is_declared():
    violations = import_rules.check(TARGET / "src")
    assert violations == []
    assert "codex_harness.adapters.monitor_frontend_checks" in import_rules.SHIMS
    assert import_rules.classify("codex_harness.adapters.monitor_frontend_checks") == ("SHIM", None)
    assert import_rules.classify(module.__name__)[1] == "observation"
    assert import_rules.classify(composition.__name__)[0] != "UNCLASSIFIED" and import_rules.classify(entry.__name__)[0] != "UNCLASSIFIED"


# ---- R-f1/R-f2: the unwired capture is refused first, with no effect and no output -------------------------

class Untouched:
    def __getattr__(self, name):
        raise AssertionError(f"touched {name} before the refusal")

    def __call__(self, *args, **kwargs):
        raise AssertionError("called before the refusal")


def test_an_unwired_capture_is_refused_by_observe_before_any_copy_scan_or_process(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    (candidate / "frontend" / "monitor").mkdir(parents=True)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    with monkeypatch.context() as patch:
        for name in ("scan_source", "_copy_source", "_bind_dependencies", "_run_checks", "_environment", "_file_digest", "_cleanup"):
            patch.setattr(module, name, Untouched())
        patch.setattr(module.tempfile, "mkdtemp", Untouched())
        patch.setattr(module.os, "scandir", Untouched())
        with pytest.raises(ContractError, match=REQUIRE_MESSAGE):
            module.observe(candidate, node=PY, dependencies=tmp_path / "store")
        with pytest.raises(ContractError, match=REQUIRE_MESSAGE):
            module.observe(candidate, node=PY, dependencies=tmp_path / "store", capture=None)
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_the_refusal_comes_before_the_non_posix_and_argument_decisions_too(tmp_path, monkeypatch):
    monkeypatch.setattr(module.os, "name", "nt")
    with pytest.raises(ContractError, match=REQUIRE_MESSAGE):
        module.observe(tmp_path)


def test_an_unwired_capture_is_refused_by_main_before_any_output_even_for_an_invalid_invocation(capsys, monkeypatch):
    monkeypatch.setattr(module, "observe", Untouched())
    for arguments in (None, [], ["--help"], ["extra"], ["a", "b"]):
        monkeypatch.setattr(module.sys, "argv", ["monitor_frontend_checks"])
        with pytest.raises(ContractError, match=REQUIRE_MESSAGE):
            module.main(arguments)
        with pytest.raises(ContractError, match=REQUIRE_MESSAGE):
            module.main(arguments, capture=None)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_main_passes_its_capture_to_observe_unchanged_and_keeps_m7s_exit_codes(capsys, monkeypatch, tmp_path):
    seen = []
    sentinel = object()

    def fake(cwd, **kwargs):
        seen.append((cwd, kwargs))
        return {"status": "ok", "schema": module.SCHEMA}

    monkeypatch.setattr(module, "observe", fake)
    monkeypatch.chdir(tmp_path)
    assert module.main([], capture=sentinel) == module.EXIT_OK and seen == [(Path.cwd(), {"capture": sentinel})]
    assert json.loads(capsys.readouterr().out) == {"schema": module.SCHEMA, "status": "ok"}
    monkeypatch.setattr(module, "observe", lambda cwd, **kwargs: {"status": "failed"})
    assert module.main([], capture=sentinel) == module.EXIT_FAILED
    capsys.readouterr()

    def boom(cwd, **kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(module, "observe", boom)
    assert module.main([], capture=sentinel) == module.EXIT_FAILED
    out = capsys.readouterr().out
    assert json.loads(out)["error"] == {"kind": "internal_error"} and "secret detail" not in out


def test_an_argument_is_invalid_with_a_wired_capture_and_never_reaches_observe(capsys, monkeypatch):
    monkeypatch.setattr(module, "observe", Untouched())
    for arguments in (["--help"], ["frontend/monitor"], [""], ["--json"], ["a", "b"]):
        assert module.main(arguments, capture=object()) == module.EXIT_INVOCATION == 2
        body = json.loads(capsys.readouterr().out)
        assert body["status"] == "error" and body["error"] == {"kind": "invalid_invocation"} and body["usage"].endswith("(no arguments)")


# ---- the composition binds the real `_capture` with the host_os ProcessTree ----------------------------------

def test_the_composition_is_the_one_partial_over_main_with_the_real_capture_and_the_host_os_process_tree_class():
    command = composition.frontend_checks_command()
    assert isinstance(command, functools.partial) and command.func is module.main and command.args == ()
    assert set(command.keywords) == {"capture"}
    capture = command.keywords["capture"]
    assert isinstance(capture, functools.partial) and capture.func is evidence_inspection._capture and capture.args == ()
    assert capture.keywords == {"process_tree": process_tree.ProcessTree} and capture.keywords["process_tree"] is process_tree.ProcessTree
    assert composition.frontend_checks_command() is not command, "a fresh binding per call, nothing cached"
    tree = ast.parse(Path(composition.__file__).read_text(encoding="utf-8"))
    assert from_imports(tree) == {"__future__": ["annotations"], "codex_harness.evidence.adapters.evidence_inspection": ["_capture"],
                                  "codex_harness.host_os.adapters.process_tree": ["ProcessTree"], "codex_harness.observation.adapters": ["monitor_frontend_checks"]}
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)] == ["frontend_checks_command"]


def test_the_composition_capture_runs_the_three_checks_through_the_real_bounded_capture(tmp_path):
    """The labelled fixture of M7's tests (the host Python stands in for node; three Python files stand in for eslint/tsc/vite): the real `_capture` over real children."""
    candidate = tmp_path / "candidate"
    project = candidate / "frontend" / "monitor"
    project.mkdir(parents=True)
    (project / "package.json").write_bytes(PACKAGE)
    (project / "package-lock.json").write_bytes(LOCK)
    (project / "App.tsx").write_text("export const App = () => null\n", encoding="utf-8")
    store = tmp_path / "store"
    (store / "node_modules").mkdir(parents=True)
    (store / "package.json").write_bytes(PACKAGE)
    (store / "package-lock.json").write_bytes(LOCK)
    for parts in (("eslint", "bin", "eslint.js"), ("typescript", "bin", "tsc"), ("vite", "bin", "vite.js")):
        entrypoint = store.joinpath("node_modules", *parts)
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("import os, sys\nsys.stdout.write('fixture ok\\n')\n"
                              "if '--outDir' in sys.argv:\n    os.makedirs(sys.argv[sys.argv.index('--outDir') + 1], exist_ok=True)\n", encoding="utf-8")
    report = module.observe(candidate, node=PY, dependencies=store, capture=composition.frontend_checks_command().keywords["capture"])
    assert report["status"] == "ok" and report["defects"] == [], report
    assert [check["status"] for check in report["checks"]] == ["passed"] * 3 and all(check["cleanup_confirmed"] for check in report["checks"])
    assert all(check["cleanup"]["tree"]["boundary"]["owned_from_spawn"] for check in report["checks"]), "an owned ProcessTree boundary, as E-4b requires"
    bare = functools.partial(evidence_inspection._capture)
    with pytest.raises(ContractError, match="process_tree is not wired"):
        module.observe(candidate, node=PY, dependencies=store, capture=bare)  # E-4b: the composition's binding is what makes the command run


# ---- the entry and the shim ------------------------------------------------------------------------------------

def test_the_entry_main_delegates_argv_to_the_composition_command_and_returns_its_status(monkeypatch):
    seen = []
    monkeypatch.setattr(entry, "frontend_checks_command", lambda: lambda argv: seen.append(argv) or 7)
    assert entry.main(["x"]) == 7 and entry.main() == 7 and seen == [["x"], None]
    tree = ast.parse(Path(entry.__file__).read_text(encoding="utf-8"))
    assert from_imports(tree) == {"__future__": ["annotations"], "codex_harness.composition.monitor_frontend_checks": ["frontend_checks_command"]}
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)] == ["main"]


def test_the_shim_is_at_most_ten_lines_and_only_delegates():
    assert len(SHIM_TEXT.rstrip("\n").split("\n")) <= 10
    tree = ast.parse(SHIM_TEXT)
    assert isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)
    assert [ast.unparse(n) for n in tree.body[1:]] == ["from codex_harness.entry.processes.monitor_frontend_checks import main",
                                                       "if __name__ == '__main__':\n    raise SystemExit(main())"]
    assert shim.main is entry.main and not [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))]


# ---- the pinned argv, in a subprocess, against M7's own main ------------------------------------------------------

def run_pinned(cwd, *arguments):
    environment = {"PYTHONPATH": str(TARGET_SRC), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"}
    return subprocess.run([PY, "-m", "codex_harness.adapters.monitor_frontend_checks", *arguments], cwd=cwd, env=environment, capture_output=True, text=True, timeout=120)


def m7_output(monkeypatch, cwd, arguments):
    reference = stand_in_m7()
    buffer = io.StringIO()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(sys, "stdout", buffer)
    code = reference.main(arguments)
    monkeypatch.undo()
    return code, buffer.getvalue()


def test_the_pinned_argv_with_an_extra_argument_gives_m7s_invalid_invocation_and_exit_code(tmp_path, monkeypatch):
    for arguments in (["extra"], ["--help"], ["a", "b"], [""]):
        done = run_pinned(tmp_path, *arguments)
        code, expected = m7_output(monkeypatch, tmp_path, arguments)
        assert (done.returncode, done.stdout, done.stderr) == (code, expected, "") and code == 2, arguments
        body = json.loads(done.stdout)
        assert body["error"] == {"kind": "invalid_invocation"} and body["status"] == "error" and body["schema"] == "zeus.monitor-frontend-checks/v1"


def test_the_pinned_argv_with_no_argument_gives_m7s_observation_over_a_fixture_tree(tmp_path, monkeypatch):
    """Needs no toolchain: with the image's node or dependency store absent the observation is M7's own refusal (host-dependent kinds are asserted, not guessed)."""
    for name, build in (("empty", lambda root: None), ("tree", lambda root: (root / "frontend" / "monitor").mkdir(parents=True))):
        root = tmp_path / name
        root.mkdir()
        build(root)
        if module.NODE.is_file() and (module.DEPENDENCY_ROOT / "node_modules").is_dir() and name == "tree":
            pytest.skip("the image toolchain is installed here: the run would be a real one")
        done = run_pinned(root)
        code, expected = m7_output(monkeypatch, root, [])
        assert (done.returncode, done.stdout, done.stderr) == (code, expected, "") and code == 1, name
        body = json.loads(done.stdout)
        assert body["schema"] == "zeus.monitor-frontend-checks/v1" and body["status"] == "unavailable" and body["candidate"] == str(root.resolve())
        assert body["refusal"]["kind"] == ("monitor_project_missing" if name == "empty" else body["refusal"]["kind"])
        assert body["refusal"]["kind"] in {"monitor_project_missing", "node_missing", "dependencies_missing"}
        assert [check["status"] for check in body["checks"]] == ["not_run"] * 3
        assert body["node"] == "/usr/local/bin/node" and body["dependency_root"] == "/opt/zeus-monitor"


def test_the_pinned_argv_strings_of_the_target_resources_are_unchanged_and_resolve_through_the_shim():
    argv = "codex_harness.adapters.monitor_frontend_checks"
    resources = TARGET_SRC / "codex_harness" / "resources"
    pinning = [resources / "evidence-policy.json", resources / "worker-profile-v1.json", TARGET_SRC / "codex_harness" / "evidence" / "domain" / "evidence.py"]
    assert [p.name for p in pinning if argv in p.read_text(encoding="utf-8")] == [p.name for p in pinning], "the policy, the profile and the domain still name the pinned module"
    from codex_harness.evidence.domain import evidence
    assert evidence.MONITOR_FRONTEND_ARGV == ["python", "-m", argv]
    allowed = json.loads((resources / "evidence-policy.json").read_text(encoding="utf-8"))["replay"]["allowed_argv_prefixes"]
    assert ["python", "-m", argv] in allowed
    assert (TARGET_SRC / "codex_harness" / "adapters" / "monitor_frontend_checks.py").is_file()


# ---- no new spawn site --------------------------------------------------------------------------------------------

def test_no_new_spawn_site_the_only_process_start_is_the_injected_capture_called_once():
    for text in (TEXT, SHIM_TEXT, Path(composition.__file__).read_text(encoding="utf-8"), Path(entry.__file__).read_text(encoding="utf-8")):
        tree = ast.parse(text)
        body = text.split('"""', 2)[2] if text.lstrip().startswith('"""') else text
        for banned in ("subprocess", "Popen", "multiprocessing", "os.system", "os.popen", "os.exec", "os.spawn", "os.fork", "threading"):
            assert banned not in body, banned
        spawn = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                 and n.func.value.id == "os" and re.match(r"(exec|spawn|posix_spawn|system|popen|fork)", n.func.attr)]
        assert spawn == []
    captures = [n for n in ast.walk(ast.parse(TEXT)) if is_call_to(n, "capture")]
    theirs = [n for n in ast.walk(ast.parse(M7_TEXT)) if is_call_to(n, "capture")]
    assert len(captures) == len(theirs) == 1
    assert [f.name for f in ast.parse(TEXT).body if isinstance(f, ast.FunctionDef) and any(is_call_to(n, "capture") for n in ast.walk(f))] == ["_run_checks"]
