"""S8 pilot 80: the M7 execution evidence port moved into research, VERBATIM through one named rule
(A/evidence/rebuild/s8/autonomous-evidence-move/transcribe.py; DESIGN-s8 §6 V11).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.autonomous_evidence` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
MODULE = "codex_harness.research.adapters.autonomous_evidence"
M7_PATH = "src/codex_harness/adapters/autonomous_evidence.py"
R_S0_IMPORTS = {"codex_harness.kernel.errors": ["ContractError"]}
M7_IMPORTS = {"codex_harness.domain.model": ["ContractError"]}
REF = "sha256:" + "ab" * 32


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True, text=True).stdout


def target_text():
    return Path(importlib.import_module(MODULE).__file__).read_text()


def statements(src):
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        assert isinstance(node, ast.ClassDef)
        out[node.name] = node
    return out


def from_imports(src):
    return {n.module: [a.name for a in n.names] for n in ast.parse(src).body if isinstance(n, ast.ImportFrom)}


def test_every_statement_is_m7_s_by_ast_in_m7_order():
    ref, ours = statements(m7_text()), statements(target_text())
    assert list(ours) == list(ref) == ["EvidenceUnavailable", "ExecutionEvidence"]
    for key in ref:
        assert ast.dump(ours[key]) == ast.dump(ref[key]), key


def test_the_only_change_is_the_import_rule_r_s0_and_the_header():
    old, new = from_imports(m7_text()), from_imports(target_text())
    assert {k: v for k, v in old.items() if k.startswith("codex_harness.")} == M7_IMPORTS
    assert {k: v for k, v in new.items() if k.startswith("codex_harness.")} == R_S0_IMPORTS
    assert new["__future__"] == old["__future__"] == ["annotations"]
    marker = "\n\nclass EvidenceUnavailable"
    assert m7_text().split(marker, 1)[1] == target_text().split(marker, 1)[1]
    doc = ast.get_docstring(ast.parse(target_text()))
    assert doc.startswith(ast.get_docstring(ast.parse(m7_text())))
    for line in ("Layer: adapters", "Context: research", "Entry points: EvidenceUnavailable, ExecutionEvidence", "Contracts: INV-AUTONOMOUS-001"):
        assert line in doc.splitlines()


def test_imports_are_only_the_kernel_home_and_the_module_never_writes():
    mods = {n.module for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == set(R_S0_IMPORTS)
    assert "codex_harness.domain" not in target_text().replace("codex_harness.research.domain", "")
    assert not [n for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.Import)]
    for word in (".put(", "open(", "write", "subprocess", "psycopg"):
        assert word not in target_text().split('"""', 2)[2], word


class Artifacts:
    def __init__(self, fault=None, result=None):
        self.fault, self.result, self.asked = fault, result if result is not None else {"answer": "ok"}, []

    def document(self, ref):
        self.asked.append(ref)
        if self.fault is not None:
            raise self.fault
        return self.result


def test_the_exception_is_a_contract_error_with_the_fixed_message_and_code():
    from codex_harness.kernel.errors import ContractError

    module = importlib.import_module(MODULE)
    exc = module.EvidenceUnavailable("evidence_invalid")
    assert isinstance(exc, ContractError) and str(exc) == "execution evidence evidence_invalid" and exc.reason_code == "evidence_invalid"


def test_a_success_returns_the_stores_document_and_passes_the_reference_unchanged():
    module = importlib.import_module(MODULE)
    store = Artifacts()
    assert module.ExecutionEvidence(store).document(REF) is store.result
    assert store.asked == [REF] and store.asked[0] is REF


@pytest.mark.parametrize("reference", [None, 7, b"sha256:abc", ["a"]])
def test_a_non_str_reference_is_missing_with_no_chain_and_no_store_call(reference):
    module = importlib.import_module(MODULE)
    store = Artifacts()
    with pytest.raises(module.EvidenceUnavailable) as info:
        module.ExecutionEvidence(store).document(reference)
    assert info.value.reason_code == "evidence_missing" and info.value.__cause__ is None and info.value.__context__ is None
    assert store.asked == []


@pytest.mark.parametrize("fault, code", [
    (FileNotFoundError("gone"), "evidence_missing"),
    (OSError("disk"), "evidence_corrupt"),
    (PermissionError("denied"), "evidence_corrupt"),
    (ValueError("bad json"), "evidence_corrupt"),
    (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), "evidence_corrupt"),
])
def test_a_store_failure_maps_to_one_fixed_code_chained_from_the_fault(fault, code):
    module = importlib.import_module(MODULE)
    with pytest.raises(module.EvidenceUnavailable) as info:
        module.ExecutionEvidence(Artifacts(fault)).document(REF)
    assert info.value.reason_code == code and str(info.value) == "execution evidence " + code
    assert info.value.__cause__ is fault and info.value.__suppress_context__


@pytest.mark.parametrize("message", ["Artifact modified: x", "Invalid artifact reference", "Evidence document must be an object", "unrelated"])
def test_a_contract_error_is_evidence_corrupt_because_the_value_error_branch_precedes_it(message):
    # M7's `except (OSError, ValueError, ...)` catches ContractError (a ValueError) first: the `ContractError` branch (and
    # `evidence_invalid`) is unreachable, and the golden records exactly that.
    from codex_harness.kernel.errors import ContractError

    module = importlib.import_module(MODULE)
    with pytest.raises(module.EvidenceUnavailable) as info:
        module.ExecutionEvidence(Artifacts(ContractError(message))).document(REF)
    assert info.value.reason_code == "evidence_corrupt"


@pytest.mark.parametrize("fault", [KeyError("k"), RuntimeError("boom")])
def test_a_fault_outside_the_mapping_propagates_unchanged(fault):
    module = importlib.import_module(MODULE)
    with pytest.raises(type(fault)) as info:
        module.ExecutionEvidence(Artifacts(fault)).document(REF)
    assert info.value is fault


def test_the_drivers_use_this_module_and_no_stand_in_remains():
    for name in ("s8_autonomous.py", "s8_council.py"):
        driver = (REPO / "compare" / "drivers" / "target" / name).read_text()
        assert "from codex_harness.research.adapters.autonomous_evidence import EvidenceUnavailable" in driver
        assert "class EvidenceUnavailable" not in driver
