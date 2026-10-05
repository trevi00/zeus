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
# FINDINGS awaiting an owner ruling, not waivers: the detector flags these assertions (AST/source-text checks of
# production code, or of packaged text). Each group below names the structural contract that justifies it and the
# {file relative to target/tests: [assert lines]} it covers; a pin is exempt line by line, never a whole file, and
# every pinned line must still be a flagged assertion (test_every_structural_pin_still_names_a_flagged_assertion).
# Group 1, owner ruling (DESIGN-s11 §6.1, 2026-10-05): these 8 assertions are in the S8 move-fidelity pins. They are
# structural policy tests by purpose: they pin the import sets and moved-symbol shapes of the S8 moves. That is M7's own
# exempt category ("Structural policy tests inspect source deliberately"). The moved code's behaviour is covered by its
# ported suites and compare families.
# Groups 2-7 (S11 unit TQ-1, B7): the hits the extended detector (read-then-assert, `*_SCRIPT|*_SOURCE|*_TEMPLATE`
# constants) found in the target suite, each classified by the contract it pins; none is behavioural acceptance.
PIN_GROUPS: list[tuple[str, dict[str, list[int]]]] = [
    ("S8 move fidelity: import sets and moved-symbol shapes (DESIGN-s11 §6.1)", {
        "test_s8_audit_progress_move.py": [134],
        "test_s8_batch_b5a_move.py": [187],
        "test_s8_batch_b7a_move.py": [82, 133],
        "test_s8_batch_b8_move.py": [204],
        "test_s8_domain_moves_c.py": [153],
        "test_s8_research_program_adapter_move.py": [122],
        "test_s8_research_program_app_move.py": [188],
    }),
    ("S8 move fidelity: the moved module's import homes (import-rule contract of the move, like group 1)", {
        "test_s8_audit_progress_move.py": [129, 132],
        "test_s8_audit_repair_move.py": [179],
        "test_s8_autonomous_evidence_move.py": [68],
        "test_s8_autonomous_move.py": [102, 109],
        "test_s8_autonomous_roles_move.py": [95],
        "test_s8_completion_move.py": [88],
        "test_s8_council_move.py": [84, 88],
        "test_s8_council_snapshot_move.py": [88],
        "test_s8_dge_move.py": [78],
        "test_s8_evidence_inspection_move.py": [182],
        "test_s8_research_app_move.py": [145, 148],
        "test_s8_research_program_adapter_move.py": [115, 120],
        "test_s8_research_program_app_move.py": [156, 162, 165],
        "test_s8_reverse_source_apps_move.py": [129],
        "test_s8_threshold_approvals_move.py": [91],
    }),
    ("S8 move fidelity: the moved declaration is M7's (`__all__` surface, moved-out name, ports class, injectable rule)", {
        "test_s8_portfolio_move.py": [75, 173],
        "test_s8_research_app_move.py": [184],
        "test_s8_thresholds_a_move.py": [185],
    }),
    ("S8 move fidelity: the composed consumer still makes the call the moved producer's signature serves", {
        "test_s8_release_suite_move.py": [261],
    }),
    ("OWNER-DECISIONS-S11 #11: the product's own composition names the module that static.source's keep_shim pins", {
        "test_compare_harness.py": [205],
    }),
    ("packaged-resource declaration: the shipped hook manifest and the shipped research schema state what the profile and "
     "the output contract declare (data, not code; the replay and canary behaviour is covered by the ported suites)", {
        "ported/test_native_hooks.py": [106, 107],
        "ported/test_output_schema.py": [110],
    }),
    ("TQ-1 B8 restated structural pins: each docstring names its structural contract and the behavioural tests", {
        "test_s10_a5_1a_dead_letter_drain.py": [53, 56],
        "test_s4_decision_owners.py": [166],
    }),
]
STRUCTURAL_PINS: dict[str, list[int]] = {}
for _contract, _pins in PIN_GROUPS:
    for _file, _lines in _pins.items():
        STRUCTURAL_PINS.setdefault(_file, []).extend(_lines)


CONSTANT_SUFFIXES = ("_SCRIPT", "_SOURCE", "_TEMPLATE")


