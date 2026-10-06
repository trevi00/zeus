"""S10 unit C2a: `composition.build()` and the store roots init-db, status, inspect, cancel, release-retry, goal (DESIGN-s10 §3 C2).

Parity with M7 on a disposable PostgreSQL is the `entry.cli_store.pg` compare family; these tests cover the structure it cannot:
the dispatch table, the entry import homes, the frozen service handle and the light composition import.
"""

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness import composition
from codex_harness.entry import cli

CLI_DIR = Path(cli.__file__).resolve().parent
ROOTS = ("paths", "setup", "organization", "validate", "canary", "doctor",
         "init-db", "status", "inspect", "cancel", "release-retry", "goal")


def dispatch_keys() -> list[str]:
    tree = ast.parse((CLI_DIR / "__init__.py").read_text(encoding="utf-8"))
    tables = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "composed" for t in node.targets)]
    assert len(tables) == 1 and isinstance(tables[0].value, ast.Dict)
    return [key.value for key in tables[0].value.keys]


def test_the_dispatch_table_holds_the_twelve_composed_roots():
    assert set(ROOTS) <= set(dispatch_keys())


def test_no_entry_cli_module_imports_an_adapter():
    for path in sorted(CLI_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert ".adapters" not in name and name.split(".")[0] != "psycopg", (path.name, name)


def test_the_service_handle_is_frozen_and_holds_only_store_and_org():
    assert [f.name for f in dataclasses.fields(composition.ServiceHandle)] == ["store", "org"]
    handle = composition.ServiceHandle("store", "org")
    with pytest.raises(dataclasses.FrozenInstanceError):
        handle.store = "other"
    public = {n for n in vars(composition.ServiceHandle) if not n.startswith("_")}
    assert public == {"store", "org"} or public == set()   # no method beyond the two fields


def test_importing_composition_does_not_import_psycopg():
    code = ("import sys, codex_harness.composition, codex_harness.composition.cli; "
            "sys.exit(1 if 'psycopg' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_database_url_refuses_when_unset(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("HARNESS_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Run scripts/setup.py or set HARNESS_DATABASE_URL"):
        composition.database_url()
