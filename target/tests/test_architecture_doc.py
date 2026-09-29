"""docs/context/ARCHITECTURE.md: CURRENT symbols resolve in the reference, PROPOSED symbols do not
pretend to exist in the target, contract IDs resolve, and the map is linked (S0 exit checks 6, 7)."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "context" / "ARCHITECTURE.md"
REFERENCE_SRC = ROOT / "src"
TARGET_SRC = ROOT / "target" / "src"
CONTRACTS = (ROOT / "docs" / "contracts.md").read_text(encoding="utf-8")


def rows():
    out = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[1] in {"CURRENT", "PROPOSED", "TARGET"}:
            out.append(cells)
    return out


def resolve(src: Path, symbol: str) -> bool:
    module, _, qual = symbol.partition(":")
    base = src.joinpath(*module.split("."))
    path = base.with_suffix(".py") if base.with_suffix(".py").is_file() else base / "__init__.py"
    if not path.is_file():
        return False
    if not qual:
        return True
    scope = ast.parse(path.read_text(encoding="utf-8")).body
    for part in qual.split("."):
        found = next((n for n in scope if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == part), None)
        if found is None:
            return False
        scope = found.body
    return True


def ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


ROWS = rows()


def test_map_has_current_and_proposed_rows_for_every_capability():
    caps = {}
    for cells in ROWS:
        caps.setdefault(cells[0], set()).add(cells[1])
    assert len(caps) == 10 and all({"CURRENT", "PROPOSED"} <= labels for labels in caps.values())


@pytest.mark.parametrize("cells", ROWS, ids=[f"{c[0]}-{c[1]}" for c in ROWS])
def test_symbols_are_labelled_truthfully(cells):
    label = cells[1]
    for symbol in [s for cell in cells[2:5] for s in ticks(cell)]:
        if label == "CURRENT":
            assert resolve(REFERENCE_SRC, symbol), f"CURRENT {symbol} does not resolve in the reference"
        elif label == "PROPOSED":
            assert not resolve(TARGET_SRC, symbol), f"{symbol} exists in the target: relabel it TARGET"
        else:
            assert resolve(TARGET_SRC, symbol), f"TARGET {symbol} does not resolve in target/src"
    for ident in re.findall(r"INV-[A-Z0-9-]+-\d{3}", cells[5]):
        assert ident in CONTRACTS
    for test in ticks(cells[6]):
        path, _, func = test.partition("::")
        assert (ROOT / path).is_file(), test
        if func:
            assert re.search(rf"^def {re.escape(func)}\(", (ROOT / path).read_text(encoding="utf-8"), re.M)


def test_map_is_linked_from_the_index_and_the_design_ssot():
    assert "(ARCHITECTURE.md)" in (ROOT / "docs" / "context" / "README.md").read_text(encoding="utf-8")
    assert "context/ARCHITECTURE.md" in (ROOT / "docs" / "design.md").read_text(encoding="utf-8")


def test_map_is_reference_only_and_has_no_status_column():
    text = DOC.read_text(encoding="utf-8")
    assert "**Reference-only.**" in text and "**Not a status table.**" in text
    assert not re.search(r"^\|[^\n]*\|\s*Status\s*\|", text, re.M)
