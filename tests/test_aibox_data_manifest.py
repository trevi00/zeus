"""aibox data-transfer tooling (scripts/aibox_data). Isolated fixtures only: temp directories and
hand-built inventory documents. No PostgreSQL/Redis server, credentials or production path is used,
so these tests prove the offline contracts, not a real export, restore or cutover."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aibox_data import cli, contracts, gates, inventory, mapping, transfer  # noqa: E402

SHA = "sha256:" + "a" * 64


def put_artifact(root: Path, body: bytes, meta: dict | None = None) -> str:
    key = hashlib.sha256(body).hexdigest()
    (root / f"{key}.txt").write_bytes(body)
    (root / f"{key}.json").write_text(json.dumps(meta or {"ref": "sha256:" + key, "bytes": len(body),
                                                          "source": "fixture", "at": "t"}))
    return key


@pytest.fixture
def tree(tmp_path):
    source = tmp_path / "source"
    (source / "logs").mkdir(parents=True)
    (source / "logs" / "run.log").write_bytes(b"line\n" * 1000)
    (source / "big.bin").write_bytes(os.urandom(3 * 1024 * 1024 + 17))
    (source / "empty.txt").write_bytes(b"")
    os.symlink("logs/run.log", source / "latest")
    return source


# --- inventory and manifest -------------------------------------------------------------------

def test_manifest_records_bytes_hashes_and_links_without_following(tree, tmp_path):
    os.symlink(str(tmp_path), tree / "outside")
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "fixture-host")
    entries = {e["path"]: e for e in manifest["roots"]["art"]["entries"]}
    big = tree / "big.bin"
    assert entries["big.bin"]["sha256"] == hashlib.sha256(big.read_bytes()).hexdigest()
    assert entries["big.bin"]["bytes"] == big.stat().st_size
    assert entries["latest"] == {"path": "latest", "kind": "symlink", "link_target": "logs/run.log",
                                 "escapes_root": False}
    assert entries["outside"]["escapes_root"] is True
    assert manifest["roots"]["art"]["findings"]["external_symlinks"] == ["outside"]
    assert inventory.verify_manifest_digest(manifest)


def test_manifest_digest_is_stable_and_detects_tampering(tree):
    first = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    os.utime(tree / "empty.txt", (1, 1))  # mtime is descriptive, not identity
    assert inventory.build_manifest("mig-1", {"art": str(tree)}, "h")["digest"] == first["digest"]
    first["roots"]["art"]["entries"][0]["bytes"] += 1
    assert not inventory.verify_manifest_digest(first)


def test_case_collisions_and_windows_names_are_reported(tmp_path):
    (tmp_path / "Report.json").write_text("a")
    (tmp_path / "report.JSON").write_text("b")
    (tmp_path / "con.txt").write_text("c")
    (tmp_path / "bad:name").write_text("d")
    found = inventory.scan_root(tmp_path)["findings"]
    assert found["case_collisions"] == [["Report.json", "report.JSON"]]
    problems = {item["path"]: item["problems"] for item in found["windows_incompatible"]}
    assert problems == {"con.txt": ["reserved_name"], "bad:name": ["invalid_character"]}


def test_artifact_store_verification_matches_file_artifacts_rules(tmp_path):
    good = put_artifact(tmp_path, b"hello")
    bad_bytes = put_artifact(tmp_path, b"world", {"ref": "sha256:" + hashlib.sha256(b"world").hexdigest(),
                                                 "bytes": 99})
    modified = put_artifact(tmp_path, b"original")
    (tmp_path / f"{modified}.txt").write_bytes(b"tampered")
    orphan = "b" * 64
    (tmp_path / f"{orphan}.json").write_text("{}")
    report = inventory.verify_artifact_store(tmp_path)
    assert {(p["key"], p["problem"]) for p in report["problems"]} == {
        (bad_bytes, "metadata_bytes_mismatch"), (modified, "body_hash_mismatch"),
        (orphan, "orphan_metadata")}
    assert good not in {p["key"] for p in report["problems"]}
    assert not report["valid"]


def test_artifact_store_accepts_real_file_artifacts_output(tmp_path):
    from codex_harness.adapters.artifacts import FileArtifacts
    store = FileArtifacts(str(tmp_path / "artifacts"))
    store.put("evidence body", "fixture")
    assert inventory.verify_artifact_store(tmp_path / "artifacts")["valid"]


def test_path_references_are_reported_not_rewritten(tmp_path):
    log = tmp_path / "old.log"
    log.write_text('run at D:\\workspaces\\zeus\\artifacts\\x and "C:/Users/rudtn/zeus/y"\n')
    before = log.read_bytes()
    report = inventory.scan_path_references(tmp_path)
    assert report["files_with_windows_paths"][0]["count"] == 2
    assert log.read_bytes() == before


# --- staged copy, resume and refusal ----------------------------------------------------------

def test_stage_copies_verifies_and_is_idempotent(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging, journal = tmp_path / "staging", tmp_path / "journal.json"
    first = transfer.stage_root(manifest, "art", tree, staging, journal)
    assert first["status"] == "complete"
    assert transfer.verify_staged(manifest, "art", staging)["match"]
    assert os.readlink(staging / "latest") == "logs/run.log"
    second = transfer.stage_root(manifest, "art", tree, staging, journal)
    assert {e["action"] for e in second["events"]} == {"verified_existing"}


def test_interrupted_copy_resumes_from_verified_partial(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging, journal = tmp_path / "staging", tmp_path / "journal.json"
    stopped = transfer.stage_root(manifest, "art", tree, staging, journal, limit_bytes=1024 * 1024)
    assert stopped["status"] == "interrupted"
    part = staging / "big.bin.part"
    assert part.exists() and 0 < part.stat().st_size < (tree / "big.bin").stat().st_size
    assert not transfer.verify_staged(manifest, "art", staging)["match"]
    resumed = transfer.stage_root(manifest, "art", tree, staging, journal)
    big = next(e for e in resumed["events"] if e["path"] == "big.bin")
    assert big["resumed_from_bytes"] == 1024 * 1024
    assert (staging / "big.bin").read_bytes() == (tree / "big.bin").read_bytes()
    assert transfer.verify_staged(manifest, "art", staging)["match"]


def test_diverged_partial_and_conflicting_staged_file_are_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "big.bin.part").write_bytes(b"not the source prefix")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, staging, tmp_path / "j.json")
    assert refused.value.reason == "partial_diverged"
    (staging / "big.bin.part").unlink()
    (staging / "empty.txt").write_bytes(b"different")
    with pytest.raises(transfer.TransferRefused) as conflict:
        transfer.stage_root(manifest, "art", tree, staging, tmp_path / "j2.json")
    assert conflict.value.reason == "staged_conflict"
    assert (staging / "empty.txt").read_bytes() == b"different"  # never overwritten


def test_source_change_after_seal_is_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    (tree / "logs" / "run.log").write_bytes(b"changed after seal")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "j.json")
    assert refused.value.reason == "source_changed_after_seal"
    assert not (tmp_path / "staging" / "logs" / "run.log").exists()


def test_same_migration_id_with_different_digest_is_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    journal = tmp_path / "j.json"
    transfer.stage_root(manifest, "art", tree, tmp_path / "staging", journal)
    (tree / "new.txt").write_text("new")
    changed = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(changed, "art", tree, tmp_path / "staging", journal)
    assert refused.value.reason == "journal_binding_mismatch"


def test_external_symlink_is_not_created_and_blocks_verification(tree, tmp_path):
    os.symlink("/etc/hostname", tree / "outside")
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    report = transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "j.json")
    assert report["status"] == "needs_decision"
    assert not os.path.lexists(tmp_path / "staging" / "outside")
    assert transfer.verify_staged(manifest, "art", tmp_path / "staging")["missing"] == ["outside"]


# --- mapping allowlist ------------------------------------------------------------------------

ALLOWLIST = {"schema": mapping.ALLOWLIST_SCHEMA,
             "fields": [{"bucket": "lanes", "path": ["runtime", "root"]}],
             "immutable_buckets": ["audit"],
             "prefix_rules": [{"source": "D:/workspaces/zeus/", "target": "/srv/zeus/"}]}


def test_binding_plan_maps_only_allowlisted_fields_with_receipt():
    rows = [{"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "D:\\workspaces\\zeus\\runtime\\l1"},
                                                      "note": "D:\\workspaces\\zeus\\keep"}},
            {"bucket": "audit", "id": "a1", "body": {"runtime": {"root": "D:/workspaces/zeus/x"}}}]
    plan = mapping.plan_binding_changes(rows, ALLOWLIST)
    assert plan["valid"]
    [change] = plan["receipt"]["changes"]
    assert change["fields"] == [{"path": ["runtime", "root"], "before": "D:\\workspaces\\zeus\\runtime\\l1",
                                 "after": "/srv/zeus/runtime/l1"}]
    assert change["before_sha256"] == mapping.body_sha(rows[0]["body"])
    assert rows[0]["body"]["runtime"]["root"] == "D:\\workspaces\\zeus\\runtime\\l1"  # input untouched


def test_binding_plan_refuses_unmapped_and_parent_escape():
    rows = [{"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "C:/Users/rudtn/zeus"}}},
            {"bucket": "lanes", "id": "l2", "body": {"runtime": {"root": "D:/workspaces/zeus/../x"}}}]
    plan = mapping.plan_binding_changes(rows, ALLOWLIST)
    assert not plan["valid"]
    assert [r["reason"] for r in plan["refused"]] == ["no_prefix_rule", "parent_segment"]


def test_allowlist_rejects_mapping_an_immutable_bucket():
    bad = dict(ALLOWLIST, fields=[{"bucket": "audit", "path": ["x"]}])
    assert "immutable_bucket_mapped:audit" in mapping.validate_allowlist(bad)


# --- PostgreSQL inventory contract ------------------------------------------------------------

def pg_inventory(tmp_path, name, rows, sequences=None):
    export = tmp_path / f"{name}.jsonl"
    export.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"schema": contracts.PG_SCHEMA, "server_version_num": 170004,
            "extensions": {"plpgsql": "1.0", "vector": "0.8.0"},
            "schemas": {name: {"tables": ["documents"], "sequences": sequences or {"s": 5},
                               "buckets": contracts.pg_schema_from_export(export)}}}


def test_pg_comparison_accepts_identity_and_receipted_delta(tmp_path):
    rows = [{"bucket": "lanes", "id": "l1", "body": {"runtime": {"root": "D:/workspaces/zeus/r"}}},
            {"bucket": "tasks", "id": "t1", "body": {"b": 1, "a": 2}}]
    source = pg_inventory(tmp_path, "zeus_control", rows)
    plan = mapping.plan_binding_changes(rows, ALLOWLIST)
    mapped = [rows[0] | {"body": {"runtime": {"root": "/srv/zeus/r"}}},
              {"bucket": "tasks", "id": "t1", "body": {"a": 2, "b": 1}}]  # key order is not identity
    target = pg_inventory(tmp_path, "zeus_aibox_control", mapped)
    result = contracts.compare_pg(source, target, {"zeus_control": "zeus_aibox_control"},
                                  plan["receipt"])
    assert result["match"], result
    unreceipted = contracts.compare_pg(source, target, {"zeus_control": "zeus_aibox_control"})
    assert [r["problem"] for r in unreceipted["rows"]] == ["changed"]


def test_pg_comparison_rejects_missing_rows_public_and_version_skew(tmp_path):
    source = pg_inventory(tmp_path, "zeus_control", [{"bucket": "t", "id": "1", "body": {}},
                                                     {"bucket": "t", "id": "2", "body": {}}])
    target = pg_inventory(tmp_path, "zeus_aibox_control", [{"bucket": "t", "id": "1", "body": {}}],
                          sequences={"s": 4})
    target["server_version_num"] = 180000
    result = contracts.compare_pg(source, target, {"zeus_control": "zeus_aibox_control"})
    assert "server_major_mismatch" in result["problems"]
    assert "sequence_behind:zeus_control.s" in result["problems"]
    assert result["rows"] == [{"schema": "zeus_control", "bucket": "t", "id": "2", "problem": "missing"}]
    public = pg_inventory(tmp_path, "public", [])
    assert "schema_name:public" in contracts.validate_pg(public)


def test_pg_export_rejects_duplicate_rows(tmp_path):
    export = tmp_path / "x.jsonl"
    export.write_text('{"bucket":"t","id":"1","body":{}}\n{"bucket":"t","id":"1","body":{}}\n')
    with pytest.raises(ValueError, match="duplicate"):
        contracts.pg_schema_from_export(export)


# --- Redis stream/group/PEL inventory contract ------------------------------------------------

def redis_inventory(pending=None, expire=None, captured=1_000):
    pending = [{"id": "5-0", "consumer": "c1", "deliveries": 1}] if pending is None else pending
    return {"schema": contracts.REDIS_SCHEMA, "captured_at_ms": captured, "namespace_prefixes": ["zeus"],
            "keys": {"zeus:agent:claude": {"type": "stream", "expire_at_ms": None},
                     "zeus:dedup:m1": {"type": "string", "expire_at_ms": expire, "dump_sha256": "c" * 64}},
            "streams": {"zeus:agent:claude": {
                "length": 3, "last_generated_id": "7-0", "entries_sha256": "d" * 64,
                "groups": {"workers": {"last_delivered_id": "6-0",
                                       "consumers": {"c1": len(pending)} if pending else {},
                                       "pending": pending}}}}}


def test_redis_comparison_preserves_groups_pel_and_absolute_expiry():
    source = redis_inventory(expire=5_000)
    assert contracts.validate_redis(source) == []
    assert contracts.compare_redis(source, redis_inventory(expire=5_000, captured=2_000))["match"]


def test_redis_comparison_rejects_dropped_pel_and_extended_ttl():
    source = redis_inventory(expire=5_000)
    target = redis_inventory(pending=[], expire=9_000)
    problems = {d["problem"] for d in contracts.compare_redis(source, target)["diffs"]}
    assert problems == {"pel_dropped", "consumers", "ttl_extended"}


def test_redis_key_expired_during_downtime_is_classified_not_missing():
    source = redis_inventory(expire=1_500)
    target = redis_inventory(expire=1_500, captured=2_000)
    del target["keys"]["zeus:dedup:m1"]
    result = contracts.compare_redis(source, target)
    assert result["match"] and result["expired_during_downtime"] == ["zeus:dedup:m1"]
    early = redis_inventory(expire=1_500, captured=1_200)
    del early["keys"]["zeus:dedup:m1"]
    assert not contracts.compare_redis(source, early)["match"]


def test_redis_validation_rejects_out_of_allowlist_keys_and_impossible_pel():
    inventory_doc = redis_inventory(pending=[{"id": "9-0", "consumer": "c1", "deliveries": 1}])
    inventory_doc["keys"]["other:app"] = {"type": "string", "expire_at_ms": None, "dump_sha256": "c" * 64}
    problems = contracts.validate_redis(inventory_doc)
    assert "key_outside_allowlist:other:app" in problems
    assert "pel_id:zeus:agent:claude/workers/9-0" in problems


def test_stream_entries_digest_depends_on_ids_and_fields_not_field_order():
    first = contracts.stream_entries_sha256([("1-0", {"body": "a", "x": "1"})])
    assert first == contracts.stream_entries_sha256([("1-0", {"x": "1", "body": "a"})])
    assert first != contracts.stream_entries_sha256([("1-1", {"body": "a", "x": "1"})])


def test_pending_entries_must_map_to_pg_owner():
    doc = redis_inventory()
    assert contracts.check_pel_owners(doc, {})["unowned"] == ["zeus:agent:claude/workers/5-0"]
    owners = {"zeus:agent:claude/workers/5-0": {"bucket": "operations", "id": "op-1"}}
    assert contracts.check_pel_owners(doc, owners)["valid"]


# --- rollback and retirement gates ------------------------------------------------------------

R0_OK = {"target_authoritative_writes": 0, "target_external_effects": 0, "target_fenced": True,
         "target_writer_count": 0, "source_sealed_digest": SHA, "source_current_digest": SHA,
         "source_runtime_pointer_unchanged": True, "source_single_owner_confirmed": True}


def test_r0_requires_untouched_source_and_silent_target():
    assert gates.rollback_r0(R0_OK)["eligible"]
    assert gates.rollback_r0(R0_OK | {"target_authoritative_writes": 3})["reasons"] == ["target_has_written_use_r1"]
    changed = gates.rollback_r0(R0_OK | {"source_current_digest": "sha256:" + "b" * 64})
    assert changed["reasons"] == ["source_changed_since_seal"]
    assert "target_fenced_not_confirmed" in gates.rollback_r0({k: v for k, v in R0_OK.items()
                                                               if k != "target_fenced"})["reasons"]


R1_OK = {"target_reachable": True, "target_admission_stopped": True, "target_fenced": True,
         "reverse_file_manifest_match": True, "reverse_pg_match": True, "reverse_redis_match": True,
         "reverse_mapping_roundtrip_verified": True, "windows_runtime_binding_receipt": True,
         "single_owner_resume_planned": True, "target_writer_count": 0, "unknown_external_effects": 0,
         "windows_incompatible_names": 0, "case_collisions": 0,
         "windows_restore_db_identity": "win-restore-2", "original_snapshot_identity": "win-snap-1",
         "external_effects": [{"id": "pr-201", "disposition": "reconciled_no_rerun"}]}


def test_r1_refuses_old_snapshot_reuse_and_unreconciled_effects():
    assert gates.rollback_r1(R1_OK)["eligible"]
    reuse = gates.rollback_r1(R1_OK | {"windows_restore_db_identity": "win-snap-1"})
    assert reuse["reasons"] == ["old_windows_snapshot_reuse_refused"]
    rerun = gates.rollback_r1(R1_OK | {"external_effects": [{"id": "merge", "disposition": "rerun"}]})
    assert rerun["reasons"] == ["external_effect_unreconciled:merge"]
    unreachable = gates.rollback_r1(R1_OK | {"target_reachable": False})
    assert unreachable["reasons"] == ["target_unreachable_close_both_admissions_and_report_incident"]


C_ITEM = {"absolute_path": "D:/workspaces/zeus/runtime", "owner": "zeus", "kind": "runtime",
          "prior_sha256": SHA, "dirty_ignored_checked": True, "server_copy_verified": True}
C_OK = {"completion_state": "autonomous_qualified", "a_accepted": True, "b_accepted": True,
        "backup_restore_verified": True, "server_references_resolved_without_windows": True,
        "windows_observer_disabled": True, "unresolved_windows_references": 0,
        "deletion_manifest": [C_ITEM]}


def test_retirement_gate_c_requires_a_b_backup_and_exact_items():
    assert gates.retirement_gate_c(C_OK)["eligible"]
    limited = gates.retirement_gate_c(C_OK | {"completion_state": "migrated_limited", "b_accepted": False})
    assert set(limited["reasons"]) == {"b_acceptance_missing", "b_accepted_not_confirmed"}
    protected = [C_ITEM | {"absolute_path": "C:/Users/rudtn/.claude"},
                 C_ITEM | {"absolute_path": "flexday-pg", "kind": "shared"},
                 C_ITEM | {"kind": "claude_harness_original"},
                 C_ITEM | {"dirty_ignored_checked": None}]
    result = gates.retirement_gate_c(C_OK | {"deletion_manifest": protected})
    assert [item["problems"] for item in result["blocked_items"]] == [
        ["protected_or_not_zeus_owned"], ["absolute_path"],
        ["original_harness_absorption_unconfirmed"], ["dirty_ignored_not_checked"]]
    assert result["action"] == "none_performed"


# --- CLI --------------------------------------------------------------------------------------

def test_cli_inventory_stage_verify_roundtrip(tree, tmp_path, capsys):
    out = tmp_path / "manifest.json"
    assert cli.main(["inventory", "--migration-id", "mig-1", "--root", f"art={tree}",
                     "--host", "fixture", "--out", str(out)]) == 0
    capsys.readouterr()
    assert cli.main(["stage", "--manifest", str(out), "--root-id", "art", "--source", str(tree),
                     "--staging", str(tmp_path / "s"), "--journal", str(tmp_path / "j.json")]) == 0
    capsys.readouterr()
    assert cli.main(["verify-staged", "--manifest", str(out), "--root-id", "art",
                     "--staging", str(tmp_path / "s")]) == 0
    assert json.loads(capsys.readouterr().out)["match"] is True
    evidence = tmp_path / "r0.json"
    evidence.write_text(json.dumps(R0_OK | {"target_fenced": False}))
    assert cli.main(["gate", "r0", "--evidence", str(evidence)]) == 1
    assert cli.main(["gate", "bogus", "--evidence", str(evidence)]) == 2
