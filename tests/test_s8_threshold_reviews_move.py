"""S8 pilot 101 (DESIGN-s8 §17 V22 R-tr1..R-tr4): M7 `application/threshold_reviews.py` moves to `research.application.threshold_reviews` with the decision
validation and the decision record injected, and `ThresholdReviewRecords` added as research's side of coordination's `ThresholdReviewRecovery`.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `research.threshold_reviews` golden (the wired module is target-equal to it); the unwired-port refusals have no M7 counterpart
and are pinned here, each with the store left exactly as it was.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import subprocess
from pathlib import Path

import pytest
from _layout import REPO, TARGET

from codex_harness.coordination import ports as coordination_ports
from codex_harness.coordination.application import decisions
from codex_harness.coordination.application.decision_claims import claim_decision
from codex_harness.coordination.application.decisions import DecisionOwnership
from codex_harness.coordination.application.execution_recovery import ExecutionRecovery
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest
from codex_harness.research import ports
from codex_harness.research.application import audit_gate
from codex_harness.research.application import threshold_reviews as module
from codex_harness.research.application.threshold_reviews import ThresholdReviewRecords, ThresholdReviews
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

SRC = TARGET / "src" / "codex_harness"
SOURCE = "e38aa722"
M7_PATH = "src/codex_harness/application/threshold_reviews.py"
REWRITTEN = ["__init__", "_queue", "_prepare", "complete"]
BUCKET = "threshold_review_requests"
HOMES = {"codex_harness.kernel.errors": ["require"], "codex_harness.kernel.ids": ["digest", "utcnow"], "codex_harness.kernel.message": ["envelope"]}
VALIDATION_MESSAGE = "Decision validation is not wired"
DECISIONS_MESSAGE = "Decision record is not wired"
LEAD, CONDUCTOR = "lead:improvement", "conductor"
REVISION = "a" * 40


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


def methods(src, name="ThresholdReviews"):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def calls(body):
    """[(line, dotted name)] of every call in a function body, in source order."""
    return sorted((c.lineno, ast.unparse(c.func)) for c in ast.walk(body) if isinstance(c, ast.Call))


def puts(body):
    """[(line, bucket literal)] of every `tx.put("<literal>", ...)` in a function body, in source order."""
    return sorted((c.lineno, c.args[0].value) for c in ast.walk(body)
                  if isinstance(c, ast.Call) and ast.unparse(c.func) == "tx.put" and isinstance(c.args[0], ast.Constant))


# ---- the structure -----------------------------------------------------------------------------------------------------------------
def test_application_is_m7_in_m7_order_plus_the_records_class_and_only_four_methods_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ref) == [("ThresholdReviews",)] and list(ours) == [("ThresholdReviews",), ("ThresholdReviewRecords",)]
    theirs, mine = methods(m7_text()), methods(target_text())
    assert list(mine) == list(theirs) == ["__init__", "_row", "request", "_queue", "_prepare", "prepare", "complete", "exhausted"]
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == REWRITTEN


def test_r_tr4_exhausted_is_m7s_static_method_verbatim_and_row_request_prepare_are_untouched():
    theirs, mine = methods(m7_text()), methods(target_text())
    assert ast.dump(mine["exhausted"]) == ast.dump(theirs["exhausted"])
    assert [ast.unparse(d) for d in mine["exhausted"].decorator_list] == ["staticmethod"]
    assert [a.arg for a in mine["exhausted"].args.args] == ["tx", "decision"]
    for name in ("_row", "request", "prepare"):
        assert ast.dump(mine[name]) == ast.dump(theirs[name]), name
    assert puts(mine["exhausted"]) == [(puts(mine["exhausted"])[0][0], BUCKET)]


def test_r_tr1_init_ports_are_keyword_only_and_the_m7_positional_signature_is_unchanged():
    new, old = methods(target_text())["__init__"].args, methods(m7_text())["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args] == ["self", "workflow", "artifacts"]
    assert old.kwonlyargs == [] and [a.arg for a in new.kwonlyargs] == ["decision_validation", "decisions"]
    assert [ast.unparse(d) for d in new.kw_defaults] == ["None", "None"] and new.defaults == old.defaults == []
    assert "self.decision_validation, self.decisions = decision_validation, decisions" in target_text()


def test_r_tr1_the_lazy_import_and_construction_become_one_require_and_the_injected_call_in_prepare():
    m7, ours = methods(m7_text())["_prepare"].body, methods(target_text())["_prepare"].body
    lazy = [i for i, st in enumerate(m7) if isinstance(st, ast.ImportFrom)]
    assert lazy == [2] and ast.unparse(m7[3]) == "ExecutionRecovery(self.store, self.org, self.artifacts).validate_decision(tx, current)"
    assert not [st for st in ast.walk(methods(target_text())["_prepare"]) if isinstance(st, ast.ImportFrom)]
    assert ast.unparse(ours[2]) == f"require(self.decision_validation is not None, {VALIDATION_MESSAGE!r})"
    assert ast.unparse(ours[3]) == "self.decision_validation.validate_decision(tx, current)"
    # everything around the two statements is M7's, statement for statement
    assert [ast.dump(s) for s in ours[:2]] == [ast.dump(s) for s in m7[:2]] and [ast.dump(s) for s in ours[4:]] == [ast.dump(s) for s in m7[4:]]
    assert len(ours) == len(m7)


def test_r_tr2_queue_has_one_require_immediately_before_the_in_place_record_with_the_same_row():
    """Structural: the moved `_queue` statements equal M7's but for one `require` before the in-place record (the S8 move
    rule, V22 R-tr2); behaviour is covered by test_request_writes_the_request_then_queues_the_lead_decision and
    test_r_tr2_unwired_decisions_refuse_request_and_write_nothing_not_even_the_request."""
    m7, ours = methods(m7_text())["_queue"].body, methods(target_text())["_queue"].body
    assert [ast.dump(s) for s in ours[:-2]] == [ast.dump(s) for s in m7[:-1]]
    assert ast.unparse(ours[-2]) == f"require(self.decisions is not None, {DECISIONS_MESSAGE!r})"
    old, new = m7[-1].value, ours[-1].value
    assert ast.unparse(old.func) == "tx.put" and ast.unparse(new.func) == "self.decisions.record"
    assert [ast.unparse(a) for a in old.args][0] == "'decisions_pending'" and ast.unparse(old.args[1]) == "key"
    assert ast.dump(old.args[2]) == ast.dump(new.args[1]) and ast.unparse(new.args[0]) == "tx" and len(new.args) == 2
    assert puts(methods(target_text())["_queue"]) == []


def test_r_tr2_complete_keeps_m7s_write_order_with_the_decision_record_in_place_of_its_put():
    """Structural: the moved `complete` unit equals M7's statement for statement but for the decision record in place of
    its put (the S8 move rule, V22 R-tr2); behaviour is covered by
    test_complete_writes_the_decision_then_the_request_then_the_conductor_decision."""
    m7, ours = methods(m7_text())["complete"], methods(target_text())["complete"]
    block_old = next(n for n in m7.body if isinstance(n, ast.With)).body
    block_new = next(n for n in ours.body if isinstance(n, ast.With)).body
    # outside the transaction: M7's statements exactly
    assert [ast.dump(s) for s in m7.body if not isinstance(s, ast.With)] == [ast.dump(s) for s in ours.body if not isinstance(s, ast.With)]
    names_old = [n for _, n in calls(ast.Module(body=block_old, type_ignores=[])) if n in ("tx.put", "self._queue")]
    names_new = [n for _, n in calls(ast.Module(body=block_new, type_ignores=[])) if n in ("tx.put", "self.decisions.record", "self._queue")]
    assert names_old == ["tx.put", "tx.put", "self._queue"]
    assert names_new == ["self.decisions.record", "tx.put", "self._queue"]
    index = next(i for i, s in enumerate(block_new) if ast.unparse(s).startswith("self.decisions.record"))
    assert ast.unparse(block_new[index - 1]) == f"require(self.decisions is not None, {DECISIONS_MESSAGE!r})"
    assert ast.unparse(block_new[index]) == "self.decisions.record(tx, current)"
    assert ast.unparse(block_old[index - 1]) == "tx.put('decisions_pending', current['id'], current)"
    assert ast.unparse(block_new[index - 2]).startswith("current.update(") and ast.unparse(block_old[index - 2]).startswith("current.update(")
    # the rest of the unit is M7's, statement for statement
    rest_old = [ast.dump(s) for i, s in enumerate(block_old) if i != index - 1]
    rest_new = [ast.dump(s) for i, s in enumerate(block_new) if i not in (index - 1, index)]
    assert rest_old == rest_new
    assert [b for _, b in puts(ours)] == [BUCKET]


def test_the_module_writes_no_decisions_pending_row_itself_and_writes_its_own_bucket_four_times():
    tree = ast.parse(target_text())
    literals = [c.args[0].value for c in ast.walk(tree) if isinstance(c, ast.Call) and ast.unparse(c.func) == "tx.put"]
    assert literals == [BUCKET] * 4
    m7_literals = [c.args[0].value for c in ast.walk(ast.parse(m7_text())) if isinstance(c, ast.Call) and ast.unparse(c.func) == "tx.put"]
    assert sorted(m7_literals) == ["decisions_pending"] * 2 + [BUCKET] * 3
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.col_offset > 0]


def test_the_injected_port_requires_are_exactly_three_and_carry_the_v22_messages():
    tree = ast.parse(target_text())
    found = sorted(ast.unparse(c.args[0]) + " | " + ast.unparse(c.args[1]) for c in ast.walk(tree)
                   if isinstance(c, ast.Call) and ast.unparse(c.func) == "require" and "self.decision" in ast.unparse(c.args[0]))
    assert found == sorted([f"self.decision_validation is not None | {VALIDATION_MESSAGE!r}", f"self.decisions is not None | {DECISIONS_MESSAGE!r}",
                            f"self.decisions is not None | {DECISIONS_MESSAGE!r}"])


def test_r_tr3_records_row_is_the_same_function_object_and_restore_is_the_inline_put_of_m7_recovery():
    assert ThresholdReviewRecords.row is ThresholdReviews._row
    klass = next(n for n in ast.parse(target_text()).body if isinstance(n, ast.ClassDef) and n.name == "ThresholdReviewRecords")
    body = {n.name if isinstance(n, ast.FunctionDef) else ast.unparse(n.targets[0]): n for n in klass.body if not isinstance(n, ast.Expr)}
    assert list(body) == ["__init__", "row", "restore"] and ast.unparse(body["row"].value) == "ThresholdReviews._row"
    assert [a.arg for a in body["__init__"].args.args] == ["self", "artifacts"] and ast.unparse(body["__init__"].body[0]) == "self.artifacts = artifacts"
    assert [a.arg for a in body["restore"].args.args] == ["self", "tx", "request"]
    assert ast.unparse(body["restore"].body[0]) == "tx.put('threshold_review_requests', request['id'], request)"
    # M7 execution_recovery.py:252 is that put, verbatim
    recovery = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/application/execution_recovery.py"], check=True,
                              capture_output=True, text=True).stdout
    assert "tx.put('threshold_review_requests', restored['request']['id'], restored['request'])" in recovery
    assert ThresholdReviewRecords(object()).artifacts is not None


def test_imports_are_only_kernel_homes():
    tree = ast.parse(target_text())
    found = {n.module: sorted(a.name for a in n.names) for n in tree.body if isinstance(n, ast.ImportFrom)}
    assert found == {k: sorted(v) for k, v in HOMES.items()}
    old = next(n for n in ast.parse(m7_text()).body if isinstance(n, ast.ImportFrom))
    assert sorted(a.name for a in old.names) == ["digest", "envelope", "require", "utcnow"]
    assert sorted(n for names in HOMES.values() for n in names) == sorted(a.name for a in old.names)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in mods if not m.startswith("codex_harness.kernel")]


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    assert header.startswith("Leased, ordered assessment of calculated threshold evidence; no apply authority.")
    for needle in ("Layer: application", "Context: research", "Owns:", "Does not own:", "Entry points: ThresholdReviews, ThresholdReviewRecords",
                   "Contracts: INV-THRESHOLD-REVIEW-001", "Moved from M7 `application/threshold_reviews.py`", "SOURCE e38aa722", "V22",
                   "A/evidence/rebuild/s8/threshold-reviews-move/transcribe.py", "R-tr0", "R-tr1", "R-tr2", "R-tr3", "R-tr4"):
        assert needle in header, needle


# ---- the ports and the buckets -----------------------------------------------------------------------------------------------------
def _params(fn):
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values() if p.name != "self"]


def _protocol_methods(proto):
    return {n: f for n, f in vars(proto).items() if inspect.isfunction(f) and not n.startswith("_")}


def test_ports_are_structurally_satisfied_by_the_coordination_owner_operation_and_by_research():
    assert sorted(_protocol_methods(ports.DecisionRecord)) == ["record"]
    assert _params(DecisionOwnership.record) == _params(ports.DecisionRecord.record) == [
        ("tx", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty), ("current", inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.empty)]
    assert sorted(_protocol_methods(coordination_ports.ThresholdReviewRecovery)) == ["restore", "row"]
    for name, fn in _protocol_methods(coordination_ports.ThresholdReviewRecovery).items():
        assert _params(getattr(ThresholdReviewRecords, name)) == _params(fn), name
    # DecisionValidation (already research's port) is satisfied by the coordination recovery
    for name, fn in _protocol_methods(ports.DecisionValidation).items():
        assert _params(getattr(ExecutionRecovery, name)) == _params(fn), name


def writers(values):
    """Relative paths of target modules with a `.put`/`.delete` whose first argument is the literal `values`."""
    found = set()
    for path in sorted(SRC.rglob("*.py")):
        for call in ast.walk(ast.parse(path.read_text())):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in ("put", "delete") and call.args:
                if isinstance(call.args[0], ast.Constant) and call.args[0].value in values:
                    found.add(path.relative_to(SRC).as_posix())
    return found


def test_v4_research_owns_the_bucket_once_and_only_this_module_writes_it():
    assert ports.OWNED_BUCKETS.count(BUCKET) == 1
    for context in ("coordination", "evidence", "knowledge", "review", "delivery", "intake", "routing", "storage", "execution", "observation"):
        path = SRC / context / "ports.py"
        if path.exists():
            owned = [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Assign)
                     and any(getattr(t, "id", "") == "OWNED_BUCKETS" for t in n.targets)]
            assert not owned or BUCKET not in ast.literal_eval(owned[0].value), context
    assert writers({BUCKET}) == {"research/application/threshold_reviews.py"}


def test_the_decision_row_is_written_through_coordinations_owner_operation_only():
    assert "research/application/threshold_reviews.py" not in writers({"decisions_pending"})
    assert decisions.BUCKET == "decisions_pending"
    assert [ast.unparse(s) for s in ast.parse(inspect.getsource(DecisionOwnership.record).strip().replace("\n    ", "\n")).body[0].body] == [
        "tx.put(BUCKET, current['id'], current)"]


# ---- behaviour that has no M7 counterpart: the unwired ports -----------------------------------------------------------------------
class Artifacts:
    """`FileArtifacts.document(ref)` over scripted documents."""

    def __init__(self):
        self.docs = {}

    def add(self, document):
        ref = "sha256:" + hashlib.sha256(canonical(document).encode()).hexdigest()
        self.docs[ref] = copy.deepcopy(document)
        return ref

    def document(self, ref):
        return copy.deepcopy(self.docs[ref])


def records(store):
    with store.transaction() as tx:
        return sorted((r["bucket"], r["id"], digest(r["body"])) for r in tx.records())


class World:
    """A MemoryStore with one calculated proposal (planted as `ThresholdProposals.collect` leaves it), its run and its evidence document."""

    def __init__(self):
        self.store, self.org, self.artifacts = MemoryStore(), packaged_organization(), Artifacts()
        proposal = {"id": "proposal-1", "name": "skill_match.FULL_BODY_MIN_SCORE", "current": 3, "suggested": 4, "policy_revision": REVISION}
        self.evidence = self.artifacts.add({"project_key": "project", "proposals": [proposal]})
        run_id = digest(["project", self.evidence])
        self.row_id = digest([run_id, proposal["id"]])
        row = {"id": self.row_id, "run_id": run_id, "project_key": "project", "evidence_ref": self.evidence, "proposal": proposal, "status": "calculated",
               "activation_ready": False, "activation_blockers": ["native_task_success_and_release_review_required"]}
        with self.store.transaction() as tx:
            tx.put("threshold_proposals", self.row_id, row)
            tx.put("threshold_proposal_runs", run_id, {"id": run_id, "activation_ready": False, "proposals": [copy.deepcopy(row)]})
        self.workflow = Workflow(self.store, self.org, ticket_binding=tickets.ticket_binding, TicketSuperseded=tickets.TicketSuperseded,
                                 adoption=audit_gate.require_adoption)
        self.recovery = ExecutionRecovery(self.store, self.org, self.artifacts, audit_binding=audit_gate.binding,
                                          threshold_reviews=ThresholdReviewRecords(self.artifacts))

    def reviews(self, **overrides):
        ports_ = {"decision_validation": self.recovery, "decisions": DecisionOwnership(self.workflow, self.recovery, self.org), **overrides}
        return ThresholdReviews(self.workflow, self.artifacts, **ports_)

    def claim(self, actor=LEAD):
        row = claim_decision(self.store, self.org, actor, "owner-" + actor, None, recovery=self.recovery, ticket_binding=tickets.ticket_binding,
                             TicketSuperseded=tickets.TicketSuperseded, threshold_exhausted=ThresholdReviews.exhausted)
        return {**row, "_bucket": "decisions_pending"}

    def execution(self, lease, bundle):
        """The documents and the result M7's executor leaves for an accepting review of `bundle`."""
        evidence = self.artifacts.add({"review": bundle})
        packet = self.artifacts.add({"agent_id": lease["actor"], "task_id": lease["id"], "required": {"external_context": {"ref": evidence}}})
        answer = {"accepted": True, "reason": "fixture assessment", "blocked": False, "risks": [], "sre_assessment": "fixture", "arc42_assessment": "fixture"}
        receipt = self.artifacts.add({"answer": answer, "context_ref": packet, "inspection_blocked": False, "interrupted": False,
                                      "research_binding": {"stage": "threshold_review", "evidence_ref": evidence, "basis_revision": REVISION}})
        return {**answer, "execution_ref": receipt, "basis_revision": REVISION}


