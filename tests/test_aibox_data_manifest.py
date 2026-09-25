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


def _can_symlink() -> bool:
    """Whether this process may create symlinks here (Windows needs a privilege or Developer Mode;
    WinError 1314 otherwise). Probed for real, never assumed from the platform name."""
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        try:
            os.symlink("target", os.path.join(scratch, "probe"))
        except (OSError, NotImplementedError):
            return False
    return True


SYMLINKS = _can_symlink()
needs_symlink = pytest.mark.skipif(not SYMLINKS, reason="this process cannot create symlinks "
                                   "(e.g. Windows without SeCreateSymbolicLinkPrivilege); link handling is untested here")
# POSIX permission bits: chmod(0) blocks a directory listing only on POSIX, and never for root.
posix_permissions = pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0,
                                       reason="needs POSIX directory permissions enforced for a non-root user")


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
    if SYMLINKS:  # the staging/verification tests run either way; link-specific ones are marked
        os.symlink("logs/run.log", source / "latest")
    return source


# --- inventory and manifest -------------------------------------------------------------------

@needs_symlink
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


@pytest.mark.skipif(os.name == "nt", reason="the fixture needs a case-sensitive filesystem that can hold "
                    "`bad:name` and `con.txt` (on NTFS these are one file, an alternate stream and a device)")
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

def partial_of(work: Path, root_id: str, relative: str) -> Path:
    return work / "partials" / (hashlib.sha256(f"{root_id}\0{relative}".encode()).hexdigest() + ".part")


def test_stage_copies_verifies_and_is_idempotent(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging, work = tmp_path / "staging", tmp_path / "work"
    first = transfer.stage_root(manifest, "art", tree, staging, work)
    assert first["status"] == "complete"
    assert transfer.verify_staged(manifest, "art", staging, work)["match"]
    if SYMLINKS:
        assert os.readlink(staging / "latest") == "logs/run.log"
    assert sorted(os.listdir(work)) == ["journal.json", "partials"]  # no state inside staging
    second = transfer.stage_root(manifest, "art", tree, staging, work)
    assert {e["action"] for e in second["events"]} == {"verified_existing"}


def test_interrupted_copy_resumes_from_verified_partial(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging, work = tmp_path / "staging", tmp_path / "work"
    stopped = transfer.stage_root(manifest, "art", tree, staging, work, limit_bytes=1024 * 1024)
    assert stopped["status"] == "interrupted"
    part = partial_of(work, "art", "big.bin")
    assert part.exists() and 0 < part.stat().st_size < (tree / "big.bin").stat().st_size
    assert not os.path.lexists(staging / "big.bin")
    interrupted = transfer.verify_staged(manifest, "art", staging, work)
    assert not interrupted["match"] and interrupted["partials"] == [part.name]
    resumed = transfer.stage_root(manifest, "art", tree, staging, work)
    big = next(e for e in resumed["events"] if e["path"] == "big.bin")
    assert big["resumed_from_bytes"] == 1024 * 1024
    assert (staging / "big.bin").read_bytes() == (tree / "big.bin").read_bytes()
    assert transfer.verify_staged(manifest, "art", staging, work)["match"]


def test_diverged_partial_and_conflicting_staged_file_are_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging, work = tmp_path / "staging", tmp_path / "work"
    assert transfer.stage_root(manifest, "art", tree, staging, work, limit_bytes=1024)["status"] == "interrupted"
    partial_of(work, "art", "big.bin").write_bytes(b"not the source prefix")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, staging, work)
    assert refused.value.reason == "partial_diverged"
    staging.mkdir(exist_ok=True)
    (staging / "empty.txt").write_bytes(b"different")
    with pytest.raises(transfer.TransferRefused) as conflict:
        transfer.stage_root(manifest, "art", tree, staging, tmp_path / "work2")
    assert conflict.value.reason == "staged_conflict"
    assert (staging / "empty.txt").read_bytes() == b"different"  # never overwritten


def test_source_change_after_seal_is_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    (tree / "logs" / "run.log").write_bytes(b"changed after seal")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "work")
    assert refused.value.reason == "source_changed_after_seal"
    assert not (tmp_path / "staging" / "logs" / "run.log").exists()


