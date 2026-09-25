"""Host migration (INV-HOST-MIGRATION-001): manifest, coordinator, activation intent, canonical wiring.

Everything here runs on fixture data in temporary directories and the memory store. The canonical
offline tooling (scripts/aibox_data) is invoked through this adapter's CLI as a real subprocess, so
its actual exit code is what the receipts record. The Redis round trip runs only against two
disposable servers named by ZEUS_MIGRATION_TEST_REDIS_SOURCE / ZEUS_MIGRATION_TEST_REDIS_TARGET
(unix socket paths); without them it skips and proves nothing.
"""
from __future__ import annotations

import copy
import hashlib
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


def _can_symlink() -> bool:
    """A real probe: Windows needs a privilege or Developer Mode (WinError 1314 otherwise)."""
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        try:
            os.symlink("target", os.path.join(scratch, "probe"))
        except (OSError, NotImplementedError):
            return False
    return True


needs_symlink = pytest.mark.skipif(not _can_symlink(), reason="this process cannot create symlinks; the "
                                   "link counterexample is untested here, not passed")
posix_permissions = pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                                       reason="needs POSIX directory permissions enforced for a non-root user")
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
    accepted = json.loads((control / "host-activation.json").read_text("utf-8"))
    assert accepted == first.activation_document("aibox-migration-001")
    assert accepted["state"] == "restored_paused" and accepted["intent_id"] == written["intent_id"]
    assert written["sha256"] == hashlib.sha256((control / "host-activation.json").read_bytes()).hexdigest()
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


def test_the_linux_launcher_accepts_exactly_the_coordinator_written_receipt(tmp_path):
    service = launcher()  # skips BEFORE importing the Linux-only tool on a non-POSIX host
    coordinator = HostMigrations(MemoryStore())
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    coordinator.intend_activation(INTENT)
    control = tmp_path / "runtime" / "control"
    control.mkdir(parents=True)
    written = adapter.write_activation(control, coordinator.activation_document("aibox-migration-001"))
    accepted = service.check_activation(control, tmp_path / "releases" / COMMIT, HOST_ID)
    assert accepted["state"] == "restored_paused" and accepted["intent_id"] == written["intent_id"]
    with pytest.raises(service.Refused):
        service.check_activation(control, tmp_path / "releases" / ("9" * 40), HOST_ID)


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


@posix_permissions
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


@needs_symlink
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
    def __init__(self, listing="; header\n1; 2615 SCHEMA\n2; 1259 TABLE\n"):
        self.calls, self.listing = [], listing

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        stdout = {"sha256sum": "d" * 64 + "  /dump/x.dump\n", "pg_restore": self.listing}.get(argv[3], "")
        return subprocess.CompletedProcess(argv, 0, stdout, "")


def test_whole_database_dump_runs_in_the_container_without_a_dsn_and_refuses_an_empty_archive():
    runner = Docker()
    dump = adapter.pg_dump_database("zeus-pg", "zeus", "zeus", "/dump/x.dump", runner=runner)
    assert dump["archive_sha256"] == "d" * 64 and dump["toc_entries"] == 2
    assert runner.calls[0] == ["docker", "exec", "zeus-pg", "pg_dump", "-U", "zeus", "-h", "/var/run/postgresql",
                               "-d", "zeus", "-Fc", "-f", "/dump/x.dump"]  # no -n: the whole database
    assert all("://" not in arg and "password" not in arg.lower() for call in runner.calls for arg in call)
    with pytest.raises(MigrationRefused, match="pg_dump_empty"):
        adapter.pg_dump_database("zeus-pg", "zeus", "zeus", "/dump/x.dump", runner=Docker(listing="; only\n"))
    with pytest.raises(MigrationRefused, match="pg_tool_invalid"):
        adapter.pg_dump_database("zeus-pg", "zeus", "x; DROP", "/dump/x.dump", runner=Docker())


def catalog(**schemas):
    body = {"owner": "zeus", "acl": None, "comment": None, "relations": {}, "indexes": [], "constraints": [],
            "sequences": [], "views": [], "functions": [], "triggers": []}
    return {"schema": policy.CATALOG_SCHEMA, "database": "zeus", "server_version_num": 171100,
            "extensions": [["vector", "0.8.6", "public"]], "extension_members": ["vector"],
            "schemas": {name: {**body, **extra} for name, extra in schemas.items()}}


