"""D1-D3 rehearsal on DISPOSABLE PostgreSQL 17 + pgvector servers (INV-HOST-MIGRATION-001).

Runs only when two disposable containers are named (the source-matching image, superuser `zeus`,
no network, unix sockets, one shared `/dump` directory):

    ZEUS_MIGRATION_TEST_PG_SOURCE_CONTAINER / ZEUS_MIGRATION_TEST_PG_SOURCE_SOCKET
    ZEUS_MIGRATION_TEST_PG_TARGET_CONTAINER / ZEUS_MIGRATION_TEST_PG_TARGET_SOCKET

Without them every test here skips and proves nothing about PostgreSQL. With them it seeds only
fixture data: a `public` control ledger with a Fleet registry, two lane schemas, a historical
schema, graph rows with `vector` embeddings and a sequence. It then rehearses the whole-database
dump, the restore into a NEW dedicated DB, the atomic renames, the per-schema canonical document
and catalog comparisons, the search-path/vector behaviour after the rename, the registry host
migration, a reverse (R1) restore, and refusal/recovery.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from codex_harness.adapters import host_migration as adapter
from codex_harness.adapters.fleet_recovery import (
    checkout_identity,
    collect_host_migration_proof,
    run_root,
)
from codex_harness.adapters.knowledge import PostgresKnowledge
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.fleet import BUCKET_JOBS, BUCKET_REGISTRY, Fleet
from codex_harness.domain.fleet import (
    config_digest,
    repository_identity,
    resolve_repository,
    validate_budget,
)
from codex_harness.domain.fleet_recovery import HOST_MIGRATION_SCHEMA
from codex_harness.domain.host_migration import MigrationRefused, compare_catalogs, reverse_maps

SOURCE = os.environ.get("ZEUS_MIGRATION_TEST_PG_SOURCE_CONTAINER")
SOURCE_SOCKET = os.environ.get("ZEUS_MIGRATION_TEST_PG_SOURCE_SOCKET")
TARGET = os.environ.get("ZEUS_MIGRATION_TEST_PG_TARGET_CONTAINER")
TARGET_SOCKET = os.environ.get("ZEUS_MIGRATION_TEST_PG_TARGET_SOCKET")
pytestmark = pytest.mark.skipif(not (SOURCE and SOURCE_SOCKET and TARGET and TARGET_SOCKET),
                                reason="Two disposable PostgreSQL 17 + pgvector containers required")

USER = "zeus"
HISTORICAL = "zeus_team_profile_001"
LANES = {"harness": "zeus_fleet_harness", "interface": "zeus_fleet_interface"}
# D1: exactly three renames; every other source schema keeps its name in the dedicated target DB.
D1_MAP = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness",
          "zeus_fleet_interface": "zeus_aibox_interface", HISTORICAL: HISTORICAL}
SOURCE_CONFIG = {
    "schema": "urn:zeus:fleet:1", "id": "zeus-local-fleet", "max_parallel": 2,
    "budget": {"total": 160, "per_host": 160},
    "lanes": [{"id": "harness", "team": "harness", "schema": "zeus_fleet_harness",
               "runtime": "C:\\workspaces\\zeus\\artifacts\\f2h", "repository": "C:\\workspaces\\zeus\\worktrees\\fleet-001",
               "redis_namespace": "zeus-fleet-harness"},
              {"id": "interface", "team": "interface", "schema": "zeus_fleet_interface",
               "runtime": "C:\\workspaces\\zeus\\artifacts\\f2i", "repository": "C:\\workspaces\\zeus\\worktrees\\fleet-001",
               "redis_namespace": "zeus-fleet-interface"}]}


def dsn(socket: str, database: str) -> str:
    return make_conninfo(host=socket, user=USER, dbname=database)


def seed_schema(database_dsn: str, schema: str, tag: str) -> None:
    if schema != "public":
        with psycopg.connect(database_dsn, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
    store = PostgresStore(make_conninfo(database_dsn, options=f"-c search_path={schema}"))
    store.migrate()
    with store.transaction() as tx:
        for i in range(25):
            tx.put("events", f"{tag}-{i:03d}", {"n": i, "path": "C:\\workspaces\\zeus\\artifacts\\" + tag})
        graph = tx.graph()
        for i in range(3):
            graph.put_node({"id": f"{tag}:node:{i}", "repository": "fleet-001", "kind": "module",
                            "body": f"{tag} body {i}", "source_ref": f"src/{i}.py", "revision": "r1",
                            "properties": {"i": i}})
        graph.put_edge(f"{tag}:node:0", f"{tag}:node:1", "imports")
    with psycopg.connect(database_dsn) as conn:
        conn.execute(f"UPDATE {schema}.knowledge_nodes SET embedding = '[1,0,{len(tag)}]'::public.vector, "
                     "properties = properties || '{\"embedding_model\": \"fixture\"}'")


@pytest.fixture(scope="module")
def source():
    """The fixture source DB `zeus` (seeded once per disposable container)."""
    base = dsn(SOURCE_SOCKET, "zeus")
    with psycopg.connect(base) as conn:
        seeded = conn.execute("SELECT to_regclass('public.documents')").fetchone()[0]
    if seeded is None:
        seed_schema(base, "public", "control")
        control = PostgresStore(base)
        config = {**SOURCE_CONFIG, "budget": validate_budget(SOURCE_CONFIG["budget"]),
                  "lanes": [{k: lane[k] for k in sorted(lane)} for lane in SOURCE_CONFIG["lanes"]]}
        with control.transaction() as tx:
            # The registry row exactly as the Windows host wrote it (its C:\ paths cannot be
            # re-validated on Linux, which is why the target rebinding is its own use case).
            tx.put(BUCKET_REGISTRY, config["id"], {"id": config["id"], "schema": config["schema"],
                                                   "config": config, "config_sha256": config_digest(config),
                                                   "registered_at": "2026-09-20T00:00:00+00:00"})
            tx.put(BUCKET_JOBS, "job-accepted-1", {"id": "job-accepted-1", "lane": "harness", "status": "accepted",
                                                   "repository": repository_identity(config["lanes"][0]["repository"])})
        Fleet(control).pause()
        for schema in LANES.values():
            seed_schema(base, schema, schema)
        seed_schema(base, HISTORICAL, HISTORICAL)
        with psycopg.connect(base) as conn:
            conn.execute(f"CREATE SEQUENCE {HISTORICAL}.rehearsal_seq")
            conn.execute(f"SELECT nextval('{HISTORICAL}.rehearsal_seq') FROM generate_series(1, 7)")
    return {"dsn": dsn(SOURCE_SOCKET, "postgres"), "catalog": adapter.pg_catalog(dsn(SOURCE_SOCKET, "postgres"), "zeus")}


@pytest.fixture(scope="module")
def dumped(source):
    return adapter.pg_dump_database(SOURCE, USER, "zeus", "/dump/zeus-" + uuid.uuid4().hex[:8] + ".dump")


def restore(dumped, source_catalog, database, receipt, schema_map=D1_MAP, **kwargs):
    return adapter.pg_restore_database(TARGET, USER, dsn(TARGET_SOCKET, "postgres"), database, dumped["path"],
                                       dumped["archive_sha256"], source_catalog, schema_map, receipt, **kwargs)


def canonical_inventory(tmp_path, socket, database, schema, role):
    meta, rows = tmp_path / f"{role}-{schema}-meta.json", tmp_path / f"{role}-{schema}.jsonl"
    adapter.pg_export(dsn(socket, database), schema, role, meta, rows)
    out = tmp_path / f"{role}-{schema}-inventory.json"
    result = adapter.run_canonical(["pg-inventory", "--meta", str(meta), "--export", f"{schema}={rows}",
                                    "--role", role, "--out", str(out)])
    assert result["receipt"]["ok"], result
    return json.loads(out.read_text())


def test_whole_database_restore_rename_compare_relocate_and_reverse(source, dumped, tmp_path):
    catalog = source["catalog"]
    assert sorted(catalog["schemas"]) == sorted(["public", *LANES.values(), HISTORICAL])
    assert ["vector", "0.8.6", "public"] in catalog["extensions"]
    assert {"documents", "knowledge_nodes", "knowledge_edges", "schema_migrations"} <= \
        set(catalog["schemas"]["public"]["relations"])
    assert dumped["toc_entries"] > 0
    database = "zeus_aibox_r" + uuid.uuid4().hex[:6]
    receipt = tmp_path / "restore-receipt.json"

    # --- D3: restore into a NEW dedicated DB, verify, rename atomically ---
    result = restore(dumped, catalog, database, receipt)
    assert result["state"] == "renamed" and result["cached"] is False and result["schemas"] == 4
    assert restore(dumped, catalog, database, receipt)["cached"] is True  # read-only replay
    with pytest.raises(MigrationRefused, match="target_occupied"):
        restore(dumped, catalog, database, tmp_path / "other-receipt.json")
    target_catalog = adapter.pg_catalog(dsn(TARGET_SOCKET, "postgres"), database)
    assert compare_catalogs(catalog, target_catalog, D1_MAP)["match"]
    assert set(target_catalog["schemas"]) == {"public", "zeus_aibox_control", "zeus_aibox_harness",
                                              "zeus_aibox_interface", HISTORICAL}
    assert target_catalog["schemas"]["public"]["relations"] == {}  # extension home only
    assert ["vector", "0.8.6", "public"] in target_catalog["extensions"]
    seq = target_catalog["schemas"][HISTORICAL]["sequences"]
    assert seq and seq[0][0] == "rehearsal_seq" and seq[0][2] == "7"

    # --- per-schema canonical document comparison + exact coverage ---
    receipts = []
    for src_schema, dst_schema in D1_MAP.items():
        left = canonical_inventory(tmp_path, SOURCE_SOCKET, "zeus", src_schema, "source")
        right = canonical_inventory(tmp_path, TARGET_SOCKET, database, dst_schema, "target")
        compared = adapter.pg_compare_schema(left, right, D1_MAP, src_schema)
        assert compared["receipt"]["ok"], compared["result"]
        receipts.append(compared["receipt"])
    assert adapter.pg_coverage_receipt(D1_MAP, receipts)["receipt"]["ok"]

    # --- search_path / vector after the rename ---
    target = dsn(TARGET_SOCKET, database)
    control_dsn = make_conninfo(target, options="-c search_path=zeus_aibox_control,public")
    PostgresStore(control_dsn).migrate()  # already applied history: a no-op, not a failure
    hits = PostgresKnowledge(control_dsn).vector_query([1.0, 0.0, 7.0], "fixture", 3)
    assert [hit["id"] for hit in hits][:1] == ["control:node:0"]
    with pytest.raises(psycopg.errors.UndefinedObject):
        PostgresKnowledge(make_conninfo(target, options="-c search_path=zeus_aibox_control")).vector_query(
            [1.0, 0.0, 7.0], "fixture", 3)  # the control DSN MUST list public for `::vector`
    with psycopg.connect(target) as conn:
        typed = conn.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = "
                             "'zeus_aibox_harness.knowledge_nodes'::regclass AND attname = 'embedding'").fetchone()[0]
    assert typed == "vector"

    # --- D2: registry host migration through the Fleet use case ---
    root = tmp_path / "srv" / "zeus"
    repo, runtimes = root / "repo", {lane: root / "runtime" / "lanes" / lane for lane in LANES}
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=f@x", "-c", "user.name=f", "commit", "-q",
                    "--allow-empty", "-m", "root"], check=True)
    for path in runtimes.values():
        run_root(str(path)).mkdir(parents=True)  # an initialized runtime: its runs root exists and is empty
    journal = root / "journal.jsonl"
    journal.write_text('{"event":"start","run_id":"r1"}\n{"event":"exit","run_id":"r1"}\n')
    fleet = Fleet(PostgresStore(control_dsn))
    before = fleet.registered()
    request = {"schema": HOST_MIGRATION_SCHEMA, "fleet": "zeus-local-fleet", "operator": "owner",
               "migration_id": "aibox-migration-001", "manifest_sha256": "a" * 64,
               "expected_config_sha256": before["config_sha256"],
               "source_repository_identity": checkout_identity(str(repo)),
               "lanes": [{"lane": lane,
                          "repository": {"from": "C:\\workspaces\\zeus\\worktrees\\fleet-001", "to": str(repo)},
                          "runtime": {"from": old, "to": str(runtimes[lane])},
                          "schema": {"from": LANES[lane], "to": D1_MAP[LANES[lane]]}}
                         for lane, old in (("harness", "C:\\workspaces\\zeus\\artifacts\\f2h"),
                                           ("interface", "C:\\workspaces\\zeus\\artifacts\\f2i"))],
               "recorded_at": "2026-09-25T09:00:00Z"}
    with PostgresStore(control_dsn).transaction() as tx:
        jobs = tx.scan(BUCKET_JOBS)
    proof = collect_host_migration_proof(request, jobs, journal=journal, host_dsn=target)
    migrated = fleet.migrate_host(request, proof)
    assert migrated["migrated"] and migrated["cached"] is False
    assert fleet.migrate_host(request, proof)["cached"] is True
    with PostgresStore(control_dsn).transaction() as tx:
        registry = tx.get(BUCKET_REGISTRY, "zeus-local-fleet")
        receipt_row = tx.scan("fleet_host_migrations")[0]
        frozen = tx.get(BUCKET_JOBS, "job-accepted-1")
        aliases = fleet._repository_aliases(tx)
    lanes = {lane["id"]: lane for lane in registry["config"]["lanes"]}
    assert lanes["harness"]["schema"] == "zeus_aibox_harness" and lanes["interface"]["schema"] == "zeus_aibox_interface"
    assert lanes["harness"]["runtime"] == str(runtimes["harness"]) and lanes["harness"]["repository"] == str(repo)
    assert [lanes[k]["redis_namespace"] for k in ("harness", "interface")] == ["zeus-fleet-harness", "zeus-fleet-interface"]
    assert receipt_row["prior_config"] == before["config"] or receipt_row["prior_config_sha256"] == before["config_sha256"]
    assert frozen["repository"] == repository_identity("C:\\workspaces\\zeus\\worktrees\\fleet-001")  # unchanged
    assert resolve_repository(frozen["repository"], aliases) == repository_identity(str(repo))
    # After the rebinding only the registry row changed and one receipt row was added.
    after = canonical_inventory(tmp_path, TARGET_SOCKET, database, "zeus_aibox_control", "target")
    left = canonical_inventory(tmp_path, SOURCE_SOCKET, "zeus", "public", "source")
    changed = adapter.pg_compare_schema(left, after, D1_MAP, "public")["result"]
    assert sorted((r["bucket"], r["problem"]) for r in changed["rows"]) == \
        sorted([("fleet_registry", "changed"), ("fleet_host_migrations", "extra")])

    # --- R1: reverse restore of the target's LATEST state into a NEW source-side DB ---
    latest = adapter.pg_catalog(dsn(TARGET_SOCKET, "postgres"), database)
    back = adapter.pg_dump_database(TARGET, USER, database, "/dump/" + database + ".dump")
    reverse_map = reverse_maps({"schema_map": D1_MAP, "path_map": []})["schema_map"]
    reverse_db = "zeus_reverse_" + uuid.uuid4().hex[:6]
    reversed_ = adapter.pg_restore_database(SOURCE, USER, dsn(SOURCE_SOCKET, "postgres"), reverse_db, back["path"],
                                            back["archive_sha256"], latest, reverse_map, tmp_path / "reverse.json",
                                            reverse=True)
    assert reversed_["state"] == "renamed"
    reverse_catalog = adapter.pg_catalog(dsn(SOURCE_SOCKET, "postgres"), reverse_db)
    assert compare_catalogs(latest, reverse_catalog, reverse_map)["match"]
    assert set(reverse_catalog["schemas"]) == set(catalog["schemas"])  # original names restored
    against_original = compare_catalogs(catalog, reverse_catalog, {k: k for k in catalog["schemas"]})
    # Only the control ledger's documents differ from the original: the target's new records.
    assert {(d["schema"], d["section"]) for d in against_original["diffs"]} == {("public", "relations")}


def test_failed_or_hollow_restore_is_never_success_and_recovers_only_explicitly(source, dumped, tmp_path):
    catalog = source["catalog"]
    database = "zeus_aibox_f" + uuid.uuid4().hex[:6]
    receipt = tmp_path / "receipt.json"

    def failing_restore(argv, timeout):
        if "pg_restore" in argv and "--exit-on-error" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "injected")
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    def hollow_restore(argv, timeout):
        if "pg_restore" in argv and "--exit-on-error" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")  # exit 0, restored nothing
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    with pytest.raises(MigrationRefused, match="pg_restore_failed"):
        restore(dumped, catalog, database, receipt, runner=failing_restore)
    assert json.loads(receipt.read_text())["state"] == "restore_failed"
    with pytest.raises(MigrationRefused, match="target_occupied"):
        restore(dumped, catalog, database, receipt)  # no silent retry into an existing DB
    with pytest.raises(MigrationRefused, match="restore_contents_mismatch"):
        restore(dumped, catalog, database, receipt, recover=True, runner=hollow_restore)
    with pytest.raises(MigrationRefused, match="target_occupied"):
        restore(dumped, catalog, database, receipt, recover=True)  # restored state is not "known partial"
    other = "zeus_aibox_g" + uuid.uuid4().hex[:6]
    other_receipt = tmp_path / "other.json"
    with pytest.raises(MigrationRefused, match="pg_restore_failed"):
        restore(dumped, catalog, other, other_receipt, runner=failing_restore)
    done = restore(dumped, catalog, other, other_receipt, recover=True)
    assert done["state"] == "renamed"
    with pytest.raises(MigrationRefused, match="archive_digest_mismatch"):
        adapter.pg_restore_database(TARGET, USER, dsn(TARGET_SOCKET, "postgres"), "zeus_aibox_h" + uuid.uuid4().hex[:6],
                                    dumped["path"], "0" * 64, catalog, D1_MAP, tmp_path / "bad.json")
    with pytest.raises(MigrationRefused, match="rename_map_not_total"):
        restore(dumped, catalog, "zeus_aibox_i" + uuid.uuid4().hex[:6], tmp_path / "partial.json",
                schema_map={k: v for k, v in D1_MAP.items() if k != HISTORICAL})
    assert Path(other_receipt).exists()