def test_the_wired_module_requests_once_queues_the_lead_and_a_second_request_returns_the_row_with_the_store_unchanged():
    world = World()
    request = world.reviews().request(world.row_id)
    assert request["status"] == "awaiting_lead" and request["activation_ready"] is False
    with world.store.transaction() as tx:
        row, = tx.scan("decisions_pending")
        assert row["actor"] == LEAD and row["phase"] == "threshold_review" and row["id"] == digest([request["id"], LEAD])
        assert tx.get(BUCKET, request["id"]) == request
    before = records(world.store)
    assert world.reviews().request(world.row_id) == request and records(world.store) == before


def test_r_tr2_unwired_decisions_refuse_request_and_write_nothing_not_even_the_request():
    world = World()
    before = records(world.store)
    for overrides in ({"decisions": None}, {"decisions": None, "decision_validation": None}):
        with pytest.raises(ContractError) as info:
            world.reviews(**overrides).request(world.row_id)
        assert str(info.value) == DECISIONS_MESSAGE
        assert records(world.store) == before
    with world.store.transaction() as tx:
        assert tx.scan(BUCKET) == [] and tx.scan("decisions_pending") == []
    # `decision_validation` alone is not used by `request`: it still admits
    assert world.reviews(decision_validation=None).request(world.row_id)["status"] == "awaiting_lead"


