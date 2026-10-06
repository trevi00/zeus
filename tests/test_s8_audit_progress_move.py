"""S8 pilot 72: the M7 `AuditProgress` moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/audit-progress-move/transcribe.py; DESIGN-s8 §1 V3/V4, §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.audit_progress` golden.
"""
import ast
import importlib
import inspect
import subprocess
from pathlib import Path

import pytest
from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.research.application.audit_progress"
M7_PATH = "src/codex_harness/application/audit_progress.py"
REWRITTEN = ["__init__", "_facts", "_candidate"]
BUCKETS = ("audit_progress_state", "audit_progress_windows")
INVESTIGATIONS = "portfolio_investigations"


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


def methods(src, name="AuditProgress"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def calls(body):
    """[(line, name)] of every call in a function body, by attribute or plain name, in source order."""
    out = []
    for call in ast.walk(body):
        if isinstance(call, ast.Call):
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            out.append((call.lineno, name))
    return sorted(out)


def test_application_is_m7_in_m7_order_and_only_the_rewritten_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref)
    assert list(ref) == [("BUCKET_STATE", "BUCKET_WINDOWS"), ("POLICY_RESOURCE",), ("SOURCE_READ",), ("SEMANTIC",),
                         ("NON_SEMANTIC",), ("packaged_policy",), ("_seconds",), ("AuditProgress",), ("status_view",),
                         ("__all__",)]
    for key, node in ref.items():
        if key != ("AuditProgress",):
            assert ast.dump(ours[key]) == ast.dump(node), key
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) and len(theirs) == 14
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN


def test_rule_sites_pinned_by_name():
    text, m7 = target_text(), m7_text()
    for old, new, count in (
            ("existing = tx.get(BUCKET_INVESTIGATIONS, identifier)",
             "existing = self.investigations.progress_candidate(tx, identifier)", 1),
            ("tx.put(BUCKET_INVESTIGATIONS, identifier, row)",
             "self.investigations.record_progress_candidate(tx, identifier, row)", 2)):
        assert m7.count(old) == count and text.count(new) == count and old not in text, old
    assert "tx.put(BUCKET_INVESTIGATIONS" not in text and "tx.get(BUCKET_INVESTIGATIONS" not in text
    assert text.count("require(self.investigations is not None, 'Investigation candidates are not wired')") == 1
    # the lazy import of the audit core follows ResearchAudits to its research home
    assert "from codex_harness.application.research import ResearchAudits" in m7
    assert "from codex_harness.research.application.research import ResearchAudits" in text
    # `candidates()` still SCANS the investigations bucket (a read, as in M7), so the name stays imported
    assert text.count("BUCKET_INVESTIGATIONS") == 2 and m7.count("BUCKET_INVESTIGATIONS") == 5


def test_r_ap1_order_require_then_query_then_decision_then_record_as_in_m7():
    body = methods(target_text())["_candidate"]
    # the added require is the first statement after the docstring
    first = body.body[1]
    assert isinstance(first, ast.Expr) and calls(first)[0][1] == "require"
    order = [name for _, name in calls(body) if name in ("require", "scan", "progress_candidate", "record_observation", "candidate_row",
                                                          "record_progress_candidate")]
    # M7's order: the window scan, the owner query, the existing-row branch (record_observation then write), then the first record
    assert order == ["require", "scan", "progress_candidate", "record_observation", "record_progress_candidate",
                     "candidate_row", "record_progress_candidate"]
    # M7's own sequence over the investigations bucket: the get, then the first-record's put after the existing-row put
    m7 = methods(m7_text())["_candidate"]
    sites = sorted((c.lineno, c.func.attr) for c in ast.walk(m7) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                   and c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "BUCKET_INVESTIGATIONS")
    assert [name for _, name in sites] == ["get", "put", "put"]


def test_init_port_is_keyword_only_after_clock_and_m7_signature_is_unchanged():
    new, old = methods(target_text())["__init__"].args, methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args] == ["self", "store", "artifacts"]
    assert [a.arg for a in old.kwonlyargs] == ["policy", "clock"]
    assert [a.arg for a in new.kwonlyargs] == ["policy", "clock", "investigations"]
    assert isinstance(new.kw_defaults[-1], ast.Constant) and new.kw_defaults[-1].value is None


def test_imports_are_only_kernel_intake_domain_and_research_homes():
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == {"codex_harness.intake.domain.portfolio", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                    "codex_harness.research.application.research", "codex_harness.research.domain.audit_progress",
                    "codex_harness.research.domain.research"}
    assert not [m for m in mods if m.startswith(("codex_harness.coordination", "codex_harness.domain",
                                                 "codex_harness.application", "codex_harness.intake.application"))]
    assert {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "codex_harness.intake.domain.portfolio"
            for a in n.names} == {"BUCKET_INVESTIGATIONS", "RESEARCH_REQUIRED"}


def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def _protocol_methods(proto):
    return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}


def test_port_is_structurally_satisfied_by_intakes_owner_op():
    from codex_harness.intake.application.progress_candidates import ProgressCandidates
    from codex_harness.research import ports

    declared = _protocol_methods(ports.InvestigationCandidates)
    assert sorted(declared) == ["progress_candidate", "record_progress_candidate"]
    for name, fn in declared.items():
        assert _params(fn) == _params(getattr(ProgressCandidates, name)), name


def test_v4_research_owns_the_progress_buckets_and_only_this_module_writes_them():
    from codex_harness.research import ports

    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    module = importlib.import_module(APP)
    assert (module.BUCKET_STATE, module.BUCKET_WINDOWS) == BUCKETS
    for context in ("coordination", "evidence", "knowledge", "review", "delivery", "intake", "routing", "storage"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or not set(BUCKETS) & set(getattr(other, "OWNED_BUCKETS", ())), context
    assert writers(BUCKETS, ("BUCKET_STATE", "BUCKET_WINDOWS")) == {"research/application/audit_progress.py"}


def test_after_the_move_the_only_target_writer_of_portfolio_investigations_is_intake():
    from codex_harness.intake import ports as intake_ports
    from codex_harness.research import ports

    assert intake_ports.OWNED_BUCKETS.count(INVESTIGATIONS) == 1 and INVESTIGATIONS not in ports.OWNED_BUCKETS
    found = writers((INVESTIGATIONS,), ("BUCKET_INVESTIGATIONS", "INVESTIGATIONS"))
    assert found == {"intake/application/portfolio.py", "intake/application/progress_candidates.py"}


def writers(values, names):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is one of `values` (a literal) or `names`."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                first = call.args[0]
                if (isinstance(first, ast.Constant) and first.value in values) or (isinstance(first, ast.Name) and first.id in names):
                    found.add(path.relative_to(SRC).as_posix())
    return found


def test_candidate_without_the_investigations_port_is_refused_by_the_added_require():
    from codex_harness.kernel.errors import ContractError
    from codex_harness.research.application.audit_progress import AuditProgress
    from codex_harness.storage.adapters.memory_store import MemoryStore

    observer = AuditProgress(MemoryStore(), None)
    assert observer.investigations is None
    with MemoryStore().transaction() as tx, pytest.raises(ContractError) as info:
        observer._candidate(tx, {"id": "e"}, {"index": 1}, 2, "2026-01-01T00:00:00+00:00")
    assert str(info.value) == "Investigation candidates are not wired"
