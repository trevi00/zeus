"""S8 pilot 93 (DESIGN-s8 §13 V18): M7 `adapters/correction_feedback.py` moved to `research.adapters.correction_feedback`. Everything but the named
rules is M7's (A/evidence/rebuild/s8/correction-feedback-move/transcribe.py): R-cf1 (`redact` is an injected keyword-only rule, one `require` before
the route test), R-cf2 (`_research` takes `redact` positionally), R-cf3 (the import homes).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
checked on the TARGET only, against literals; the recorded comparison is the `research.correction_feedback` golden. The first-use refusal (the rule is
not wired) has no M7 counterpart and is pinned here, including its one deviation from M7: an unwired call that would return None on a non-correction
route without research refuses instead.
"""
import ast
import inspect
import subprocess
from pathlib import Path

import pytest

from codex_harness.execution import ports
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain.observation import redact_text
from codex_harness.research.adapters import correction_feedback as module
from codex_harness.research.adapters.correction_feedback import (
    CorrectionFeedbackRefused,
    deliver,
    require_context,
)
from codex_harness.storage.adapters.memory_store import MemoryStore

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
UNWIRED = "correction feedback needs the redaction rule"
REWRITTEN = (("deliver",), ("_research",))
HOMES = {"__future__": ["annotations"], "re": [], "codex_harness.kernel.errors": ["ContractError", "require"], "codex_harness.kernel.ids": ["digest"]}
REVISION = "c" * 40
REVIEW_REF = "sha256:" + "1" * 64
RESEARCH_REF = "sha256:" + "5" * 64
POLICY = "a" * 64


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/adapters/correction_feedback.py"], check=True,
                          capture_output=True, text=True).stdout


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


def function(src, name):
    return statements(src)[(name,)]


# ---- the transcription: AST against M7 ---------------------------------------------------------------------------------
def test_every_statement_but_deliver_and_research_is_m7s_in_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref)
    for key in ref:
        if key not in REWRITTEN:
            assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_r_cf2_research_takes_redact_positionally_and_only_renames_the_rule():
    ref, ours = function(m7_text(), "_research"), function(target_text(), "_research")
    assert [a.arg for a in ours.args.args] == ["artifacts", "research", "redact"] and ours.args.defaults == [] and ours.args.kwonlyargs == []
    assert ast.unparse(ours) == ast.unparse(ref).replace("_research(artifacts, research: dict)", "_research(artifacts, research: dict, redact)").replace(
        "redact_text(", "redact(")
    assert ast.unparse(ours).count("redact(") == 1


