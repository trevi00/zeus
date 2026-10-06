"""S8 pilot 68: the M7 autonomous cycle moved into coordination (V12), VERBATIM through named rules
(A/evidence/rebuild/s8/autonomous-move/transcribe.py; DESIGN-s8 §1 V3/V4/V9, §6 V11, §7 V12).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.autonomous` golden.
"""
import ast
import importlib
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.coordination.application.autonomous"
M7_PATH = "src/codex_harness/application/autonomous.py"
ADDED = {("SESSIONS",)}  # R-a2
REWRITTEN = ["__init__", "run", "_freeze_packet", "_implement_and_promote", "_role", "_deliver", "_promote"]


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


def methods(src, name="AutonomousRun"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def test_application_is_m7_plus_sessions_in_m7_order_and_only_the_rewritten_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    assert set(ours) - set(ref) == ADDED and set(ref) <= set(ours)
    assert [k for k in ours if k not in ADDED] == list(ref)
    for key in ref:
        if key != ("AutonomousRun",):
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) and len(theirs) == 19
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN
    assert len(ref) == 13 and len(ours) == 14


def test_r_a1_r_a3_r_a4_sites_pinned_by_name():
    text, m7 = target_text(), m7_text()
    for old, new, count in (
            ("DebateSessions(self.service.store, self.clock)", "self.sessions_factory(self.service.store, self.clock)", 1),
            ("EvidenceInspections(self.service.store, None).require_all_checked(", "self.evidence_records.require_all_checked(", 1),
            ("promotion = promote(tx, run_id, graph,", "promotion = self.promotion.promote(tx, run_id, graph,", 1),
            ("operation = Operation(self.service, self.executor, self.bus, self.workflow, self.budget, self.collector,",
             "operation = self.operation_factory(self.executor, self.bus, self.workflow, self.budget, self.collector,", 1),
            ("flush_outbox(self.service, ", "flush_outbox(self.service.flusher, ", 3)):
        assert m7.count(old) == count and text.count(new) == count and old not in text, old
    assert "Operation(" not in text.replace("self.operation_factory(", "")  # R-a3: the import is gone too


def test_init_ports_are_keyword_only_after_evidence_and_m7_require_is_verbatim():
    new = methods(target_text())["__init__"].args
    old = methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args]  # positional signature unchanged (CouncilRun's super().__init__)
    assert [a.arg for a in new.kwonlyargs] == ["sessions_factory", "evidence_records", "promotion", "operation_factory"]
    assert all(isinstance(d, ast.Constant) and d.value is None for d in new.kw_defaults)
    run = methods(target_text())["run"]
    requires = [n for n in run.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "require"]
    m7_requires = [n for n in methods(m7_text())["run"].body if isinstance(n, ast.Expr)
                   and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "require"]
    assert len(requires) == 2 and len(m7_requires) == 1
    assert ast.dump(requires[0]) == ast.dump(m7_requires[0])  # M7's require, verbatim, first


def test_imports_are_only_kernel_coordination_intake_and_research_homes():
    mods = {n.module for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == {
        "codex_harness.coordination.application.execution_notices", "codex_harness.coordination.application.local_cycle",
        "codex_harness.coordination.application.operation", "codex_harness.coordination.application.outbox_relay",
        "codex_harness.coordination.domain.operation", "codex_harness.intake.domain.operation_manifest",
        "codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.message",
        "codex_harness.research.domain.autonomous", "codex_harness.research.domain.council", "codex_harness.research.domain.dge"}
    # no forbidden context application import (research/evidence/knowledge applications arrive only through the ports)
    assert not [m for m in mods if m.startswith(("codex_harness.research.application", "codex_harness.evidence",
                                                 "codex_harness.knowledge"))]
    assert "codex_harness.domain" not in target_text().replace("codex_harness.research.domain", "").replace(
        "codex_harness.coordination.domain", "").replace("codex_harness.intake.domain", "")


def test_the_dge_refused_is_the_single_research_class():
    app = importlib.import_module(APP)
    assert app.DgeRefused is importlib.import_module("codex_harness.research.domain.dge").DgeRefused
    assert app.DgeRefused is importlib.import_module("codex_harness.research.application.dge").DgeRefused


def test_r_a2_sessions_equals_the_research_published_language_name():
    app = importlib.import_module(APP)
    dge = importlib.import_module("codex_harness.research.application.dge")
    assert app.SESSIONS == dge.SESSIONS == "dge_sessions"
    assert app.BUCKET == "autonomous_runs"


def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def test_ports_are_structurally_satisfied_by_the_three_implementations():
    from codex_harness.coordination import ports
    from codex_harness.evidence.application.inspections import EvidenceRecords
    from codex_harness.knowledge.application import promotion
    from codex_harness.research.application.dge import DebateSessions

    def protocol_methods(proto):
        return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}

    for proto, impl in ((ports.DebateSessions, DebateSessions), (ports.EvidenceRecords, EvidenceRecords),
                        (ports.KnowledgePromotion, promotion)):
        declared = protocol_methods(proto)
        assert 0 < len(declared) <= 6
        for name, fn in declared.items():
            assert _params(fn) == _params(getattr(impl, name)), (proto.__name__, name)
    assert sorted(protocol_methods(ports.DebateSessions)) == ["register", "status", "submit"]
    assert sorted(protocol_methods(ports.KnowledgePromotion)) == ["promote"]


