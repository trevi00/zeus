"""Host migration (INV-HOST-MIGRATION-001): manifest, coordinator, copies and the systemd target.

Everything here runs on fixture data in temporary directories and the memory store. The Redis
round trip runs only against two disposable servers named by ZEUS_MIGRATION_TEST_REDIS_SOURCE /
ZEUS_MIGRATION_TEST_REDIS_TARGET (unix socket paths); without them it skips and proves nothing.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import time

import pytest

from codex_harness.adapters import host_migration as adapter
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_migration import HostMigrations
from codex_harness.domain import host_migration as policy
from codex_harness.domain.host_delivery import KIND_SYSTEMD, validate_targets
from codex_harness.domain.host_migration import MigrationRefused

H = "a" * 64
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64


def engine(kind: str, host: str) -> dict:
    if kind == "postgres":
        return {"image": "pgvector/pgvector:pg17", "image_digest": IMAGE, "major": 17, "database": "zeus",
                "endpoint": {"kind": "docker_exec", "name": host + "-postgres"}, "extensions": ["vector"]}
    return {"image": "redis:7.4-alpine", "image_digest": IMAGE, "major": 7,
            "instance": "dedicated", "endpoint": {"kind": "docker_exec", "name": host + "-redis"},
            "namespaces": ["zeus"]}


def manifest(**overrides) -> dict:
    document = {
        "schema": policy.MANIFEST_SCHEMA, "migration_id": "aibox-migration-001",
        "created_at": "2026-09-25T05:00:00Z",
        "source": {"host_id": "windows-pc", "platform": "windows",
                   "postgres": engine("postgres", "src"), "redis": engine("redis", "src")},
        "target": {"host_id": "aibox", "platform": "linux",
                   "postgres": engine("postgres", "dst"), "redis": engine("redis", "dst")},
        "schema_map": {"zeus_control": "zeus_aibox_control", "zeus_lane_a": "zeus_aibox_lane_a"},
        "path_map": [{"id": "artifacts", "from": "D:/workspaces/zeus/artifacts", "to": "/srv/zeus/artifacts"},
                     {"id": "backups", "from": "D:/workspaces/zeus/backups", "to": "/srv/zeus/backups"}],
        "repository": {"commit": COMMIT, "dirty_count": 0, "dirty_sha256": H, "ignored_preserved": [".venv-notes"]},
        "artifact_roots": [{"id": "evidence", "path_id": "artifacts", "entries": 3, "bytes": 10, "tree_sha256": H}],
        "pg_buckets": [{"schema": "zeus_control", "bucket": "fleet_jobs", "count": 2, "sha256": H}],
        "redis_keys": [{"key": "zeus:stream:worker", "type": "stream", "sha256": H, "expires_at_ms": None,
                        "stream": {"length": 2, "last_generated_id": "1-1",
                                   "groups": [{"name": "workers", "last_delivered_id": "1-0",
                                               "pending": 1, "consumers": 1}]}}],
        "writers": [{"id": "zeus-owner-continuation", "kind": "scheduled_task", "owner": "zeus",
                     "zeus_owned": True, "disposition": "stop_and_fence"},
                    {"id": "baldrix-cron", "kind": "scheduled_task", "owner": "user",
                     "zeus_owned": False, "disposition": "leave_untouched_not_zeus"}],
        "fence": {"kind": "admission_pause_and_marker", "marker_id": "aibox-migration-001"},
        "rollback": {"location_id": "backups", "reverse_supported": True, "source_retained": True},
    }
    document.update(overrides)
    return document


def transition(sha: str, frm: str, to: str, *, reason=None, exit_code=0, evidence=None) -> dict:
    return {"schema": policy.TRANSITION_SCHEMA, "migration_id": "aibox-migration-001", "manifest_sha256": sha,
            "from": frm, "to": to, "actor": "claude-implementation", "host": "aibox",
            "at": "2026-09-25T05:10:00Z",
            "identity": {"config_sha256": H, "commit": COMMIT, "image": IMAGE, "profile_sha256": H},
            "evidence": evidence if evidence is not None else {name: H for name in policy.GATES.get(to, ())},
            "exit_code": exit_code, "reason_code": reason}


def checkpoint(step: str, input_sha: str = H, output_sha: str = H) -> dict:
    return {"schema": policy.CHECKPOINT_SCHEMA, "migration_id": "aibox-migration-001", "step": step,
            "input_sha256": input_sha, "output_sha256": output_sha, "at": "2026-09-25T05:20:00Z"}


def walk(coordinator, sha, until):
    state = policy.PLANNED
    for to in policy.FORWARD[1:policy.FORWARD.index(until) + 1]:
        coordinator.advance(transition(sha, state, to))
        state = to
    return state


# ----- manifest -----------------------------------------------------------------------------------
def test_manifest_validates_and_digest_is_order_independent():
    first = policy.validate_manifest(manifest())
    shuffled = manifest()
    shuffled["writers"] = list(reversed(shuffled["writers"]))
    assert policy.manifest_digest(first) == policy.manifest_digest(policy.validate_manifest(shuffled))


@pytest.mark.parametrize("mutate, reason", [
    (lambda d: d["target"]["postgres"]["endpoint"].update(name="postgresql://zeus:hunter2@db/zeus"), "secret_value"),
    (lambda d: d["source"]["redis"]["endpoint"].update(name="redis://:hunter2@host:6379/0"), "secret_value"),
    (lambda d: d["fence"].update(password="x"), "secret_field"),
    (lambda d: d["target"]["postgres"].update(major=18), "major_version_mismatch"),
    (lambda d: d["target"]["redis"].update(namespaces=["zeus_aibox"]), "namespace_rewrite"),
    (lambda d: d["target"]["redis"].update(instance="shared"), "target_redis_shared"),
    (lambda d: d["target"]["postgres"].update(extensions=[]), "extension_mismatch"),
    (lambda d: d["schema_map"].update(zeus_lane_a="zeus_aibox_control"), "map_not_bijective"),
    (lambda d: d["schema_map"].update(zeus_lane_a="public"), "public_schema"),
    (lambda d: d["path_map"][1].update(to="/srv/zeus/artifacts/nested"), "path_overlap"),
    (lambda d: d["redis_keys"][0].update(key="other:stream"), "redis_key_outside_namespace"),
    (lambda d: d["writers"][1].update(disposition="stop_and_fence"), "writer_disposition"),
    (lambda d: d["rollback"].update(reverse_supported=False), "rollback_unsupported"),
    (lambda d: d["pg_buckets"][0].update(schema="unmapped"), "schema_unmapped"),
    (lambda d: d["target"].update(host_id="windows-pc"), "manifest_same_host"),
])
def test_manifest_refusals_name_a_field_never_a_value(mutate, reason):
    document = manifest()
    mutate(document)
    with pytest.raises(MigrationRefused) as caught:
        policy.validate_manifest(document)
    assert caught.value.reason_code == reason
    assert "hunter2" not in str(caught.value)


def test_reverse_maps_are_exact_inverses():
    reverse = policy.reverse_maps(policy.validate_manifest(manifest()))
    assert reverse["schema_map"] == {"zeus_aibox_control": "zeus_control", "zeus_aibox_lane_a": "zeus_lane_a"}
    assert {p["id"]: (p["from"], p["to"]) for p in reverse["path_map"]}["artifacts"] == \
        ("/srv/zeus/artifacts", "D:/workspaces/zeus/artifacts")


# ----- coordinator ------------------------------------------------------------------------------
def test_plan_is_idempotent_and_a_different_manifest_is_refused():
    coordinator = HostMigrations(MemoryStore())
    first = coordinator.plan(manifest())
    assert first["cached"] is False and first["state"] == policy.PLANNED
    assert coordinator.plan(manifest())["cached"] is True
    changed = manifest()
    changed["pg_buckets"][0]["count"] = 3
    with pytest.raises(MigrationRefused, match="manifest_conflict"):
        coordinator.plan(changed)


def test_forward_walk_replays_and_refuses_stale_skip_and_missing_gate():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    step = transition(sha, policy.PLANNED, "network_ready")
    coordinator.advance(step)
    assert coordinator.advance(step)["cached"] is True  # identical request after a restart
    with pytest.raises(MigrationRefused, match="state_stale"):
        coordinator.advance(transition(sha, policy.PLANNED, "network_ready", evidence={"network_receipt": "d" * 64}))
    with pytest.raises(MigrationRefused, match="transition_not_allowed"):
        coordinator.advance(transition(sha, "network_ready", "draining"))
    with pytest.raises(MigrationRefused, match="gate_evidence_missing"):
        coordinator.advance(transition(sha, "network_ready", "staged", evidence={"target_layout": H}))
    with pytest.raises(MigrationRefused, match="manifest_stale"):
        coordinator.advance(transition("e" * 64, "network_ready", "staged"))
    assert walk(coordinator, sha, policy.QUALIFIED) == policy.QUALIFIED
    status = coordinator.status("aibox-migration-001")
    assert status["state"] == policy.QUALIFIED and status["transitions"] == len(policy.FORWARD) - 1
    with pytest.raises(MigrationRefused, match="transition_not_allowed"):
        coordinator.advance(transition(sha, policy.QUALIFIED, policy.FAILED, reason="late", exit_code=1))


def test_failure_records_reason_and_resumes_only_into_its_own_state():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "snapshot_sealed")
    with pytest.raises(MigrationRefused, match="transition_invalid"):
        coordinator.advance(transition(sha, "snapshot_sealed", policy.FAILED, exit_code=1))  # no reason
    coordinator.advance(transition(sha, "snapshot_sealed", policy.FAILED, reason="pg-restore-interrupted",
                                   exit_code=1))
    with pytest.raises(MigrationRefused, match="transition_not_allowed"):
        coordinator.advance(transition(sha, policy.FAILED, "restored_paused"))
    coordinator.advance(transition(sha, policy.FAILED, "snapshot_sealed"))
    assert coordinator.status("aibox-migration-001")["state"] == "snapshot_sealed"


def test_checkpoint_resume_replays_same_input_and_refuses_another_snapshot():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("pg_restore"))
    walk(coordinator, sha, "snapshot_sealed")
    assert coordinator.checkpoint(checkpoint("pg_restore"))["recorded"] is True
    assert coordinator.checkpoint(checkpoint("pg_restore"))["cached"] is True
    assert coordinator.completed_step("aibox-migration-001", "pg_restore", H)["output_sha256"] == H
    with pytest.raises(MigrationRefused, match="checkpoint_conflict"):
        coordinator.checkpoint(checkpoint("pg_restore", input_sha="f" * 64))
    with pytest.raises(MigrationRefused, match="checkpoint_conflict"):
        coordinator.completed_step("aibox-migration-001", "pg_restore", "f" * 64)
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("reverse_pg_restore"))


def test_rollback_before_target_writes_is_r0_without_reverse_steps():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    coordinator.advance(transition(sha, "restored_paused", policy.ROLLBACK_REQUIRED, reason="canary-refused",
                                   exit_code=1))
    plan = coordinator.rollback_plan("aibox-migration-001")
    assert plan["mode"] == policy.ROLLBACK_R0 and plan["steps"] == []
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("reverse_pg_restore"))
    coordinator.advance(transition(sha, policy.ROLLBACK_REQUIRED, policy.ROLLED_BACK))
    assert coordinator.status("aibox-migration-001")["state"] == policy.ROLLED_BACK


def test_rollback_after_target_writes_is_r1_reverse_migration_only():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "limited_active")
    coordinator.advance(transition(sha, "limited_active", policy.ROLLBACK_REQUIRED, reason="b1-failed",
                                   exit_code=1))
    plan = coordinator.rollback_plan("aibox-migration-001")
    assert plan["mode"] == policy.ROLLBACK_R1
    assert "restart_source_from_original_snapshot" in plan["forbidden"]
    assert plan["reverse"]["schema_map"]["zeus_aibox_control"] == "zeus_control"
    assert coordinator.checkpoint(checkpoint("reverse_pg_restore"))["recorded"] is True
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("pg_restore"))


# ----- artifacts ------------------------------------------------------------------------------------
def tree(root, files):
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_artifact_copy_is_hash_verified_resumable_and_never_overwrites(tmp_path):
    source, target = tmp_path / "src", tmp_path / "dst"
    tree(source, {"a/one.json": b"1", "a/two.json": b"22", "b/three.log": b"333" * 1000})
    inventory = adapter.artifact_inventory(source)
    assert inventory["entries"] == 3 and inventory["anomalies"] == []
    tree(target, {"a/one.json": b"1"})  # an interrupted earlier copy
    result = adapter.copy_artifacts(source, target, inventory)
    assert (result["copied"], result["skipped"]) == (2, 1)
    assert adapter.copy_artifacts(source, target, inventory) == {**result, "copied": 0, "skipped": 3}
    assert policy.compare_trees(inventory, adapter.artifact_inventory(target))["equal"] is True
    (target / "a/two.json").write_bytes(b"XX")
    with pytest.raises(MigrationRefused, match="artifact_target_different"):
        adapter.copy_artifacts(source, target, inventory)
    assert (target / "a/two.json").read_bytes() == b"XX"  # never replaced
    comparison = policy.compare_trees(inventory, adapter.artifact_inventory(target))
    assert comparison["equal"] is False and comparison["differences"] == [{"path": "a/two.json", "status": "different"}]


def test_artifact_source_change_after_seal_and_symlinks_refuse(tmp_path):
    source, target = tmp_path / "src", tmp_path / "dst"
    tree(source, {"x.bin": b"sealed"})
    inventory = adapter.artifact_inventory(source)
    (source / "x.bin").write_bytes(b"changed")
    with pytest.raises(MigrationRefused, match="artifact_source_changed"):
        adapter.copy_artifacts(source, target, inventory)
    assert not (target / "x.bin").exists()
    (source / "link").symlink_to(tmp_path)
    linked = adapter.artifact_inventory(source)
    assert linked["anomalies"] == ["symlink:link"]
    with pytest.raises(MigrationRefused, match="artifact_anomalies"):
        adapter.copy_artifacts(source, target, linked)


def test_artifact_inventory_reports_case_collisions(tmp_path):
    tree(tmp_path, {"Report.json": b"1", "report.json": b"2"})
    assert adapter.artifact_inventory(tmp_path)["anomalies"] == ["case_collision:report.json"]


# ----- PostgreSQL documents and Redis comparisons -------------------------------------------------
def test_bucket_inventory_and_comparison_with_schema_map_and_allowed_delta():
    source, target = MemoryStore(), MemoryStore()
    for store in (source, target):
        with store.transaction() as tx:
            tx.put("fleet_jobs", "j1", {"status": "accepted"})
            tx.put("fleet_registry", "fleet", {"config": {"repository": "D:/zeus"}})
    with target.transaction() as tx:
        tx.put("fleet_registry", "fleet", {"config": {"repository": "/srv/zeus/repo"}})
    left = adapter.store_inventory(source, "zeus_control")
    right = adapter.store_inventory(target, "zeus_aibox_control")
    mapping = {"zeus_control": "zeus_aibox_control"}
    strict = policy.compare_buckets(left, right, mapping)
    assert strict["equal"] is False and strict["failed"] == 1
    allowed = policy.compare_buckets(left, right, mapping, [("zeus_aibox_control", "fleet_registry")])
    assert allowed["equal"] is True
    assert {row["bucket"]: row["status"] for row in allowed["rows"]} == \
        {"fleet_jobs": "equal", "fleet_registry": "allowed_delta"}
    missing = policy.compare_buckets(left, right[:1], mapping)
    assert missing["equal"] is False and "missing_on_target" in {row["status"] for row in missing["rows"]}


def test_redis_comparison_separates_downtime_expiry_from_loss():
    rows = [{"key": "zeus:lock:a", "type": "string", "sha256": H, "expires_at_ms": 1000, "stream": None},
            {"key": "zeus:dedup:b", "type": "string", "sha256": H, "expires_at_ms": None, "stream": None}]
    result = policy.compare_redis(rows, [], restored_at_ms=2000)
    assert {row["key"]: row["status"] for row in result["rows"]} == \
        {"zeus:dedup:b": "missing_on_target", "zeus:lock:a": "expired_in_downtime"}
    assert result["equal"] is False
    assert policy.compare_redis(rows[:1], [], restored_at_ms=2000)["equal"] is True


REDIS_SOURCE = os.environ.get("ZEUS_MIGRATION_TEST_REDIS_SOURCE")
REDIS_TARGET = os.environ.get("ZEUS_MIGRATION_TEST_REDIS_TARGET")


@pytest.mark.skipif(not (REDIS_SOURCE and REDIS_TARGET), reason="Two disposable Redis servers required")
def test_redis_dump_restore_preserves_stream_groups_pel_and_absolute_expiry():
    from redis import Redis

    source, target = Redis(unix_socket_path=REDIS_SOURCE), Redis(unix_socket_path=REDIS_TARGET)
    for client in (source, target):
        client.flushall()
    source.xadd("zeus:stream:worker", {"m": "1"}, id="1-0")
    source.xadd("zeus:stream:worker", {"m": "2"}, id="2-0")
    source.xgroup_create("zeus:stream:worker", "workers", id="0")
    source.xreadgroup("workers", "consumer-a", {"zeus:stream:worker": ">"}, count=2)
    source.xack("zeus:stream:worker", "workers", "1-0")
    source.set("zeus:dedup:x", "done")
    source.set("zeus:lock:y", "held", px=600000)
    source.set("zeus:lock:gone", "held", px=50)
    source.set("other:project", "untouched")
    time.sleep(0.2)
    before = adapter.redis_inventory(source, ["zeus"])
    result = adapter.copy_redis(source, target, [row["key"] for row in before])
    after = adapter.redis_inventory(target, ["zeus"])
    comparison = policy.compare_redis(before, after, restored_at_ms=result["restored_at_ms"])
    assert comparison["equal"] is True, comparison
    stream = {row["key"]: row for row in after}["zeus:stream:worker"]["stream"]
    assert stream["groups"] == [{"name": "workers", "last_delivered_id": "2-0", "pending": 1, "consumers": 1}]
    assert target.xpending("zeus:stream:worker", "workers")["pending"] == 1
    assert target.exists("other:project") == 0
    assert adapter.copy_redis(source, target, [row["key"] for row in before])["skipped"] == len(before)
    target.set("zeus:dedup:x", "changed")
    with pytest.raises(MigrationRefused, match="redis_target_different"):
        adapter.copy_redis(source, target, ["zeus:dedup:x"])


# ----- systemd service --------------------------------------------------------------------------
def unit(**overrides) -> dict:
    document = {"schema": policy.UNIT_SCHEMA, "unit": "zeus-owner", "description": "Zeus owner (aibox)",
                "user": "trevi", "group": "trevi", "working_directory": "/srv/zeus/releases/current",
                "exec_start": ["/srv/zeus/releases/current/.venv/bin/python", "-m",
                               "codex_harness.adapters.host_delivery", "service",
                               "--state-dir", "/srv/zeus/runtime/control/owner"],
                "path": "/srv/zeus/releases/current/.venv/bin:/usr/bin:/bin",
                "environment": {"ZEUS_RUNTIME_DIR": "/srv/zeus/runtime/control"},
                "stop_timeout_seconds": 90, "restart_seconds": 10, "start_limit_burst": 3,
                "start_limit_interval_seconds": 300}
    document.update(overrides)
    return document


def test_render_unit_is_absolute_bounded_and_control_group_killed():
    text = policy.render_unit(unit())
    for line in ("User=trevi", "KillMode=control-group", "TimeoutStopSec=90", "Restart=on-failure",
                 "StartLimitBurst=3", "WorkingDirectory=/srv/zeus/releases/current"):
        assert line in text.splitlines()


@pytest.mark.parametrize("overrides, reason", [
    ({"user": "root"}, "unit_invalid"),
    ({"working_directory": "srv/zeus"}, "unit_invalid"),
    ({"exec_start": ["python", "-m", "x"]}, "unit_invalid"),
    ({"exec_start": ["/bin/sh", "-c", "echo $HOME; rm"]}, "unit_invalid"),
    ({"environment": {"ZEUS_CLAUDE_TOKEN": "x"}}, "secret_field"),
    ({"environment": {"ANTHROPIC_API_KEY": "x"}}, "secret_field"),
    ({"environment": {"PYTHONPATH": "/x"}}, "manifest_invalid"),
    ({"stop_timeout_seconds": 0}, "unit_invalid"),
])
def test_unit_refusals(overrides, reason):
    with pytest.raises(MigrationRefused) as caught:
        policy.validate_unit(unit(**overrides))
    assert caught.value.reason_code == reason


class Systemctl:
    def __init__(self, states):
        self.states, self.calls = list(states), []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        stdout = self.states.pop(0) if argv[-2] == "is-active" and self.states else ""
        return subprocess.CompletedProcess(argv, 0 if stdout != "failed-to-start" else 1, stdout, "")


def test_systemd_target_uses_only_the_registered_unit(tmp_path):
    registry = validate_targets({"schema": "urn:zeus:host-delivery-targets:1", "targets": [
        {"target_id": "aibox-owner", "kind": KIND_SYSTEMD, "root": "/srv/zeus/releases/current",
         "state_dir": str(tmp_path), "service": "zeus-owner"}]})
    target = registry["targets"][0]
    runner = Systemctl(["active\n", "inactive\n", "inactive\n"])
    host = adapter.SystemdHostTarget(runner=runner)
    assert host.running(target) is True
    assert host.stop(target)["stopped"] is True
    descriptor = {"schema": "urn:zeus:host-descriptor:1", "target_id": "aibox-owner",
                  "root": "/srv/zeus/releases/current", "revision": COMMIT, "worker_image": IMAGE,
                  "profile_digest": H, "predecessor": None}
    launched = host._launch(target, descriptor, None)
    assert launched["started"] is True and json.loads((tmp_path / "controller-state.json").read_text())["service"] == "zeus-owner"
    assert [call[1:] for call in runner.calls] == [["is-active", "zeus-owner.service"],
                                                   ["stop", "zeus-owner.service"],
                                                   ["is-active", "zeus-owner.service"],
                                                   ["is-active", "zeus-owner.service"],
                                                   ["start", "zeus-owner.service"]]
    with pytest.raises(RuntimeError, match="unavailable"):
        adapter.SystemdHostTarget(runner=Systemctl(["unknown\n"])).running(target)
    user = Systemctl(["inactive\n"])
    adapter.SystemdHostTarget(runner=user, user_scope=True).running(target)
    assert user.calls[0][:2] == ["systemctl", "--user"]


# ----- layout and CLI -----------------------------------------------------------------------------
def test_prepare_layout_is_dry_run_by_default_and_idempotent(tmp_path):
    root = tmp_path / "srv-zeus"
    dry = adapter.prepare_layout(root)
    assert not root.exists() and {row["state"] for row in dry["directories"]} == {"would_create"}
    adapter.prepare_layout(root, apply=True)
    again = adapter.prepare_layout(root, apply=True)
    assert {row["state"] for row in again["directories"]} == {"present"}
    (root / "tmp").rmdir()
    (root / "tmp").write_text("x")
    with pytest.raises(MigrationRefused, match="layout_conflict"):
        adapter.prepare_layout(root, apply=True)


def test_cli_validate_reports_digest_and_never_echoes_a_secret(tmp_path, capsys):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(manifest()))
    leaked = copy.deepcopy(manifest())
    leaked["target"]["postgres"]["endpoint"]["name"] = "postgresql://zeus:hunter2@db/zeus"
    bad.write_text(json.dumps(leaked))
    assert adapter.main(["validate", "--file", str(good)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert adapter.main(["validate", "--file", str(bad)]) == 1
    output = capsys.readouterr().out
    assert "hunter2" not in output and json.loads(output)["refused"] == "secret_value"


class Docker:
    def __init__(self, probe="0"):
        self.calls, self.probe = [], probe

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        stdout = {"sha256sum": "d" * 64 + "  /dump/x.dump\n", "psql": self.probe + "\n",
                  "pg_restore": "; header\n1; 2615 SCHEMA\n2; 1259 TABLE\n"}.get(argv[3], "")
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def test_pg_tools_run_inside_the_container_without_a_dsn_and_never_merge_a_schema():
    runner = Docker()
    dump = adapter.pg_dump("zeus-pg", "postgres", "zeus", "zeus_control", "/dump/x.dump", runner=runner)
    assert dump["sha256"] == "d" * 64 and dump["toc_entries"] == 2
    assert runner.calls[0] == ["docker", "exec", "zeus-pg", "pg_dump", "-U", "postgres", "-h", "/var/run/postgresql",
                               "-d", "zeus", "-n", "zeus_control", "-Fc", "-f", "/dump/x.dump"]
    assert all("://" not in arg and "password" not in arg.lower() for call in runner.calls for arg in call)
    restore = Docker()
    adapter.pg_restore("zeus-pg", "postgres", "zeus_aibox", "/dump/x.dump", "zeus_control", "zeus_aibox_control",
                       runner=restore)
    assert [call[3] for call in restore.calls] == ["psql", "pg_restore", "psql"]
    assert restore.calls[-1][-1] == "ALTER SCHEMA zeus_control RENAME TO zeus_aibox_control"
    with pytest.raises(MigrationRefused, match="pg_restore_schema_present"):
        adapter.pg_restore("zeus-pg", "postgres", "zeus_aibox", "/dump/x.dump", "zeus_control",
                           "zeus_aibox_control", runner=Docker(probe="1"))
    with pytest.raises(MigrationRefused, match="pg_tool_invalid"):
        adapter.pg_dump("zeus-pg", "postgres", "zeus", "x; DROP", "/dump/x.dump", runner=Docker())
