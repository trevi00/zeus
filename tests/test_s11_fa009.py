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

from _layout import TESTS

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
# FA-009c removed the KNOWN FALSE POSITIVE group (`ported/test_pipeline.py:48`, a packaged YAML golden compared with the
# result of `merge_stages`): it is behavioural and no longer flagged. No other pin changed.
# Groups 2-7 (S11 unit TQ-1, B7): the hits the extended detector (read-then-assert, `*_SCRIPT|*_SOURCE|*_TEMPLATE`
# constants) found in the target suite, each classified by the contract it pins; none is behavioural acceptance.
PIN_GROUPS: list[tuple[str, dict[str, list[int]]]] = [
    ("S8 move fidelity: import sets and moved-symbol shapes (DESIGN-s11 §6.1)", {
        "test_s8_audit_progress_move.py": [134],
        "test_s8_batch_b5a_move.py": [188],
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
        "test_s8_thresholds_a_move.py": [186],
    }),
    ("S8 move fidelity: the composed consumer still makes the call the moved producer's signature serves", {
        "test_s8_release_suite_move.py": [261],
    }),
    ("OWNER-DECISIONS-S11 #11: the product's own composition names the module that static.source's keep_shim pins", {
        "test_compare_harness.py": [206],
    }),
    ("packaged-resource declaration: the shipped hook manifest and the shipped research schema state what the profile and "
     "the output contract declare (data, not code; the replay and canary behaviour is covered by the ported suites)", {
        "ported/test_native_hooks.py": [106, 107],
        "ported/test_output_schema.py": [110],
    }),
    ("S8/S9 move fidelity: the moved module's header is M7's docstring plus the DESIGN-s11 §3.2 fields (layer, context, "
     "owner, contracts, SOURCE, rule ids); a provenance contract, asserted through the `header()` helper (FA-009b)", {
        "test_s8_batch_b1_move.py": [77, 79, 121, 124],
        "test_s8_batch_b2_move.py": [174, 177, 324, 327],
        "test_s9_batch_l2b1_move.py": [85, 86, 156, 157, 159],
        "test_s9_batch_l2b2_move.py": [82, 108, 110, 117, 118, 119, 121, 123],
    }),
    ("S8 move rules R-ta1 (the spawn chokepoint), R-tk2 and R-gh1 (the injected clock and port): the moved module's body, "
     "outside its header, carries no spawn name and no bare `utcnow()` (FA-009b; the behaviour is covered by the same "
     "files' behavioural tests)", {
        "test_s8_batch_b1_move.py": [131],
        "test_s8_batch_b2_move.py": [266, 367, 434],
    }),
    ("packaged-resource declaration, read through a helper (FA-009b): the shipped research schema declares the vocabulary "
     "the domain declares (group 6's contract)", {
        "ported/test_audit_output_vocabulary.py": [72],
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
# FA-009c: a packaged DATA resource is named by one of these suffixes (or parsed by one of these loaders) and by none of
# the code/template suffixes. The code list is the one the detector treats as source: `.py` is the only one the target
# tests read from a production location today (measured 2026-10-05); `.sh`, `.ps1`, `.service` and `.in` are the
# scripts/unit/template files named by the owner rule. Code evidence always wins.
CODE_SUFFIXES = (".py", ".sh", ".ps1", ".service", ".in")
DATA_SUFFIXES = (".json", ".yaml", ".yml", ".toml")
DATA_PARSERS = re.compile(r"\b(json\.loads?|yaml\.(safe_)?load|tomllib\.loads?|load_yaml)\s*\(")
READ_TEXT_CALL = re.compile(r"\b(read_text|read_bytes)\s*\(")
# Call roots that are not the behaviour under test (builtins, parsers, path and AST helpers).
NEUTRAL_CALLS = frozenset({"len", "set", "list", "tuple", "dict", "sorted", "str", "int", "float", "bool", "isinstance",
                           "min", "max", "sum", "any", "all", "enumerate", "zip", "range", "reversed", "frozenset",
                           "repr", "type", "Path", "files", "json", "yaml", "tomllib", "ast", "inspect", "load_yaml"})


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


PRODUCTION_TEXT = re.compile(r"__doc__|\b(getsource|getdoc|get_docstring)\s*\(")


def _is_production_text(text):
    """A module `__doc__`, `getsource`/`getdoc`/`ast.get_docstring`, or `read_text`/`read_bytes` of a production location."""
    return bool(PRODUCTION_TEXT.search(text) or
                (re.search(r"\b(read_text|read_bytes)\s*\(", text) and PRODUCTION_LOCATIONS.search(text)))


def _function_returns(function):
    """The `return` statements of one function, not those of a function nested in it."""
    stack, out = list(function.body), []
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Return) and node.value is not None:
            out.append(node)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))
    return out