def test_r_cf1_deliver_only_gains_the_keyword_the_renamed_calls_the_research_argument_and_one_require():
    ref, ours = function(m7_text(), "deliver"), function(target_text(), "deliver")
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["store", "artifacts", "binding"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["redact"] and [ast.unparse(d) for d in ours.args.kw_defaults] == ["None"]
    assert ours.args.defaults == [] and ours.returns is not None and ast.dump(ours.returns) == ast.dump(ref.returns)
    marker = "    research = _research_reference(binding)\n"
    text = ast.unparse(ref).replace("redact_text(", "redact(").replace("_research(artifacts, research)", "_research(artifacts, research, redact)")
    text = text.replace("def deliver(store, artifacts, binding: dict | None)", "def deliver(store, artifacts, binding: dict | None, *, redact=None)")
    assert text.count(marker) == 1
    assert ast.unparse(ours) == text.replace(marker, marker + f"    require(redact is not None, {UNWIRED!r})\n")


def test_the_one_require_precedes_every_use_of_redact():
    tree = ast.parse(target_text())
    requires = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require"]
    assert [ast.unparse(r) for r in requires] == [f"require(redact is not None, {UNWIRED!r})"]
    body = function(target_text(), "deliver").body
    first = next(i for i, n in enumerate(body) if any(isinstance(m, ast.Name) and m.id == "redact" for m in ast.walk(n)))
    assert ast.unparse(body[first]).startswith("require(redact is not None"), "the first statement mentioning redact is the require"
    assert [ast.unparse(n) for n in body[first - 1:first]] == ["research = _research_reference(binding)"]
    calls = [ast.unparse(n) for n in ast.walk(function(target_text(), "deliver")) if isinstance(n, ast.Call) and ast.unparse(n.func) == "_research"]
    assert calls == ["_research(artifacts, research, redact)"] * 2


def test_imports_are_only_the_v18_homes_and_nothing_reaches_m7_observation_or_context():
    found = {}
    for n in ast.parse(target_text()).body:
        if isinstance(n, ast.ImportFrom):
            found[n.module] = sorted(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            found.update({a.name: [] for a in n.names})
    assert found == HOMES
    assert not any(isinstance(n, ast.Name) and n.id == "redact_text" for n in ast.walk(ast.parse(target_text())))


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    for needle in ("Layer: adapters", "Context: research", "Owns:", "Does not own:", "Entry points:", "Contracts: INV-CONTINUATION-001",
                   "Moved from M7 `adapters/correction_feedback.py`", "SOURCE e38aa722", "V18", "A/evidence/rebuild/s8/correction-feedback-move/transcribe.py",
                   "R-cf1", "R-cf2", "R-cf3"):
        assert needle in header, needle


def test_the_module_creates_no_process_and_opens_no_database():
    code = target_text().split('"""', 2)[2]
    for word in ("subprocess", "psycopg", "open(", "os.", "Popen"):
        assert word not in code, word


# ---- the consumer shape: execution.ports.CorrectionFeedback, called positionally ----------------------------------------
def test_the_module_still_satisfies_the_execution_port_positionally():
    assert {"deliver", "require_context"} <= set(vars(ports.CorrectionFeedback))
    inspect.signature(deliver).bind(object(), object(), None)
    inspect.signature(deliver).bind(object(), object(), {})
    inspect.signature(require_context).bind(1, 2)
    params = inspect.signature(deliver).parameters
    assert [p.name for p in params.values() if p.kind is p.KEYWORD_ONLY] == ["redact"] and params["redact"].default is None
    assert [p.name for p in params.values() if p.kind is p.POSITIONAL_OR_KEYWORD] == ["store", "artifacts", "binding"]
    port = inspect.signature(ports.CorrectionFeedback.deliver)
    assert [p for p in port.parameters if p != "self"] == ["store", "artifacts", "continuation"]


# ---- behaviour on the target: the first-use refusal and the injected rule ---------------------------------------------------
class Artifacts:
    """LABELLED double of the artifact store: scripted texts and documents; every call is recorded."""

    def __init__(self, documents=None, texts=None):
        self.documents, self.texts, self.calls = documents or {}, texts or {}, []

    def document(self, reference):
        self.calls.append(("document", reference))
        return self.documents[reference]

    def text(self, reference, max_bytes):
        self.calls.append(("text", reference))
        return self.texts[reference]


class ForbiddenStore:
    """A store that must never be opened."""

    def transaction(self, *args, **kwargs):
        raise AssertionError("the store was opened")


def research_binding(route="evidence_repair", **fields):
    predecessor = {"job_id": "op-1", "task_id": "origin-task", "candidate_revision": REVISION, "decision_id": "dec-1",
                   "review_execution_ref": REVIEW_REF, "inspection_id": None}
    research = {"intent_id": "c" * 64, "receipt_sha256": "d" * 64, "evidence_refs": [RESEARCH_REF], "policy_sha256": POLICY, "family": "op-1", **fields}
    if route != "correction":
        predecessor.update(decision_id=None, review_execution_ref=None)
    return {"policy_sha256": POLICY, "family": "op-1", "route": route, "workspace": None, "predecessor": {**predecessor, "research": research}}


def seeded_store(answer):
    store = MemoryStore()
    candidate = {"revision": REVISION, "base": "b" * 40}
    with store.transaction() as tx:
        tx.put("tasks", "origin-task", {"id": "origin-task", "status": "succeeded", "result": {"candidate": candidate}})
        tx.put("operations", "op-1", {"id": "op-1", "status": "rejected", "task_id": "origin-task", "decision_id": "dec-1"})
        tx.put("decisions_pending", "dec-1", {
            "id": "dec-1", "phase": "review_lead", "status": "succeeded", "input": {"candidate": candidate},
            "message": {"what": {"details": {"task_id": "origin-task"}}}, "result": {**answer, "execution_ref": REVIEW_REF}})
    return store


ANSWER = {"accepted": False, "reason": "fix a.py token=abc", "risks": ["r1", "r2 password=x"]}
CORRECTION = {"policy_sha256": POLICY, "family": "op-1", "route": "correction", "workspace": None,
              "predecessor": {"job_id": "op-1", "task_id": "origin-task", "candidate_revision": REVISION, "decision_id": "dec-1",
                              "review_execution_ref": REVIEW_REF, "inspection_id": None}}


def refusal_of(call):
    with pytest.raises(Exception) as caught:
        call()
    return caught.value


def test_unwired_none_binding_still_returns_none():
    assert deliver(ForbiddenStore(), Artifacts(), None) is None


@pytest.mark.parametrize("binding", [CORRECTION, research_binding(), research_binding(route="correction"), {"route": "evidence_repair"},
                                     {"route": "requalification"}])
def test_unwired_calls_refuse_before_any_store_or_artifact_access(binding):
    artifacts = Artifacts(documents={REVIEW_REF: {"answer": ANSWER}}, texts={RESEARCH_REF: "text"})
    error = refusal_of(lambda: deliver(ForbiddenStore(), artifacts, binding))
    assert type(error) is ContractError and str(error) == UNWIRED
    assert artifacts.calls == []


def test_unwired_non_correction_route_without_research_refuses_where_m7_returned_none():
    """The one recorded deviation of R-cf1: the require sits before the route test, so no path can reach `redact` unchecked."""
    error = refusal_of(lambda: deliver(ForbiddenStore(), Artifacts(), {"route": "evidence_repair"}))
    assert str(error) == UNWIRED
    assert deliver(ForbiddenStore(), Artifacts(), {"route": "evidence_repair"}, redact=redact_text) is None


@pytest.mark.parametrize("fields", [{"family": "op-other"}, {"scope": "wider"}, {"evidence_refs": []}])
def test_an_invalid_research_reference_is_still_refused_first_by_its_own_code(fields):
    error = refusal_of(lambda: deliver(ForbiddenStore(), Artifacts(), research_binding(**fields)))
    assert isinstance(error, CorrectionFeedbackRefused) and error.reason_code in {"feedback_research_foreign", "feedback_research_invalid"}


def test_the_research_handoff_redacts_every_evidence_text_through_the_injected_rule():
    seen = []

    def stub(text):
        seen.append(text)
        return "<" + text + ">", 2

    artifacts = Artifacts(texts={RESEARCH_REF: "report token=abc"})
    block = deliver(ForbiddenStore(), artifacts, research_binding(), redact=stub)
    assert seen == ["report token=abc"] and block["evidence"] == [{"ref": RESEARCH_REF, "text": "<report token=abc>"}]
    assert block["redaction"] == {"applied": True, "spans": 2} and block["schema"] == module.RESEARCH_SCHEMA
    assert artifacts.calls == [("text", RESEARCH_REF)]


def test_the_correction_findings_and_the_research_beside_them_use_the_injected_rule_for_every_text():
    seen = []

    def stub(text):
        seen.append(text)
        return "[" + text + "]", 1

    artifacts = Artifacts(documents={REVIEW_REF: {"answer": ANSWER}}, texts={RESEARCH_REF: "evidence"})
    binding = {**CORRECTION, "predecessor": {**CORRECTION["predecessor"], "research": research_binding(route="correction")["predecessor"]["research"]}}
    block = deliver(seeded_store(ANSWER), artifacts, binding, redact=stub)
    assert seen == ["fix a.py token=abc", "r1", "r2 password=x", "evidence"]
    assert block["findings"] == {"accepted": False, "reason": "[fix a.py token=abc]", "risks": ["[r1]", "[r2 password=x]"]}
    assert block["redaction"] == {"applied": True, "spans": 3} and block["research"]["redaction"] == {"applied": True, "spans": 1}
    assert block["schema"] == module.SCHEMA


def test_observations_redact_text_injected_redacts_and_counts():
    block = deliver(seeded_store(ANSWER), Artifacts(documents={REVIEW_REF: {"answer": ANSWER}}), CORRECTION, redact=redact_text)
    assert block["findings"] == {"accepted": False, "reason": "fix a.py token=[REDACTED credential]", "risks": ["r1", "r2 password=[REDACTED credential]"]}
    assert block["redaction"] == {"applied": True, "spans": 2} and "abc" not in str(block) and "password=x" not in str(block)
    assert block["truncation"] == {"applied": False, "limit_chars": 15000, "characters": len(block["findings"]["reason"]) + 2 + len(block["findings"]["risks"][1])}


def test_a_refusal_before_the_first_redaction_does_not_call_the_rule():
    def rule(text):
        raise AssertionError("redact was called")

    error = refusal_of(lambda: deliver(ForbiddenStore(), Artifacts(texts={RESEARCH_REF: "  \n"}), research_binding(), redact=rule))
    assert isinstance(error, CorrectionFeedbackRefused) and error.reason_code == "feedback_research_empty"


def test_require_context_is_unchanged():
    require_context(10, 10)
    assert refusal_of(lambda: require_context(11, 10)).reason_code == "feedback_context_insufficient"