REL = {"documents": {"kind": "r", "columns": [["embedding", "public.vector", False, None]], "rows": 2,
                     "rows_sha256": H}}
D1 = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness",
      "zeus_fleet_interface": "zeus_aibox_interface", "zeus_team_profile_001": "zeus_team_profile_001"}


def source_catalog():
    fk = {"constraints": [["knowledge_edges", "fk", "f", "FOREIGN KEY (source) REFERENCES public.knowledge_nodes(id)"]]}
    return catalog(public={"relations": copy.deepcopy(REL), **fk}, zeus_fleet_harness={"relations": copy.deepcopy(REL)},
                   zeus_fleet_interface={"relations": copy.deepcopy(REL)},
                   zeus_team_profile_001={"relations": copy.deepcopy(REL)})


def test_rename_plan_is_total_and_allows_public_only_as_the_control_ledger():
    plan = policy.rename_plan(source_catalog(), D1)
    assert plan["renames"] == [["public", "zeus_aibox_control"], ["zeus_fleet_harness", "zeus_aibox_harness"],
                               ["zeus_fleet_interface", "zeus_aibox_interface"]]
    with pytest.raises(MigrationRefused, match="rename_map_not_total"):
        policy.rename_plan(source_catalog(), {k: v for k, v in D1.items() if k != "zeus_team_profile_001"})
    with pytest.raises(MigrationRefused, match="source_public_mapping"):
        policy.rename_plan(source_catalog(), {**D1, "public": "zeus_other"})
    with pytest.raises(MigrationRefused, match="public_schema"):
        policy.rename_plan(source_catalog(), {**D1, "zeus_team_profile_001": "public"})
    with pytest.raises(MigrationRefused, match="rename_target_occupied"):
        policy.rename_plan(source_catalog(), {**D1, "zeus_fleet_harness": "zeus_team_profile_001",
                                              "zeus_team_profile_001": "zeus_team_profile_x"})
    reverse = policy.reverse_maps({"schema_map": D1, "path_map": []})["schema_map"]
    target = catalog(public={}, zeus_aibox_control={"relations": REL}, zeus_aibox_harness={"relations": REL},
                     zeus_aibox_interface={"relations": REL}, zeus_team_profile_001={"relations": REL})
    assert ["zeus_aibox_control", "public"] in policy.rename_plan(target, reverse, reverse=True)["renames"]
    with pytest.raises(MigrationRefused, match="public_schema"):
        policy.rename_plan(target, reverse)  # only an explicit reverse may name public as a target


def test_catalog_comparison_maps_names_but_keeps_extension_references():
    source = source_catalog()
    renamed = copy.deepcopy(source)
    renamed["schemas"] = {D1[k]: v for k, v in renamed["schemas"].items()}
    renamed["schemas"]["zeus_aibox_control"]["constraints"] = [
        ["knowledge_edges", "fk", "f", "FOREIGN KEY (source) REFERENCES zeus_aibox_control.knowledge_nodes(id)"]]
    renamed["schemas"]["public"] = catalog(public={})["schemas"]["public"]  # the bare extension home
    assert policy.compare_catalogs(source, renamed, D1)["match"]
    changed = copy.deepcopy(renamed)
    changed["schemas"]["zeus_aibox_harness"]["relations"]["documents"]["rows"] = 1
    report = policy.compare_catalogs(source, changed, D1)
    assert report["diffs"] == [{"schema": "zeus_aibox_harness", "section": "relations"}]
    typed = copy.deepcopy(renamed)
    typed["schemas"]["zeus_aibox_harness"]["relations"]["documents"]["columns"][0][1] = "zeus_aibox_control.vector"
    assert not policy.compare_catalogs(source, typed, D1)["match"]  # vector must stay in public
    missing = copy.deepcopy(renamed)
    del missing["schemas"]["zeus_team_profile_001"]
    assert {"schema": "zeus_team_profile_001", "section": "missing_on_target"} in \
        policy.compare_catalogs(source, missing, D1)["diffs"]
    other_ext = copy.deepcopy(renamed)
    other_ext["extensions"] = [["vector", "0.8.5", "public"]]
    assert {"schema": None, "section": "extensions"} in policy.compare_catalogs(source, other_ext, D1)["diffs"]


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


