"""S10 unit T2: the remaining V27 argparse entries (`entry.cli.threshold_replay`, `entry.cli.observed_assets`), DESIGN-s8 section 26.

Both mains run over a fake store and monkeypatched `composition` builders (no database, no adapter); the exit codes and the error JSON shapes
are M7's (0/1/2). `observed_assets` also runs as `python -m` (its `__main__` guard).
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.composition import research_entries, thresholds
from codex_harness.entry.cli import observed_assets, threshold_replay
from codex_harness.kernel.errors import ContractError
from codex_harness.storage.adapters.memory_store import MemoryStore

ENTRIES = Path(threshold_replay.__file__).resolve().parent
REPLAY_ARGS = ["--github-repo", "owner/repo", "--old-value", "3", "--proposed-value", "4",
               "--holdout-boundary", "2026-02-01T00:00:00Z"]


def test_threshold_replay_contract_error_is_exit_2_with_the_invalid_arguments_json(capsys):
    assert threshold_replay.main([*REPLAY_ARGS[:-1], "not-a-time"], store=MemoryStore()) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "Invalid replay arguments", "message": "Invalid holdout boundary"}


def test_threshold_replay_unexpected_failure_is_exit_1_with_the_type_only(capsys, monkeypatch, tmp_path):
    class Broken:
        def transaction(self):
            raise OSError("backend details")

    monkeypatch.setattr(thresholds, "replay_artifacts", lambda path: pytest.fail("artifacts are not reached"))
    assert threshold_replay.main([*REPLAY_ARGS, "--artifacts", str(tmp_path)], store=Broken()) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and json.loads(captured.err) == {"error": "Replay unavailable", "type": "OSError"}


def test_threshold_replay_builds_the_store_through_composition_when_none_is_given(capsys, monkeypatch, tmp_path):
    built = []
    monkeypatch.setattr(thresholds, "replay_store", lambda: built.append("store") or MemoryStore())
    assert threshold_replay.main([*REPLAY_ARGS, "--artifacts", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert built == ["store"] and "events" not in output and output["evidence_ref"]


def test_observed_assets_contract_error_is_exit_2_with_the_contract_error_json(capsys, tmp_path):
    assert observed_assets.main(["audit", str(tmp_path / "missing.json"), "--dry-run"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": "ContractError", "message": "Manifest must be a regular file"}


def test_observed_assets_registration_failures_are_exit_2_and_exit_1(capsys, monkeypatch, tmp_path):
    manifest = tmp_path / "observed.json"
    manifest.write_text(json.dumps([{"path": "notes/a.md", "basis": "observed", "state": "unreviewed_observed_asset",
                                     "sha256": None, "size": 1, "evidence_refs": []}]), encoding="utf-8")

    class Audits:
        def __init__(self, error):
            self.error = error

        def observe_assets(self, audit_id, assets):
            raise self.error

    monkeypatch.setattr(research_entries, "observed_assets_artifacts", lambda path: object())
    for error, code, body in ((ContractError("Unknown audit"), 2, {"error": "ContractError", "message": "Unknown audit"}),
                              (RuntimeError("down"), 1, {"error": "Registration unavailable", "type": "RuntimeError"})):
        monkeypatch.setattr(research_entries, "observed_assets_audits", lambda store, artifacts, error=error: Audits(error))
        assert observed_assets.main(["audit", str(manifest)], store=MemoryStore()) == code
        assert json.loads(capsys.readouterr().err) == body


def test_observed_assets_runs_as_a_module():
    done = subprocess.run([sys.executable, "-m", "codex_harness.entry.cli.observed_assets", "--help"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "observed-asset ledger" in done.stdout


@pytest.mark.parametrize("name", ["threshold_replay", "observed_assets"])
def test_the_entry_imports_no_adapter(name):
    tree = ast.parse((ENTRIES / f"{name}.py").read_text(encoding="utf-8"))
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [module for module in imported if ".adapters" in module], imported