def _local_readers(tree):
    """Names of functions defined in the module whose return value is production text (FA-009b, one level of helper):
    a returned expression that is production text, or a returned name bound in that function from production text."""
    readers = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {}
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not isinstance(node.value, ast.Constant) and _is_production_text(ast.unparse(node.value)):
                    bound.update({name: node.lineno for target in targets for name in _bound_names(target)})
        for ret in _function_returns(function):
            if isinstance(ret.value, ast.Constant):
                continue
            names = {n.id for n in ast.walk(ret.value) if isinstance(n, ast.Name)}
            if _is_production_text(ast.unparse(ret.value)) or any(bound.get(n, ret.lineno) < ret.lineno for n in names):
                readers.add(function.name)
    return readers


def _calls_reader(node, readers):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in readers for n in ast.walk(node))


def _function_statements(function):
    """The binding statements of one function as `(line, value expression, bound names)`."""
    statements = []
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            statements.append((node.lineno, node.value, set().union(*map(_bound_names, targets))))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            statements += [(node.lineno, item.context_expr, _bound_names(item.optional_vars))
                           for item in node.items if item.optional_vars is not None]
    return statements


def _function_bindings(function, imported, readers=frozenset()):
    """Names bound inside one function, as `{name: first binding line}`: `source` holds names bound from a statement that
    reads production source (the reader regex and a production location in the statement; a reader statement that
    names an already-bound source name extends the set, e.g. `tree = ast.parse(text)`), `constant` names bound from a
    harness `*_SCRIPT|*_SOURCE|*_TEMPLATE` constant. A statement that calls a local reader (`readers`, FA-009b) also
    binds `source`."""
    statements = _function_statements(function)
    source: dict[str, int] = {}
    constant: dict[str, int] = {}
    for line, value, names in sorted(statements, key=lambda s: s[0]):
        if isinstance(value, ast.Constant):  # a string that merely contains the words is not a read
            continue
        text = ast.unparse(value)
        reads = SOURCE_TEXT_READERS.search(text)
        if _calls_reader(value, readers):
            source.update({name: source.get(name, line) for name in names})
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


def _constants(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _data_evidence(node):
    """FA-009c: the subtree names a DATA resource: a `DATA_SUFFIXES` string (or an f-string part) or a data loader call,
    and no `CODE_SUFFIXES` string, `__doc__`, `getsource`, `getdoc` or `get_docstring`. Code evidence always wins."""
    text = ast.unparse(node)
    constants = _constants(node)
    if PRODUCTION_TEXT.search(text) or any(c.endswith(CODE_SUFFIXES) for c in constants):
        return False
    return any(c.endswith(DATA_SUFFIXES) for c in constants) or bool(DATA_PARSERS.search(text))


def _local_data_readers(tree, readers):
    """The local readers whose own body (docstring aside) names a data resource and no code text (FA-009c)."""
    out = set()
    for function in ast.walk(tree):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and function.name in readers:
            body = function.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]
            if body and _data_evidence(ast.Module(body=body, type_ignores=[])):
                out.add(function.name)
    return out


def _reader_call_is_data(call, data_readers):
    """A call to a local reader reads data when the helper does and no code suffix is passed, or the arguments name data."""
    arguments = ast.Module(body=[ast.Expr(value=a) for a in [*call.args, *(k.value for k in call.keywords)]],
                           type_ignores=[])
    if any(c.endswith(CODE_SUFFIXES) for c in _constants(arguments)):
        return False
    return call.func.id in data_readers or _data_evidence(arguments)


def _text_kinds(node, readers, data_readers, data_names):
    """`(data, code)`: whether the subtree derives from production DATA text (a data reader call, a data-resource read,
    or a name bound from one) and whether it derives from production CODE text (a non-data reader call, a source read,
    `__doc__`/`getsource`/`getdoc`/`get_docstring`)."""
    data = code = False
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in readers:
            if _reader_call_is_data(n, data_readers):
                data = True
            else:
                code = True
        elif isinstance(n, ast.Name) and n.id in data_names:
            data = True
    text = ast.unparse(node)
    if READ_TEXT_CALL.search(text) and PRODUCTION_LOCATIONS.search(text) and _data_evidence(node):
        data = True
    elif SOURCE_TEXT_READERS.search(text) or PRODUCTION_TEXT.search(text):
        code = True
    return data, code


