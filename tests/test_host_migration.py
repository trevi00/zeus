"""Host migration (INV-HOST-MIGRATION-001): manifest, coordinator, activation intent, canonical wiring.

Everything here runs on fixture data in temporary directories and the memory store. The canonical
offline tooling (scripts/aibox_data) is invoked through this adapter's CLI as a real subprocess, so
its actual exit code is what the receipts record. The Redis round trip runs only against two
disposable servers named by ZEUS_MIGRATION_TEST_REDIS_SOURCE / ZEUS_MIGRATION_TEST_REDIS_TARGET
(unix socket paths); without them it skips and proves nothing.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from codex_harness.adapters import host_migration as adapter
from codex_harness.adapters.host_delivery import DeliveryRefused
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.host_migration import HostMigrations
from codex_harness.domain import host_migration as policy
from codex_harness.domain.host_delivery import KIND_SYSTEMD, validate_targets
from codex_harness.domain.host_migration import MigrationRefused

ROOT = Path(__file__).resolve().parents[1]
H = "a" * 64
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64
HOST_ID = "machine-id-sha256:" + "d" * 64


def engine(kind: str, host: str) -> dict:
    if kind == "postgres":
        return {"image": "pgvector/pgvector:pg17", "image_digest": IMAGE, "major": 17, "database": "zeus",
                "endpoint": {"kind": "docker_exec", "name": host + "-postgres"}, "extensions": ["plpgsql", "vector"]}
    return {"image": "redis:7.4-alpine", "image_digest": IMAGE, "major": 7,
            "instance": "dedicated", "endpoint": {"kind": "docker_exec", "name": host + "-redis"},
            "namespaces": ["zeus-fleet-harness", "zeus-fleet-interface"]}


def manifest(**overrides) -> dict:
    document = {
        "schema": policy.MANIFEST_SCHEMA, "migration_id": "aibox-migration-001",
        "created_at": "2026-09-25T05:00:00Z",
        "source": {"host_id": "windows-pc", "platform": "windows",
                   "postgres": engine("postgres", "src"), "redis": engine("redis", "src")},
        "target": {"host_id": "aibox", "platform": "linux",
                   "postgres": engine("postgres", "dst"), "redis": engine("redis", "dst")},
        # The actual source control ledger is `public` (source-inventory.json, 2026-09-25).
        "schema_map": {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness"},
        "path_map": [{"id": "artifacts", "from": "D:/workspaces/zeus/artifacts", "to": "/srv/zeus/artifacts"},
                     {"id": "backups", "from": "D:/workspaces/zeus/backups", "to": "/srv/zeus/backups"}],
        "repository": {"commit": COMMIT, "dirty_count": 0, "dirty_sha256": H, "ignored_preserved": [".venv-notes"]},
        "artifact_roots": [{"id": "evidence", "path_id": "artifacts", "entries": 3, "bytes": 10, "tree_sha256": H}],
        "pg_buckets": [{"schema": "public", "bucket": "fleet_registry", "count": 1, "sha256": H},
                       {"schema": "zeus_fleet_harness", "bucket": "operations", "count": 2, "sha256": H}],
        "redis_keys": [{"key": "zeus-fleet-harness:stream:worker", "type": "stream", "sha256": H,
                        "expires_at_ms": None,
                        "stream": {"length": 2, "last_generated_id": "1-1",
                                   "groups": [{"name": "workers", "last_delivered_id": "1-0",
                                               "pending": 1, "consumers": 1}]}}],
        "writers": [{"id": "zeusfleet-run", "kind": "scheduled_task", "owner": "zeus",
                     "zeus_owned": True, "disposition": "stop_and_fence"},
                    {"id": "baldrix-cron", "kind": "scheduled_task", "owner": "user",
                     "zeus_owned": False, "disposition": "leave_untouched_not_zeus"}],
        "fence": {"kind": "admission_pause_and_marker", "marker_id": "aibox-migration-001"},
        "rollback": {"location_id": "backups", "reverse_supported": True, "source_retained": True},
    }
    document.update(overrides)
    return document


def receipt(check: str, subject=None, *, ok=True, exit_code=None) -> dict:
    return {"schema": policy.EVIDENCE_SCHEMA, "check": check, "subject": subject,
            "exit_code": (0 if ok else 1) if exit_code is None else exit_code, "ok": ok, "result_sha256": H}


def gate_evidence(to: str, **bound) -> dict:
    evidence = {}
    for gate, kinds in policy.GATES.get(to, {}).items():
        evidence[gate] = bound.get(gate) or receipt(kinds[0] if kinds else policy.OBSERVATION,
                                                    ok=kinds is not None)
    return evidence


def transition(sha: str, frm: str, to: str, *, reason=None, exit_code=0, evidence=None, identity=None) -> dict:
    return {"schema": policy.TRANSITION_SCHEMA, "migration_id": "aibox-migration-001", "manifest_sha256": sha,
            "from": frm, "to": to, "actor": "claude-implementation", "host": "aibox",
            "at": "2026-09-25T05:10:00Z",
            "identity": identity or {"config_sha256": H, "commit": COMMIT, "image": IMAGE, "profile_sha256": H},
            "evidence": evidence if evidence is not None else gate_evidence(to),
            "exit_code": exit_code, "reason_code": reason}


def failure(sha, frm, to, reason):
    return transition(sha, frm, to, reason=reason, exit_code=1)


def checkpoint(step: str, input_sha: str = H, output_sha: str = H) -> dict:
    return {"schema": policy.CHECKPOINT_SCHEMA, "migration_id": "aibox-migration-001", "step": step,
            "input_sha256": input_sha, "output_sha256": output_sha, "at": "2026-09-25T05:20:00Z"}


INTENT = {"schema": policy.INTENT_SCHEMA, "migration_id": "aibox-migration-001", "host_id": HOST_ID,
          "release_revision": COMMIT, "image": IMAGE, "profile_sha256": H, "actor": "owner",
          "at": "2026-09-25T06:00:00Z"}


def walk(coordinator, sha, until):
    state = policy.PLANNED
    for to in policy.FORWARD[1:policy.FORWARD.index(until) + 1]:
        if to == policy.LIMITED_ACTIVE:
            coordinator.advance(activation_transition(coordinator, sha))
        else:
            coordinator.advance(transition(sha, state, to))
        state = to
    return state


def activation_transition(coordinator, sha):
    intent_id = coordinator.status("aibox-migration-001")["activation_intent"]
    if intent_id is None:
        intent_id = coordinator.intend_activation(INTENT)["intent_id"]
    return transition(sha, policy.RESTORED_PAUSED, policy.LIMITED_ACTIVE, evidence=gate_evidence(
        policy.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
        service_consumption=receipt("service-startup", "revision=" + COMMIT)))


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
    (lambda d: d["target"]["postgres"].update(extensions=["vector"]), "extension_mismatch"),
    (lambda d: d["schema_map"].update(zeus_fleet_harness="zeus_aibox_control"), "map_not_bijective"),
    (lambda d: d["schema_map"].update(zeus_fleet_harness="public"), "public_schema"),
    (lambda d: d["schema_map"].update(public="zeus_aibox_other"), "source_public_mapping"),
    (lambda d: d.update(pg_buckets=[b for b in d["pg_buckets"] if b["schema"] != "public"]),
     "source_public_not_inventoried"),
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


def test_source_public_is_accepted_only_as_the_control_ledger_and_reverses_exactly():
    valid = policy.validate_manifest(manifest())
    assert valid["schema_map"]["public"] == "zeus_aibox_control"
    reverse = policy.reverse_maps(valid)
    assert reverse["schema_map"] == {"zeus_aibox_control": "public", "zeus_aibox_harness": "zeus_fleet_harness"}
    assert {p["id"]: (p["from"], p["to"]) for p in reverse["path_map"]}["artifacts"] == \
        ("/srv/zeus/artifacts", "D:/workspaces/zeus/artifacts")


def test_schema_scope_allows_source_public_and_refuses_target_public():
    assert adapter._schema("public", "source") == "public"
    with pytest.raises(MigrationRefused, match="public_schema"):
        adapter._schema("public", "target")
    with pytest.raises(MigrationRefused, match="public_schema"):
        adapter.schema_store("host=/nonexistent dbname=x", "public", "target")


# ----- coordinator: typed evidence ----------------------------------------------------------------
def test_plan_is_idempotent_and_a_different_manifest_is_refused():
    coordinator = HostMigrations(MemoryStore())
    first = coordinator.plan(manifest())
    assert first["cached"] is False and first["state"] == policy.PLANNED
    assert "not proof" in first["authority"]
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
    other = transition(sha, policy.PLANNED, "network_ready",
                       evidence={"network_receipt": receipt("observation") | {"result_sha256": "e" * 64}})
    with pytest.raises(MigrationRefused, match="state_stale"):
        coordinator.advance(other)
    with pytest.raises(MigrationRefused, match="transition_not_allowed"):
        coordinator.advance(transition(sha, "network_ready", "draining"))
    with pytest.raises(MigrationRefused, match="gate_evidence_fields"):
        coordinator.advance(transition(sha, "network_ready", "staged",
                                       evidence={"target_layout": receipt("observation")}))
    with pytest.raises(MigrationRefused, match="manifest_stale"):
        coordinator.advance(transition("e" * 64, "network_ready", "staged"))
    assert walk(coordinator, sha, policy.QUALIFIED) == policy.QUALIFIED
    status = coordinator.status("aibox-migration-001")
    assert status["state"] == policy.QUALIFIED and "not proof" in status["authority"]


@pytest.mark.parametrize("bad, reason", [
    (receipt("pg-coverage", ok=False), "gate_evidence_failed"),
    (receipt("pg-coverage", ok=True, exit_code=1), "evidence_inconsistent"),
    (receipt("pg-coverage", ok=False, exit_code=0), "evidence_inconsistent"),
    (receipt("compare-pg"), "gate_evidence_kind"),  # one schema is not coverage of all schemas
    (receipt("observation"), "gate_evidence_kind"),
    ({**receipt("pg-coverage"), "check": "hand_typed"}, "evidence_check_unknown"),
])
def test_a_failing_unknown_or_inconsistent_receipt_never_advances(bad, reason):
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "snapshot_sealed")
    evidence = gate_evidence(policy.RESTORED_PAUSED, pg_comparison=bad)
    with pytest.raises(MigrationRefused) as caught:
        coordinator.advance(transition(sha, "snapshot_sealed", "restored_paused", evidence=evidence))
    assert caught.value.reason_code == reason
    assert coordinator.status("aibox-migration-001")["state"] == "snapshot_sealed"


def test_failure_records_reason_and_resumes_only_into_its_own_state():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "snapshot_sealed")
    with pytest.raises(MigrationRefused, match="transition_invalid"):
        coordinator.advance(transition(sha, "snapshot_sealed", policy.FAILED, exit_code=1))  # no reason
    coordinator.advance(failure(sha, "snapshot_sealed", policy.FAILED, "pg-restore-interrupted"))
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
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("reverse_pg_restore"))


# ----- activation: intent first, receipt bound, conservative rollback ------------------------------
def test_limited_active_requires_the_intent_and_receipts_bound_to_it():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    unbound = transition(sha, policy.RESTORED_PAUSED, policy.LIMITED_ACTIVE)
    with pytest.raises(MigrationRefused, match="activation_intent_missing"):
        coordinator.advance(unbound)
    intent_id = coordinator.intend_activation(INTENT)["intent_id"]
    assert coordinator.intend_activation(INTENT)["cached"] is True
    with pytest.raises(MigrationRefused, match="activation_intent_conflict"):
        coordinator.intend_activation({**INTENT, "release_revision": "9" * 40})
    with pytest.raises(MigrationRefused, match="activation_receipt_unbound"):
        coordinator.advance(unbound)
    active_only = gate_evidence(policy.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
                                service_consumption=receipt("service-startup", "unit=active"))
    with pytest.raises(MigrationRefused, match="service_consumption_unbound"):
        coordinator.advance(transition(sha, policy.RESTORED_PAUSED, policy.LIMITED_ACTIVE, evidence=active_only))
    other_image = activation_transition(coordinator, sha) | {
        "identity": {"config_sha256": H, "commit": COMMIT, "image": "sha256:" + "0" * 64, "profile_sha256": H}}
    with pytest.raises(MigrationRefused, match="activation_identity_mismatch"):
        coordinator.advance(other_image)
    assert coordinator.advance(activation_transition(coordinator, sha))["state"] == policy.LIMITED_ACTIVE


def test_intent_is_recorded_only_in_restored_paused_and_blocks_further_forward_restore():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "snapshot_sealed")
    with pytest.raises(MigrationRefused, match="activation_state"):
        coordinator.intend_activation(INTENT)
    with pytest.raises(MigrationRefused, match="activation_intent_missing"):
        coordinator.activation_document("aibox-migration-001")


def launcher():
    """deploy/aibox's launcher module (Linux-only; accepted service tooling)."""
    if os.name != "posix":
        pytest.skip("Linux launcher tooling")
    spec = importlib.util.spec_from_file_location("zeus_aibox_service_under_test",
                                                  ROOT / "deploy" / "aibox" / "zeus_aibox_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_writer_start_receipt_gap_is_reconciled_by_r1_never_r0(tmp_path):
    """Deterministic interruption: intent recorded, launcher receipt written, service may have
    started, then the coordinator dies before `limited_active` is recorded."""
    store = MemoryStore()
    first = HostMigrations(store)
    sha = first.plan(manifest())["manifest_sha256"]
    walk(first, sha, "restored_paused")
    assert first.rollback_plan("aibox-migration-001")["mode"] == policy.ROLLBACK_R0  # no intent yet
    control = tmp_path / "runtime" / "control"
    control.mkdir(parents=True)
    with pytest.raises(MigrationRefused, match="activation_intent_missing"):
        first.activation_document("aibox-migration-001")  # no launcher document without an intent
    with pytest.raises(MigrationRefused, match="activation_receipt_invalid"):
        adapter.write_activation(control, {"schema": policy.ACTIVATION_SCHEMA})  # nor a file
    assert not (control / "host-activation.json").exists()
    first.intend_activation(INTENT)
    written = adapter.write_activation(control, first.activation_document("aibox-migration-001"))
    # The launcher of deploy/aibox accepts exactly this file for this host and revision.
    service = launcher()
    release = tmp_path / "releases" / COMMIT
    accepted = service.check_activation(control, release, HOST_ID)
    assert accepted["state"] == "restored_paused" and accepted["intent_id"] == written["intent_id"]
    with pytest.raises(service.Refused):
        service.check_activation(control, tmp_path / "releases" / ("9" * 40), HOST_ID)
    del first  # --- crash here: no limited_active receipt was ever written ---
    second = HostMigrations(store)
    assert second.status("aibox-migration-001")["state"] == policy.RESTORED_PAUSED
    plan = second.rollback_plan("aibox-migration-001")
    assert plan["mode"] == policy.ROLLBACK_R1 and "restart_source_from_original_snapshot" in plan["forbidden"]
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        second.checkpoint(checkpoint("artifact_copy"))  # no forward restore once an intent exists
    second.advance(failure(sha, policy.RESTORED_PAUSED, policy.ROLLBACK_REQUIRED, "writer-start-unknown"))
    with pytest.raises(MigrationRefused, match="activation_state"):
        second.activation_document("aibox-migration-001")  # never re-issued while rolling back
    fenced = adapter.write_fence(control, "aibox-migration-001", "rollback-r1")
    assert Path(fenced["written"]).exists()
    with pytest.raises(MigrationRefused, match="host_fenced"):
        adapter.write_activation(control, {**accepted})
    r0 = transition(sha, policy.ROLLBACK_REQUIRED, policy.ROLLED_BACK,
                    evidence={"rollback_gate": receipt("gate-r0")})
    with pytest.raises(MigrationRefused, match="rollback_gate_mode"):
        second.advance(r0)
    r1 = transition(sha, policy.ROLLBACK_REQUIRED, policy.ROLLED_BACK,
                    evidence={"rollback_gate": receipt("gate-r1")})
    with pytest.raises(MigrationRefused, match="reverse_step_missing"):
        second.advance(r1)
    for step in policy.REVERSE_STEPS:
        second.checkpoint(checkpoint(step))
    assert second.advance(r1)["state"] == policy.ROLLED_BACK


def test_rollback_without_any_intent_is_r0_with_its_own_gate():
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    coordinator.advance(failure(sha, "restored_paused", policy.ROLLBACK_REQUIRED, "canary-refused"))
    assert coordinator.rollback_plan("aibox-migration-001")["mode"] == policy.ROLLBACK_R0
    with pytest.raises(MigrationRefused, match="step_not_allowed"):
        coordinator.checkpoint(checkpoint("reverse_pg_restore"))
    with pytest.raises(MigrationRefused, match="rollback_gate_mode"):
        coordinator.advance(transition(sha, policy.ROLLBACK_REQUIRED, policy.ROLLED_BACK,
                                       evidence={"rollback_gate": receipt("gate-r1")}))
    done = coordinator.advance(transition(sha, policy.ROLLBACK_REQUIRED, policy.ROLLED_BACK,
                                          evidence={"rollback_gate": receipt("gate-r0")}))
    assert done["state"] == policy.ROLLED_BACK


def test_fence_refuses_every_launcher_role_including_monitors(tmp_path):
    service = launcher()
    control = tmp_path / "runtime" / "control"
    control.mkdir(parents=True)
    adapter.write_fence(control, "aibox-migration-001", "rollback-r0")
    for role in ("fleet", "monitor-collect", "monitor-web"):
        with pytest.raises(service.Refused) as refused:
            service.launch_plan(role, {"ZEUS_AIBOX_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"})
        assert refused.value.reason == "host_fenced"


# ----- canonical tooling wiring (actual subprocess of scripts/aibox_data) ------------------------------
def cli(capsys, *argv):
    code = adapter.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_unreadable_nested_directory_is_a_failed_inventory_not_an_empty_one(tmp_path, capsys):
    source = tmp_path / "source"
    (source / "a" / "denied").mkdir(parents=True)
    (source / "a" / "denied" / "proof.txt").write_bytes(b"hidden")
    os.chmod(source / "a" / "denied", 0)
    try:
        code, out = cli(capsys, "artifact-inventory", "--migration-id", "m1", "--root", f"art={source}",
                        "--out", str(tmp_path / "manifest.json"))
    finally:
        os.chmod(source / "a" / "denied", 0o700)
    assert code == 1 and out["receipt"]["ok"] is False and out["receipt"]["exit_code"] == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["roots"]["art"]["unreadable"] == [{"path": "a/denied", "error": "PermissionError"}]


def test_stage_refuses_preexisting_destination_ancestor_symlink_and_writes_nothing_outside(tmp_path, capsys):
    source, staging, outside = tmp_path / "source", tmp_path / "staging", tmp_path / "outside"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "evidence").write_bytes(b"proof")
    staging.mkdir()
    outside.mkdir()
    os.symlink(outside, staging / "sub")
    code, _ = cli(capsys, "artifact-inventory", "--migration-id", "m1", "--root", f"art={source}",
                  "--out", str(tmp_path / "manifest.json"))
    assert code == 0
    code, out = cli(capsys, "artifact-stage", "--manifest", str(tmp_path / "manifest.json"), "--root-id", "art",
                    "--source", str(source), "--staging", str(staging), "--work", str(tmp_path / "work"))
    assert code == 1 and out["receipt"]["ok"] is False
    assert out["result"]["reason"] == "staging_ancestor_symlink"
    assert os.listdir(outside) == []