def test_v4_coordination_owns_autonomous_runs_and_only_this_module_writes_it():
    from codex_harness.coordination import ports

    assert "autonomous_runs" in ports.OWNED_BUCKETS and ports.OWNED_BUCKETS.count("autonomous_runs") == 1
    for context in ("research", "evidence", "knowledge", "execution", "review", "delivery", "intake", "routing"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or "autonomous_runs" not in getattr(other, "OWNED_BUCKETS", ())
    writers = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text()
        if "autonomous_runs" not in text:
            continue
        for call in ast.walk(ast.parse(text)):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                first = call.args[0]
                if (isinstance(first, ast.Constant) and first.value == "autonomous_runs") or (
                        isinstance(first, ast.Name) and first.id in ("BUCKET", "RUNS", "RESEARCH_RUNS")
                        and f'{first.id} = "autonomous_runs"' in text.replace("'", '"')):
                    writers.append(path.relative_to(SRC).as_posix())
    assert sorted(set(writers)) == ["coordination/application/autonomous.py"]


def _manifest():
    from codex_harness.research.domain.autonomous import validate_autonomous_manifest
    from codex_harness.routing.adapters.provider_policy import packaged_policy

    document = {"schema": "urn:zeus:autonomous:1", "id": "auto-001", "base_revision": "a" * 40,
                "goal": {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "c", "rationale": "r"},
                "plan": {"objective": "o", "acceptance_criteria": ["focused tests pass"], "allowed_paths": ["docs/x.md"]},
                "budget": {"per_host": 8, "total": 16},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2},
                "deadline": "2099-01-01T00:00:00+00:00",
                "research": {"topic": "t", "questions": ["q"], "search_scope": ["docs"]}}
    return validate_autonomous_manifest(document, packaged_policy()), document["goal"]


IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p", "provider": {"policy_digest": "x", "config_digest": "y"}}
PORTS = ("sessions_factory", "evidence_records", "promotion", "operation_factory")
M7_MESSAGE = "Autonomous run needs an executor, a call budget, a bus, a workflow and an evidence port"
PORT_MESSAGE = "Autonomous run needs a debate-session factory, an evidence-records port, a promotion port and an operation factory"


def _run(**overrides):
    from codex_harness.coordination.application.autonomous import AutonomousRun
    from codex_harness.storage.adapters.memory_store import MemoryStore

    manifest, goal = _manifest()
    service = SimpleNamespace(store=MemoryStore(), org=None, flusher=None)
    thing = object()
    kwargs = {"executor": thing, "budget": thing, "bus": None, "workflow": thing, "evidence": thing,
              **{name: thing for name in PORTS}, **overrides}
    kwargs["bus"] = kwargs["bus"] or thing
    return AutonomousRun(service, **kwargs), manifest, goal


@pytest.mark.parametrize("missing", PORTS)
def test_each_missing_port_is_refused_by_the_separate_port_require_after_m7_s_own(missing):
    from codex_harness.kernel.errors import ContractError

    run, manifest, goal = _run(**{missing: None})
    with pytest.raises(ContractError) as info:
        run.run(manifest, IDENTITY, goal)
    assert str(info.value) == PORT_MESSAGE


def test_a_missing_executor_still_gets_m7_s_exact_message_before_the_port_check():
    from codex_harness.kernel.errors import ContractError

    run, manifest, goal = _run(executor=None, sessions_factory=None)
    with pytest.raises(ContractError) as info:
        run.run(manifest, IDENTITY, goal)
    assert str(info.value) == M7_MESSAGE


def test_ports_default_to_none_and_a_bare_run_is_refused_at_run_not_at_construction():
    from codex_harness.coordination.application.autonomous import AutonomousRun

    bare = AutonomousRun(SimpleNamespace(store=None))
    assert (bare.sessions_factory, bare.evidence_records, bare.promotion, bare.operation_factory) == (None,) * 4
