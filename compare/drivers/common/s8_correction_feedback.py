"""Shared S8 scenario steps for `research.correction_feedback`, characterized BEFORE pilot 93 moves M7 `adapters/correction_feedback.py`
(DESIGN-s8 §13 V18):

- `deliver(store, artifacts, binding)`: no binding, a non-correction route, a research-only binding (an evidence repair), a correction, a
  correction with the research beside the findings, a conductor rejection, the redaction counts over secret-shaped text, every refusal;
- `require_context(rendered_bytes, usable_bytes)`;
- `_predecessor`, `_decision`, `_answer`, `_research_reference`, `_evidence_text` and `_research`, reached only through `deliver` (the
  public path every caller uses); `CorrectionFeedbackRefused` and the constants.

The reference module redacts with M7's own `domain.observation.redact_text`; the target module takes `redact` as a keyword-only argument
(R-cf1) and the target driver injects observation's `redact_text`. The recorded results must be identical.

The store is the product's `MemoryStore` seeded with the lane rows the way M7 `tests/test_correction_feedback.py` (`seed_rejection`) shapes
them; the artifacts are a LABELLED fake (`FakeArtifacts`): `document` and `text` answer a scripted value or raise a scripted fault. No real
`FileArtifacts`, git repository, `Executor` or provider is used: M7's cases that reach the module through `Executor.execute_one` are mapped to
the `deliver` cases in `M7_TESTS`. Nothing in the module draws an id or reads the clock, so none is scripted.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `deliver`, `require_context`, `MemoryStore`, `ContractError`,
`CorrectionFeedbackRefused`, `REFUSALS`, `SCHEMA`, `RESEARCH_SCHEMA`, `MAX_FINDINGS_CHARS`."""

from __future__ import annotations

import copy
import json

SECRET = "hunter2-CREDENTIAL-CANARY"
TRACE = "TRACE-CANARY-provider-events-never-delivered"
FINDINGS = ("Reject 92da6a74af96. P1 release_suite.py:193-201 persists unredacted parameter IDs "
            "(for example password=" + SECRET + ") through progress and reconciliation fields. "
            "P2 commands.py:105-111 calls process.wait() without a deadline after tree-kill failure.")
RISKS = ["credential-bearing node ids reach artifacts", "unbounded reap after kill failure"]
REVISION = "c" * 40
BASE = "b" * 40
REVIEW_REF = "sha256:" + "1" * 64
RESEARCH_REPORT = ("LABELLED fixture research report: the evidence gate refused because the declared check "
                   "ids were stale (token=" + SECRET + "); re-run the corrected profile.\n")
POLICY = "a" * 64
FAMILY = "op-1"
LIMIT = 15000
BUCKETS = ("tasks", "operations", "decisions_pending")


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    return value


def outcome(fn) -> dict:
    """The returned value, or the refusal's type, fixed code and message."""
    try:
        return {"returned": plain(fn())}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:300]}


def verdict(reason=FINDINGS, risks=None, accepted=False):
    return {"accepted": accepted, "reason": reason, "blocked": False,
            "risks": list(RISKS if risks is None else risks), "sre_assessment": "s", "arc42_assessment": "a"}


def reference(n) -> str:
    return "sha256:" + format(n, "x") * 64


class FakeArtifacts:
    """LABELLED double of `FileArtifacts` as `correction_feedback` calls it: `document(ref)` and `text(ref, max_bytes)` answer the scripted value
    or raise the scripted fault (an exception instance); an unscripted reference is a `FileNotFoundError`. Every call is recorded."""

    def __init__(self):
        self.documents, self.texts, self.calls = {}, {}, []

    def _answer(self, table, reference):
        value = table.get(reference, FileNotFoundError("absent"))
        if isinstance(value, BaseException):
            raise value
        return copy.deepcopy(value)

    def document(self, reference):
        self.calls.append(["document", reference])
        return self._answer(self.documents, reference)

    def text(self, reference, max_bytes):
        self.calls.append(["text", reference, max_bytes])
        return self._answer(self.texts, reference)


