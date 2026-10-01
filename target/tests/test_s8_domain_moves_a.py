"""S8 step 1a: seven pure M7 domain modules and `parse_json`, moved verbatim by
A/evidence/rebuild/s8/domain-moves-a/transcribe.py (DESIGN-s8 §3 step 1, V2b).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals read from M7.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest

from codex_harness.kernel.errors import ContractError

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
M7 = "src/codex_harness/domain/"
MODULES = {
    "evidence": "codex_harness.evidence.domain.evidence",
    "completion": "codex_harness.evidence.domain.completion",
    "gate_verdicts": "codex_harness.evidence.domain.gate_verdicts",
    "project_evidence": "codex_harness.evidence.domain.project_evidence",
    "sdd": "codex_harness.review.domain.sdd",
    "ticket_lifecycle": "codex_harness.intake.domain.ticket_lifecycle",
    "frontdesk": "codex_harness.intake.domain.frontdesk",
}


def m7_text(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{path}"], check=True, capture_output=True,
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
def test_module_imports_and_names_equal_m7(m7name):
    module = importlib.import_module(MODULES[m7name])
    ref = m7_text(M7 + m7name + ".py")
    assert top_names(target_text(MODULES[m7name])) == top_names(ref)
    assert all(hasattr(module, name) for name in top_names(ref))


@pytest.mark.parametrize("m7name", MODULES)
def test_every_function_and_class_ast_equals_m7(m7name):
    ours, ref = definitions(target_text(MODULES[m7name])), definitions(m7_text(M7 + m7name + ".py"))
    assert ref and ours == ref


def test_parse_json_is_m7_verbatim_and_strict():
    from codex_harness.kernel import strict_json

    ref = definitions(m7_text("src/codex_harness/adapters/sdd.py"))["parse_json"]
    assert definitions(target_text("codex_harness.kernel.strict_json")) == {"parse_json": ref}
    assert strict_json.parse_json('{"a": 1}') == {"a": 1}
    with pytest.raises(ContractError, match="Duplicate JSON key: a"):
        strict_json.parse_json('{"a":1,"a":2}')


def test_evidence_classify_replays():
    from codex_harness.evidence.domain import evidence

    assert evidence.classify_replays([{"returncode": 0}], 0) == ("checked", "exit 0 as claimed on 1 identical replay(s)")
    assert evidence.classify_replays([{"returncode": 1}], 0) == ("verified_mismatch", "exit 1, claimed 0")
    with pytest.raises(ContractError, match="At least one replay run is required to classify"):
        evidence.classify_replays([], 0)


def test_completion_timestamp_and_latest():
    from codex_harness.evidence.domain import completion

    assert completion.parse_timestamp("2026-01-01T00:00:00+00:00").utcoffset().total_seconds() == 0
    with pytest.raises(ContractError, match="Completion verdict rejected: observed_at must carry a timezone"):
        completion.parse_timestamp("2026-01-01T00:00:00")
    assert completion.latest([{"sequence": 1}, {"sequence": 3}, {"sequence": 2}]) == {"sequence": 3}
    assert completion.latest([]) is None


def test_gate_verdicts_parse_verdict():
    from codex_harness.evidence.domain import gate_verdicts

    document = {"statement_id": "s1", "stage": "unit", "run_id": "r1", "cycle": 0, "definition_hash": "a" * 64,
                "artifact_hash": None, "environment_hash": None, "verdict": "PASS", "origin": "reviewer_decision",
                "receipt_ref": None, "exit_status": None, "actor": "rev", "authority": "authenticated_provider",
                "sequence": 1}
    assert gate_verdicts.parse_verdict(document).state == "passed"
    with pytest.raises(ContractError, match="Unknown gate verdict$"):
        gate_verdicts.parse_verdict({**document, "verdict": "MAYBE"})
    with pytest.raises(ContractError, match="Unknown gate verdict fields"):
        gate_verdicts.parse_verdict({**document, "extra": 1})


def test_project_evidence_classify_check_and_evidence_import():
    from codex_harness.evidence.domain import evidence, project_evidence

    assert project_evidence.MAX_ARGV is evidence.MAX_ARGV and project_evidence.authorized is evidence.authorized
    claim = {"reported_exit": 1, "expected_exit": 0}
    assert project_evidence.classify_check(claim, "checked", "c", [0]) == (
        "verified_mismatch", "worker reported exit 1, host expected 0; replay exits [0]")
    assert project_evidence.classify_check(claim, "missing", "c", [0]) == ("missing", "c")


def test_sdd_coverage_and_environment_refusal():
    from codex_harness.review.domain import sdd

    spec = {"scenarios": [{"id": "A", "status": "active"}, {"id": "B", "status": "active"},
                          {"id": "C", "status": "retired"}]}
    assert sdd.coverage(spec, ["A", "Z"]) == {"matched": ["A"], "missing": ["B"], "orphan": ["Z"],
                                              "authority": "structural_only_not_acceptance"}
    with pytest.raises(ContractError, match="Incomplete environment identity"):
        sdd.validate_environment({})


def test_ticket_lifecycle_timestamp():
    from codex_harness.intake.domain import ticket_lifecycle

    assert ticket_lifecycle.timestamp("2026-01-01T00:00:00+00:00").year == 2026
    with pytest.raises(ContractError, match="Timestamp must include timezone"):
        ticket_lifecycle.timestamp("2026-01-01T00:00:00")
    with pytest.raises(ContractError, match="Invalid lifecycle timestamp"):
        ticket_lifecycle.timestamp("not a time")


def test_frontdesk_safe_code_and_identifier():
    from codex_harness.intake.domain import frontdesk

    assert frontdesk.safe_code("invalid_id") == "invalid_id"
    assert frontdesk.safe_code("has a space") == "unknown"
    assert frontdesk.safe_code(5) == "unknown"
    with pytest.raises(frontdesk.DeskRefused, match=r"desk refused: invalid_id \(session_id\)"):
        frontdesk.identifier("not-a-uuid", "session_id")
    assert frontdesk.identifier("123e4567-e89b-12d3-a456-426614174000", "session_id").startswith("123e4567")
