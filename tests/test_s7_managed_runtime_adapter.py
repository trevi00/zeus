"""S7 pilot 43: the moved managed_runtime adapter's package-path rule, required collaborators and injected processes."""
import subprocess
from pathlib import Path

import pytest

import codex_harness
from codex_harness.delivery.adapters import managed_runtime


def test_launcher_environment_resolves_to_the_directory_above_the_imported_package():
    package = Path(codex_harness.__file__).resolve().parent
    assert managed_runtime.launcher_environment()["PYTHONPATH"] == str(package.parent)


def test_supervise_requires_its_gate_and_launcher():
    with pytest.raises(TypeError):
        managed_runtime.supervise("state", launcher=lambda *a: 0)
    with pytest.raises(TypeError):
        managed_runtime.supervise("state", gate=lambda *a: {})


def test_systemd_target_requires_its_runner():
    with pytest.raises(TypeError):
        managed_runtime.SystemdManagedFleetTarget(processes=object(), configuration=object())


def test_materializer_git_goes_through_the_injected_processes():
    seen = []

    class Processes:
        def run(self, argv, **kwargs):
            seen.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

    managed_runtime.Materializer({"source": "/src"}, processes=Processes())._git("rev-parse", "x")
    assert seen == [(["git", "-C", "/src", "rev-parse", "x"],
                     {"input": None, "capture_output": True, "timeout": managed_runtime.GIT_TIMEOUT})]
