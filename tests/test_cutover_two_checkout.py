"""Cutover G2-W1: the suite passes the incumbent controller's two-checkout evaluation without weakening R-O.

The controller runs the INCUMBENT tests (checkout A) against the CANDIDATE package (checkout B, editable-installed,
the pytest cwd) with `-c A/pyproject.toml --import-mode=importlib` and `PYTHONPATH=A/tests`. Sources of the expected
results: the g2 critique #4 (ported helper imports under importlib) and #5 (a trusted audit root that does not come
from the import system), and the R-O contract (REBUILD-DESIGN-v2 §5.2): the audit refuses every other origin.

Behavioural: the anchor table drives `audit_root` with injected inputs; the miniature runs a real pytest subprocess
over a small copy of A against this checkout as B, and each negative control applies the mutation its name states.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import provider_guard
import pytest
from _audit_root import audit_root
from _layout import TARGET

DEFAULT = Path("/x/tests-tree/src")
CWD = Path("/x/canary-7")
PYPROJECT = '[project]\nname = "zeus-harness"\n'


def editable(url: str) -> dict:
    return {"url": url, "dir_info": {"editable": True}}


@pytest.mark.parametrize(
    ("direct_url", "pyproject", "expected"),
    [
        (editable("file:///x/canary-7/src"), PYPROJECT, CWD / "src"),
        (editable("file:///x/canary-7"), PYPROJECT, CWD / "src"),
        (editable("file:///x/canary-7/reference/m7/src"), PYPROJECT, DEFAULT),
        ({"url": "file:///x/canary-7/src", "dir_info": {}}, PYPROJECT, DEFAULT),
        ({"url": "file:///x/canary-7.whl", "archive_info": {"hash": "sha256=0"}}, PYPROJECT, DEFAULT),
        (editable("file:///x/canary-8/src"), PYPROJECT, DEFAULT),
        (editable("file:///x/canary-7/src"), '[project]\nname = "another"\n', DEFAULT),
        (editable("file:///x/canary-7/src"), None, DEFAULT),
        (editable("https://example.invalid/x/canary-7/src"), PYPROJECT, DEFAULT),
        (None, PYPROJECT, DEFAULT),
    ],
    ids=["editable-src", "editable-project-dir", "reference-tree", "not-editable", "wheel", "third-directory",
         "other-project", "no-pyproject", "non-file-url", "missing-direct-url"],
)
def test_audit_root_anchor_table(direct_url, pyproject, expected):
    assert audit_root(direct_url, CWD, pyproject, DEFAULT) == expected


def test_audit_root_refuses_a_checkout_under_a_reference_path():
    cwd = Path("/x/reference/m7")
    assert audit_root(editable("file:///x/reference/m7/src"), cwd, PYPROJECT, DEFAULT) == DEFAULT


# --- the miniature two-checkout run -------------------------------------------------------------------------------

REAL_TEST = "test_s7_relocations.py"
PORTED_TEST = "test_pipeline.py"  # imports `ported_support`, a sibling helper
PORTED_LINE = "sys.path.insert(0, str(TESTS / \"ported\"))\n"


def copy_checkout_a(root: Path) -> Path:
    """A = the tests' tree reduced to what the session imports: both conftests, `_layout`, `_audit_root`, the helpers,
    two test files, the guard and harness modules, the root pyproject and a copy of `src/codex_harness` (the ported
    conftest attests a copy of its own tree's package; A's `src` is never on `sys.path`, so A's package is never loaded)."""
    a = root / "evaluator-1"
    (a / "tests" / "ported").mkdir(parents=True)
    for name in ("conftest.py", "_layout.py", "_audit_root.py", REAL_TEST):
        shutil.copy2(TARGET / "tests" / name, a / "tests" / name)
    for name in ("conftest.py", "ported_support.py", PORTED_TEST):
        shutil.copy2(TARGET / "tests" / "ported" / name, a / "tests" / "ported" / name)
    for part in ("guard", "harness"):
        shutil.copytree(TARGET / "compare" / part, a / "compare" / part, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(TARGET / "src" / "codex_harness", a / "src" / "codex_harness",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(TARGET / "pyproject.toml", a / "pyproject.toml")
    return a


def run_incumbent(a: Path, root: Path, *, extra_pythonpath: Path | None = None):
    """The controller's incumbent run: cwd = B (this checkout), PYTHONPATH = A/tests, importlib mode."""
    pythonpath = str(a / "tests")
    if extra_pythonpath is not None:
        pythonpath = str(extra_pythonpath) + ":" + pythonpath
    env = provider_guard.child_environment(root / "child", extra={"PYTHONPATH": pythonpath})
    argv = [sys.executable, "-m", "pytest", str(a / "tests" / REAL_TEST), str(a / "tests" / "ported" / PORTED_TEST),
            "-c", str(a / "pyproject.toml"), "--import-mode=importlib", "-q", "-p", "no:cacheprovider",
            f"--basetemp={root / 'bt'}"]
    return subprocess.run(argv, cwd=TARGET, env=env, capture_output=True, text=True, timeout=540)


def tail(result) -> str:
    return (result.stdout + result.stderr)[-3000:]


@pytest.fixture
def checkout_a(tmp_path):
    return copy_checkout_a(tmp_path)


def test_two_checkout_run_passes(checkout_a, tmp_path):
    result = run_incumbent(checkout_a, tmp_path)
    assert result.returncode == 0, tail(result)
    assert re.search(r"\b\d+ passed\b", result.stdout), tail(result)


def test_control_shadowing_path_entry_resolves_codex_harness_outside_b_src_and_fails_with_r_o(checkout_a, tmp_path):
    """Mutation: a rogue `codex_harness` package earlier on the path, outside B's `src`."""
    rogue = tmp_path / "rogue"
    (rogue / "codex_harness").mkdir(parents=True)
    (rogue / "codex_harness" / "__init__.py").write_text("")
    result = run_incumbent(checkout_a, tmp_path, extra_pythonpath=rogue)
    assert result.returncode != 0, tail(result)
    assert "R-O" in result.stdout + result.stderr, tail(result)


def test_control_without_the_ported_path_line_fails_collection_on_ported_support(checkout_a, tmp_path):
    """Mutation: A's `tests/conftest.py` with the `sys.path.insert(0, ... "ported")` line removed."""
    conftest = checkout_a / "tests" / "conftest.py"
    text = conftest.read_text(encoding="utf-8")
    assert PORTED_LINE in text
    conftest.write_text(text.replace(PORTED_LINE, ""), encoding="utf-8")
    result = run_incumbent(checkout_a, tmp_path)
    assert result.returncode != 0, tail(result)
    assert "No module named 'ported_support'" in result.stdout + result.stderr, tail(result)
