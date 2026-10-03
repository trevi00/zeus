"""S10 unit C1: the store-free `zeus` roots composed behind `entry.cli.main` (DESIGN-s10 §3 C1).

Parity with M7 is the `entry.cli_storefree` compare family; these tests cover what it cannot: the canary
with a fake runtime (the real one spawns `codex`), the declared transitional refusals, and the import homes.
"""

import ast
import json
import sys
from pathlib import Path

import pytest

from codex_harness.composition import cli as composition
from codex_harness.entry import cli

CLI_DIR = Path(cli.__file__).resolve().parent
ROOTS = ("paths", "setup", "organization", "validate", "canary", "doctor")


def run_main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["zeus", *argv])
    try:
        cli.main()
        code = 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class Probe:
    def __init__(self, passed):
        self.passed = passed

    def probe(self):
        return {"passed": self.passed, "version": "fake", "exit_code": 0 if self.passed else 1}


def test_canary_exit_follows_the_probe(monkeypatch, capsys):
    monkeypatch.setattr(composition, "codex_runtime", lambda: Probe(True))
    code, out, err = run_main(monkeypatch, capsys, "canary")
    assert (code, json.loads(out)["passed"], err) == (0, True, "")
    monkeypatch.setattr(composition, "codex_runtime", lambda: Probe(False))
    code, out, err = run_main(monkeypatch, capsys, "canary")
    assert (code, json.loads(out)["passed"], err) == (1, False, "")


def test_a_root_not_composed_yet_is_a_json_error_with_exit_one(monkeypatch, capsys):
    # C8 moves this example to a still-uncomposed root, or retires it when all 51 are composed.
    code, out, err = run_main(monkeypatch, capsys, "fleet", "pause")
    assert code == 1 and out == ""
    assert json.loads(err) == {"error": "zeus fleet is not composed in the rebuild yet (DESIGN-s10 §3)"}


def test_doctor_without_offline_is_the_c2_refusal(monkeypatch, capsys):
    code, out, err = run_main(monkeypatch, capsys, "doctor")
    assert code == 1 and out == ""
    assert json.loads(err) == {"error": "zeus doctor without --offline is composed in S10 unit C2"}


def imports(module: str) -> set[str]:
    tree = ast.parse((CLI_DIR / f"{module}.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("module", ROOTS)
def test_root_modules_import_only_composition_entry_and_the_standard_library(module):
    found = imports(module)
    product = {name for name in found if name.startswith("codex_harness")}
    assert not any(".adapters" in name for name in product)
    assert all(name.startswith(("codex_harness.composition", "codex_harness.entry.cli")) for name in product)


def test_main_imports_select_repository_from_composition_and_no_adapter():
    found = imports("__init__")
    assert "codex_harness.composition.configuration.select_repository" in found
    assert not any(".adapters" in name for name in found if name.startswith("codex_harness"))
    assert set(composition.__all__) == {"organization", "codex_runtime", "validate_message", "resolve_codex"}
