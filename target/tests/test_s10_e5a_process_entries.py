"""S10 E5a: the `experience`, `isolated_worker` and `service_entry` process entries and `composition.process_entries` (R-e5a).

Composition functions are monkeypatched; no network, Docker or PostgreSQL is touched. The subprocess cases run only argv forms that
end before any effect (help, bad argv)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys

import pytest

from codex_harness.composition import process_entries
from codex_harness.entry import cli
from codex_harness.entry.processes import experience, service_entry
from codex_harness.entry.processes import isolated_worker_runs as isolated_worker
from codex_harness.host_os.adapters import service_entry as host_service_entry
from codex_harness.kernel.errors import ContractError


def _run(module, *argv):
    return subprocess.run([sys.executable, "-m", f"codex_harness.entry.processes.{module}", *argv],
                          capture_output=True, text=True, timeout=120)


def test_experience_dry_run_calls_preview_only(monkeypatch, capsys):
    seen = {}

    def preview(paths, source, basis, prefix):
        seen["call"] = (paths, source, basis, prefix)
        return {"preview_only": True}

    monkeypatch.setattr(process_entries, "experience_preview", preview)
    monkeypatch.setattr(process_entries, "experience_import", lambda *a: pytest.fail("import called"))
    monkeypatch.setattr(process_entries, "experience_store", lambda: pytest.fail("store built"))
    assert experience.main(["--basis", "observed", "--dry-run", "lessons"]) == 0
    assert json.loads(capsys.readouterr().out) == {"preview_only": True}
    assert seen["call"][1:] == ("harness", {"kind": "observed", "revision": None}, "")


def test_experience_import_uses_store_and_artifacts(monkeypatch, capsys):
    monkeypatch.setattr(process_entries, "experience_store", lambda: "S")
    monkeypatch.setattr(process_entries, "experience_artifacts", lambda path: "A:" + path)
    monkeypatch.setattr(process_entries, "experience_import",
                        lambda paths, source, basis, store, artifacts, prefix: {"got": [store, artifacts]})
    assert experience.main(["--basis", "observed", "lessons"]) == 0
    assert json.loads(capsys.readouterr().out) == {"got": ["S", "A:.runtime/artifacts"]}


def test_experience_contract_error_exits_2(monkeypatch, capsys):
    def refuse(*a):
        raise ContractError("nope")

    monkeypatch.setattr(process_entries, "experience_preview", refuse)
    assert experience.main(["--basis", "observed", "--dry-run", "lessons"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "ContractError", "message": "nope"}


def test_experience_other_exception_exits_1(monkeypatch, capsys):
    def fail(*a):
        raise OSError("x")

    monkeypatch.setattr(process_entries, "experience_preview", fail)
    assert experience.main(["--basis", "observed", "--dry-run", "lessons"]) == 1
    assert json.loads(capsys.readouterr().err) == {"error": "Import unavailable", "type": "OSError"}


def test_isolated_worker_status_concatenates(monkeypatch, capsys):
    monkeypatch.setattr(process_entries, "isolated_worker_status", lambda roots: [{"r": r} for r in roots])
    assert isolated_worker.main(["status", "d1", "d2"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"r": "d1"}, {"r": "d2"}]


def test_isolated_worker_reconcile_prints(monkeypatch, capsys):
    monkeypatch.setattr(process_entries, "isolated_worker_reconcile", lambda root: {"reconciled": root})
    assert isolated_worker.main(["reconcile", "d"]) == 0
    assert json.loads(capsys.readouterr().out) == {"reconciled": "d"}


@pytest.mark.parametrize("argv", [[], ["status"], ["reconcile"], ["reconcile", "a", "b"], ["other", "a"]])
def test_isolated_worker_bad_argv_exits_2(argv):
    with pytest.raises(SystemExit) as raised:
        isolated_worker.main(argv)
    assert raised.value.code == 2


def test_service_entry_injects_entry_cli_main(monkeypatch):
    seen = {}

    def fake(argv, *, cli_main):
        seen.update(argv=argv, cli_main=cli_main)
        return 7

    monkeypatch.setattr(process_entries, "service_entry_main", fake)
    assert service_entry.main(["x"]) == 7
    assert seen == {"argv": ["x"], "cli_main": cli.main}


def test_service_entry_bad_argv_prints_usage(capsys):
    assert service_entry.main(["--help"]) == host_service_entry.EXIT_DIAGNOSTICS_FAILED
    assert capsys.readouterr().err == host_service_entry.USAGE + "\n"


def test_composition_service_entry_delegates(monkeypatch):
    monkeypatch.setattr(host_service_entry, "main", lambda argv, *, cli_main: (argv, cli_main))
    assert process_entries.service_entry_main(["a"], cli_main="c") == (["a"], "c")


def test_subprocess_experience_help_exits_0():
    done = _run("experience", "--help")
    assert done.returncode == 0 and "--basis" in done.stdout


def test_subprocess_isolated_worker_no_argument_exits_2():
    assert _run("isolated_worker_runs").returncode == 2


def test_subprocess_isolated_worker_status_empty_root(tmp_path):
    done = _run("isolated_worker_runs", "status", str(tmp_path))
    assert (done.returncode, json.loads(done.stdout)) == (0, [])


def test_subprocess_service_entry_bad_argv_exits_125():
    done = _run("service_entry", "--help")
    assert done.returncode == host_service_entry.EXIT_DIAGNOSTICS_FAILED
    assert done.stderr.strip() == host_service_entry.USAGE


@pytest.mark.parametrize("name", ["experience", "service_entry"])
def test_no_module_at_the_m7_dotted_path(name):
    assert importlib.util.find_spec(f"codex_harness.adapters.{name}") is None


def test_isolated_worker_has_no_main_at_the_m7_path():
    assert importlib.util.find_spec("codex_harness.adapters.isolated_worker") is None