def test_verify_mismatch_exits_nonzero_and_match_exits_zero(tmp_path, capsys):
    source, staging = tmp_path / "source", tmp_path / "staging"
    (source / "d").mkdir(parents=True)
    (source / "d" / "x.bin").write_bytes(b"sealed")
    manifest = str(tmp_path / "manifest.json")
    cli(capsys, "artifact-inventory", "--migration-id", "m1", "--root", f"art={source}", "--out", manifest)
    code, _ = cli(capsys, "artifact-stage", "--manifest", manifest, "--root-id", "art", "--source", str(source),
                  "--staging", str(staging), "--work", str(tmp_path / "work"))
    assert code == 0
    code, out = cli(capsys, "artifact-verify", "--manifest", manifest, "--root-id", "art", "--staging", str(staging))
    assert code == 0 and out["receipt"] == {**out["receipt"], "ok": True, "check": "verify-staged",
                                            "subject": "root=art", "exit_code": 0}
    (staging / "d" / "x.bin").write_bytes(b"CHANGED")
    code, out = cli(capsys, "artifact-verify", "--manifest", manifest, "--root-id", "art", "--staging", str(staging))
    assert code == 1 and out["receipt"]["ok"] is False and out["result"]["match"] is False


def test_a_wrapper_never_promotes_exit_zero_beside_a_failing_typed_result(tmp_path):
    def lying(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, json.dumps({"match": False}).encode(), b"")

    outcome = adapter.run_canonical(["compare-redis", "--source", "s", "--target", "t"], runner=lying)
    assert outcome["receipt"]["ok"] is False and outcome["receipt"]["exit_code"] == 1

    def garbage(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, b"not json", b"")

    assert adapter.run_canonical(["pel-owners"], runner=garbage)["receipt"]["ok"] is False