def _has_target_call(node, readers, bound):
    """A call to a function or method other than a reader, a builtin/parser/path helper, or a method of a name already
    bound from data or from a call result (FA-009c: the behaviour under test)."""
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        root = n.func
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        if not isinstance(root, ast.Name):
            continue  # a call on a literal, an operator result or another call: the inner call is visited on its own
        if root.id in readers or root.id in NEUTRAL_CALLS or (isinstance(n.func, ast.Attribute) and root.id in bound):
            continue
        return True
    return False


def _value_bindings(function, readers, data_readers):
    """`(data_names, call_names)` of one function (one level of dataflow, as FA-009b): a name is DATA when bound from a
    statement deriving from data text, CALL when bound from a statement that calls target code (it may be both)."""
    data_names: dict[str, int] = {}
    call_names: dict[str, int] = {}
    for line, value, names in sorted(_function_statements(function), key=lambda s: s[0]):
        if isinstance(value, ast.Constant):
            continue
        if _text_kinds(value, readers, data_readers, data_names)[0]:
            data_names.update({name: data_names.get(name, line) for name in names})
        if _has_target_call(value, readers, {*data_names, *call_names}) or any(
                isinstance(n, ast.Name) and n.id in call_names for n in ast.walk(value)):
            call_names.update({name: call_names.get(name, line) for name in names})
    return data_names, call_names


def _assert_leaves(test):
    """The conjunct/disjunct/negated leaves of an assert test."""
    if isinstance(test, ast.BoolOp):
        return [leaf for value in test.values for leaf in _assert_leaves(value)]
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _assert_leaves(test.operand)
    return [test]


def _golden_comparison(leaf, readers, data_readers, data_names, call_names, code_read, line):
    """FA-009c: a comparison (`==`, `!=`, `in`, `not in`, including `len(a) == len(b)`) of packaged DATA text (the golden)
    against the result of a call to target code (the behaviour under test), neither side derived from code text."""
    if not isinstance(leaf, ast.Compare):
        return False
    data_bound = {name for name, bound in data_names.items() if bound < line}
    call_bound = {name for name, bound in call_names.items() if bound < line}
    sides = [leaf.left, *leaf.comparators]
    for left, op, right in zip(sides, leaf.ops, sides[1:]):
        if not isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
            continue
        for golden, behaviour in ((left, right), (right, left)):
            golden_data, golden_code = _text_kinds(golden, readers, data_readers, data_bound)
            behaviour_data, behaviour_code = _text_kinds(behaviour, readers, data_readers, data_bound)
            called = _has_target_call(behaviour, readers, {*data_bound, *call_bound}) or any(
                isinstance(n, ast.Name) and n.id in call_bound for n in ast.walk(behaviour))
            pure = golden_data and not _has_target_call(golden, readers, {*data_bound, *call_bound}) and not any(
                isinstance(n, ast.Name) and n.id in call_bound for n in ast.walk(golden))
            code_names = {n.id for n in (*ast.walk(golden), *ast.walk(behaviour)) if isinstance(n, ast.Name)}
            if pure and called and not golden_code and not behaviour_code and not code_names & code_read:
                return True
    return False


def _drop_golden_comparisons(tree, findings, readers, imported):
    """FA-009c: remove the findings whose assertion compares a packaged DATA golden with the result of a call to target
    code. Every flagged leaf of the assert must be such a comparison; an assertion whose subject is the text itself
    (`'X' in text`, a docstring, a code read) keeps its flag."""
    data_readers = _local_data_readers(tree, readers)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    kept = dict(findings)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or node.lineno not in findings:
            continue
        function = node
        while function is not None and not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = parents.get(function)
        if function is None:
            read, constant, data_names, call_names = {}, {}, {}, {}
        else:
            read, constant = _function_bindings(function, imported, readers)
            data_names, call_names = _value_bindings(function, readers, data_readers)
        code_read = {name for name, line in read.items()
                     if line < node.lineno and name not in data_names and name not in call_names}
        qualifying, flagged_leaves = 0, 0
        for leaf in _assert_leaves(node.test):
            if _golden_comparison(leaf, readers, data_readers, data_names, call_names, code_read, node.lineno):
                qualifying += 1
                continue
            names = {n.id for n in ast.walk(leaf) if isinstance(n, ast.Name)}
            if (SOURCE_TEXT_READERS.search(ast.unparse(leaf)) and PRODUCTION_LOCATIONS.search(ast.unparse(leaf))) or \
                    _calls_reader(leaf, readers) or any(read.get(name, node.lineno) < node.lineno for name in names) or \
                    _constant_text_assertion(leaf, imported, constant):
                flagged_leaves += 1
        if qualifying and not flagged_leaves:
            del kept[node.lineno]
    return kept


