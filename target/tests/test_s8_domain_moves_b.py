"""S8 step 1b: six research domain modules and `timestamp`, moved verbatim by
A/evidence/rebuild/s8/domain-moves-b/transcribe.py (DESIGN-s8 §3 step 1, V2g, V7).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals read from M7.
"""
import ast
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.kernel.errors import ContractError

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
BASE_HEAD = "c794de5271601ff24a4dc8540e01a6b1286092bf"
M7 = "src/codex_harness/domain/"
MODULES = {name: f"codex_harness.research.domain.{name}" for name in (
    "audit_repair", "council_input", "decision_feedback", "threshold_replay", "threshold_proposals", "research")}
S4_PAIR = ("research_origin", "require_dispatch")


def git_text(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True,
                          text=True).stdout


def target_text(module):
    return Path(importlib.import_module(module).__file__).read_text()


def top_names(src):
    names = set()
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def definitions(src):
    return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


@pytest.mark.parametrize("m7name", MODULES)
def test_module_names_equal_m7(m7name):
    module = importlib.import_module(MODULES[m7name])
    ref = git_text(SOURCE, M7 + m7name + ".py")
    assert top_names(target_text(MODULES[m7name])) == top_names(ref)
    assert all(hasattr(module, name) for name in top_names(ref))


@pytest.mark.parametrize("m7name", MODULES)
def test_every_function_and_class_ast_equals_m7(m7name):
    ours, ref = definitions(target_text(MODULES[m7name])), definitions(git_text(SOURCE, M7 + m7name + ".py"))
    assert ref and ours == ref