# ----- HostDelivery factory wiring of the systemd control directory ---------------------------------
def test_controller_wires_the_configured_control_dir_into_the_systemd_start(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from codex_harness.adapters.host_delivery import controller
    from codex_harness.bootstrap import organization

    root = tmp_path / "srv" / "zeus"
    control = root / "runtime" / "control"
    control.mkdir(parents=True)
    monkeypatch.setenv("ZEUS_AIBOX_ROOT", str(root))
    store = MemoryStore()
    wired = controller(SimpleNamespace(store=store, org=organization()), enabled=False)
    host = wired.hosts[KIND_SYSTEMD]
    assert host.control_dir == str(control) and host.control_reason is None
    host.runner = Systemctl(["inactive"] * 10)  # only the systemctl client is faked
    registered = target(tmp_path)
    host.switch(registered, DESCRIPTOR, expected=None)
    with pytest.raises(DeliveryRefused, match="activation_receipt_required"):
        host.start(registered, DESCRIPTOR)  # the shared lifecycle, before any unit start
    assert not any(call[1] == "start" for call in host.runner.calls)
    coordinator = HostMigrations(store)
    sha = coordinator.plan(manifest())["manifest_sha256"]
    walk(coordinator, sha, "restored_paused")
    coordinator.intend_activation(INTENT)
    adapter.write_activation(control, coordinator.activation_document("aibox-migration-001"))
    started = host.start(registered, DESCRIPTOR)
    assert started["started"] is True and started["launch"]["intent_id"]
    assert [call[1:] for call in host.runner.calls if call[1] == "start"] == [["start", "zeus-aibox-fleet.service"]]


@pytest.mark.parametrize("setting, reason", [(None, "control_dir_unconfigured"), ("relative/root", "control_dir_invalid"),
                                             pytest.param("link", "control_dir_invalid", marks=needs_symlink)])
def test_controller_without_a_valid_control_dir_refuses_the_systemd_start_by_name(tmp_path, monkeypatch,
                                                                                    setting, reason):
    from types import SimpleNamespace

    from codex_harness.adapters.host_delivery import controller
    from codex_harness.bootstrap import organization

    if setting is None:
        monkeypatch.delenv("ZEUS_AIBOX_ROOT", raising=False)
        monkeypatch.delenv("HARNESS_AIBOX_ROOT", raising=False)
    elif setting == "link":
        real = tmp_path / "real" / "runtime" / "control"
        real.mkdir(parents=True)
        (tmp_path / "linked").symlink_to(tmp_path / "real")
        monkeypatch.setenv("ZEUS_AIBOX_ROOT", str(tmp_path / "linked"))
    else:
        monkeypatch.setenv("ZEUS_AIBOX_ROOT", setting)
    wired = controller(SimpleNamespace(store=MemoryStore(), org=organization()), enabled=False)
    host = wired.hosts[KIND_SYSTEMD]
    host.runner = Systemctl(["inactive"] * 10)
    registered = target(tmp_path)
    host.switch(registered, DESCRIPTOR, expected=None)
    with pytest.raises(DeliveryRefused) as refused:
        host.start(registered, DESCRIPTOR)
    assert refused.value.reason_code == reason
    assert not any(call[1] == "start" for call in host.runner.calls)


# ----- source-side command construction (runs on Windows and Linux; no server, no guarantee) --------
class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)


class FakeConnection:
    """Records every statement; answers from a table keyed by a statement prefix."""

    def __init__(self, answers):
        self.answers, self.statements = answers, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        text = statement if isinstance(statement, str) else statement.as_string(None)
        self.statements.append(" ".join(text.split()))
        for prefix, rows in self.answers.items():
            if " ".join(text.split()).startswith(prefix):
                return FakeCursor(rows)
        return FakeCursor([])