# ----- PostgreSQL: one schema per comparison, exact coverage ------------------------------------------
def canonical_inventory(tmp_path, role, schemas):
    contracts = adapter.canonical_module("contracts")
    inventory = {"schema": contracts.PG_SCHEMA, "server_version_num": 171100,
                 "extensions": {"plpgsql": "1.0", "vector": "0.8.6"}, "schemas": {}}
    for name, rows in schemas.items():
        export = tmp_path / f"{role}-{name}.jsonl"
        export.write_text("".join(json.dumps(r) + "\n" for r in rows))
        inventory["schemas"][name] = {"tables": ["documents"], "sequences": {},
                                      "buckets": contracts.pg_schema_from_export(export)}
    return inventory


REGISTRY = {"bucket": "fleet_registry", "id": "fleet", "body": {"repository": "C:\\workspaces\\zeus\\repo"}}
HISTORY = {"bucket": "events", "id": "e1", "body": {"path": "C:\\workspaces\\zeus\\artifacts\\old"}}
LANE = {"bucket": "operations", "id": "o1", "body": {"status": "accepted"}}
MAP = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness"}


def relocated_registry():
    return REGISTRY | {"body": {"repository": "/srv/zeus/repo"}}


def registry_delta():
    mapping = adapter.canonical_module("mapping")
    return {"changes": [{"bucket": "fleet_registry", "id": "fleet",
                         "before_sha256": mapping.body_sha(REGISTRY["body"]),
                         "after_sha256": mapping.body_sha(relocated_registry()["body"])}]}


