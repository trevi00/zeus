"""S8 pilot 66: the M7 evidence-inspection application moved into evidence, VERBATIM through named rules
(A/evidence/rebuild/s8/evidence-inspection-move/transcribe.py; DESIGN-s8 §1 V4/V7, §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`evidence.inspections` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

from _layout import REPO, TARGET

SOURCE = "e38aa722"
APP = "codex_harness.evidence.application.evidence_inspection"
S5 = "codex_harness.evidence.application.inspections"
M7_PATH = "src/codex_harness/application/evidence_inspection.py"
ADDED = {("RECORDS",)}  # R-e1: the one EvidenceRecords instance the delegation reads through


def m7_text(path=M7_PATH):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module):
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


def cls(src, name):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)


def method(klass, name):
    return next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_application_is_m7_plus_the_one_records_instance_with_the_declared_r_e1_method():
    ref, ours = statements(m7_text()), statements(target_text(APP))
    assert set(ours) - set(ref) == ADDED and set(ref) <= set(ours)
    assert [k for k in ours if k not in ADDED] == list(ref)  # M7 order
    for key in ref:
        if key != ("EvidenceInspections",):
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key
    theirs, mine = ref[("EvidenceInspections",)], ours[("EvidenceInspections",)]
    names = [n.name for n in theirs.body if isinstance(n, ast.FunctionDef)]
    assert names == ["__init__", "binding", "inspect", "require_all_checked"]
    assert [n.name for n in mine.body if isinstance(n, ast.FunctionDef)] == names
    for name in names[:-1]:  # the three bodies M7 owns here, AST-identical (decorators included)
        assert ast.dump(method(mine, name)) == ast.dump(method(theirs, name)), name
    assert len(ref) == 4 and len(ours) == 5


def test_r_e1_require_all_checked_keeps_the_m7_signature_and_docstring_and_has_only_the_delegation():
    old, new = method(cls(m7_text(), "EvidenceInspections"), "require_all_checked"), method(
        cls(target_text(APP), "EvidenceInspections"), "require_all_checked")
    assert ast.dump(new.args) == ast.dump(old.args) and new.decorator_list == old.decorator_list == []
    assert ast.get_docstring(new) == ast.get_docstring(old)
    assert len(new.body) == 2 and isinstance(new.body[1], ast.Return)
    assert ast.unparse(new.body[1]) == "return RECORDS.require_all_checked(tx, inspection_id, policy_hash=policy_hash, binding=binding)"


def test_the_s5_body_it_delegates_to_is_m7_s_require_all_checked_and_bucket():
    s5 = method(cls(target_text(S5), "EvidenceRecords"), "require_all_checked")
    m7 = method(cls(m7_text(), "EvidenceInspections"), "require_all_checked")
    assert ast.dump(s5) == ast.dump(m7)
    app, records = importlib.import_module(APP), importlib.import_module(S5)
    assert app.BUCKET == records.BUCKET == "evidence_inspections"
    assert app.NOTICES == "evidence_inspection_notices"


def test_delegation_goes_through_one_evidence_records_instance_and_never_the_inspector_or_the_store():
    from codex_harness.evidence.application.inspections import EvidenceRecords
    from codex_harness.storage.adapters.memory_store import MemoryStore

    app = importlib.import_module(APP)
    assert isinstance(app.RECORDS, EvidenceRecords) and app.EvidenceInspections.require_all_checked is not EvidenceRecords.require_all_checked
    seen = []

    class Spy(EvidenceRecords):
        def require_all_checked(self, tx, inspection_id, *, policy_hash=None, binding=None):
            seen.append((tx, inspection_id, policy_hash, binding))
            return {"id": inspection_id, "spy": True}

    store = MemoryStore()
    inspections = app.EvidenceInspections(None, None)  # neither the store nor the inspector is read
    original, app.RECORDS = app.RECORDS, Spy()
    try:
        with store.transaction() as tx:
            row = inspections.require_all_checked(tx, "row-1", policy_hash="p" * 64, binding={"task_id": "t"})
            assert row == {"id": "row-1", "spy": True}
            assert seen == [(tx, "row-1", "p" * 64, {"task_id": "t"})]
            inspections.require_all_checked(tx, "row-2")
            assert seen[1] == (tx, "row-2", None, None)
    finally:
        app.RECORDS = original
    # the body is not duplicated: the module itself never reads the bucket in this method
    body = ast.get_source_segment(target_text(APP), method(cls(target_text(APP), "EvidenceInspections"), "require_all_checked"))
    assert "tx.get" not in body and "require(" not in body


def test_the_delegation_gives_the_m7_refusals_on_real_rows():
    import pytest

    from codex_harness.kernel.errors import ContractError
    from codex_harness.storage.adapters.memory_store import MemoryStore

    app = importlib.import_module(APP)
    store = MemoryStore()
    rows = {"ok": {"id": "ok", "policy_hash": "p", "binding": {"task_id": "t"}, "verdict": "all_checked", "denominator": {"checked": 1, "claims": 1}},
            "open": {"id": "open", "policy_hash": "p", "binding": {"task_id": "t"}, "verdict": "incomplete",
                     "denominator": {"checked": 1, "not_checked": 1, "claims": 2}}}
    with store.transaction() as tx:
        for key, row in rows.items():
            tx.put(app.BUCKET, key, row)
    inspections = app.EvidenceInspections(store, None)
    with store.transaction() as tx:  # example 2: an unchecked claim, through EvidenceRecords
        with pytest.raises(ContractError, match="Evidence inspection is incomplete: checked=1, not_checked=1"):
            inspections.require_all_checked(tx, "open")
        assert inspections.require_all_checked(tx, "ok", policy_hash="p", binding={"task_id": "t"}) == rows["ok"]
        with pytest.raises(ContractError, match="another policy"):
            inspections.require_all_checked(tx, "ok", policy_hash="q")
        with pytest.raises(ContractError, match="another execution or revision"):
            inspections.require_all_checked(tx, "ok", binding={"task_id": "u"})
        with pytest.raises(ContractError, match="missing"):
            inspections.require_all_checked(tx, "nope")


def test_inspect_fence_refusal_is_raised_unchanged_with_no_row_and_no_notice():
    from codex_harness.storage.adapters.memory_store import MemoryStore

    app = importlib.import_module(APP)
    ident = {"policy_hash": "a" * 64, "environment_digest": "e" * 64, "interpreter": "/py"}

    class Inspector:
        def snapshot(self, cwd=None):
            return {"identity": ident, "environment": {"PATH": "/bin"}, "interpreter": "/py"}

        def inspect(self, claims, cwd, binding, environment=None, interpreter=None):
            return {"policy_hash": ident["policy_hash"], "findings": [], "context": {
                "environment_digest": ident["environment_digest"], "interpreter": "/py"}}

    store, refusal = MemoryStore(), RuntimeError("lease moved")

    def guard(tx):
        raise refusal

    task, candidate = {"id": "t", "generation": 1, "attempt": 1}, {"revision": "c" * 40}
    try:
        app.EvidenceInspections(store, Inspector()).inspect(task, candidate, [], "/ws", guard=guard)
    except RuntimeError as exc:
        assert exc is refusal  # example 1: the caller's refusal, unchanged
    else:
        raise AssertionError("the fence must refuse")
    with store.transaction() as tx:
        assert tx.scan(app.BUCKET) == [] and tx.scan(app.NOTICES) == []


def test_imports_are_only_kernel_and_evidence_homes():
    mods = [n.module for n in ast.walk(ast.parse(target_text(APP))) if isinstance(n, ast.ImportFrom)
            and n.module.startswith("codex_harness.")]
    assert sorted(set(mods)) == ["codex_harness.evidence.application.inspections", "codex_harness.evidence.domain.evidence",
                                 "codex_harness.kernel.errors", "codex_harness.kernel.ids"]
    assert "codex_harness.domain" not in target_text(APP).replace("codex_harness.evidence.domain", "")


def test_v4_evidence_owns_the_inspection_buckets():
    from codex_harness.evidence import ports

    assert ports.OWNED_BUCKETS == ("evidence_inspections", "evidence_inspection_notices", "completion_verdicts", "completion_rejections")
    app = importlib.import_module(APP)
    assert {app.BUCKET, app.NOTICES} == set(ports.OWNED_BUCKETS[:2])


def test_only_the_evidence_inspection_application_writes_the_inspection_buckets():
    # Literals of the two bucket names occur only in the ports, the writer and the S5 read; coordination reads the
    # ledger through its own constant and `tx.get` (never a put), and nothing else names either bucket.
    src = TARGET / "src" / "codex_harness"
    allowed = {"evidence/application/evidence_inspection.py", "evidence/application/inspections.py", "evidence/ports.py",
               "coordination/application/operation.py"}
    named = [path.relative_to(src).as_posix() for path in sorted(src.rglob("*.py"))
             if any(f"'{b}'" in path.read_text() or f'"{b}"' in path.read_text()
                    for b in ("evidence_inspections", "evidence_inspection_notices"))]
    assert set(named) <= allowed, named
    operation = (src / "coordination/application/operation.py").read_text()
    assert "put(INSPECTIONS" not in operation and "tx.get(INSPECTIONS" in operation
    reader = (src / "evidence/application/inspections.py").read_text()
    assert ".put(" not in reader
    # both writes are in the moved module: the row (BUCKET) and the notice (NOTICES)
    writer = target_text(APP)
    assert "tx.put(BUCKET, key, row)" in writer and "tx.put(NOTICES, notice['id'], notice)" in writer
