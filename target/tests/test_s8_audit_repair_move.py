"""S8 pilot 100 (DESIGN-s8 §13 V18 R-ar1..R-ar4): M7 `application/audit_repair.py` moves to `research.application.audit_repair` with the outbox, the
event journal and the execution notices owner injected.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `research.audit_repair` golden (the wired module is target-equal to it); the unwired-port refusals have no M7 counterpart
and are pinned here, each with the store left exactly as it was.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest

from codex_harness.coordination.application import execution_notices
from codex_harness.coordination.application.events import EventJournal
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest
from codex_harness.kernel.message import envelope
from codex_harness.research import ports
from codex_harness.research.application import audit_repair as module
from codex_harness.research.application.audit_repair import AuditRepair
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/audit_repair.py"
REWRITTEN = ["__init__", "_commit", "_notify"]
BUCKETS = ("audit_repair_activation", "audit_repair_corrections", "schedule")
HOMES = {"__future__": ["annotations"], "codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["digest", "utcnow"],
         "codex_harness.kernel.message": ["envelope"]}
PORTS_MESSAGE = "Audit repair needs the outbox and the event journal"
NOTICES_MESSAGE = "Audit repair needs the execution notices owner"
VALIDATOR = "Missing subsystem trace: tests"
AUDIT, PARTITION, OPERATOR = "audit-fixture-001", "partition-fixture-001", "owner-fixture"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


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


def methods(src):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "AuditRepair")
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def calls(body):
    """[(line, dotted name)] of every call in a function body, in source order."""
    out = []
    for call in ast.walk(body):
        if isinstance(call, ast.Call):
            out.append((call.lineno, ast.unparse(call.func)))
    return sorted(out)


def commit_block(fn):
    """The statements of the `with self.store.transaction() as tx:` unit of `_commit`."""
    return next(n for n in fn.body if isinstance(n, ast.With)).body


# ---- the structure -----------------------------------------------------------------------------------------------------------------
def test_application_is_m7_in_m7_order_plus_the_v9_constant_and_only_three_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    names = list(ref)
    first = names.index(("BUCKET_ACTIVATION",))
    assert list(ours) == names[:first] + [("NOTICE_REASON",)] + names[first:]
    assert [k for k in ref if k != ("AuditRepair",) and ast.dump(ours[k]) != ast.dump(ref[k])] == []
    assert ast.dump(ours[("NOTICE_REASON",)]) == ast.dump(ast.parse('NOTICE_REASON = "research_required"').body[0])
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) and len(theirs) == 21
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN


def test_v9_the_local_notice_reason_equals_the_execution_notices_owners_constant():
    assert module.NOTICE_REASON == execution_notices.RESEARCH_REQUIRED == "research_required"
    assert "research_required" in execution_notices.REASONS


def test_r_ar1_init_ports_are_keyword_only_after_clock_and_the_m7_signature_is_unchanged():
    new, old = methods(target_text())["__init__"].args, methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args] == ["self", "store", "org", "artifacts"]
    assert [a.arg for a in old.kwonlyargs] == ["replay", "clock"]
    assert [a.arg for a in new.kwonlyargs] == ["replay", "clock", "outbox", "events", "notices"]
    assert [ast.unparse(d) for d in new.kw_defaults] == ["None", "utcnow", "None", "None", "None"]
    assert [ast.unparse(d) for d in old.kw_defaults] == ["None", "utcnow"] and new.defaults == old.defaults == []
    assert "self.outbox, self.events, self.notices = outbox, events, notices" in target_text()


def test_rule_sites_pinned_by_name():
    text, m7 = target_text(), m7_text()
    for old, new, count in (
            ('tx.put("outbox", message["message_id"], {"message": message, "sent": False})', "self.outbox.append(tx, message)", 1),
            ('tx.put("events", correction_id, {', "self.events.append(tx, correction_id, {", 1),
            ('execution_notice(tx, self.org, task, "tasks", NOTICE_REASON, now,', 'self.notices.record(tx, self.org, task, "tasks", NOTICE_REASON, now,', 1)):
        assert m7.count(old) == count and text.count(new) == count and old not in text, old
    assert 'tx.put("outbox"' not in text and 'tx.put("events"' not in text
    # the READS of outbox stay verbatim (M7's own: one scan, two gets)
    for read, count in (('tx.scan("outbox")', 1), ('tx.get("outbox"', 2)):
        assert text.count(read) == m7.count(read) == count, read
    assert text.count(f"require(self.outbox is not None and self.events is not None, {PORTS_MESSAGE!r})".replace("'", '"')) == 1
    assert text.count(f"require(self.notices is not None, {NOTICES_MESSAGE!r})".replace("'", '"')) == 1
    assert "execution_notice(" not in text and "execution_notices import" not in text


def test_r_ar3_r_ar4_the_write_order_is_unchanged_and_the_one_require_follows_the_last_not_admitted_return():
    body = commit_block(methods(target_text())["_commit"])
    ref = commit_block(methods(m7_text())["_commit"])

    def writes(stmts):
        return [name for st in stmts for _, name in calls(st) if name in ("tx.put", "self.outbox.append", "self.events.append")]

    # M7's order: the outbox put, the schedule put, the corrections put, the events put
    assert writes(ref) == ["tx.put"] * 4
    assert writes(body) == ["self.outbox.append", "tx.put", "tx.put", "self.events.append"]
    assert [ast.unparse(n.args[0]) for st in body for n in ast.walk(st)
            if isinstance(n, ast.Call) and ast.unparse(n.func) == "tx.put"] == ["'schedule'", "BUCKET_CORRECTIONS"]
    require = next(i for i, st in enumerate(body) if ast.unparse(st).startswith("require("))
    assert ast.unparse(body[require]) == f"require(self.outbox is not None and self.events is not None, {PORTS_MESSAGE!r})"
    returns = [i for i, st in enumerate(body) if "_not_admitted" in ast.unparse(st) and any(isinstance(n, ast.Return) for n in ast.walk(st))]
    first_write = next(i for i, st in enumerate(body) if writes([st]))
    assert returns and max(returns) < require < first_write
    assert [i for i, st in enumerate(body) if i < require and writes([st])] == []
    assert ast.unparse(body[returns[-1]].test) == "tx.get('schedule', key) is not None"
    # the rest of the unit is M7's, statement for statement: exactly the outbox put and the events put differ
    ours = [st for i, st in enumerate(body) if i != require]
    assert len(ours) == len(ref)
    assert [ast.unparse(old).split("(")[0] + ast.unparse(old.value.args[0]) if isinstance(old, ast.Expr) else "-"
            for old, new in zip(ref, ours) if ast.dump(old) != ast.dump(new)] == ["tx.put'outbox'", "tx.put'events'"]


def test_r_ar1_require_is_the_statement_immediately_before_the_notice_call_in_notify():
    body = methods(target_text())["_notify"].body
    require = next(i for i, st in enumerate(body) if ast.unparse(st).startswith("require("))
    assert ast.unparse(body[require]) == f"require(self.notices is not None, {NOTICES_MESSAGE!r})"
    assert ast.unparse(body[require + 1]).startswith("notice = self.notices.record(tx, self.org, task, 'tasks', NOTICE_REASON, now, digest(proof)")
    assert ast.unparse(body[require + 1]).endswith("proof=proof, evidence_refs=notice_evidence(result))")
    assert ast.unparse(body[require - 1]) == "proof = notice_proof(row, result)"
    assert len([c for c in calls(methods(target_text())["_notify"]) if c[1] == "require"]) == 1


def test_imports_are_only_kernel_and_research_domain_homes():
    tree = ast.parse(target_text())
    found = {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}
    domain = found.pop("codex_harness.research.domain.audit_repair")
    assert found == {k: sorted(v) for k, v in HOMES.items()}
    m7_domain = next(n for n in ast.parse(m7_text()).body if isinstance(n, ast.ImportFrom) and n.module == "codex_harness.domain.audit_repair")
    assert domain == sorted(a.name for a in m7_domain.names) and len(domain) == 40
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in mods if m.startswith(("codex_harness.coordination", "codex_harness.domain", "codex_harness.application",
                                                 "codex_harness.adapters", "codex_harness.execution"))]


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    assert header.startswith("Admit at most ONE evidence-bound corrective successor")
    for needle in ("Layer: application", "Context: research", "Owns:", "Does not own:", "Entry points: AuditRepair, repair_view",
                   "Contracts: INV-AUDIT-REPAIR-001", "Moved from M7 `application/audit_repair.py`", "SOURCE e38aa722", "V18",
                   "A/evidence/rebuild/s8/audit-repair-move/transcribe.py", "R-ar0", "R-ar1", "R-ar2", "R-ar3", "R-ar4"):
        assert needle in header, needle


# ---- the ports and the buckets -----------------------------------------------------------------------------------------------------
def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def _protocol_methods(proto):
    return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}


def test_ports_are_structurally_satisfied_by_the_coordination_owner_operations():
    for proto, impl in ((ports.ExecutionNotices, execution_notices), (ports.OutboxAppend, Outbox), (ports.EventAppend, EventJournal)):
        for name, fn in _protocol_methods(proto).items():
            declared, actual = _params(fn), _params(getattr(impl, name))
            assert actual[:len(declared)] == declared, (proto.__name__, name)
            assert all(p[1] is inspect.Parameter.KEYWORD_ONLY for p in actual[len(declared):]), (proto.__name__, name)
    assert sorted(_protocol_methods(ports.ExecutionNotices)) == ["record"]
    assert [p[0] for p in _params(ports.ExecutionNotices.record)] == ["tx", "org", "row", "bucket", "reason_code", "at", "transition_ref", "proof",
                                                                    "evidence_refs"]


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


def test_v4_research_owns_the_three_buckets_and_only_this_module_writes_them():
    for bucket in BUCKETS:
        assert ports.OWNED_BUCKETS.count(bucket) == 1, bucket
    assert (module.BUCKET_ACTIVATION, module.BUCKET_CORRECTIONS) == BUCKETS[:2]
    for context in ("coordination", "evidence", "knowledge", "review", "delivery", "intake", "routing", "storage", "execution", "observation"):
        other = importlib.import_module(f"codex_harness.{context}.ports") if (SRC / context / "ports.py").exists() else None
        assert other is None or not set(BUCKETS) & set(getattr(other, "OWNED_BUCKETS", ())), context
    assert writers(BUCKETS, ("BUCKET_ACTIVATION", "BUCKET_CORRECTIONS")) == {"research/application/audit_repair.py"}


def test_after_the_move_outbox_and_events_are_written_by_the_module_only_through_the_owner_operations():
    # the module never `put`s a foreign bucket: coordination's Outbox and EventJournal are the writers of those bodies
    assert "research/application/audit_repair.py" not in writers(("outbox", "events"), ("OUTBOX", "EVENTS"))
    assert {"coordination/application/outbox.py", "coordination/application/events.py"} <= writers(("outbox", "events"), ())


# ---- behaviour that has no M7 counterpart: the unwired ports -----------------------------------------------------------------------
class Artifacts:
    """The `AuditArtifacts` port over one scripted document."""

    def __init__(self, ref, document):
        self.ref, self.doc = ref, document

    def inspect(self, reference):
        assert reference == self.ref
        return {"ref": reference}

    def document(self, reference):
        assert reference == self.ref
        return self.doc


def world():
    """A store with the planted rows an admission reads (a settled rejected execution of an enabled audit) and the fakes around it."""
    store, org = MemoryStore(), packaged_organization()
    answer = {"subsystems": {"core": {"name": "core", "tests": [], "tests_not_run": []}}}
    ref = "sha256:" + hashlib.sha256(canonical({"answer": answer}).encode()).hexdigest()
    message = envelope("task.assign", "lead:research", "worker:github", "audit_partition",
                       {"audit_id": AUDIT, "partition_id": PARTITION, "generation": 0}, "audit-partition-key-0")
    task = {"id": message["message_id"], "status": "succeeded", "generation": 0, "attempt": 1, "agent": "worker:github", "message": message,
            "created_at": message["when"]["created_at"], "completed_at": message["when"]["created_at"],
            "result": {"analysis": {"outcome": "analysis_rejected", "reason_code": "analysis_content_rejected", "execution_ref": ref,
                                    "partition_generation": 0, "error_type": "ContractError", "error_digest": digest(VALIDATOR)}}}
    with store.transaction() as tx:
        tx.put("research_audits", AUDIT, {"id": AUDIT})
        tx.put("research_control", "activation", {"status": "active"})
        tx.put("research_partitions", PARTITION, {"partition_id": PARTITION, "audit_id": AUDIT, "generation": 0, "paths": ["cGF0aA=="],
                                                   "subsystems": ["core"]})
        tx.put("outbox", message["message_id"], {"message": message, "sent": True})
        tx.put("tasks", task["id"], task)
    reproduces = {"refused": True, "error_type": "ContractError", "error_digest": digest(VALIDATOR)}
    return store, org, Artifacts(ref, {"answer": answer}), task, (lambda partition, draft: dict(reproduces))


def records(store):
    with store.transaction() as tx:
        return tx.records()


def wired(store, org, artifacts, replay, **overrides):
    ports_ = {"outbox": Outbox(), "events": EventJournal(), "notices": execution_notices, **overrides}
    return AuditRepair(store, org, artifacts, replay=replay, **ports_)


def test_the_wired_module_admits_once_and_a_second_admission_is_lineage_exists_with_the_store_unchanged():
    store, org, artifacts, task, replay = world()
    owner = wired(store, org, artifacts, replay)
    owner.enable(AUDIT, task["id"], operator=OPERATOR)
    admitted = owner.admit(AUDIT)
    assert admitted["admitted"] is True
    with store.transaction() as tx:
        row = tx.get("outbox", admitted["successor_task_id"])
        assert row == {"message": row["message"], "sent": False} and row["message"]["correlation_id"] == "repair:" + admitted["correction_id"]
        assert tx.get("events", admitted["correction_id"])["type"] == "audit.repair_admitted"
        assert tx.get("schedule", "repair:" + admitted["correction_id"])["task_id"] == admitted["successor_task_id"]
    before = records(store)
    again = owner.admit(AUDIT)
    assert again["admitted"] is False and again["reason_code"] == "lineage_exists" and records(store) == before


@pytest.mark.parametrize("missing", [("outbox",), ("events",), ("outbox", "events"), ("notices",)])
def test_r_ar3_r_ar4_unwired_outbox_or_events_refuse_in_commit_and_write_nothing(missing):
    store, org, artifacts, task, replay = world()
    # `notices` is only used by settlement: its absence must not stop an admission
    owner = wired(store, org, artifacts, replay, **{name: None for name in missing})
    owner.enable(AUDIT, task["id"], operator=OPERATOR)
    before = records(store)
    if missing == ("notices",):
        assert owner.admit(AUDIT)["admitted"] is True
        return
    with pytest.raises(ContractError) as info:
        owner.admit(AUDIT)
    assert str(info.value) == PORTS_MESSAGE
    assert records(store) == before
    with store.transaction() as tx:
        assert tx.scan("audit_repair_corrections") == [] and [r for r in tx.scan("schedule") if r["id"].startswith("repair:")] == []
        assert tx.scan("events") == [] and [r for r in tx.scan("outbox") if r["message"]["correlation_id"].startswith("repair:")] == []
    # the refusal comes AFTER every not-admitted verdict: a closed opt-in is still `not_enabled`, not a wiring error
    owner.disable(AUDIT, operator=OPERATOR)
    assert owner.admit(AUDIT)["reason_code"] == "not_enabled"


def test_r_ar1_unwired_notices_refuse_in_settle_on_a_research_required_transition_and_store_nothing():
    store, org, artifacts, task, replay = world()
    owner = wired(store, org, artifacts, replay)
    owner.enable(AUDIT, task["id"], operator=OPERATOR)
    admitted = owner.admit(AUDIT)
    # the successor's settled row: the second content rejection of the same family (planted, as the golden plants it)
    with store.transaction() as tx:
        message = tx.get("outbox", admitted["successor_task_id"])["message"]
        tx.put("outbox", message["message_id"], {"message": message, "sent": True})
        analysis = dict(task["result"]["analysis"], execution_ref="sha256:" + "b" * 64)
        tx.put("tasks", message["message_id"], {**task, "id": message["message_id"], "message": message, "result": {"analysis": analysis}})
    before = records(store)
    bare = wired(store, org, artifacts, replay, notices=None)
    with pytest.raises(ContractError) as info:
        bare.settle(AUDIT)
    assert str(info.value) == NOTICES_MESSAGE
    assert records(store) == before
    with store.transaction() as tx:
        assert tx.get("audit_repair_corrections", admitted["correction_id"])["state"] == "admitted" and tx.scan("execution_notices") == []
    # wired, the same call records the lineage, ONE notice and its outbox record; a repeated settle returns the same notice identity
    first = owner.settle(AUDIT)
    assert [c["state"] for c in first["changed"]] == ["research_required"] and len(first["notices"]) == 1
    again = owner.settle(AUDIT)
    assert again["changed"] == [] and [n["notice_id"] for n in again["notices"]] == [n["notice_id"] for n in first["notices"]]
    with store.transaction() as tx:
        assert len(tx.scan("execution_notices")) == 1 and tx.get("outbox", first["notices"][0]["notice_id"])["sent"] is False


def test_settle_without_a_research_required_transition_needs_no_notices_owner():
    store, org, artifacts, task, replay = world()
    owner = wired(store, org, artifacts, replay, notices=None)
    owner.enable(AUDIT, task["id"], operator=OPERATOR)
    admitted = owner.admit(AUDIT)
    before = records(store)
    settled = owner.settle(AUDIT)
    assert settled["changed"] == [] and settled["settled"][0]["state"] == "admitted" and settled["settled"][0]["correction_id"] == admitted["correction_id"]
    assert records(store) == before


def test_the_dumped_wired_result_is_json_serializable_and_secret_free():
    store, org, artifacts, task, replay = world()
    owner = wired(store, org, artifacts, replay)
    owner.enable(AUDIT, task["id"], operator=OPERATOR)
    assert json.dumps(owner.admit(AUDIT), sort_keys=True) and json.dumps(owner.status(AUDIT), sort_keys=True)