def test_same_migration_id_with_different_digest_is_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    work = tmp_path / "work"
    transfer.stage_root(manifest, "art", tree, tmp_path / "staging", work)
    (tree / "new.txt").write_text("new")
    changed = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(changed, "art", tree, tmp_path / "staging", work)
    assert refused.value.reason == "journal_binding_mismatch"


@needs_symlink
def test_external_symlink_is_not_created_and_blocks_verification(tree, tmp_path):
    os.symlink("/etc/hostname", tree / "outside")
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    report = transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "work")
    assert report["status"] == "blocked"
    assert report["blocking"]["external_symlinks"] == ["outside"]
    assert not os.path.lexists(tmp_path / "staging" / "outside")
    verified = transfer.verify_staged(manifest, "art", tmp_path / "staging")
    assert verified["missing"] == ["outside"] and not verified["match"]


# Review defect 2 (b7cbe79): a symlinked destination ancestor was followed and written through.

@needs_symlink
def test_symlinked_staging_ancestor_is_refused_before_any_write(tmp_path):
    source, staging, outside = tmp_path / "source", tmp_path / "staging", tmp_path / "outside"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "evidence").write_bytes(b"proof")
    staging.mkdir()
    outside.mkdir()
    os.symlink(outside, staging / "sub")
    manifest = inventory.build_manifest("mig-1", {"art": str(source)}, "h")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", source, staging, tmp_path / "work")
    assert refused.value.reason == "staging_ancestor_symlink"
    assert os.listdir(outside) == []
    assert os.listdir(tmp_path / "work" / "partials") == []
    assert not transfer.verify_staged(manifest, "art", staging)["match"]


@needs_symlink
def test_symlinked_nested_ancestor_created_after_first_level_is_refused(tmp_path):
    source, staging, outside = tmp_path / "source", tmp_path / "staging", tmp_path / "outside"
    (source / "a" / "b").mkdir(parents=True)
    (source / "a" / "b" / "f").write_bytes(b"x")
    (staging / "a").mkdir(parents=True)
    outside.mkdir()
    os.symlink(outside, staging / "a" / "b")
    manifest = inventory.build_manifest("mig-1", {"art": str(source)}, "h")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", source, staging, tmp_path / "work")
    assert refused.value.reason == "staging_ancestor_symlink"
    assert os.listdir(outside) == []


@needs_symlink
def test_symlinked_staging_root_work_dir_partial_and_journal_are_refused(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, tmp_path / "staging-link")
    with pytest.raises(transfer.TransferRefused) as root_link:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging-link", tmp_path / "w1")
    assert root_link.value.reason == "staging_root_symlink"
    os.symlink(outside, tmp_path / "work-link")
    with pytest.raises(transfer.TransferRefused) as work_link:
        transfer.stage_root(manifest, "art", tree, tmp_path / "s2", tmp_path / "work-link")
    assert work_link.value.reason == "work_dir_symlink"
    victim = outside / "victim"
    victim.write_bytes(b"keep")
    work = tmp_path / "w3"
    transfer.stage_root(manifest, "art", tree, tmp_path / "s3", work, limit_bytes=1024)
    partial_of(work, "art", "big.bin").unlink()
    os.symlink(victim, partial_of(work, "art", "big.bin"))
    with pytest.raises(transfer.TransferRefused) as part_link:
        transfer.stage_root(manifest, "art", tree, tmp_path / "s3", work)
    assert part_link.value.reason == "partial_not_regular"
    work4 = tmp_path / "w4"
    work4.mkdir()
    os.symlink(victim, work4 / "journal.json")
    with pytest.raises(transfer.TransferRefused) as journal_link:
        transfer.stage_root(manifest, "art", tree, tmp_path / "s4", work4)
    assert journal_link.value.reason == "journal_not_regular"
    assert victim.read_bytes() == b"keep" and os.listdir(outside) == ["victim"]


