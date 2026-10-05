"""S10 E5c + E5d: the host-migration operator CLI process (`entry.processes.host_migration`, `composition.host_migration_cli`,
`composition.host_migration_evidence_cli`, `composition.canonical_tools`) and the managed runtime's `fleet_gate` and `run_fleet` with the
`supervise` entry branch (R-e5cd, R-e5c-ct, DESIGN-s10 §16).

MemoryStore and monkeypatched builders; no docker, systemd, Redis, PostgreSQL or network."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from _layout import TARGET

from codex_harness import composition
from codex_harness.composition import (
    canonical_tools,
    cli_fleet,
    host_migration_cli,
    host_migration_evidence_cli,
)
from codex_harness.composition import managed_runtime as wiring
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.domain.fleet import FleetRefused
from codex_harness.delivery.adapters.managed_runtime import EXIT_REFUSED
from codex_harness.delivery.domain.host_migration import MigrationRefused
from codex_harness.entry.processes import host_migration as cli
from codex_harness.entry.processes import managed_runtime as entry
from codex_harness.routing.adapters.organization_source import packaged_organization
from codex_harness.storage.adapters.memory_store import MemoryStore

DIGEST = "d" * 64


@pytest.fixture
def service(monkeypatch):
    handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
    monkeypatch.setattr(composition, "build", lambda: handle)
    return handle


def config_for(tmp_path) -> dict:
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": "a", "team": "team-a", "repository": str(tmp_path / "a" / "repo"), "schema": "lane_a",
                       "redis_namespace": "ns-a", "runtime": str(tmp_path / "a" / "runtime")}]}


def test_fleet_gate_of_an_unregistered_fleet_refuses(service):
    with pytest.raises(FleetRefused) as refused:
        wiring.fleet_gate("managed-fleet", DIGEST)
    assert refused.value.reason_code == "unregistered"


def test_fleet_gate_commits_the_pause_and_reports_settled_debt_of_the_host_store(service, tmp_path):
    (tmp_path / "a" / "repo").mkdir(parents=True)
    FleetRegistry(service.store).register(config_for(tmp_path))
    verdict = wiring.fleet_gate("managed-fleet", DIGEST)
    assert verdict == {"paused": True, "hold": True, "reserving": [], "units_held": [], "settled": True}


def test_supervise_with_the_fleet_gate_refuses_a_state_dir_without_a_launch_request(tmp_path, capsys):
    assert entry.main(["supervise", "--state-dir", str(tmp_path)]) == EXIT_REFUSED
    assert capsys.readouterr().out == ""


def test_the_supervise_branch_passes_the_composition_fleet_gate(monkeypatch):
    seen = {}
    monkeypatch.setattr(entry, "supervise", lambda state_dir, *, gate: seen.update(state=state_dir, gate=gate) or 7)
    assert entry.main(["supervise", "--state-dir", "/state"]) == 7
    assert seen == {"state": "/state", "gate": wiring.fleet_gate}


def test_run_fleet_calls_the_fleet_cli_runner_with_once_false_and_the_control(monkeypatch, service):
    calls = []
    monkeypatch.setattr(cli_fleet, "run_fleet",
                        lambda handle, args, *, control=None: calls.append((handle, args, control)) or {"ticks": 1})
    control = object()
    assert wiring.run_fleet(control) == {"ticks": 1}
    [(handle, args, passed)] = calls
    assert handle is service and passed is control
    assert args == argparse.Namespace(once=False)


def test_the_fleet_workload_of_entry_runs_run_fleet_with_the_runtime_control(monkeypatch, tmp_path):
    from codex_harness.delivery.adapters.managed_runtime import RuntimeControl
    from codex_harness.delivery.domain.managed_runtime import WORKLOADS

    assert "fleet" in WORKLOADS
    descriptor = {"sentinel": True}
    monkeypatch.setattr(wiring, "validate_descriptor", lambda document: document)
    monkeypatch.setattr(wiring, "_read_json", lambda path: descriptor)
    monkeypatch.setattr(wiring, "_effective", lambda: ("image", "profile"))
    monkeypatch.setattr(wiring.host_delivery, "startup_receipt",
                        lambda document, *, image, profile_digest: {"descriptor_sha256": DIGEST})
    monkeypatch.setattr(wiring, "_write_json", lambda path, document: None)
    seen = []
    monkeypatch.setattr(wiring, "run_fleet", lambda control: seen.append(control))
    assert wiring.entry(str(tmp_path), "fleet") == 0
    [control] = seen
    assert isinstance(control, RuntimeControl) and control.activation() == DIGEST


def test_the_entry_module_has_no_unimplemented_carry():
    import inspect

    assert "NotImplementedError" not in inspect.getsource(entry)
    assert "NotImplementedError" not in inspect.getsource(wiring)


# ----- E5c: the host-migration CLI process -------------------------------------------------------------------------------------------

M7_SOURCE = Path("/home/trevi/workspaces/zeus/scratch/m7-source-e38aa722/src")


def subcommands(parser) -> list:
    return sorted(next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction)).choices)


@pytest.mark.skipif(not M7_SOURCE.is_dir(), reason="the M7 SOURCE checkout is not on this host")
def test_the_parser_subcommands_equal_m7s_read_from_source_in_a_subprocess():
    code = ("from codex_harness.adapters.host_migration import parser\nimport argparse, json\n"
            "p = parser()\nprint(json.dumps(sorted(next(a for a in p._actions if isinstance(a, argparse._SubParsersAction)).choices)))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                          env={"PYTHONPATH": str(M7_SOURCE), "PATH": "/usr/bin:/bin"})
    assert done.returncode == 0, done.stderr[-400:]
    assert json.loads(done.stdout) == subcommands(cli.parser())


def test_main_prints_a_refusal_as_json_and_exits_1(monkeypatch, capsys):
    def refuse(args):
        raise MigrationRefused("layout_conflict", "root")

    monkeypatch.setattr(cli, "execute", refuse)
    assert cli.main(["prepare-layout", "--root", "/x"]) == 1
    assert json.loads(capsys.readouterr().out) == {"refused": "layout_conflict", "field": "root"}


def test_main_exits_1_for_a_result_that_is_not_ok(monkeypatch, capsys):
    monkeypatch.setattr(cli, "execute", lambda args: ({"x": 1}, False))
    assert cli.main(["prepare-layout", "--root", "/x"]) == 1
    assert json.loads(capsys.readouterr().out) == {"x": 1}


def test_env_missing_is_refused_by_name(monkeypatch):
    monkeypatch.delenv("E5CD_MISSING_DSN", raising=False)
    with pytest.raises(MigrationRefused) as refused:
        host_migration_cli._env("E5CD_MISSING_DSN")
    assert (refused.value.reason_code, refused.value.field) == ("environment_missing", "E5CD_MISSING_DSN")


def test_prepare_layout_runs_through_main_and_the_module_guard(tmp_path):
    done = subprocess.run([sys.executable, "-m", "codex_harness.entry.processes.host_migration", "prepare-layout",
                           "--root", str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    assert json.loads(done.stdout)["applied"] is False


def test_the_module_help_exits_0():
    done = subprocess.run([sys.executable, "-m", "codex_harness.entry.processes.host_migration", "--help"],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "prepare-layout" in done.stdout


def test_observe_command_refuses_a_bad_request_before_any_read_with_ports_injected(monkeypatch):
    def forbidden(args):
        raise AssertionError("cli_ports must not be called")

    monkeypatch.setattr(host_migration_evidence_cli, "cli_ports", forbidden)
    args = argparse.Namespace(migration_id="bad id!", expected_id="x", target_id="t", plan_id="p", actor="a",
                              root="relative", config_file=None, post_transition=False, expect=None)
    with pytest.raises(MigrationRefused):
        host_migration_evidence_cli.observe_command(args, ports=object())


def test_cli_ports_refuses_an_invalid_env_name_without_echoing_the_value(monkeypatch):
    secret = "postgresql://user:hunter2" "@db/zeus"
    args = argparse.Namespace(schema="migration", control_schema="control", dsn_env=secret,
                              control_dsn_env="HARNESS_DATABASE_URL", lane=None)
    with pytest.raises(MigrationRefused) as refused:
        host_migration_evidence_cli.cli_ports(args)
    assert (refused.value.reason_code, refused.value.field) == ("environment_name_invalid", "dsn_env")
    assert "hunter2" not in repr(refused.value) and "hunter2" not in str(refused.value)


# ----- R-e5c-ct: canonical_module -----------------------------------------------------------------------------------------------------
def tool_contracts():
    spec = importlib.util.spec_from_file_location("e5cd_aibox_contracts", TARGET / "scripts" / "aibox_data" / "contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entries", [
    [],
    [("1-0", {"a": "1"}), ("2-0", {"b": "2", "c": "3"})],
    [("1-0", {"k": "h\u00e9llo \u4e16\u754c"})],
    [("1-0", {"b": "2", "a": "1"}), ("1-1", {"a": "1", "b": "2"})],
    [("1-0", [("z", "9"), ("a", "8")])],
])
def test_canonical_module_contracts_digest_equals_the_tools(entries):
    assert canonical_tools.canonical_module("contracts").stream_entries_sha256(entries) == \
        tool_contracts().stream_entries_sha256(entries)


def test_canonical_module_refuses_any_other_name():
    with pytest.raises(MigrationRefused) as refused:
        canonical_tools.canonical_module("mapping")
    assert refused.value.reason_code == "canonical_tool_unavailable"


def test_canonical_tools_has_no_dynamic_import():
    tree = ast.parse(Path(canonical_tools.__file__).read_text(encoding="utf-8"))
    names = {getattr(node.func, "attr", getattr(node.func, "id", "")) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not names & {"import_module", "__import__"}