def test_per_schema_comparison_with_registry_delta_only_on_public(tmp_path):
    source = canonical_inventory(tmp_path, "s", {"public": [REGISTRY, HISTORY], "zeus_fleet_harness": [LANE]})
    target = canonical_inventory(tmp_path, "t", {"zeus_aibox_control": [relocated_registry(), HISTORY],
                                                 "zeus_aibox_harness": [LANE]})
    public = adapter.pg_compare_schema(source, target, MAP, "public", registry_delta())
    lane = adapter.pg_compare_schema(source, target, MAP, "zeus_fleet_harness")
    assert public["receipt"]["ok"] and public["receipt"]["subject"] == "schema=public"
    assert lane["receipt"]["ok"]
    undeclared = adapter.pg_compare_schema(source, target, MAP, "public")
    assert undeclared["receipt"]["ok"] is False and undeclared["canonical_exit"] == 1
    with pytest.raises(MigrationRefused, match="delta_not_allowed"):
        adapter.pg_compare_schema(source, target, MAP, "zeus_fleet_harness", registry_delta())
    history_delta = {"changes": [{**registry_delta()["changes"][0], "bucket": "events", "id": "e1"}]}
    with pytest.raises(MigrationRefused, match="delta_bucket_not_allowed"):
        adapter.pg_compare_schema(source, target, MAP, "public", history_delta)
    coverage = adapter.pg_coverage_receipt(MAP, [public["receipt"], lane["receipt"]])
    assert coverage["receipt"]["ok"] and coverage["receipt"]["check"] == "pg-coverage"
    missing = adapter.pg_coverage_receipt(MAP, [public["receipt"]])
    assert missing["receipt"]["ok"] is False and missing["result"]["missing"] == ["schema=zeus_fleet_harness"]
    twice = adapter.pg_coverage_receipt(MAP, [public["receipt"], public["receipt"], lane["receipt"]])
    assert twice["result"]["duplicated"] == ["schema=public"] and twice["receipt"]["ok"] is False
    failing = adapter.pg_coverage_receipt(MAP, [undeclared["receipt"], lane["receipt"]])
    assert failing["result"]["failed"] == ["schema=public"] and failing["receipt"]["ok"] is False