class World:
    """One lane as M7's `seed_rejection` writes it: the origin task, the rejected operation, the succeeded lead review and its execution
    artifact. `predecessor` is the binding predecessor `_successor` would record."""

    def __init__(self, api, answer=None):
        self.api, self.store, self.artifacts = api, api.MemoryStore(), FakeArtifacts()
        self.candidate = {"revision": REVISION, "base": BASE}
        self.answer = verdict() if answer is None else answer
        self.predecessor = {"job_id": "op-1", "task_id": "origin-task", "candidate_revision": REVISION,
                            "decision_id": "dec-1", "review_execution_ref": REVIEW_REF, "inspection_id": None}
        self.artifacts.documents[REVIEW_REF] = self.document(self.answer)
        with self.store.transaction() as tx:
            tx.put("tasks", "origin-task", {"id": "origin-task", "status": "succeeded", "agent": "worker:implementation",
                                            "result": {"candidate": dict(self.candidate)}})
            tx.put("operations", "op-1", {"id": "op-1", "status": "rejected", "reason_code": "lead_rejected",
                                          "task_id": "origin-task", "decision_id": "dec-1"})
            tx.put("decisions_pending", "dec-1", {
                "id": "dec-1", "actor": "lead:improvement", "phase": "review_lead", "status": "succeeded", "attempt": 1,
                "input": {"candidate": dict(self.candidate)}, "message": {"what": {"details": {"task_id": "origin-task"}}},
                "result": {**self.answer, "execution_ref": REVIEW_REF, "basis_revision": REVISION,
                           "candidate": dict(self.candidate), "release_id": "rel-1"}})

    @staticmethod
    def document(answer):
        """The review execution artifact as `persist_result` writes it: the whole runner result, provider events (the trace canary) included."""
        return {"answer": answer, "model_answer_text": json.dumps(answer), "thread_id": "thread", "turn_id": "turn",
                "events": [{"method": "item/completed", "params": {"item": {"type": "commandExecution", "id": "c1", "command": TRACE}}}],
                "usage": None, "rotate": False, "interrupted": False}

    def binding(self, route="correction", **overrides):
        value = {"schema": "fixture", "operation_id": "cont-1", "policy_sha256": POLICY, "intent_id": "b" * 64, "family": FAMILY,
                 "route": route, "session": None,
                 "workspace": {"origin_task_id": "origin-task", "head": REVISION, "base": BASE},
                 "predecessor": copy.deepcopy(self.predecessor)}
        value.update(overrides)
        return value

    def research(self, refs, route="evidence_repair", **fields):
        """A binding carrying a research reference as `domain.continuation.research_reference` records it."""
        value = self.binding(route=route)
        if route != "correction":
            value["predecessor"] = {**value["predecessor"], "decision_id": None, "review_execution_ref": None}
        value["predecessor"]["research"] = {"intent_id": "c" * 64, "receipt_sha256": "d" * 64, "evidence_refs": refs,
                                            "policy_sha256": POLICY, "family": FAMILY, **fields}
        return value

    def update(self, bucket, key, **fields):
        with self.store.transaction() as tx:
            row = tx.get(bucket, key)
            row.update(fields)
            tx.put(bucket, key, row)

    def edit(self, bucket, key, fn):
        with self.store.transaction() as tx:
            row = tx.get(bucket, key)
            fn(row)
            tx.put(bucket, key, row)

    def rows(self):
        with self.store.transaction() as tx:
            return {bucket: {row["id"]: copy.deepcopy(row) for row in tx.scan(bucket)} for bucket in BUCKETS}

    def reseed(self, answer):
        """The same review decision with another answer (its artifact and its committed result)."""
        self.answer = answer
        self.artifacts.documents[REVIEW_REF] = self.document(answer)
        self.edit("decisions_pending", "dec-1", lambda row: row.update(
            result={**answer, "execution_ref": REVIEW_REF, "basis_revision": REVISION, "candidate": dict(self.candidate), "release_id": "rel-1"}))

    def text(self, n, body):
        self.artifacts.texts[reference(n)] = body
        return reference(n)


