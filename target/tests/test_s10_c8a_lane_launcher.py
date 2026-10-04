"""S10 unit C8a: the lane launcher's injected ports and their `composition.fleet` bindings (R-c16, GAP #3).

The M7 behavior is the ported `test_fleet_runtime`, `test_background_processes` and `test_subscription_accounting`
tests; these cover what they cannot: an unwired port refuses before any effect, and the bindings are the production
objects. Nothing is spawned: the spawn is a recording fake.
"""
import ast
import subprocess
from pathlib import Path

import pytest
import test_architecture

from codex_harness.composition import fleet
from codex_harness.coordination.adapters import fleet_runtime
from codex_harness.execution.adapters.call_budget import CallBudget
from codex_harness.execution.adapters.containers import owned_container
from codex_harness.host_os.adapters.process_groups import no_console_kwargs
from codex_harness.kernel.errors import ContractError


def lane(tmp_path):
    return {"id": "a", "repository": str(tmp_path), "schema": "lane_a", "runtime": str(tmp_path / "rt"),
            "redis_namespace": "fleet-a"}


def test_lane_environment_without_a_loader_refuses(tmp_path):
    with pytest.raises(ContractError, match="Lane isolation is not wired"):
        fleet_runtime.lane_environment(lane(tmp_path), {}, base={})


def test_launch_without_a_spawn_refuses_before_any_effect(tmp_path):
    launcher = fleet_runtime.LaneLauncher({"lanes": [lane(tmp_path)]}, {}, budget=object(), load_isolation=lambda host: {})
    with pytest.raises(ContractError, match="Lane spawn is not wired"):
        launcher.launch({"id": "op-1", "lane": "a", "manifest": {}})
    assert not (tmp_path / "rt").exists()


def test_budget_exhausted_without_a_budget_refuses(tmp_path):
    launcher = fleet_runtime.LaneLauncher({"lanes": [lane(tmp_path)]}, {})
    with pytest.raises(ContractError, match="Call budget is not wired"):
        launcher.budget_exhausted({"per_host": 1, "total": 1})


def test_composition_binds_the_production_objects(tmp_path, monkeypatch):
    launcher = fleet.lane_launcher({"lanes": [lane(tmp_path)]}, {})
    assert launcher.load_isolation is owned_container.load_host_isolation
    assert isinstance(launcher.budget, CallBudget) and launcher.popen is fleet.lane_popen
    own = object()
    assert fleet.lane_launcher({"lanes": []}, {}, budget=own).budget is own
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs)) or "child")
    assert fleet.lane_popen(["zeus"], cwd="x", stdin=subprocess.DEVNULL) == "child"
    assert calls == [(["zeus"], {"cwd": "x", "stdin": subprocess.DEVNULL, **no_console_kwargs(process_group=True)})]
    # the composition environment binding hands the host loader to the moved function
    monkeypatch.setattr(owned_container, "load_host_isolation", lambda host: None)
    with pytest.raises(fleet_runtime.LaunchRefused, match="isolation_required"):
        fleet.lane_environment(lane(tmp_path), {}, base={})


def test_fleet_runtime_imports_stay_inside_its_allowed_edges():
    imports = {node.module for node in ast.walk(ast.parse(Path(fleet_runtime.__file__).read_text(encoding="utf-8")))
               if isinstance(node, ast.ImportFrom) and node.module}
    assert not [name for name in imports if ".execution." in name or ".host_os.adapters" in name]
    assert "codex_harness.coordination.domain.fleet" in imports
    test_architecture.test_target_tree_has_no_violation_and_no_exception()  # the tree-wide rule