def test_r_tr1_unwired_decision_validation_refuses_prepare_and_writes_nothing_and_the_wired_prepare_returns_the_bundle():
    world = World()
    request = world.reviews().request(world.row_id)
    lease = world.claim()
    before = records(world.store)
    with pytest.raises(ContractError) as info:
        world.reviews(decision_validation=None).prepare(lease)
    assert str(info.value) == VALIDATION_MESSAGE and records(world.store) == before
    bundle = world.reviews().prepare(lease)
    assert bundle["request_id"] == request["id"] and bundle["execution"] == {"decision_id": lease["id"], "generation": lease["generation"]}
    assert records(world.store) == before


def test_r_tr2_unwired_decisions_refuse_complete_before_any_write_and_the_wired_complete_queues_the_conductor():
    world = World()
    request = world.reviews().request(world.row_id)
    lease = world.claim()
    bundle = world.reviews().prepare(lease)
    result = world.execution(lease, bundle)
    before = records(world.store)
    with pytest.raises(ContractError) as info:
        world.reviews(decisions=None).complete(lease, bundle, result)
    assert str(info.value) == DECISIONS_MESSAGE and records(world.store) == before
    with world.store.transaction() as tx:
        assert tx.get(BUCKET, request["id"])["reviews"] == [] and tx.get("decisions_pending", lease["id"])["status"] == "running"
    done = world.reviews().complete(lease, bundle, result)
    assert done["status"] == "succeeded"
    with world.store.transaction() as tx:
        assert tx.get(BUCKET, request["id"])["status"] == "awaiting_conductor"
        assert sorted((r["actor"], r["status"]) for r in tx.scan("decisions_pending")) == [(CONDUCTOR, "pending"), (LEAD, "succeeded")]