def delivered(api, world, binding):
    """`deliver` over the world's rows and artifacts: the result, the artifact calls in order, and whether the lane rows are unchanged."""
    before = world.rows()
    result = outcome(lambda: api.deliver(world.store, world.artifacts, binding))
    result["artifact_calls"] = list(world.artifacts.calls)
    result["rows_unchanged"] = world.rows() == before
    return result


def case(api, binding_of, setup=None, answer=None):
    world = World(api, answer)
    if setup is not None:
        setup(world)
    return delivered(api, world, binding_of(world))


# =====================================================================================================================
# deliver: the paths and the redaction
# =====================================================================================================================
SHAPES = ("password=" + SECRET + " then https://user:hunter3@example.invalid/x then Bearer abcdefgh12345678 then "
          "sk-abcdefghijklmnopqrstuvwx and ghp_abcdefghijklmnopqrstuvwxyz0123 and AKIAABCDEFGHIJKLMNOP and "
          "xoxb-1234567890-abcdef and eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4 and "
          "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----\n"
          "and 비밀번호: 값 and api_key 'quoted secret'.")


def d1_paths(api) -> dict:
    cases = {}
    cases["no_binding_is_none"] = case(api, lambda w: None)
    cases["evidence_repair_without_research_is_none"] = case(api, lambda w: w.binding(route="evidence_repair"))
    cases["requalification_without_research_is_none"] = case(api, lambda w: w.binding(route="requalification"))
    cases["unknown_route_without_research_is_none"] = case(api, lambda w: w.binding(route="unknown"))
    cases["route_absent_is_none"] = case(api, lambda w: {k: v for k, v in w.binding().items() if k != "route"})
    cases["correction_redacts_the_credential"] = case(api, lambda w: w.binding())
    cases["correction_without_a_secret_applies_no_redaction"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="No secret here, only a finding at a.py:1.", risks=["r1", "r2"]))
    cases["correction_redacts_every_shape_in_reason_and_risks"] = case(
        api, lambda w: w.binding(), answer=verdict(reason=SHAPES, risks=["risk Bearer 12345678abcdef", "plain", "token=a"]))
    cases["correction_counts_each_span_once"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="password=a password=b token=c", risks=["secret: d", "ok"]))
    cases["correction_blank_reason_with_a_risk_delivers"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="  ", risks=["only the risk"]))
    cases["correction_blank_risks_with_a_reason_delivers"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="the reason", risks=["  ", ""]))
    cases["correction_without_risks_key"] = case(
        api, lambda w: w.binding(), answer={"accepted": False, "reason": "no risks key", "blocked": False})
    cases["correction_korean_text"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="한글 지적 사항 password=비밀", risks=["위험 하나"]))
    cases["correction_without_workspace_skips_the_head_check"] = case(api, lambda w: w.binding(workspace=None))
    cases["correction_workspace_head_mismatch"] = case(
        api, lambda w: w.binding(workspace={"origin_task_id": "origin-task", "head": "e" * 40, "base": BASE}))
    cases["correction_workspace_without_head_key"] = case(api, lambda w: w.binding(workspace={"origin_task_id": "origin-task"}))

    def conductor(w):
        answer = verdict(reason="Conductor: rollback evidence missing for P1.", risks=[])
        ref = reference(2)
        w.artifacts.documents[ref] = w.document(answer)
        w.edit("decisions_pending", "dec-1", lambda row: row["result"].update(accepted=True))
        with w.store.transaction() as tx:
            tx.put("decisions_pending", "cond-1", {
                "id": "cond-1", "actor": "conductor", "phase": "review_conductor", "status": "succeeded", "attempt": 1,
                "input": {"candidate": dict(w.candidate)}, "message": {"what": {"details": {"decision_id": "dec-1"}}},
                "result": {**answer, "execution_ref": ref}})
        w.predecessor.update(decision_id="cond-1", review_execution_ref=ref)
    cases["conductor_rejection_delivers_its_own_review"] = case(api, lambda w: w.binding(), setup=conductor)

    def conductor_lead_absent(w):
        conductor(w)
        w.edit("decisions_pending", "cond-1", lambda row: row.update(message={"what": {"details": {"decision_id": "dec-gone"}}}))
    cases["conductor_rejection_without_its_lead"] = case(api, lambda w: w.binding(), setup=conductor_lead_absent)

    def conductor_lead_id_not_text(w):
        conductor(w)
        w.edit("decisions_pending", "cond-1", lambda row: row.update(message={"what": {"details": {"decision_id": 7}}}))
    cases["conductor_rejection_with_a_non_text_lead_id"] = case(api, lambda w: w.binding(), setup=conductor_lead_id_not_text)

    def conductor_lead_other_operation(w):
        conductor(w)
        w.edit("operations", "op-1", lambda row: row.update(decision_id="dec-other"))
    cases["conductor_rejection_of_another_operations_lead"] = case(api, lambda w: w.binding(), setup=conductor_lead_other_operation)

    world = World(api)
    binding = world.binding()
    first = delivered(api, world, binding)
    second = delivered(api, world, binding)
    first["twice_equal"] = first["returned"] == second["returned"]
    first["second_calls"] = second["artifact_calls"]
    cases["deliver_twice_is_deterministic_and_mutates_nothing"] = first

    # the bound answer reaches the result; the provider trace in the artifact never does
    only = World(api)
    cases["only_the_answer_travels"] = delivered(api, only, only.binding())
    serialized = json.dumps(cases["only_the_answer_travels"], default=str)
    cases["only_the_answer_travels"]["trace_in_result"] = TRACE in serialized
    cases["only_the_answer_travels"]["credential_in_result"] = SECRET in serialized

    cases["bounds_reason_at_the_limit_delivers"] = case(api, lambda w: w.binding(), answer=verdict(reason="x" * LIMIT, risks=[]))
    cases["bounds_reason_over_the_limit_refuses"] = case(api, lambda w: w.binding(), answer=verdict(reason="x" * (LIMIT + 1), risks=[]))
    cases["bounds_reason_and_risks_at_the_limit_deliver"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="x" * (LIMIT - 10), risks=["y" * 4, "z" * 6]))
    cases["bounds_reason_and_risks_over_the_limit_refuse"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="x" * (LIMIT - 10), risks=["y" * 4, "z" * 7]))
    cases["bounds_original_under_but_redacted_text_over_the_limit_refuses"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="token=a " * 1000, risks=[]))
    cases["bounds_original_over_the_limit_refuses_though_redaction_shrinks_it"] = case(
        api, lambda w: w.binding(), answer=verdict(reason="AKIAABCDEFGHIJKLMNOP " * 800, risks=[]))
    return cases


