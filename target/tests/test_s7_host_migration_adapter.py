"""S7 pilot 44: the moved host_migration adapter's package-path rule and required runners (V6)."""
import inspect
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_harness
from codex_harness.delivery.adapters import host_migration


def test_package_dir_is_the_imported_package_directory():
    assert host_migration.PACKAGE_DIR == Path(codex_harness.__file__).resolve().parent


def test_canonical_tool_resolves_like_m7_from_the_package_location(tmp_path, monkeypatch):
    # M7: Path(codex_harness.__file__).resolve().parents[2] / "scripts" / "aibox_data"
    package = tmp_path / "src" / "codex_harness"
    (tmp_path / "scripts" / "aibox_data").mkdir(parents=True)
    (tmp_path / "scripts" / "aibox_data" / "__main__.py").write_text("")
    package.mkdir(parents=True)
    stand_in = SimpleNamespace(__file__=str(package / "__init__.py"))
    m7 = Path(stand_in.__file__).resolve().parents[2] / "scripts" / "aibox_data"
    monkeypatch.setattr(host_migration, "PACKAGE_DIR", package.resolve())
    assert host_migration.canonical_tool() == m7 == tmp_path.resolve() / "scripts" / "aibox_data"


def test_every_process_runner_is_required():
    required = [host_migration.run_canonical, host_migration.pg_compare_schema, host_migration._docker_pg,
                host_migration.pg_dump_database, host_migration.pg_restore_database,
                host_migration.recovery_preconditions, host_migration.SystemdHostTarget.__init__]
    for function in required:
        assert inspect.signature(function).parameters["runner"].default is inspect.Parameter.empty, function


def test_systemd_target_requires_its_runner():
    with pytest.raises(TypeError):
        host_migration.SystemdHostTarget(control_dir="/x")


def test_switch_effect_default_observer_fails_closed_without_a_runner(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    violations = host_migration.recovery_preconditions(control, tmp_path / "managed", runner=None,
                                                       proc=tmp_path / "proc")
    assert any(v.startswith("unit_state_unknown:") for v in violations)


def test_run_canonical_uses_only_the_injected_runner(monkeypatch):
    seen = []

    def runner(argv, **kwargs):
        seen.append((argv[2:], kwargs))
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")

    monkeypatch.setattr(host_migration, "canonical_tool", lambda: Path("/tool"))
    host_migration.run_canonical(["inventory"], runner=runner)
    assert seen == [(["inventory"], {"capture_output": True, "timeout": host_migration.CANONICAL_TIMEOUT})]