def test_research_keeps_the_s4_bytes_and_appends_m7_in_order():
    text = target_text(MODULES["research"])
    base = git_text(BASE_HEAD, "target/src/codex_harness/research/domain/research.py")
    assert base[base.index("def research_origin"):].rstrip("\n") in text
    ref = git_text(SOURCE, M7 + "research.py")
    ours = [n.name for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    assert ours[:2] == list(S4_PAIR)
    assert ours[2:] == [n.name for n in ast.parse(ref).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                        and n.name not in S4_PAIR]


def test_kernel_names_equal_the_m7_operation_and_threshold_definitions():
    from codex_harness.kernel import ids, numbers

    m7 = ast.parse(git_text(SOURCE, M7 + "operation.py"))
    values = {t.id: ast.dump(n.value) for n in m7.body if isinstance(n, ast.Assign)
              for t in n.targets if isinstance(t, ast.Name)}
    ours = {t.id: ast.dump(n.value) for n in ast.parse(Path(ids.__file__).read_text()).body
            if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    for name in ("ID", "REVISION", "SHA256"):
        assert values[name] == ours[name]
    assert definitions(Path(ids.__file__).read_text())["safe_relative_path"] == \
        definitions(git_text(SOURCE, M7 + "operation.py"))["safe_relative_path"]
    # S2 added only the `-> bool` annotation; the body is M7's.
    def body(src):
        return [ast.dump(n) for n in next(
            d for d in ast.parse(src).body if isinstance(d, ast.FunctionDef) and d.name == "finite_number").body]

    assert body(Path(numbers.__file__).read_text()) == body(git_text(SOURCE, M7 + "threshold_replay.py"))


def test_timestamp_is_m7_verbatim_and_shared():
    from codex_harness.context.domain.skills import audit
    from codex_harness.kernel import timestamps

    ref = definitions(git_text(SOURCE, M7 + "skill_audit.py"))["timestamp"]
    assert definitions(Path(timestamps.__file__).read_text()) == {"timestamp": ref}
    assert audit.timestamp is timestamps.timestamp
    assert "timestamp" not in definitions(target_text("codex_harness.context.domain.skills.audit"))
    for module in ("threshold_replay", "threshold_proposals"):
        assert importlib.import_module(MODULES[module]).timestamp is timestamps.timestamp
    assert timestamps.timestamp("2026-01-01T00:00:00Z") == 1767225600.0
    assert timestamps.timestamp("2026-01-01T00:00:00") == 1767225600.0
    assert timestamps.timestamp(None) is None
    assert timestamps.timestamp("bad") is None


def test_s6_and_kernel_imports_resolve_to_the_moved_names():
    from codex_harness.kernel import numbers
    from codex_harness.research.domain import (
        autonomous,
        council,
        decision_feedback,
        dge,
        threshold_proposals,
        threshold_replay,
    )

    assert threshold_proposals.replay is threshold_replay
    assert threshold_proposals.finite_number is numbers.finite_number
    assert decision_feedback.ARBITER is autonomous.ARBITER and decision_feedback.TERMINAL is autonomous.TERMINAL
    assert decision_feedback.VERDICTS is dge.VERDICTS
    assert decision_feedback.COUNCIL_AGENTS is council.COUNCIL_AGENTS


def test_audit_repair_identifier():
    from codex_harness.research.domain import audit_repair

    assert audit_repair.identifier("audit-1") == "audit-1"
    assert audit_repair.identifier("has space") is None
    assert audit_repair.identifier(5) is None
    assert audit_repair.identifier("x" * 129) is None


def test_council_input_byte_policy():
    from codex_harness.research.domain import council_input

    assert council_input.canonical_bytes({"a": "é"}) == 10
    assert council_input.PAYLOAD_POOL == 32768
    assert council_input.RESERVATIONS == {council_input.PACKET: 16384, council_input.DBA_REPORT: 4096,
                                          council_input.RESEARCH_PROPOSAL: 4096,
                                          council_input.IMPROVEMENT_PROPOSAL: 8192}
    assert council_input.SCHEMA == "urn:zeus:council-input:2"


def test_decision_feedback_constants():
    from codex_harness.research.domain import decision_feedback

    assert decision_feedback.DECIDING_ROLE == "conductor"
    assert decision_feedback.OCCURRENCE_THRESHOLD == 2
    assert decision_feedback.REMEDIATIONS == ("existing_owner_review", "script", "skill")
    assert decision_feedback.OUTCOME_STATES == ("pending", "accepted", "rejected", "failed", "cancelled", "unknown")


def test_threshold_replay_helpers():
    from codex_harness.research.domain import threshold_replay

    assert threshold_replay.top_entries({"top": [{"a": 1}, 3]}) == [{"a": 1}]
    assert threshold_replay.top_entries("x") == []
    assert threshold_replay.finite_number(1.5) and not threshold_replay.finite_number(True)
    assert not threshold_replay.finite_number(float("inf"))
    with pytest.raises(ContractError, match="Invalid holdout boundary"):
        threshold_replay.split_by_holdout([], "bad")
    assert threshold_replay.split_by_holdout([{"at": "2026-01-01T00:00:00Z"}, {"at": "2026-03-01T00:00:00Z"}],
                                             "2026-02-01T00:00:00Z")[0] == [{"at": "2026-01-01T00:00:00Z"}]


def test_threshold_proposals_direction_and_boundary():
    from codex_harness.research.domain import threshold_proposals

    assert threshold_proposals.HOLDOUT_FRACTION == 0.30 and threshold_proposals.CALCULATION_VERSION == 2
    assert threshold_proposals.holdout_boundary([]) is None
    raise_safe = SimpleNamespace(direction_safety="raise_safe")
    assert threshold_proposals.direction_allowed(raise_safe, 1, 2) is True
    assert threshold_proposals.direction_allowed(raise_safe, 2, 1) is False
    assert threshold_proposals.direction_allowed(SimpleNamespace(direction_safety="either"), 2, 1) is True
    with pytest.raises(ContractError, match="Invalid policy revision"):
        threshold_proposals.propose_threshold_changes(events_by_source={}, current_values={}, policy_revision="x")


def test_research_contracts_and_s4_guard():
    from codex_harness.research.domain import research

    research.reference("sha256:" + "a" * 64)
    with pytest.raises(ContractError, match="Invalid immutable evidence reference"):
        research.reference("sha256:short")
    with pytest.raises(research.AuditDraftRejected, match="no good"):
        research.reject(False, "no good")
    assert issubclass(research.AuditDraftRejected, ContractError)
    assert research.research_origin({"x": [{"audit_id": 1}]}) is True
    assert research.research_origin({"x": 1}) is False
    with pytest.raises(ContractError, match="Research adoption deferred"):
        research.require_dispatch({"proposal": 1})
