"""S8 pilot 70: the M7 `ResearchAudits` moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/research-app-move/transcribe.py; DESIGN-s8 §1 V3/V4, §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.audit_core` golden.
"""
import ast
import importlib
import inspect
import subprocess
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from _layout import REPO, TARGET

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
APP = "codex_harness.research.application.research"
M7_PATH = "src/codex_harness/application/research.py"
REWRITTEN = ["__init__", "checkpoint", "propose", "_queue_review", "review", "_eligible"]
BUCKETS = ("research_adaptations", "research_approvals", "research_audits", "research_backlog", "research_checkpoints",
           "research_evidence_history", "research_observed_assets", "research_partitions", "research_paths",
           "research_receipts", "research_reviews", "research_subsystems")


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


def methods(src, name="ResearchAudits"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def test_application_is_m7_in_m7_order_and_only_the_rewritten_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == [("ResearchAudits",)]
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) and len(theirs) == 16
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN


def test_rule_sites_pinned_by_name():
    text, m7 = target_text(), m7_text()
    for old, new, count in (
            ("tx.put('outbox', continuation['message_id'], {'message': continuation, 'sent': False})",
             "self.outbox.append(tx, continuation)", 1),
            ("ExecutionRecovery(self.store, self.workflow.org, self.artifacts).validate_decision(tx, current)",
             "self.decision_validation.validate_decision(tx, current)", 1),
            ("if tx.get('decisions_pending', key):", "if self.pending_decisions.exists(tx, key):", 1),
            ("tx.put('decisions_pending', key, {", "self.pending_decisions.queue(tx, {", 1)):
        assert m7.count(old) == count and text.count(new) == count and old not in text, old
    code = {n.id for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Attribute)}
    assert "ExecutionRecovery" not in code  # R-r2: the lazy coordination import is gone
    assert "tx.put('decisions_pending'" not in text and "tx.put('outbox'" not in text
    assert "@staticmethod\n    def _queue_review" in m7 and "def _queue_review(self, tx," in text


def test_an_existing_row_draws_no_id():
    """Behaviour (R-r4'): `_queue_review` queues one pending decision and draws one message id; asked again for the same
    binding (the row exists) it draws no id and writes nothing."""
    from codex_harness.coordination.application.decisions import PendingDecisions
    from codex_harness.kernel import message
    from codex_harness.storage.adapters.memory_store import MemoryStore

    class CountingIds:
        def __init__(self):
            self.draws = 0

        def uuid4(self):
            self.draws += 1
            return f"00000000-0000-4000-8000-{self.draws:012d}"

    ids = CountingIds()
    audits = importlib.import_module(APP).ResearchAudits(MemoryStore(), None, None, None,
                                                         pending_decisions=PendingDecisions())
    store = MemoryStore()
    original, message.SYSTEM_IDS = message.SYSTEM_IDS, ids
    try:
        with store.transaction() as tx:
            audits._queue_review(tx, "audit-1", {"author": "worker:a"}, "binding-1", "conductor")
            assert ids.draws == 1 and len(tx.scan("decisions_pending")) == 1
            before = tx.scan("decisions_pending")
            audits._queue_review(tx, "audit-1", {"author": "worker:a"}, "binding-1", "conductor")
            assert ids.draws == 1 and tx.scan("decisions_pending") == before
    finally:
        message.SYSTEM_IDS = original


def test_r_r4_prime_order_exists_before_envelope_before_queue():
    """Structural: the call order exists, envelope, queue and the early return between the first two are M7's
    (the S8 move rule); behaviour is covered by test_an_existing_row_draws_no_id."""
    body = methods(target_text())["_queue_review"]
    lines = {}
    for call in ast.walk(body):
        if isinstance(call, ast.Call):
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
            if name in ("exists", "envelope", "queue"):
                lines.setdefault(name, call.lineno)
    assert sorted(lines, key=lines.get) == ["exists", "envelope", "queue"]
    # the early return sits between the query and the envelope: no id is drawn for a row that already exists
    returns = [n.lineno for n in ast.walk(body) if isinstance(n, ast.Return)]
    assert returns and lines["exists"] < min(returns) < lines["envelope"]


def test_init_ports_are_keyword_only_after_runner_and_m7_positional_signature_is_unchanged():
    new, old = methods(target_text())["__init__"].args, methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args]
    assert [a.arg for a in new.kwonlyargs] == ["decision_validation", "outbox", "pending_decisions"]
    assert all(isinstance(d, ast.Constant) and d.value is None for d in new.kw_defaults)


def test_imports_are_only_kernel_and_research_and_storage_homes():
    mods = {n.module for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.ImportFrom)
            and n.module.startswith("codex_harness.")}
    assert mods == {"codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.message",
                    "codex_harness.research.application.audit_gate", "codex_harness.research.domain.research",
                    "codex_harness.research.ports", "codex_harness.storage.ports"}
    assert not [m for m in mods if m.startswith(("codex_harness.coordination", "codex_harness.domain"))]