def test_work_dir_must_be_migration_owned_and_separate(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("someone else's")
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging", foreign)
    assert refused.value.reason == "work_dir_not_migration_owned"
    with pytest.raises(transfer.TransferRefused) as inside:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "staging" / "w")
    assert inside.value.reason == "work_dir_overlaps"
    with pytest.raises(transfer.TransferRefused) as overlap:
        transfer.stage_root(manifest, "art", tree, tree / "copy", tmp_path / "work")
    assert overlap.value.reason == "staging_overlaps_source"


def test_unsafe_manifest_paths_are_refused_even_with_a_valid_digest(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    manifest["roots"]["art"]["entries"][0]["path"] = "../escape"
    manifest["digest"] = inventory.manifest_digest(manifest)
    with pytest.raises(transfer.TransferRefused) as refused:
        transfer.stage_root(manifest, "art", tree, tmp_path / "staging", tmp_path / "work")
    assert refused.value.reason == "unsafe_manifest_path"
    assert not (tmp_path / "escape").exists()


# Review defect 3 (b7cbe79): an unreadable source subtree staged "complete" and verified as a match.

@posix_permissions
def test_unreadable_source_subtree_blocks_stage_and_verification(tmp_path):
    source = tmp_path / "source"
    (source / "denied").mkdir(parents=True)
    (source / "denied" / "proof.txt").write_bytes(b"hidden")
    os.chmod(source / "denied", 0)
    try:
        manifest = inventory.build_manifest("mig-1", {"art": str(source)}, "h")
    finally:
        os.chmod(source / "denied", 0o700)
    root = manifest["roots"]["art"]
    assert root["entries"] == [] and root["unreadable"] == [{"path": "denied", "error": "PermissionError"}]
    report = transfer.stage_root(manifest, "art", source, tmp_path / "staging", tmp_path / "work")
    assert report["status"] == "blocked"
    assert report["blocking"]["source_unreadable"] == ["denied"]
    verified = transfer.verify_staged(manifest, "art", tmp_path / "staging", tmp_path / "work")
    assert not verified["match"] and verified["source_unreadable"] == ["denied"]
    assert inventory.compare_roots(root, root)["match"] is False


def test_truly_empty_root_stages_and_verifies(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest = inventory.build_manifest("mig-1", {"art": str(source)}, "h")
    report = transfer.stage_root(manifest, "art", source, tmp_path / "staging", tmp_path / "work")
    assert report == {"status": "complete", "blocking": {"source_unreadable": [], "special_files": [],
                                                        "external_symlinks": []},
                      "events": [], "journal": str(tmp_path / "work" / "journal.json")}
    assert transfer.verify_staged(manifest, "art", tmp_path / "staging", tmp_path / "work")["match"]


# Review defect 4 (b7cbe79): a legitimate source file ending in .part was hidden by suffix exclusion.

def test_source_files_named_part_stage_and_verify_under_real_names(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "log").write_bytes(os.urandom(2 * 1024 * 1024))
    (source / "log.part").write_bytes(b"a real file whose name ends in .part\n")
    (source / "big.bin.part").write_bytes(b"another")
    manifest = inventory.build_manifest("mig-1", {"art": str(source)}, "h")
    staging, work = tmp_path / "staging", tmp_path / "work"
    stopped = transfer.stage_root(manifest, "art", source, staging, work, limit_bytes=1024 * 1024)
    assert stopped["status"] == "interrupted"
    assert [e["path"] for e in stopped["events"]] == ["big.bin.part", "log"]
    assert (staging / "big.bin.part").read_bytes() == b"another"
    assert not os.path.lexists(staging / "log")
    resumed = transfer.stage_root(manifest, "art", source, staging, work)
    assert resumed["status"] == "complete"
    # The byte budget is shared: big.bin.part consumed 7 bytes before log was interrupted.
    assert next(e for e in resumed["events"] if e["path"] == "log")["resumed_from_bytes"] == 1024 * 1024 - 7
    for name in ("log", "log.part", "big.bin.part"):
        assert (staging / name).read_bytes() == (source / name).read_bytes()
    verified = transfer.verify_staged(manifest, "art", staging, work)
    assert verified["match"], verified
    assert verified["partials"] == [] and verified["missing"] == []


def test_leftover_staged_part_named_file_is_extra_not_hidden(tree, tmp_path):
    manifest = inventory.build_manifest("mig-1", {"art": str(tree)}, "h")
    staging = tmp_path / "staging"
    transfer.stage_root(manifest, "art", tree, staging, tmp_path / "work")
    (staging / "stray.part").write_bytes(b"not in the manifest")
    verified = transfer.verify_staged(manifest, "art", staging, tmp_path / "work")
    assert verified["extra"] == ["stray.part"] and not verified["match"]


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
    assert "schema_name:public" in contracts.validate_pg(public, "target")


# Review defect 1 (b7cbe79): the real source keeps its control ledger in `public`
# (aibox-migration-001/source-inventory.json lists `public` plus lane schemas such as
# zeus_asset_operation_001). Names below mirror that inventory; the rows are fixtures.

def two_schema_inventory(tmp_path, names, rows):
    merged = None
    for name in names:
        one = pg_inventory(tmp_path, name, rows)
        merged = one if merged is None else merged | {"schemas": merged["schemas"] | one["schemas"]}
    return merged


def test_source_public_control_schema_is_supported(tmp_path):
    rows = [{"bucket": "audit_progress_windows", "id": "w1", "body": {"n": 1}}]
    source = two_schema_inventory(tmp_path, ["public", "zeus_asset_operation_001"], rows)
    target = two_schema_inventory(tmp_path, ["zeus_aibox_control", "zeus_aibox_asset_operation_001"], rows)
    assert contracts.validate_pg(source, "source") == []
    schema_map = {"public": "zeus_aibox_control",
                  "zeus_asset_operation_001": "zeus_aibox_asset_operation_001"}
    assert contracts.compare_pg(source, target, schema_map)["match"]


def test_public_stays_forbidden_as_target_schema_and_map_destination(tmp_path):
    rows = [{"bucket": "t", "id": "1", "body": {}}]
    source = pg_inventory(tmp_path, "public", rows)
    target = pg_inventory(tmp_path, "public", rows)
    assert contracts.validate_pg(target, "target") == ["schema_name:public"]
    result = contracts.compare_pg(source, target, {"public": "public"})
    assert result["problems"] == ["target:schema_name:public"]
    ok_target = pg_inventory(tmp_path, "zeus_aibox_control", rows)
    mapped_to_public = contracts.compare_pg(source, ok_target, {"public": "public"})
    assert "schema_map_not_injective_or_public" in mapped_to_public["problems"]
    with pytest.raises(ValueError):
        contracts.validate_pg(source, "either")


def test_cli_pg_inventory_requires_role_and_accepts_source_public(tmp_path, capsys):
    export = tmp_path / "public.jsonl"
    export.write_text('{"bucket":"tasks","id":"t1","body":{"a":1}}\n')
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"schema": contracts.PG_SCHEMA, "server_version_num": 170011,
                                "extensions": {"plpgsql": "1.0", "vector": "0.8.6"},
                                "schemas": {"public": {"tables": ["documents"], "sequences": {}}}}))
    base = ["pg-inventory", "--meta", str(meta), "--export", f"public={export}"]
    assert cli.main(base + ["--role", "source"]) == 0
    assert json.loads(capsys.readouterr().out)["schemas"]["public"]["buckets"]["tasks"]["count"] == 1
    assert cli.main(base + ["--role", "target"]) == 1
    assert cli.main(base) == 2


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
                     "--staging", str(tmp_path / "s"), "--work", str(tmp_path / "w")]) == 0
    capsys.readouterr()
    assert cli.main(["verify-staged", "--manifest", str(out), "--root-id", "art",
                     "--staging", str(tmp_path / "s"), "--work", str(tmp_path / "w")]) == 0
    assert json.loads(capsys.readouterr().out)["match"] is True
    evidence = tmp_path / "r0.json"
    evidence.write_text(json.dumps(R0_OK | {"target_fenced": False}))
    assert cli.main(["gate", "r0", "--evidence", str(evidence)]) == 1
    assert cli.main(["gate", "bogus", "--evidence", str(evidence)]) == 2