def test_pg_compare_cli_mismatch_exits_nonzero(tmp_path, capsys):
    source = canonical_inventory(tmp_path, "s", {"public": [REGISTRY], "zeus_fleet_harness": [LANE]})
    target = canonical_inventory(tmp_path, "t", {"zeus_aibox_control": [REGISTRY], "zeus_aibox_harness": []})
    for name, document in (("s.json", source), ("t.json", target), ("map.json", MAP)):
        (tmp_path / name).write_text(json.dumps(document))
    code, out = cli(capsys, "pg-compare-schema", "--source", str(tmp_path / "s.json"), "--target",
                    str(tmp_path / "t.json"), "--schema-map", str(tmp_path / "map.json"),
                    "--source-schema", "zeus_fleet_harness")
    assert code == 1 and out["receipt"]["ok"] is False
    code, _ = cli(capsys, "pg-compare-schema", "--source", str(tmp_path / "s.json"), "--target",
                  str(tmp_path / "t.json"), "--schema-map", str(tmp_path / "map.json"), "--source-schema", "public")
    assert code == 0


# ----- Redis (live, disposable only) -------------------------------------------------------------
REDIS_SOURCE = os.environ.get("ZEUS_MIGRATION_TEST_REDIS_SOURCE")
REDIS_TARGET = os.environ.get("ZEUS_MIGRATION_TEST_REDIS_TARGET")