def observed_puts(monkeypatch):
    """Record every `put` any MemoryStore transaction receives, as `(bucket, key)`, in the order issued."""
    from codex_harness.storage.adapters import memory_store

    log, original = [], memory_store.MemoryTransaction.put

    def put(self, bucket, key, body):
        log.append((bucket, key))
        return original(self, bucket, key, body)

    monkeypatch.setattr(memory_store.MemoryTransaction, "put", put)
    return log


def test_request_writes_the_request_then_queues_the_lead_decision(monkeypatch):
    """Behaviour (INV-THRESHOLD-REVIEW-001; the write order of M7 `request`): the observed write sequence of a new request
    is the request row, then the lead's pending decision."""
    world = World()
    log = observed_puts(monkeypatch)
    request = world.reviews().request(world.row_id)
    assert log == [(BUCKET, request["id"]), ("decisions_pending", digest([request["id"], LEAD]))]


def test_complete_writes_the_decision_then_the_request_then_the_conductor_decision(monkeypatch):
    """Behaviour (INV-THRESHOLD-REVIEW-001: lease, exact input and ordered review commit together): the observed write
    sequence of an accepting lead `complete` is the lead's decision record, the request row, then the conductor's pending
    decision (M7's order: the decision put, the request put, `_queue`)."""
    world = World()
    request = world.reviews().request(world.row_id)
    lease = world.claim()
    bundle = world.reviews().prepare(lease)
    result = world.execution(lease, bundle)
    log = observed_puts(monkeypatch)
    world.reviews().complete(lease, bundle, result)
    assert log == [("decisions_pending", lease["id"]), (BUCKET, request["id"]),
                   ("decisions_pending", digest([request["id"], CONDUCTOR]))]


def test_r_tr3_records_restore_writes_the_request_under_its_id_and_row_is_the_modules_own_rule():
    world = World()
    records_ = ThresholdReviewRecords(world.artifacts)
    with world.store.transaction() as tx:
        assert records_.row(tx, world.row_id)["id"] == world.row_id
        with pytest.raises(ContractError, match="Calculated threshold record required"):
            records_.row(tx, "absent-row")
        records_.restore(tx, {"id": "request-1", "status": "awaiting_lead"})
    with world.store.transaction() as tx:
        assert tx.get(BUCKET, "request-1") == {"id": "request-1", "status": "awaiting_lead"}


def test_the_dumped_wired_result_is_json_serializable():
    world = World()
    assert json.dumps(world.reviews().request(world.row_id), sort_keys=True)