def wiring_assertions(source: str):
    """FA-009: assertions that only check production source text, not executed behavior.

    A `<literal> in <production file text>` or an AST-shape assertion proves that a string was
    typed, never that the wiring runs. Reading fixtures or generated runtime files is fine.

    Beyond M7's one-assert form (S11 unit TQ-1, B7; the measured blind spots of TQ-XCUT-PLAN §1 B7), a test function is
    also flagged when (a) an earlier statement reads production source and the assert names a variable bound from that
    read, or (b) the assert applies `.index(`, `.startswith(` or `in` to a module constant named `*_SCRIPT`, `*_SOURCE`
    or `*_TEMPLATE` imported from `codex_harness` (or to a local name bound from one).

    S11 unit FA-009b: a function defined in the same module whose return value is production text (a module `__doc__`,
    `inspect.getsource`/`getdoc`, `ast.get_docstring`, or `read_text`/`read_bytes` of a production location) is a READER;
    an assert on a reader's call result, directly or through a variable bound to it, is flagged like a direct read. One
    level of helper only: a helper that merely calls another reader is not itself a reader.

    S11 unit FA-009c (golden precision, DESIGN-s11 §13): an assertion is NOT structural when it is a comparison (`==`,
    `!=`, `in`, `not in`, `len(a) == len(b)`) one side of which derives from production text read from a packaged DATA
    resource (a data suffix or loader and no code suffix; one level of dataflow) and whose other side derives from a call
    to a target function or method other than a reader. Reads of code/template text, docstrings and an assertion whose
    subject is the text itself keep their classification; so does a data golden compared with no call result.
    """
    tree = ast.parse(source)
    imported = _imports_from_harness(tree)
    readers = _local_readers(tree)
    findings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            text = ast.unparse(node.test)
            if SOURCE_TEXT_READERS.search(text) and PRODUCTION_LOCATIONS.search(text) or \
                    _calls_reader(node.test, readers):
                findings[node.lineno] = text[:120]
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        read, constant = _function_bindings(function, imported, readers)
        for node in ast.walk(function):
            if not isinstance(node, ast.Assert) or node.lineno in findings:
                continue
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            if any(read.get(name, node.lineno) < node.lineno for name in names) or \
                    _constant_text_assertion(node.test, imported, constant):
                findings[node.lineno] = ast.unparse(node.test)[:120]
    return sorted(_drop_golden_comparisons(tree, findings, readers, imported).items())


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


def test_wiring_detector_flags_assertions_on_production_text_read_through_a_local_helper():
    """FA-009b positive controls (RETRO-PROPOSALS row 4): a function defined in the same module whose return value is
    production text (a module `__doc__`, `getsource`/`getdoc`, `ast.get_docstring`, or `read_text`/`read_bytes` of a
    production location) is a reader; an assert on its call result, directly or through a variable bound to it, is
    flagged like a direct read. One level of helper only."""
    positive = (
        "def header(m):\n"
        "    return m.__doc__\n"
        "def test_direct():\n"
        "    assert 'INV-METRIC-001' in header(domain_module)\n"  # 4
        "def test_through_a_variable():\n"
        "    doc = header(domain_module)\n"
        "    assert 'Layer: domain' in doc\n"  # 7
        "def header_lines(m):\n"
        "    return ast.get_docstring(ast.parse(text_of(m)))\n"
        "def source(m):\n"
        "    return inspect.getsource(m)\n"
        "def packaged():\n"
        "    body = (ROOT / 'src/codex_harness/x.py').read_text()\n"
        "    return body\n"
        "def test_other_readers():\n"
        "    assert 'a' in header_lines(m)\n"  # 16
        "    assert 'b' in source(m)\n"  # 17
        "    assert 'c' in packaged()\n")  # 18
    assert [line for line, _ in wiring_assertions(positive)] == [4, 7, 16, 17, 18]