def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def _protocol_methods(proto):
    return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}


def test_ports_are_structurally_satisfied_by_their_implementations():
    from codex_harness.coordination.application.decisions import PendingDecisions as Pending
    from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
    from codex_harness.coordination.application.outbox import Outbox
    from codex_harness.research import ports
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts

    for proto, impl in ((ports.DecisionValidation, ExecutionRecovery), (ports.PendingDecisions, Pending),
                        (ports.OutboxAppend, Outbox), (ports.AuditArtifacts, FileArtifacts)):
        declared = _protocol_methods(proto)
        assert declared, proto
        for name, fn in declared.items():
            assert _params(fn) == _params(getattr(impl, name)), (proto.__name__, name)
    assert sorted(_protocol_methods(ports.PendingDecisions)) == ["exists", "queue"]
    assert sorted(_protocol_methods(ports.DecisionValidation)) == ["validate_decision"]
    assert sorted(_protocol_methods(ports.AuditArtifacts)) == ["document", "inspect"]
    assert sorted(_protocol_methods(ports.SourceVerifier)) == ["verify"]


def test_r_r1_ports_are_m7_s_declarations():
    from codex_harness.research import ports

    ref = {n.name: n for n in ast.parse(m7_text("src/codex_harness/ports.py")).body if isinstance(n, ast.ClassDef)}
    ours = {n.name: n for n in ast.parse(Path(ports.__file__).read_text()).body if isinstance(n, ast.ClassDef)}
    for name in ("AuditArtifacts", "SourceVerifier"):
        assert ast.dump(ours[name]) == ast.dump(ref[name]), name


def test_v4_research_owns_the_audit_buckets_and_only_this_module_writes_them():
    from codex_harness.research import ports

    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    for context in ("coordination", "evidence", "knowledge", "review", "delivery", "intake", "routing", "storage"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or not set(BUCKETS) & set(getattr(other, "OWNED_BUCKETS", ())), context
    writers = set()
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text()
        if not any(b in text for b in BUCKETS):
            continue
        for call in ast.walk(ast.parse(text)):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                first = call.args[0]
                if isinstance(first, ast.Constant) and first.value in BUCKETS:
                    writers.add(path.relative_to(SRC).as_posix())
                elif isinstance(first, ast.Name) and first.id == "kind" and "research_paths" in text:
                    writers.add(path.relative_to(SRC).as_posix())  # the loop variable of checkpoint()
    # S8 batch B3 (V24): M7 `adapters/audit_execution.py` is the second research writer of `research_backlog` (the discovery mapping and the acquire
    # update; `bucket-writers-m7.txt`: `adapters/audit_execution.py[research]; application/research.py[research]`) and of no other of the twelve.
    assert writers == {"research/application/research.py", "research/adapters/audit_execution.py"}
    from codex_harness.research.adapters import audit_execution
    mine = {n.args[0].value for n in ast.walk(ast.parse(Path(audit_execution.__file__).read_text())) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "put" and n.args and isinstance(n.args[0], ast.Constant)} & set(BUCKETS)
    assert mine == {"research_backlog"}


def test_pending_decisions_queue_is_idempotent_and_exists_reports_it():
    from codex_harness.coordination.application.decisions import PendingDecisions
    from codex_harness.storage.adapters.memory_store import MemoryStore

    store, owner = MemoryStore(), PendingDecisions()
    with store.transaction() as tx:
        assert owner.exists(tx, "k") is False
        assert owner.queue(tx, {"id": "k", "n": 1}) is True
        assert owner.exists(tx, "k") is True
    with store.transaction() as tx:
        assert owner.queue(tx, {"id": "k", "n": 2}) is False
        assert tx.get("decisions_pending", "k") == {"id": "k", "n": 1}


def test_review_without_the_decision_validation_port_is_refused_by_the_added_require():
    from codex_harness.kernel.errors import ContractError
    from codex_harness.research.application.research import ResearchAudits
    from codex_harness.research.domain.research import IndependentReview
    from codex_harness.storage.adapters.memory_store import MemoryStore

    workflow = SimpleNamespace(_owned=lambda tx, task: {"id": "t"}, org=None)
    audits = ResearchAudits(MemoryStore(), None, None, workflow)
    assert (audits.decision_validation, audits.outbox, audits.pending_decisions) == (None, None, None)
    review = IndependentReview("b", "lead:research", "e", True, "l", "d", "s", "a", "g")
    with pytest.raises(ContractError) as info:
        audits.review({"id": "t"}, review)
    assert str(info.value) == "Decision validation is not wired"
    assert asdict(review)["actor"] == "lead:research"
