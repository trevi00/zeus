"""Lane launcher and `zeus fleet` wiring (INV-FLEET-001). The child here is a real subprocess of a
labeled stub script, never `zeus operate run`; PostgreSQL connections are injected fakes."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg.conninfo import conninfo_to_dict

from codex_harness import cli
from codex_harness.adapters import fleet_cli, fleet_runtime
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet, LaunchRefused
from codex_harness.application.service import Harness
from codex_harness.bootstrap import organization
from codex_harness.domain.fleet import FleetRefused

CANARY = "CANARY-must-never-be-emitted"
ISOLATION = {"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "0" * 64,
             "HARNESS_DATABASE_URL": "postgresql://harness:secret@127.0.0.1:55432/harness"}
STUB = """import json, os, sys
directory = os.path.dirname(sys.argv[sys.argv.index('--file') + 1])
with open(os.path.join(directory, 'seen.json'), 'w', encoding='utf-8') as stream:
    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'env': {k: v for k, v in os.environ.items() if k.startswith(('ZEUS_', 'HARNESS_'))}}, stream)
print('stdout-marker')
sys.exit(int(os.environ.get('STUB_EXIT', '0')))
"""


def repository(tmp_path, name="repo"):
    root = tmp_path / name
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "GOAL.md").write_bytes(b"# goal\n")
    for argv in (["init", "-q", "-b", "main"], ["add", "--all"],
                 ["-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m", "goal"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    return root, subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def config(tmp_path):
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1, "budget": {"per_host": 2, "total": 4},
            "lanes": [{"id": "a", "team": "alpha", "repository": str((tmp_path / "repo").resolve()), "schema": "lane_a",
                       "redis_namespace": "fleet-a", "runtime": str((tmp_path / "rt-a").resolve())}]}


def manifest(head):
    import hashlib
    return {"schema": "urn:zeus:operation:1", "id": "op-1", "base_revision": head,
            "goal": {"path": "docs/GOAL.md", "sha256": hashlib.sha256(b"# goal\n").hexdigest(), "criterion": "c", "rationale": CANARY},
            "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": ["docs/RUNBOOK.md"]},
            "budget": {"per_host": 2, "total": 4},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.5}}


class FakeConnection:
    """Injected PostgreSQL stand-in: answers current_schema and the operations row (fixture)."""

    def __init__(self, schema, rows, provisioned=True, fail=None):
        self.schema, self.rows, self.provisioned, self.fail = schema, rows, provisioned, fail
        self.queries = []

    def __call__(self, dsn, connect_timeout=None):
        assert "search_path=" + self.schema in dsn or self.fail
        if self.fail:
            raise self.fail
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.queries.append(sql)
        if "current_schema" in sql:
            return SimpleNamespace(fetchone=lambda: (self.schema,))
        if "to_regclass" in sql:
            return SimpleNamespace(fetchone=lambda: ("documents" if self.provisioned else None,))
        assert "bucket='operations'" in sql and params == ("op-1",)
        row = self.rows.get(params[0])
        return SimpleNamespace(fetchone=lambda: (row,) if row is not None else None)


def test_lane_environment_sets_both_prefixes_and_requires_isolation(tmp_path):
    lane = config(tmp_path)["lanes"][0]
    env = fleet_runtime.lane_environment(lane, {**ISOLATION, "ZEUS_CLAUDE_EXECUTABLE": "claude"}, base={"PATH": "p"})
    parts = conninfo_to_dict(env["ZEUS_DATABASE_URL"])
    assert parts["options"] == "-c search_path=lane_a" and parts["password"] == "secret" and parts["dbname"] == "harness"
    for key in ("REPOSITORY", "RUNTIME_DIR", "REDIS_NAMESPACE", "DATABASE_URL"):
        assert env["ZEUS_" + key] == env["HARNESS_" + key]
    assert env["ZEUS_REPOSITORY"] == lane["repository"] and env["ZEUS_REDIS_NAMESPACE"] == "fleet-a"
    assert env["PATH"] == "p" and env["ZEUS_CLAUDE_EXECUTABLE"] == "claude" and env["ZEUS_WORKER_ISOLATION"] == "docker"
    with pytest.raises(LaunchRefused, match="isolation_required"):
        fleet_runtime.lane_environment(lane, {"HARNESS_DATABASE_URL": "postgresql://x"}, base={})
    with pytest.raises(LaunchRefused, match="database_url_missing"):
        fleet_runtime.lane_environment(lane, {k: v for k, v in ISOLATION.items() if k != "HARNESS_DATABASE_URL"}, base={})
    with pytest.raises(FleetRefused, match="isolation_config_invalid"):
        fleet_runtime.LaneLauncher(config(tmp_path), {**ISOLATION, "ZEUS_WORKER_ISOLATION": "host"}, environ={}).launch(
            {"id": "op-1", "lane": "a", "manifest": {}, "operation_id": "op-1"})
    good = FakeConnection("lane_a", {})
    fleet_runtime.verify_lane_schema("search_path=lane_a", "lane_a", good)
    with pytest.raises(LaunchRefused, match="lane_schema_mismatch"):
        fleet_runtime.verify_lane_schema("search_path=public", "lane_b", FakeConnection("public", {}))
    with pytest.raises(LaunchRefused, match="lane_schema_unprovisioned"):
        fleet_runtime.verify_lane_schema("search_path=lane_a", "lane_a", FakeConnection("lane_a", {}, provisioned=False))
    with pytest.raises(LaunchRefused, match="lane_unavailable"):
        fleet_runtime.verify_lane_schema("x", "lane_a", FakeConnection("lane_a", {}, fail=OSError("down")))
    assert fleet_runtime.read_receipt("x", "lane_a", "op-1", FakeConnection("lane_a", {}, fail=OSError("down"))) == (None, "OSError")


def test_launcher_spawns_real_child_in_lane_environment_and_reads_exact_receipt(tmp_path, monkeypatch):
    root, head = repository(tmp_path)
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    cfg = config(tmp_path)
    job = {"id": "op-1", "operation_id": "op-1", "lane": "a", "manifest": manifest(head), "manifest_sha256": "m" * 64,
           "status": "dispatching", "owner_token": "t"}
    receipt = {"id": "op-1", "manifest_sha256": "m" * 64, "status": "accepted", "reason_code": "lead_accepted",
               "calls": {"reserved": 2, "settled": 2, "slots": []}}
    connection = FakeConnection("lane_a", {"op-1": receipt})
    budget = SimpleNamespace(counts=lambda: {"this_host": 1, "all_hosts": 3})
    launcher = fleet_runtime.LaneLauncher(cfg, ISOLATION, argv=(sys.executable, str(stub)), connect=connection,
                                          budget=budget, environ={**os.environ, "STUB_EXIT": "0"})
    assert launcher.budget_exhausted({"per_host": 2, "total": 4}) is False
    assert launcher.budget_exhausted({"per_host": 1, "total": 4}) is True
    handle = launcher.launch(job)
    assert handle["job_id"] == "op-1" and launcher.wait([handle], 30) == [handle]
    outcome = launcher.outcome(handle, job)
    assert outcome == {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
                       "calls": {"reserved": 2, "settled": 2}, "operation_status": "accepted"}
    directory = Path(cfg["lanes"][0]["runtime"]) / "fleet" / "op-1"
    seen = json.loads((directory / "seen.json").read_text("utf-8"))
    assert seen["argv"] == ["--repository", str(root.resolve()), "operate", "run", "--file", str(directory / "operation.json")]
    assert Path(seen["cwd"]).resolve() == root.resolve()
    assert seen["env"]["ZEUS_RUNTIME_DIR"] == seen["env"]["HARNESS_RUNTIME_DIR"] == cfg["lanes"][0]["runtime"]
    assert "search_path=lane_a" in seen["env"]["HARNESS_DATABASE_URL"] and seen["env"]["ZEUS_REDIS_NAMESPACE"] == "fleet-a"
    assert json.loads((directory / "operation.json").read_text("utf-8")) == manifest(head)
    assert (directory / "stdout.log").read_text("utf-8").strip() == "stdout-marker"
    # Nonzero exit with no lane row: the child refused before claiming; a definite failure.
    launcher.connect = FakeConnection("lane_a", {})
    launcher.environ = {**os.environ, "STUB_EXIT": "3"}
    handle = launcher.launch(job)
    launcher.wait([handle], 30)
    assert launcher.outcome(handle, job) == {"status": "failed", "reason_code": "child_refused", "exit_code": 3,
                                             "calls": {"reserved": None, "settled": None}, "operation_status": None}
    # A missing executable never leaves a process behind: a definite pre-spawn refusal.
    launcher.argv = (str(tmp_path / "absent-interpreter"),)
    with pytest.raises(LaunchRefused, match="spawn_failed"):
        launcher.launch(job)


def test_cli_register_enqueue_status_and_refusals_are_redacted(tmp_path, monkeypatch):
    root, head = repository(tmp_path)
    svc = Harness(MemoryStore(), organization())
    outputs = []
    monkeypatch.setattr(cli, "emit", outputs.append)
    for name in ("build_executor", "build_observer"):
        monkeypatch.setattr("codex_harness.bootstrap." + name, lambda *a, **k: pytest.fail(name + " built by fleet"))
    fleet_file, op_file = tmp_path / "fleet.json", tmp_path / "op.json"
    fleet_file.write_text(json.dumps(config(tmp_path)), encoding="utf-8")
    op_file.write_text(json.dumps(manifest(head)), encoding="utf-8")
    cli.fleet_command(svc, cli.parser().parse_args(["fleet", "register", "--file", str(fleet_file)]))
    assert outputs[-1]["registered"] is True and outputs[-1]["exit_code"] == 0 and str(tmp_path) not in json.dumps(outputs)
    cli.fleet_command(svc, cli.parser().parse_args(["fleet", "enqueue", "--lane", "a", "--file", str(op_file)]))
    assert outputs[-1]["job"]["status"] == "queued" and outputs[-1]["job"]["goal"]["base_revision"] == head
    cli.fleet_command(svc, cli.parser().parse_args(["fleet", "pause"]))
    cli.fleet_command(svc, cli.parser().parse_args(["fleet", "status"]))
    assert outputs[-1]["paused"] is True and outputs[-1]["reconciliation_required"] == [] and outputs[-1]["jobs"][0]["id"] == "op-1"
    cli.fleet_command(svc, cli.parser().parse_args(["fleet", "resume"]))
    assert outputs[-1]["paused"] is False and outputs[-1]["budget"] == {"per_host": 2, "total": 4}
    # The operator grant: refused while op-1 is queued, granted on an idle fleet, visible in status.
    grant = ["fleet", "authorize-budget", "--per-host", "3", "--total", "6", "--expected-total", "4"]
    with pytest.raises(SystemExit):
        cli.fleet_command(svc, cli.parser().parse_args(grant))
    assert outputs[-1] == {"status": "refused", "reason_code": "fleet_not_idle", "error_type": "FleetRefused", "exit_code": 1}
    idle = Harness(MemoryStore(), organization())
    cli.fleet_command(idle, cli.parser().parse_args(["fleet", "register", "--file", str(fleet_file)]))
    cli.fleet_command(idle, cli.parser().parse_args(grant))
    assert outputs[-1]["granted"] is True and outputs[-1]["budget"] == {"per_host": 3, "total": 6} and outputs[-1]["exit_code"] == 0
    cli.fleet_command(idle, cli.parser().parse_args(["fleet", "status"]))
    assert outputs[-1]["budget"] == {"per_host": 3, "total": 6} and outputs[-1]["paused"] is False
    with pytest.raises(SystemExit):
        cli.fleet_command(idle, cli.parser().parse_args(["fleet", "enqueue", "--lane", "a", "--file", str(op_file)]))
    assert outputs[-1]["reason_code"] == "budget_mismatch"
    assert cli.parser().parse_args(["fleet", "run", "--once"]).once is True
    assert cli.parser().parse_args(["fleet", "enqueue", "--lane", "a", "--file", "x", "--after", "j1", "--after", "j2"]).after == ["j1", "j2"]
    assert CANARY not in json.dumps(outputs)
    unresolved = config(tmp_path)
    unresolved["lanes"][0]["repository"] = str(tmp_path / "missing")
    fleet_file.write_text(json.dumps(unresolved), encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.fleet_command(svc, cli.parser().parse_args(["fleet", "register", "--file", str(fleet_file)]))
    assert outputs[-1] == {"status": "refused", "reason_code": "repository_missing", "error_type": "FleetRefused", "exit_code": 1}
    with pytest.raises(FleetRefused, match="repository_missing"):
        fleet_cli.check_resolved(unresolved)
    monkeypatch.setattr(fleet_cli, "execute", lambda service, args: (_ for _ in ()).throw(RuntimeError("dsn=" + CANARY)))
    with pytest.raises(SystemExit):
        cli.fleet_command(svc, cli.parser().parse_args(["fleet", "status"]))
    assert outputs[-1] == {"status": "refused", "reason_code": "error", "error_type": "RuntimeError", "exit_code": 1}
    assert Fleet(svc.store).status()["jobs"][0]["operation_id"] == "op-1"
