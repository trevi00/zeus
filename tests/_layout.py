"""Where the target tree, the repository root and the SOURCE reference trees are (DESIGN-s11 §20.4).

Every test that locates a tree takes the location from here, so the promotion edits only the constants below
(stdlib only; importable from every test, `ported/**` and `conftest.py` included, because pytest puts `tests/`
on `sys.path`).

The promotion moves `target/*` to the repository root and the SOURCE `src/`, `tests/` to `reference/m7/`. It then
sets `REPO = TARGET`, `REFERENCE = REPO / "reference" / "m7"` and `TARGET_PREFIX = ""`.
"""

from pathlib import Path

TESTS = Path(__file__).resolve().parent
TARGET = TESTS.parent  # the target distribution root (pyproject.toml, src/, tests/, scripts/, deploy/)
REPO = TARGET  # the repository root (compare/, coverage/, docs/, .github/, frontend/, AGENTS.md)
REFERENCE = REPO / "reference" / "m7"  # the root of the SOURCE M7 trees the promotion moves: REFERENCE / "src", REFERENCE / "tests"
TARGET_PREFIX = ""  # the target tree as a repo-relative git path prefix ("" after the promotion)
