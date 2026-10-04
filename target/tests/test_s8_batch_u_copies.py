"""DESIGN-s8 §29.2 copy check (S8 batch U2b): every M7 definition a ported-suite shim still holds as a labelled copy
is AST-equal to the M7 SOURCE definition, modulo import lines.

A copy is allowed only while its owner (an S10-carried suite or CLI module) has no target home; this test pins that the
copy is the SOURCE, not a paraphrase of it. Comments are not part of the AST. Import statements (module level and inside a
function body) are dropped from both sides: a shim imports from the target homes where M7 imported its own modules.

The SOURCE is read with `git show e38aa722:<path>`; the test skips with a named reason if git or that commit is unavailable.
Copies the shims hold at this batch (U2b), listed here so a new copy is a conscious addition:
- `m7_research`: `repository_identity` (M7 `adapters/dge_cli.py`, S10 CLI); `REVISION`, `FixtureBus`, `FixtureExecutor`,
  `connected`, `runner`, `spool_observer`, `partitions_of` (M7 `tests/test_audit_service.py`, S10-carried); `events`
  (M7 `tests/test_threshold_collection.py`, S10-carried).
- `m7_coordination`: none. `ResearchEvidence` is now the production `coordination.adapters.continuation` class (S10 C8b-1, V-c27).
`m7_delivery`'s copies belong to batch U2a and are checked there.
"""
import ast
import subprocess
from pathlib import Path

import pytest

SOURCE_COMMIT = "e38aa722"
PORTED = Path(__file__).resolve().parent / "ported"
REPO = Path(__file__).resolve().parents[2]

# (shim module file, M7 SOURCE path, copied top-level names)
COPIES = [
    ("m7_research.py", "src/codex_harness/adapters/dge_cli.py", ["repository_identity"]),
    ("m7_research.py", "tests/test_audit_service.py",
     ["REVISION", "FixtureBus", "FixtureExecutor", "connected", "runner", "spool_observer", "partitions_of"]),
    ("m7_research.py", "tests/test_threshold_collection.py", ["events"]),
]


def _source(path):
    try:
        done = subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE_COMMIT}:{path}"],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git is unavailable to read M7 SOURCE {SOURCE_COMMIT}: {type(exc).__name__}")
    if done.returncode != 0:
        pytest.skip(f"M7 SOURCE {SOURCE_COMMIT}:{path} is not readable here (git rc {done.returncode})")
    return done.stdout


class _DropImports(ast.NodeTransformer):
    def _block(self, node):
        self.generic_visit(node)
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if statements:
                kept = [s for s in statements if not isinstance(s, (ast.Import, ast.ImportFrom))]
                setattr(node, field, kept or [ast.Pass()])
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = visit_Try = visit_If = visit_With = _block


def _definitions(text):
    """Top-level name -> `ast.dump` of its definition with every import statement removed."""
    found = {}
    for node in ast.parse(text).body:
        node = _DropImports().visit(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = ast.dump(node)
    return found


@pytest.mark.parametrize(("shim", "source_path", "names"), COPIES, ids=[f"{c[0]}:{c[1]}" for c in COPIES])
def test_a_shim_copy_is_ast_equal_to_the_m7_source(shim, source_path, names):
    copy = _definitions((PORTED / shim).read_text(encoding="utf-8"))
    source = _definitions(_source(source_path))
    for name in names:
        assert name in source, f"{name} is not defined at the top level of M7 {source_path}"
        assert name in copy, f"{name} is not defined at the top level of {shim}"
        assert copy[name] == source[name], f"{shim}:{name} differs from M7 {source_path}:{name}"

