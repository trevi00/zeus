"""S8 pilot 78: the M7 council run moved into coordination (V12), VERBATIM through named rules
(A/evidence/rebuild/s8/council-move/transcribe.py; DESIGN-s8 §7 V12).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.council` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

from _layout import REPO

SOURCE = "e38aa722"
APP = "codex_harness.coordination.application.council"
M7_PATH = "src/codex_harness/application/council.py"
PORTS = ("sessions_factory", "evidence_records", "promotion", "operation_factory")


def m7_text(path=M7_PATH):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module=APP):
    return Path(importlib.import_module(module).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def methods(src, name="CouncilRun"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def test_application_is_m7_in_m7_order_and_only_init_differs():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref)  # nothing added, nothing dropped, same order
    for key in ref:
        if key != ("CouncilRun",):
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) and len(theirs) == 9
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == ["__init__"]
    assert len(ref) == 7 and len(ours) == 7


def test_init_ports_are_keyword_only_after_artifacts_and_forwarded_by_keyword():
    new, old = methods(target_text())["__init__"], methods(m7_text())["__init__"]
    assert [a.arg for a in new.args.args] == [a.arg for a in old.args.args]  # M7's positional signature unchanged
    assert [a.arg for a in new.args.args][-2:] == ["snapshot", "artifacts"]
    assert [a.arg for a in new.args.kwonlyargs] == list(PORTS)
    assert all(isinstance(d, ast.Constant) and d.value is None for d in new.args.kw_defaults)
    calls = [n for n in ast.walk(new) if isinstance(n, ast.Call) and ast.unparse(n.func) == "super().__init__"]
    assert len(calls) == 1
    m7_call = next(n for n in ast.walk(old) if isinstance(n, ast.Call) and ast.unparse(n.func) == "super().__init__")
    assert [ast.dump(a) for a in calls[0].args] == [ast.dump(a) for a in m7_call.args]  # positional args as M7 forwards them
    assert [(k.arg, ast.unparse(k.value)) for k in calls[0].keywords] == [(p, p) for p in PORTS]
    assert len(new.body) == len(old.body) and ast.dump(new.body[-1]) == ast.dump(old.body[-1])  # M7's own assignment stays


def test_imports_are_only_kernel_coordination_and_research_domain_homes():
    mods = {n.module for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.ImportFrom)
            and n.module.startswith("codex_harness.")}
    assert mods == {
        "codex_harness.coordination.application.autonomous", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
        "codex_harness.research.domain.autonomous", "codex_harness.research.domain.council",
        "codex_harness.research.domain.council_input", "codex_harness.research.domain.dge"}
    assert not [m for m in mods if m.startswith(("codex_harness.research.application", "codex_harness.evidence",
                                                 "codex_harness.knowledge", "codex_harness.adapters"))]


def test_the_imported_names_have_their_single_definers():
    app = importlib.import_module(APP)
    autonomous = importlib.import_module("codex_harness.coordination.application.autonomous")
    council = importlib.import_module("codex_harness.research.domain.council")
    assert app.AutonomousRun is autonomous.AutonomousRun and app.AutonomousRefused is autonomous.AutonomousRefused
    assert app.BUCKET == "autonomous_runs" and app.BUCKET is autonomous.BUCKET
    assert app.DgeRefused is importlib.import_module("codex_harness.research.domain.dge").DgeRefused
    assert app.DgeRefused is importlib.import_module("codex_harness.research.application.dge").DgeRefused
    assert app.SnapshotError is council.SnapshotError  # the definer is research.domain.council
    assert app.CouncilFieldRefused is council.CouncilFieldRefused


def test_council_run_is_an_autonomous_run_and_the_ports_default_to_none():
    from codex_harness.coordination.application.autonomous import AutonomousRun

    app = importlib.import_module(APP)
    assert issubclass(app.CouncilRun, AutonomousRun)
    bare = app.CouncilRun(SimpleNamespace(store=None))
    assert (bare.sessions_factory, bare.evidence_records, bare.promotion, bare.operation_factory) == (None,) * 4
    assert (bare.snapshot, bare.artifacts) == (None, None)


def test_each_port_reaches_the_base_class_and_m7_s_positional_arguments_stay_in_place():
    app = importlib.import_module(APP)
    marks = {name: object() for name in PORTS}
    service, executor, bus, workflow, budget, collector = (object() for _ in range(6))
    snapshot, artifacts, evidence, repository, observer = (object() for _ in range(5))
    run = app.CouncilRun(service, executor, bus, workflow, budget, collector, "verify", repository, observer, lambda: "t",
                         evidence, snapshot, artifacts, **marks)
    assert [getattr(run, name) for name in PORTS] == [marks[name] for name in PORTS]
    assert (run.service, run.executor, run.bus, run.workflow, run.budget, run.collector) == (
        service, executor, bus, workflow, budget, collector)
    assert (run.evidence, run.snapshot, run.artifacts, run.repository, run.observer) == (
        evidence, snapshot, artifacts, repository, observer)
    assert run.clock() == "t"