@pytest.mark.skipif(not (REDIS_SOURCE and REDIS_TARGET), reason="Two disposable Redis servers required")
def test_redis_copy_is_verified_by_the_canonical_comparison(capsys):
    from redis import Redis

    source, target = Redis(unix_socket_path=REDIS_SOURCE), Redis(unix_socket_path=REDIS_TARGET)
    for client in (source, target):
        client.flushall()
    ns = "zeus-fleet-harness"
    source.xadd(ns + ":stream", {"m": "1"}, id="1-0")
    source.xadd(ns + ":stream", {"m": "2"}, id="2-0")
    source.xgroup_create(ns + ":stream", "workers", id="0")
    source.xreadgroup("workers", "consumer-a", {ns + ":stream": ">"}, count=2)
    source.xack(ns + ":stream", "workers", "1-0")
    source.set(ns + ":dedup:x", "done")
    source.set(ns + ":lock:y", "held", px=600000)
    source.set("other:project", "untouched")
    argv = ["redis-copy", "--source-socket", REDIS_SOURCE, "--target-socket", REDIS_TARGET, "--namespace", ns]
    code, out = cli(capsys, *argv)
    assert code == 0 and out["receipt"]["ok"] and out["copy"]["restored"] == 3, out
    assert target.xpending(ns + ":stream", "workers")["pending"] == 1
    assert target.exists("other:project") == 0
    code, out = cli(capsys, *argv)
    assert code == 0 and out["copy"]["already_present"] == 3
    target.set(ns + ":dedup:x", "changed")
    code, out = cli(capsys, *argv)
    assert code == 1 and out["receipt"]["ok"] is False
    time.sleep(0)  # nothing is waited for; expiry is absolute