# =====================================================================================================================
# deliver: every correction refusal
# =====================================================================================================================
def refuse(mutate, **kw):
    return mutate, kw


def d2_correction_refusals(api) -> dict:
    cases = {}

    def edit_predecessor(**fields):
        return lambda w: w.predecessor.update(fields)

    def decision_edit(fn):
        return lambda w: w.edit("decisions_pending", "dec-1", fn)

    def task_edit(fn):
        return lambda w: w.edit("tasks", "origin-task", fn)

    mutations = {
        # feedback_binding_invalid
        "predecessor_extra_field": lambda w: w.predecessor.update(forged="x"),
        "predecessor_missing_field": lambda w: w.predecessor.pop("inspection_id"),
        "predecessor_job_id_not_text": edit_predecessor(job_id=7),
        "predecessor_task_id_bad_token": edit_predecessor(task_id="has space"),
        "predecessor_decision_id_empty": edit_predecessor(decision_id=""),
        "predecessor_candidate_revision_bad": edit_predecessor(candidate_revision="abc"),
        "predecessor_candidate_revision_uppercase": edit_predecessor(candidate_revision="C" * 40),
        "predecessor_review_ref_bad": edit_predecessor(review_execution_ref="not-a-ref"),
        "predecessor_inspection_id_set": edit_predecessor(inspection_id="insp-1"),
        # the lane rows
        "decision_absent": edit_predecessor(decision_id="dec-absent"),
        "operation_absent": lambda w: w.predecessor.update(job_id="op-absent"),
        "operation_for_another_task": lambda w: w.update("operations", "op-1", task_id="another-task"),
        "operation_names_another_decision": lambda w: w.update("operations", "op-1", decision_id="dec-other"),
        "decision_nonterminal": lambda w: w.update("decisions_pending", "dec-1", status="running"),
        "decision_accepted": decision_edit(lambda row: row["result"].update(accepted=True)),
        "decision_result_not_a_dict": lambda w: w.update("decisions_pending", "dec-1", result="x"),
        "decision_phase_not_a_review": lambda w: w.update("decisions_pending", "dec-1", phase="other"),
        "decision_row_with_another_id": lambda w: w.update("decisions_pending", "dec-1", id="dec-2"),
        "decision_details_name_another_task": lambda w: w.update(
            "decisions_pending", "dec-1", message={"what": {"details": {"task_id": "another-task"}}}),
        "decision_message_absent": lambda w: w.update("decisions_pending", "dec-1", message=None),
        "task_absent": edit_predecessor(task_id="task-absent"),
        "task_candidate_changed": task_edit(lambda row: row["result"]["candidate"].update(revision="f" * 40)),
        "task_without_a_candidate": task_edit(lambda row: row.update(result=None)),
        "decision_input_candidate_changed": decision_edit(lambda row: row["input"]["candidate"].update(revision="f" * 40)),
        "decision_input_absent": decision_edit(lambda row: row.update(input=None)),
        "decision_result_names_another_execution": decision_edit(lambda row: row["result"].update(execution_ref="sha256:" + "7" * 64)),
        # the execution artifact
        "artifact_absent": lambda w: w.artifacts.documents.pop(REVIEW_REF),
        "artifact_unreadable_oserror": lambda w: w.artifacts.documents.update({REVIEW_REF: PermissionError("secret path " + SECRET)}),
        "artifact_integrity_failure": lambda w: w.artifacts.documents.update({REVIEW_REF: api.ContractError("Artifact integrity failure")}),
        "artifact_not_json": lambda w: w.artifacts.documents.update({REVIEW_REF: json.JSONDecodeError("bad", "x", 0)}),
        "artifact_not_utf8": lambda w: w.artifacts.documents.update({REVIEW_REF: UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")}),
        "artifact_too_deep": lambda w: w.artifacts.documents.update({REVIEW_REF: RecursionError("deep")}),
        "artifact_unexpected_fault_propagates": lambda w: w.artifacts.documents.update({REVIEW_REF: RuntimeError("injected")}),
        "artifact_records_a_failure": lambda w: w.artifacts.documents[REVIEW_REF].update(failure={"code": "x"}),
        "artifact_without_an_answer": lambda w: w.artifacts.documents[REVIEW_REF].pop("answer"),
        "artifact_answer_not_a_dict": lambda w: w.artifacts.documents[REVIEW_REF].update(answer="text"),
        "artifact_answer_differs_from_the_result": lambda w: w.artifacts.documents[REVIEW_REF]["answer"].update(reason="another review"),
        "artifact_answer_accepted": lambda w: w.artifacts.documents[REVIEW_REF]["answer"].update(accepted=True),
        "artifact_answer_reason_not_text": lambda w: w.reseed({**verdict(), "reason": 7}),
        "artifact_answer_risks_not_a_list": lambda w: w.reseed({**verdict(), "risks": "r"}),
        "artifact_answer_risk_not_text": lambda w: w.reseed({**verdict(), "risks": ["ok", 3]}),
        "artifact_answer_accepted_missing": lambda w: w.reseed({k: v for k, v in verdict().items() if k != "accepted"}),
        # the findings
        "findings_blank": lambda w: w.reseed(verdict(reason="  ", risks=[])),
        "findings_blank_with_blank_risks": lambda w: w.reseed(verdict(reason="", risks=[" ", "\n"])),
        "findings_oversize": lambda w: w.reseed(verdict(reason="x" * (LIMIT + 1), risks=[])),
    }
    for name, mutate in mutations.items():
        cases[name] = case(api, lambda w: w.binding(), setup=mutate)
    return cases


# =====================================================================================================================
# deliver: the research handoff
# =====================================================================================================================
def d3_research(api) -> dict:
    cases = {}

    def with_text(body, route="evidence_repair", **fields):
        def build(w):
            ref = w.text(5, body)
            return w.research([ref], route=route, **fields)
        return build

    cases["evidence_repair_delivers_the_research_redacted"] = case(api, with_text(RESEARCH_REPORT))
    cases["evidence_repair_without_a_secret_applies_no_redaction"] = case(api, with_text("plain report\nline two\n"))
    cases["evidence_repair_redacts_every_shape"] = case(api, with_text(SHAPES))
    cases["evidence_repair_tabs_newlines_and_carriage_returns_are_text"] = case(api, with_text("a\tb\r\nc\n"))
    cases["correction_route_with_research_delivers_findings_and_research"] = case(api, with_text(RESEARCH_REPORT, route="correction"))

    def several(w):
        refs = [w.text(n, "evidence %d token=s%d" % (n, n)) for n in (3, 4, 5)]
        return w.research(refs)
    cases["several_refs_keep_their_order_and_count_spans_across_them"] = case(api, several)

    def many(count):
        def build(w):
            refs = ["sha256:" + format(n + 1, "064x") for n in range(count)]
            for ref in refs:
                w.artifacts.texts[ref] = "body " + ref[-3:]
            return w.research(refs)
        return build
    cases["sixteen_refs_are_the_most"] = case(api, many(16))
    cases["seventeen_refs_are_refused"] = case(api, many(17))

    def one_blank_one_text(w):
        return w.research([w.text(3, "  \n"), w.text(4, "real")])
    cases["one_blank_ref_with_one_text_ref_delivers"] = case(api, one_blank_one_text)

    cases["duplicate_refs_are_invalid"] = case(api, lambda w: w.research([w.text(3, "a"), reference(3)]))
    cases["research_text_at_the_limit_delivers"] = case(api, with_text("x" * LIMIT))
    cases["research_text_over_the_limit_is_refused"] = case(api, with_text("x" * (LIMIT + 1)))
    cases["research_texts_together_at_the_limit_deliver"] = case(
        api, lambda w: w.research([w.text(3, "a" * 7500), w.text(4, "b" * 7500)]))
    cases["research_texts_together_over_the_limit_are_refused"] = case(
        api, lambda w: w.research([w.text(3, "a" * 7500), w.text(4, "b" * 7501)]))
    cases["research_original_under_but_redacted_over_the_limit_is_refused"] = case(api, with_text("token=a " * 1000))
    cases["research_original_over_the_limit_is_refused_though_redaction_shrinks_it"] = case(api, with_text("AKIAABCDEFGHIJKLMNOP " * 800))
    cases["research_blank_is_refused"] = case(api, with_text("  \n\t "))
    cases["research_two_blank_refs_are_refused"] = case(api, lambda w: w.research([w.text(3, " "), w.text(4, "\n")]))

    # text faults
    faults = {
        "absent": None,
        "oserror": PermissionError("secret path " + SECRET),
        "not_utf8": UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
        "modified": api.ContractError("Artifact modified"),
        "over_the_text_budget": api.ContractError("Artifact exceeds text budget"),
        "other_contract_error": api.ContractError("Artifact integrity failure"),
        "invalid_budget": api.ContractError("Invalid text budget"),
        "plain_value_error_propagates": ValueError("plain"),
        "unexpected_fault_propagates": RuntimeError("injected"),
        "bytes_are_not_text": b"bytes",
        "none_is_not_text": None,
    }
    for name, fault in faults.items():
        def build(w, fault=fault, name=name):
            ref = reference(5)
            if name == "absent":
                return w.research([ref])
            w.artifacts.texts[ref] = fault
            return w.research([ref])
        cases["text_fault_" + name] = case(api, build)
    for control in ("\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f", "\x7f"):
        cases["control_character_%02x_is_not_text" % ord(control)] = case(api, with_text("report" + control + "binary"))

    # the binding
    cases["research_on_the_requalification_route_is_invalid"] = case(api, lambda w: w.research([w.text(5, "t")], route="requalification"))
    cases["research_on_an_unknown_route_is_invalid"] = case(api, lambda w: w.research([w.text(5, "t")], route="other"))
    cases["research_without_a_route_is_invalid"] = case(
        api, lambda w: {k: v for k, v in w.research([w.text(5, "t")]).items() if k != "route"})
    cases["research_not_a_dict_is_invalid"] = case(api, lambda w: {**w.research([w.text(5, "t")]), "predecessor": {**w.binding()["predecessor"], "decision_id": None, "review_execution_ref": None, "research": "x"}})
    cases["research_with_an_extra_field_is_invalid"] = case(api, lambda w: w.research([w.text(5, "t")], scope="wider"))

    def without(field):
        def build(w):
            binding = w.research([w.text(5, "t")])
            del binding["predecessor"]["research"][field]
            return binding
        return build
    for field in ("intent_id", "receipt_sha256", "evidence_refs", "policy_sha256", "family"):
        cases["research_without_%s_is_invalid" % field] = case(api, without(field))
    cases["research_intent_id_not_a_digest"] = case(api, lambda w: w.research([w.text(5, "t")], intent_id="x" * 64))
    cases["research_receipt_uppercase_digest"] = case(api, lambda w: w.research([w.text(5, "t")], receipt_sha256="D" * 64))
    cases["research_policy_digest_short"] = case(api, lambda w: w.research([w.text(5, "t")], policy_sha256="a" * 63))
    cases["research_family_bad_token"] = case(api, lambda w: w.research([w.text(5, "t")], family="has space"))
    cases["research_family_not_text"] = case(api, lambda w: w.research([w.text(5, "t")], family=7))
    cases["research_refs_empty"] = case(api, lambda w: w.research([]))
    cases["research_refs_not_a_list"] = case(api, lambda w: w.research("sha256:" + "5" * 64))
    cases["research_refs_a_tuple"] = case(api, lambda w: w.research((w.text(5, "t"),)))
    cases["research_ref_malformed"] = case(api, lambda w: w.research(["not-a-ref"]))
    cases["research_ref_not_text"] = case(api, lambda w: w.research([7]))
    cases["research_for_another_policy_is_foreign"] = case(api, lambda w: w.research([w.text(5, "t")], policy_sha256="e" * 64))
    cases["research_for_another_family_is_foreign"] = case(api, lambda w: w.research([w.text(5, "t")], family="op-other"))
    cases["research_binding_without_policy_or_family_is_foreign"] = case(
        api, lambda w: {k: v for k, v in w.research([w.text(5, "t")]).items() if k not in ("policy_sha256", "family")})

    # ordering of the checks: research first, then the findings
    cases["bad_research_on_a_correction_is_refused_before_any_row_or_artifact"] = case(
        api, lambda w: w.research([w.text(5, "t")], route="correction", family="op-other"))
    cases["bad_predecessor_on_a_correction_with_research_is_refused_before_the_text_read"] = case(
        api, lambda w: {**w.research([w.text(5, "t")], route="correction"), "predecessor": {**w.research([w.text(5, "t")], route="correction")["predecessor"], "inspection_id": "x"}})
    cases["research_text_fault_on_a_correction_follows_the_findings"] = case(
        api, lambda w: w.research([reference(9)], route="correction"))
    cases["research_without_a_predecessor_dict_on_a_correction_is_binding_invalid"] = case(
        api, lambda w: {**w.binding(), "predecessor": "x"})
    return cases


# =====================================================================================================================
# require_context and the refusal class
# =====================================================================================================================
def c1_context(api) -> dict:
    cases = {}
    for name, args in {
        "equal_fits": (10, 10), "under_fits": (9, 10), "zero_fits": (0, 0), "one_over_is_refused": (11, 10),
        "negative_usable_is_refused": (0, -1), "bool_is_not_an_int": (True, 10), "float_is_not_an_int": (1.0, 10),
        "none_is_not_an_int": (None, 10), "text_is_not_an_int": ("1", 10), "usable_not_comparable": (5, "9"),
        "usable_none": (5, None),
    }.items():
        cases[name] = outcome(lambda args=args: api.require_context(*args))
    return cases


def r1_class(api) -> dict:
    cases = {}
    for name, code in {"known_code": "feedback_empty", "unknown_code_falls_back": "not a code", "empty_code_falls_back": "",
                       "last_known_code": "feedback_research_oversize"}.items():
        exc = api.CorrectionFeedbackRefused(code)
        cases[name] = {"reason_code": exc.reason_code, "message": str(exc), "is_contract_error": isinstance(exc, api.ContractError),
                       "is_value_error": isinstance(exc, ValueError)}
    cases["refusals"] = sorted(api.REFUSALS)
    cases["refusals_type"] = type(api.REFUSALS).__name__
    cases["constants"] = {"SCHEMA": api.SCHEMA, "RESEARCH_SCHEMA": api.RESEARCH_SCHEMA, "MAX_FINDINGS_CHARS": api.MAX_FINDINGS_CHARS}
    return cases


M7_TESTS = {
    "test_bound_rejected_review_reaches_the_provider_input_readable_redacted_and_digested": {
        "d1_paths": "correction_redacts_the_credential (spans, digests, source_ref, predecessor), only_the_answer_travels",
        "unreachable": "the Executor.execute_one prompt composition and the provider input (S10 composition)"},
    "test_the_rendered_provider_input_crosses_the_real_container_entry_unchanged": {"unreachable": "the real isolated worker entry (not this module)"},
    "test_construction_is_deterministic_path_independent_and_mutates_nothing": {
        "d1_paths": "deliver_twice_is_deterministic_and_mutates_nothing (rows unchanged, equal results); the second artifact root is a FileArtifacts concern"},
    "test_a_conductor_rejection_delivers_its_own_review_bound_to_the_lead_decision": {"d1_paths": "conductor_rejection_*"},
    "test_unusable_feedback_refuses_with_a_fixed_code_before_any_provider": {"d2_correction_refusals": "the twelve M7 mutations plus the rest of every branch"},
    "test_empty_oversized_or_unfittable_findings_refuse_and_are_never_trimmed": {
        "d2_correction_refusals": "findings_blank, findings_oversize", "c1_context": "one_over_is_refused (the unfittable case reaches require_context)"},
    "test_an_unreadable_artifact_refuses_without_leaking_the_error": {"d2_correction_refusals": "artifact_unreadable_oserror"},
    "test_a_forged_attachment_is_still_refused_by_the_lane_binding_check": {"unreachable": "the executor's lane binding check (not this module)"},
    "test_non_correction_routes_and_the_legacy_path_deliver_nothing": {"d1_paths": "no_binding_is_none, evidence_repair_without_research_is_none"},
    "test_refusal_codes_are_fixed": {"r1_class": "known_code, unknown_code_falls_back"},
    "test_the_research_evidence_reaches_an_evidence_repair_provider_input_redacted_and_labelled": {
        "d3_research": "evidence_repair_delivers_the_research_redacted"},
    "test_a_correction_after_research_delivers_its_findings_and_the_research_beside_them": {
        "d3_research": "correction_route_with_research_delivers_findings_and_research"},
    "test_unusable_research_evidence_refuses_before_any_workspace_or_provider": {"d3_research": "the text_fault_*, control_character_*, research_* cases"},
    "test_unreadable_research_evidence_refuses_without_leaking_the_error": {"d3_research": "text_fault_oserror"},
    "test_a_research_reference_on_another_route_is_invalid": {"d3_research": "research_on_the_requalification_route_is_invalid"},
    "test_research_evidence_that_fits_the_bound_but_not_the_prompt_refuses_untrimmed": {"c1_context": "one_over_is_refused"},
}


def correction_feedback(api) -> dict:
    groups = {"d1_paths": d1_paths(api), "d2_correction_refusals": d2_correction_refusals(api), "d3_research": d3_research(api),
              "c1_context": c1_context(api), "r1_class": r1_class(api)}
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