def test_wiring_detector_leaves_non_reader_helpers_alone():
    """FA-009b negative controls: a helper that builds an object, one that returns fixture text, a helper that only
    calls a reader (one level of helper is enough), and a name read in another function."""
    negative = (
        "def build():\n"
        "    return Store()\n"
        "def fixture(tmp_path):\n"
        "    return (tmp_path / 'lease.json').read_text()\n"
        "def header(m):\n"
        "    return m.__doc__\n"
        "def outer(m):\n"
        "    return header(m)\n"
        "def test_a(tmp_path):\n"
        "    assert build().count() == 0\n"
        "    assert 'x' in fixture(tmp_path)\n"
        "    assert 'y' in outer(m)\n"
        "def test_b():\n"
        "    doc = header(m)\n"
        "    return doc\n"
        "def test_c(doc):\n"
        "    assert 'z' in doc\n")
    assert wiring_assertions(negative) == []


def test_the_measured_helper_read_miss_is_flagged():
    """FA-009b expected result 2: `test_s9_batch_l2b2_move.py:118` asserts INV-METRIC-001 on `header(module)` text (the
    miss R-L9b measured, RETRO-PROPOSALS row 4); it must be a flagged line, not only a pinned one."""
    flagged = {line for line, _ in wiring_assertions((TESTS / "test_s9_batch_l2b2_move.py").read_text(encoding="utf-8-sig"))}
    assert 118 in flagged


GOLDEN_FIXTURE = (
    "from importlib.resources import files\n"
    "def load(name):\n"
    "    return load_yaml(files('codex_harness.resources').joinpath(name).read_text())\n"
    "def load_json(name):\n"
    "    return json.loads((ROOT / f'harness_hooks/{name}').read_text())\n"
    "def header(m):\n"
    "    return m.__doc__\n"
    "def test_golden_vs_call():\n"
    "    expected = load('stages.yaml')\n"
    "    assert len(merge(a, b)) == len(expected)\n"  # 10: control 1, not flagged
    "def test_golden_vs_call_through_a_variable():\n"
    "    merged = merge(load('a.yaml'), load('b.yaml'))\n"
    "    expected = load('stages.yaml')\n"
    "    assert merged == expected\n"  # 14: not flagged
    "    assert load_json('x.json')['k'] in merged\n"  # 15: not flagged
    "    assert len(merged) != len(expected) and merged != load_json('x.json')\n"  # 16: not flagged
    "def test_source_text():\n"
    "    text = Path('src/x.py').read_text()\n"
    "    assert 'def f' in text\n"  # 19: control 2, flagged
    "def test_docstring():\n"
    "    doc = header(module)\n"
    "    assert 'INV-1' in doc\n"  # 22: control 3, flagged
    "def test_data_without_a_call():\n"
    "    data = load('k.json')\n"
    "    assert data['k'] == 1\n"  # 25: control 4, flagged
    "    assert data['k'] == len('x')\n"  # 26: builtin call is not a target call, flagged
    "def test_code_text_with_a_call():\n"
    "    text = (ROOT / 'src/codex_harness/x.py').read_text()\n"
    "    assert len(merge(a, b)) == len(text)\n"  # 29: code text, flagged
    "    assert len(merge(a, b)) == len(header(module))\n"  # 30: docstring, flagged
    "    assert merge(a, b) == load('x.py')\n"  # 31: code suffix wins, flagged
    "def test_data_golden_mixed_with_a_source_subject():\n"
    "    expected = load('stages.yaml')\n"
    "    assert len(merge(a, b)) == len(expected) and 'x' in header(module)\n"  # 34: flagged leaf remains
)


def test_wiring_detector_golden_precision_controls():
    """FA-009c controls (DESIGN-s11 §13; the profile's independent-golden rule): a comparison of packaged DATA text with
    the result of a target call is behavioural; a source-text subject, a docstring, a code-suffix read, and a data read
    compared with no call result stay flagged."""
    flagged = [line for line, _ in wiring_assertions(GOLDEN_FIXTURE)]
    assert flagged == [19, 22, 25, 26, 29, 30, 31, 34]