def recording_connect(answers):
    calls = []

    def connect(conninfo, **kwargs):
        connection = FakeConnection(answers)
        calls.append({"conninfo": conninfo, "kwargs": kwargs, "connection": connection})
        return connection
    return connect, calls


def test_source_pg_export_is_one_read_only_snapshot_scoped_to_the_schema_with_lf_bytes(tmp_path):
    connect, calls = recording_connect({
        "SELECT current_schema()": [("public",)], "SHOW server_version_num": [("171100",)],
        "SELECT extname": [("plpgsql", "1.0"), ("vector", "0.8.6")],
        "SELECT table_name": [("documents",), ("knowledge_nodes",)], "SELECT sequencename": [],
        "SELECT bucket, id, body": [("events", "e1", {"path": "C:\\workspaces\\zeus\\x"}), ("events", "e2", {"n": 2})]})
    meta, rows = tmp_path / "meta.json", tmp_path / "rows.jsonl"
    result = adapter.pg_export("host=/tmp dbname=zeus user=zeus", "public", "source", meta, rows, connect=connect)
    assert result == {"schema": "public", "role": "source", "rows": 2, "tables": 2}
    statements = calls[0]["connection"].statements
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert "search_path=public" in calls[0]["conninfo"] and "dbname=zeus" in calls[0]["conninfo"]
    data = rows.read_bytes()
    assert b"\r" not in data and data.count(b"\n") == 2  # LF-only on every platform
    assert b"\r" not in meta.read_bytes()
    assert json.loads(data.splitlines()[0])["body"]["path"] == "C:\\workspaces\\zeus\\x"
    with pytest.raises(MigrationRefused, match="public_schema"):
        adapter.pg_export("host=/tmp dbname=zeus", "public", "target", meta, rows, connect=connect)


def test_source_pg_catalog_reads_one_snapshot_with_pg_catalog_search_path():
    connect, calls = recording_connect({"SELECT n.nspname, pg_get_userbyid": [("public", "pg_database_owner", None, None)],
                                        "SHOW server_version_num": [("171100",)]})
    catalog = adapter.pg_catalog("host=C:\\pg dbname=postgres user=zeus", "zeus", connect=connect)
    assert catalog["database"] == "zeus" and catalog["server_version_num"] == 171100
    assert "dbname=zeus" in calls[0]["conninfo"] and "search_path=pg_catalog" in calls[0]["conninfo"]
    assert calls[0]["connection"].statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert not any(s.split()[0] in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
                   for s in calls[0]["connection"].statements)
    with pytest.raises(MigrationRefused, match="pg_tool_invalid"):
        adapter.pg_catalog("host=/tmp", "zeus; DROP", connect=connect)


def test_source_dump_argv_keeps_the_container_path_and_parses_crlf_output_identically():
    lf, crlf = Docker(), Docker(listing="; header\r\n1; 2615 SCHEMA\r\n2; 1259 TABLE\r\n")
    unix = adapter.pg_dump_database("zeus-local-ops-pg", "zeus", "zeus", "/dump/zeus.dump", runner=lf)
    windows = adapter.pg_dump_database("zeus-local-ops-pg", "zeus", "zeus", "/dump/zeus.dump", runner=crlf)
    assert unix == windows  # docker on Windows may print CRLF; the TOC digest must not change
    assert lf.calls[0][:4] == ["docker", "exec", "zeus-local-ops-pg", "pg_dump"]
    assert all(arg == "/dump/zeus.dump" for call in lf.calls for arg in call if arg.endswith(".dump"))


def test_canonical_tool_runs_under_this_interpreter_with_its_checkout_path():
    seen = []

    def runner(argv, **kwargs):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"valid": True}).encode(), b"")

    outcome = adapter.run_canonical(["pel-owners", "--inventory", "C:\\x\\i.json", "--owners", "o.json"], runner=runner)
    assert seen[0][:2] == [sys.executable, str(ROOT / "scripts" / "aibox_data")]
    assert seen[0][2:] == ["pel-owners", "--inventory", "C:\\x\\i.json", "--owners", "o.json"]
    assert outcome["receipt"]["ok"] is True
