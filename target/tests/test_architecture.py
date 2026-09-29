"""§3.6 allowed-edge checker: fixture verdicts and the target tree itself (S0 exit check 6)."""

import json
import re
from pathlib import Path

import import_rules
import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "import_rules"
TARGET_SRC = HERE.parent / "src"
CONTRACTS = HERE.parents[1] / "docs" / "contracts.md"
CASES = sorted(p for p in FIXTURES.iterdir() if p.is_dir())


def contract_ids() -> set[str]:
    # The ledger's 91 ids: every INV id the registry declares (summary table, sections, list items).
    return set(re.findall(r"INV-[A-Z0-9-]+-\d{3}", CONTRACTS.read_text(encoding="utf-8")))


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_fixture_verdict(case):
    expect = json.loads((case / "expect.json").read_text(encoding="utf-8"))
    violations = import_rules.check(case, contract_ids())
    verdict = "forbidden" if violations else "allowed"
    assert verdict == expect["verdict"], violations
    if expect["verdict"] == "forbidden":
        assert any(expect["rule_contains"] in v.rule for v in violations), violations


def test_fixture_set_covers_the_design_list():
    names = {c.name for c in CASES}
    assert sum(n.startswith("p") for n in names) >= 12
    assert sum(n.startswith("n") for n in names) >= 16


def test_target_tree_has_no_violation_and_no_exception():
    assert import_rules.EXCEPTIONS == ()
    assert import_rules.check(TARGET_SRC, contract_ids()) == []


def test_contract_registry_is_readable():
    assert len(contract_ids()) == 91