def _imports_from_harness(tree):
    """Names the module binds from `codex_harness` (`from codex_harness... import X`, `import codex_harness...`)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "codex_harness" and not node.level:
            names |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in node.names
                      if alias.name.split(".")[0] == "codex_harness"}
    return names


def _bound_names(target):
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _is_harness_constant(node, imported):
    """A `<Name>_SCRIPT|_SOURCE|_TEMPLATE` reference (bare, or an attribute such as `RedisBus._X_SCRIPT`) whose root
    name is imported from `codex_harness`, or which is itself imported from there (B7 b)."""
    if isinstance(node, ast.Attribute) and node.attr.endswith(CONSTANT_SUFFIXES):
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        return isinstance(root, ast.Name) and root.id in imported
    return isinstance(node, ast.Name) and node.id.endswith(CONSTANT_SUFFIXES) and node.id in imported


def _function_bindings(function, imported):
    """Names bound inside one function, as `{name: first binding line}`: `source` holds names bound from a statement that
    reads production source (the reader regex and a production location in the statement; a reader statement that
    names an already-bound source name extends the set, e.g. `tree = ast.parse(text)`), `constant` names bound from a
    harness `*_SCRIPT|*_SOURCE|*_TEMPLATE` constant."""
    statements = []
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            statements.append((node.lineno, node.value, set().union(*map(_bound_names, targets))))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            statements += [(node.lineno, item.context_expr, _bound_names(item.optional_vars))
                           for item in node.items if item.optional_vars is not None]
    source: dict[str, int] = {}
    constant: dict[str, int] = {}
    for line, value, names in sorted(statements, key=lambda s: s[0]):
        if isinstance(value, ast.Constant):  # a string that merely contains the words is not a read
            continue
        text = ast.unparse(value)
        reads = SOURCE_TEXT_READERS.search(text)
        if reads and (PRODUCTION_LOCATIONS.search(text) or any(n.id in source for n in ast.walk(value)
                                                               if isinstance(n, ast.Name))):
            source.update({name: source.get(name, line) for name in names})
        if any(_is_harness_constant(n, imported) or (isinstance(n, ast.Name) and n.id in constant)
               for n in ast.walk(value)):
            constant.update({name: constant.get(name, line) for name in names})
    return source, constant


def _constant_operands(node, imported, constant):
    """True when the subtree names a harness constant, or a local name bound from one."""
    return any(_is_harness_constant(n, imported) or (isinstance(n, ast.Name) and n.id in constant)
               for n in ast.walk(node))


def _constant_text_assertion(test, imported, constant):
    """`.index(`, `.startswith(` or `in` applied to a harness script/source/template constant (B7 b)."""
    for n in ast.walk(test):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("index", "startswith")
                and _constant_operands(n.func.value, imported, constant)):
            return True
        if isinstance(n, ast.Compare) and any(
                isinstance(op, ast.In) and _constant_operands(comparator, imported, constant)
                for op, comparator in zip(n.ops, n.comparators)):
            return True
    return False


def wiring_assertions(source: str):
    """FA-009: assertions that only check production source text, not executed behavior.

    A `<literal> in <production file text>` or an AST-shape assertion proves that a string was
    typed, never that the wiring runs. Reading fixtures or generated runtime files is fine.

    Beyond M7's one-assert form (S11 unit TQ-1, B7; the measured blind spots of TQ-XCUT-PLAN §1 B7), a test function is
    also flagged when (a) an earlier statement reads production source and the assert names a variable bound from that
    read, or (b) the assert applies `.index(`, `.startswith(` or `in` to a module constant named `*_SCRIPT`, `*_SOURCE`
    or `*_TEMPLATE` imported from `codex_harness` (or to a local name bound from one).
    """
    tree = ast.parse(source)
    imported = _imports_from_harness(tree)
    findings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            text = ast.unparse(node.test)
            if SOURCE_TEXT_READERS.search(text) and PRODUCTION_LOCATIONS.search(text):
                findings[node.lineno] = text[:120]
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        read, constant = _function_bindings(function, imported)
        for node in ast.walk(function):
            if not isinstance(node, ast.Assert) or node.lineno in findings:
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if any(read.get(name, node.lineno) < node.lineno for name in names) or \
                    _constant_text_assertion(node.test, imported, constant):
                findings[node.lineno] = ast.unparse(node.test)[:120]
    return sorted(findings.items())


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


def test_every_structural_pin_still_names_a_flagged_assertion():
    """A pin that no longer matches a flagged assertion would silently exempt whatever lands on that line next."""
    stale = []
    for rel, lines in STRUCTURAL_PINS.items():
        flagged = {line for line, _ in wiring_assertions((TESTS / rel).read_text(encoding="utf-8-sig"))}
        stale += [(rel, line) for line in lines if line not in flagged]
    assert stale == [], stale
    assert sum(len(lines) for lines in STRUCTURAL_PINS.values()) == sum(
        len(lines) for _, pins in PIN_GROUPS for lines in pins.values())


def test_scan_covers_the_target_test_tree():
    names = {p.relative_to(TESTS).as_posix() for p in scanned_tests()}
    assert "test_architecture.py" in names and "ported/test_integration.py" in names
    assert len(names) > 200


def test_wiring_detector_has_positive_and_negative_controls():
    """M7's controls. TQ-1 B7 changed one line of M7's negative control: its read-then-`assert parse(body)` form is now a
    flagged read-then-assert (rule a), so the control reads `body` without asserting on it; the flagged form is a positive
    control in test_wiring_detector_flags_a_read_then_assert_and_a_script_constant_order."""
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
        "    body = (ROOT / 'src/codex_harness/cli.py').read_text()\n"  # read, but no assert names it
        "    assert service.version() == 1\n")
    assert wiring_assertions(negative) == []


def test_wiring_detector_flags_a_read_then_assert_and_a_script_constant_order():
    """TQ-1 B7 positive controls: source read in a statement then asserted through its variable (including through
    `ast.parse`/`ast.walk` of it), and `.index(`/`in`/`startswith` on a `*_SCRIPT|*_SOURCE|*_TEMPLATE` constant
    imported from `codex_harness`, bare, through an attribute, or through a local name bound from it."""
    positive = (
        "from codex_harness.storage.adapters.redis_bus import RedisBus\n"
        "def test_read_then_assert():\n"
        "    text = (ROOT / 'src/codex_harness/x.py').read_text()\n"
        "    assert 'needle' in text\n"  # 4
        "def test_parsed_then_asserted():\n"
        "    tree = ast.parse((ROOT / 'src/codex_harness/x.py').read_text())\n"
        "    names = [n.name for n in ast.walk(tree)]\n"
        "    assert names == ['a', 'b']\n"  # 8
        "def test_lua_order():\n"
        "    script = RedisBus._DEAD_LETTER_SCRIPT\n"
        "    assert script.index('XADD') < script.index('XACK')\n"  # 11
        "    assert 'KEYS[1]' in script\n"  # 12
        "def test_constant_in_the_assert():\n"
        "    assert 'XACK' in RedisBus._DEAD_LETTER_SCRIPT\n"  # 14
        "    assert RedisBus._PUBLISH_SCRIPT.startswith('local')\n")  # 15
    assert [line for line, _ in wiring_assertions(positive)] == [4, 8, 11, 12, 14, 15]
    bare = (
        "from codex_harness.x import TEMPLATE_X_TEMPLATE\n"
        "def test_template():\n"
        "    assert 'slot' in TEMPLATE_X_TEMPLATE\n")
    assert [line for line, _ in wiring_assertions(bare)] == [3]


def test_wiring_detector_leaves_fixture_reads_runtime_outputs_and_foreign_constants_alone():
    """TQ-1 B7 negative controls: a fixture or generated file read; a run's observed output; a name read in ANOTHER
    function; a `*_SOURCE` constant the test itself defines (data, not a harness script); a harness script constant
    used as an argv element in a recorded runtime sequence (no `.index(`/`in`/`startswith`)."""
    negative = (
        "from codex_harness.storage.adapters.redis_bus import RedisBus\n"
        "LEGACY_SOURCE = {'topic': 'storage'}\n"
        "def test_fixture(tmp_path):\n"
        "    text = (tmp_path / 'lease.json').read_text()\n"
        "    assert 'x' in text\n"
        "def test_runtime_output():\n"
        "    out = run_cli(['--help'])\n"
        "    assert 'XADD' in out\n"
        "def test_reads_here():\n"
        "    text = (ROOT / 'src/codex_harness/x.py').read_text()\n"
        "    return text\n"
        "def test_asserts_elsewhere(text):\n"
        "    assert 'needle' in text\n"
        "def test_own_data_constant():\n"
        "    assert 'topic' in LEGACY_SOURCE\n"
        "def test_recorded_sequence(bus):\n"
        "    assert bus.client.calls == [('eval', (RedisBus._DEAD_LETTER_SCRIPT, 2))]\n")
    assert wiring_assertions(negative) == []
