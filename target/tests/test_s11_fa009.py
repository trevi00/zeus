"""S11 unit M: the FA-009 pair retargeted at `target/tests` (DESIGN-s11 §4 R-M3, §6; AR4).

M7 `tests/test_architecture.py` lines 24-61 hold the detector and two nodes: `wiring_assertions` flags an `assert` whose
test text both reads source (`read_text`/`read_bytes`/`getsource`/`ast.parse`/`ast.walk`/`ast.dump`) and names a production
location. The detector regexes, `wiring_assertions` and the positive/negative controls are M7's, verbatim; only the scanned
tree moves from M7 `tests/` to the target test tree (the top level and `ported/`; `fixtures/` holds data, not tests). M7
exempts exactly `test_architecture.py` (a structural policy test), kept here by name. A flagged test is a finding for the
owner, never a silent allowlist entry. `STRUCTURAL_PINS` below holds the assertions the owner has ruled on, by file and
line (tighter than M7's per-file allowlist, so a new source-text assertion in those files is still found).
"""

import ast
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent

SOURCE_TEXT_READERS = re.compile(r"\b(read_text|read_bytes|getsource|ast\.parse|ast\.walk|ast\.dump)\s*\(")
PRODUCTION_LOCATIONS = re.compile(r"(src/|scripts/|harness_hooks/|codex_harness[./])")
# Structural policy tests inspect source deliberately; behavior tests may not.
WIRING_ALLOWLIST = {"test_architecture.py"}
# FINDINGS awaiting an owner ruling, not waivers: the detector flags these S8/S10 move-pin assertions (AST/source-text
# checks of production code). {file relative to target/tests: [assert lines]}. Each entry is removed by a ruling.
# Owner ruling (DESIGN-s11 §6.1, 2026-10-05): these 8 assertions are in the S8 move-fidelity pins. They are structural
# policy tests by purpose: they pin the import sets and moved-symbol shapes of the S8 moves. That is M7's own exempt
# category ("Structural policy tests inspect source deliberately"). The moved code's behaviour is covered by its ported
# suites and compare families. They are exempt line by line, never whole files.
STRUCTURAL_PINS: dict[str, list[int]] = {
    "test_s8_audit_progress_move.py": [134],
    "test_s8_batch_b5a_move.py": [187],
    "test_s8_batch_b7a_move.py": [82, 133],
    "test_s8_batch_b8_move.py": [204],
    "test_s8_domain_moves_c.py": [153],
    "test_s8_research_program_adapter_move.py": [122],
    "test_s8_research_program_app_move.py": [188],
}


def wiring_assertions(source: str):
    """FA-009: assertions that only check production source text, not executed behavior.

    A `<literal> in <production file text>` or an AST-shape assertion proves that a string was
    typed, never that the wiring runs. Reading fixtures or generated runtime files is fine.
    """
    findings = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assert):
            continue
        text = ast.unparse(node.test)
        if SOURCE_TEXT_READERS.search(text) and PRODUCTION_LOCATIONS.search(text):
            findings.append((node.lineno, text[:120]))
    return findings


def scanned_tests():
    return sorted([*TESTS.glob("test_*.py"), *(TESTS / "ported").glob("test_*.py")])


def test_tests_assert_behavior_not_source_text():
    offenders = []
    for test in scanned_tests():
        if test.name in WIRING_ALLOWLIST:
            continue
        rel = test.relative_to(TESTS).as_posix()
        offenders += [(rel, line, text) for line, text in wiring_assertions(test.read_text(encoding="utf-8-sig"))
                      if line not in STRUCTURAL_PINS.get(rel, [])]
    assert offenders == [], offenders


def test_scan_covers_the_target_test_tree():
    names = {p.relative_to(TESTS).as_posix() for p in scanned_tests()}
    assert "test_architecture.py" in names and "ported/test_integration.py" in names
    assert len(names) > 200


def test_wiring_detector_has_positive_and_negative_controls():
    positive = (
        "from pathlib import Path\n"
        "def test_x():\n"
        "    assert 'record_incident' in (ROOT / 'src/codex_harness/cli.py').read_text()\n"
        "    assert 'fence' in Path('scripts/check.py').read_bytes().decode()\n"
        "    tree = ast.parse((ROOT / 'src/codex_harness/x.py').read_text())\n"
        "    assert any(isinstance(n, ast.Call) for n in ast.walk(ast.parse(source_of('codex_harness.x'))))\n")
    assert [line for line, _ in wiring_assertions(positive)] == [3, 4, 6]
    negative = (
        "def test_y(tmp_path):\n"
        "    assert (tmp_path / 'lease.json').read_text() == '{}'\n"  # generated runtime file
        "    assert service.record_incident(message)['occurrences'] == 1\n"  # executed behavior
        "    assert 'FASTAPI_ELIGIBLE' in prompts[0]['body']\n"  # observed output of a run
        "    body = (ROOT / 'src/codex_harness/cli.py').read_text()\n"  # read outside an assert
        "    assert parse(body)['version'] == 1\n")
    assert wiring_assertions(negative) == []