# ----- systemd service target ------------------------------------------------------------------
class Systemctl:
    def __init__(self, states):
        self.states, self.calls = list(states), []

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        stdout = ""
        if argv[1] == "show":
            state = self.states.pop(0) if self.states else "inactive"
            stdout = f"ActiveState={state}\nMainPID=0\nInvocationID=abc123\n"
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def target(tmp_path, service="zeus-aibox-fleet"):
    return validate_targets({"schema": "urn:zeus:host-delivery-targets:1", "targets": [
        {"target_id": "aibox-fleet", "kind": KIND_SYSTEMD, "root": "/srv/zeus/releases/current",
         "state_dir": str(tmp_path / "state"), "service": service}]})["targets"][0]


DESCRIPTOR = {"schema": "urn:zeus:host-descriptor:1", "target_id": "aibox-fleet",
              "root": "/srv/zeus/releases/current", "revision": COMMIT, "worker_image": IMAGE,
              "profile_digest": H, "predecessor": None}


def test_systemd_target_controls_only_the_registered_zeus_aibox_unit(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    runner = Systemctl(["active", "inactive", "inactive"])
    host = adapter.SystemdHostTarget(runner=runner, control_dir=control)
    registered = target(tmp_path)
    assert host.running(registered) is True
    assert host.stop(registered) == {"stopped": True, "exit_code": 0, "invocation_id": "abc123"}
    with pytest.raises(DeliveryRefused, match="activation_receipt_required"):
        host._launch(registered, DESCRIPTOR, None)
    store = MemoryStore()
    coordinator = HostMigrations(store)
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    coordinator.intend_activation(INTENT)
    adapter.write_activation(control, coordinator.activation_document("aibox-migration-001"))
    (tmp_path / "state").mkdir()
    launched = host._launch(registered, DESCRIPTOR, None)
    assert launched["launch"]["invocation_id"] == "abc123" and launched["launch"]["intent_id"]
    assert all(call[1] in ("show", "start", "stop") for call in runner.calls)  # never reset-failed
    with pytest.raises(DeliveryRefused, match="target_unit_not_allowed"):
        host.running(target(tmp_path, service="sshd"))
    with pytest.raises(RuntimeError, match="unavailable"):
        adapter.SystemdHostTarget(runner=Systemctl(["weird"])).running(registered)


# ----- pg tools, layout, CLI ------------------------------------------------------------------------
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
    dump = adapter.pg_dump("zeus-pg", "postgres", "zeus", "zeus_fleet_harness", "/dump/x.dump", runner=runner)
    assert dump["sha256"] == "d" * 64 and dump["toc_entries"] == 2
    assert all("://" not in arg and "password" not in arg.lower() for call in runner.calls for arg in call)
    restore = Docker()
    adapter.pg_restore("zeus-pg", "postgres", "zeus_aibox", "/dump/x.dump", "zeus_fleet_harness",
                       "zeus_aibox_harness", runner=restore)
    assert restore.calls[-1][-1] == "ALTER SCHEMA zeus_fleet_harness RENAME TO zeus_aibox_harness"
    with pytest.raises(MigrationRefused, match="pg_restore_schema_present"):
        adapter.pg_restore("zeus-pg", "postgres", "zeus_aibox", "/dump/x.dump", "zeus_fleet_harness",
                           "zeus_aibox_harness", runner=Docker(probe="1"))
    with pytest.raises(MigrationRefused, match="public_restore_unsupported"):
        adapter.pg_restore("zeus-pg", "postgres", "zeus_aibox", "/dump/x.dump", "public",
                           "zeus_aibox_control", runner=Docker())
    with pytest.raises(MigrationRefused, match="pg_tool_invalid"):
        adapter.pg_dump("zeus-pg", "postgres", "zeus", "x; DROP", "/dump/x.dump", runner=Docker())


def test_prepare_layout_is_dry_run_by_default_and_idempotent(tmp_path):
    root = tmp_path / "srv-zeus"
    dry = adapter.prepare_layout(root)
    assert not root.exists() and {row["state"] for row in dry["directories"]} == {"would_create"}
    adapter.prepare_layout(root, apply=True)
    assert {row["state"] for row in adapter.prepare_layout(root, apply=True)["directories"]} == {"present"}


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


def test_canonical_tool_is_resolved_from_this_checkout():
    assert adapter.canonical_tool() == ROOT / "scripts" / "aibox_data"
    assert sys.executable
