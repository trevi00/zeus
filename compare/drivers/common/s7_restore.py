"""Shared S7 scenario steps (`delivery.restore.pg`): the M7 whole-database restore rehearsal of
`adapters/host_migration.py` (D1-D3 and R1, INV-HOST-MIGRATION-001) on the labelled disposable PostgreSQL PAIR
(A/evidence/rebuild/s7/restore/DESIGN.md; DESIGN-s7 §4 item 4: "the restore family with equal digests on
disposable PG").

The cases mirror M7 `tests/test_host_migration_pg_rehearsal.py` (its fixtures are copied here as LABELLED
fixtures, never imported):
- `catalog`: the seeded source catalog;
- `dump`: one custom-format archive through `docker exec <source> pg_dump` (the harness admits exactly the M7 tool
  forms);
- `restore`: D3 into a NEW dedicated database, the read-only cached replay, `target_occupied`, the catalog
  comparison and the renamed schema set;
- `canonical`: the per-schema canonical document comparison and exact coverage. **Equality is ASSERTED here**, the
  Codex condition, not only recorded;
- `search_path`: the control DSN must list `public` for `::vector`;
- `registry`: D2, the Fleet host migration over the restored control ledger, and the exact changed rows afterwards;
- `reverse`: R1, the reverse restore of the target's latest state into a new source-side database;
- `refuse_recover`: a failed or hollow restore is never success, and is recovered only explicitly; the archive
  digest and rename-map refusals.

Layer: harness (never shipped). The common module never imports `codex_harness`; `api` supplies the M7 names (see
the reference driver's docstring), `TOOL_ROOT` (the root whose `scripts/aibox_data` is the canonical tool) and
`checkout(path)`, which makes the adapter's `canonical_tool` resolve `<path>/scripts/aibox_data`.

**Normalization is explicit, done here and identical on both sides:**
- this run's working root → `<root>`;
- values that cannot be stable, each replaced by a ROLE label registered by the case that produced it, and bound by
  a recorded boolean or an asserted equality to what it must cover (a wrong value is therefore still visible):
  - the archives' `archive_sha256` (the archive header carries the dump time): `<archive:source>` /
    `<archive:target>`, with `archive_matches_file` for the source dump;
  - each restore's `restore_id`: `<restore:DATABASE>`, with the cached replay and the receipt file asserted to
    carry the first run's id;
  - digests over data that holds run-root paths, i.e. the rebound lane repository/runtime: the Fleet
    `config_sha256` (`<config:migrated>`, bound to `config_digest` of the stored registry config), the host
    migration receipt id, the lanes' `path_identity`, and the reverse restore's catalog digests
    (`<catalog:latest>`, `<catalog:reversed>`, bound to `catalog_digest` of the catalogs read back). The cause was
    found by recording the catalogs twice: only `documents.rows_sha256` of the control ledger differed.

Every other digest is literal: database names and dump paths are fixed by the cases on a fresh pair per run. If any
other digest varies between runs, that is a fixture defect to fix, never a mask.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

PAIR = json.loads(os.environ["ZEUS_REBUILD_PG_PAIR"])
USER = PAIR["user"]
HISTORICAL = "zeus_team_profile_001"
LANES = {"harness": "zeus_fleet_harness", "interface": "zeus_fleet_interface"}
# D1: exactly three renames; every other source schema keeps its name in the dedicated target DB (M7 D1_MAP).
D1_MAP = {"public": "zeus_aibox_control", "zeus_fleet_harness": "zeus_aibox_harness",
          "zeus_fleet_interface": "zeus_aibox_interface", HISTORICAL: HISTORICAL}
# LABELLED fixture: the registry row as the retired Windows host wrote it (M7 SOURCE_CONFIG).
SOURCE_CONFIG = {
    "schema": "urn:zeus:fleet:1", "id": "zeus-local-fleet", "max_parallel": 2,
    "budget": {"total": 160, "per_host": 160},
    "lanes": [{"id": "harness", "team": "harness", "schema": "zeus_fleet_harness",
               "runtime": "C:\\workspaces\\zeus\\artifacts\\f2h", "repository": "C:\\workspaces\\zeus\\worktrees\\fleet-001",
               "redis_namespace": "zeus-fleet-harness"},
              {"id": "interface", "team": "interface", "schema": "zeus_fleet_interface",
               "runtime": "C:\\workspaces\\zeus\\artifacts\\f2i", "repository": "C:\\workspaces\\zeus\\worktrees\\fleet-001",
               "redis_namespace": "zeus-fleet-interface"}]}
ARCHIVE = "/dump/zeus-rehearsal.dump"
GIT_ENV = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@localhost", "GIT_AUTHOR_DATE": "2026-09-20T00:00:00Z",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@localhost",
           "GIT_COMMITTER_DATE": "2026-09-20T00:00:00Z"}


def dsn(role: str, database: str) -> str:
    return make_conninfo(host=PAIR[role]["socket"], user=USER, dbname=database)


class Run:
    def __init__(self, api):
        self.api = api
        self.root = Path.cwd().resolve() / "restore"
        self.root.mkdir()
        self.host_dump = Path(PAIR["host_dump"])
        # The canonical offline tool, COPIED from the side's TOOL_ROOT (SOURCE for the reference, `target/` for the
        # target) into a labelled checkout layout.
        self.checkout = self.root / "checkout"
        shutil.copytree(Path(api.TOOL_ROOT) / "scripts" / "aibox_data", self.checkout / "scripts" / "aibox_data",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (self.checkout / "src" / "codex_harness").mkdir(parents=True)
        self.labels = {}

    labels: dict

    def label(self, value, name: str) -> None:
        """A run-varying value, recorded by its role from here on (see the module docstring)."""
        label = f"<{name}>"
        assert isinstance(value, str) and self.labels.get(value, label) == label, (name, value)
        self.labels[value] = label

    def n(self, value):
        if isinstance(value, str) and value in self.labels:
            return self.labels[value]
        if isinstance(value, dict):
            return {self.n(k): self.n(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.n(v) for v in value]
        if isinstance(value, Path):
            value = str(value)
        if isinstance(value, str):
            return value.replace(str(self.root), "<root>")
        return value

    def refused(self, call) -> dict:
        try:
            out = call()
        except self.api.MigrationRefused as exc:
            return {"refused": type(exc).__name__, "detail": self.n(str(exc))}
        return {"refused": None, "result": self.n(out)}


# ---------------------------------------------------------------- the seeded source (M7 `seed_schema`, `source`)
def seed_schema(api, database_dsn: str, schema: str, tag: str) -> None:
    if schema != "public":
        with psycopg.connect(database_dsn, autocommit=True) as conn:
            conn.execute(f"CREATE SCHEMA {schema}")
    store = api.PostgresStore(make_conninfo(database_dsn, options=f"-c search_path={schema}"))
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


def seed(api) -> None:
    base = dsn("source", "zeus")
    seed_schema(api, base, "public", "control")
    control = api.PostgresStore(base)
    config = {**SOURCE_CONFIG, "budget": api.validate_budget(SOURCE_CONFIG["budget"]),
              "lanes": [{k: lane[k] for k in sorted(lane)} for lane in SOURCE_CONFIG["lanes"]]}
    with control.transaction() as tx:
        tx.put(api.BUCKET_REGISTRY, config["id"], {"id": config["id"], "schema": config["schema"],
                                                   "config": config, "config_sha256": api.config_digest(config),
                                                   "registered_at": "2026-09-20T00:00:00+00:00"})
        tx.put(api.BUCKET_JOBS, "job-accepted-1", {"id": "job-accepted-1", "lane": "harness", "status": "accepted",
                                                   "repository": api.repository_identity(config["lanes"][0]["repository"])})
    api.Fleet(control).pause()
    for schema in LANES.values():
        seed_schema(api, base, schema, schema)
    seed_schema(api, base, HISTORICAL, HISTORICAL)
    with psycopg.connect(base) as conn:
        conn.execute(f"CREATE SEQUENCE {HISTORICAL}.rehearsal_seq")
        conn.execute(f"SELECT nextval('{HISTORICAL}.rehearsal_seq') FROM generate_series(1, 7)")


def restore(run: Run, dumped: dict, catalog: dict, database: str, receipt: Path, schema_map=D1_MAP, **kwargs):
    return run.api.pg_restore_database(PAIR["target"]["container"], USER, dsn("target", "postgres"), database,
                                       dumped["path"], dumped["archive_sha256"], catalog, schema_map, receipt, **kwargs)


def canonical_inventory(run: Run, role: str, database: str, schema: str) -> dict:
    meta, rows = run.root / f"{role}-{database}-{schema}-meta.json", run.root / f"{role}-{database}-{schema}.jsonl"
    run.api.pg_export(dsn(role, database), schema, role, meta, rows)
    out = run.root / f"{role}-{database}-{schema}-inventory.json"
    result = run.api.run_canonical(["pg-inventory", "--meta", str(meta), "--export", f"{schema}={rows}",
                                    "--role", role, "--out", str(out)])
    assert result["receipt"]["ok"], run.n(result)
    return json.loads(out.read_text())


def receipt_view(receipt: dict) -> dict:
    return {k: receipt.get(k) for k in sorted(receipt) if k not in ("at", "recorded_at")}


# ---------------------------------------------------------------- the case groups
def catalog_case(run: Run) -> tuple[dict, dict]:
    api = run.api
    catalog = api.pg_catalog(dsn("source", "postgres"), "zeus")
    assert sorted(catalog["schemas"]) == sorted(["public", *LANES.values(), HISTORICAL])
    assert {"documents", "knowledge_nodes", "knowledge_edges", "schema_migrations"} <= \
        set(catalog["schemas"]["public"]["relations"])
    return catalog, {"schemas": sorted(catalog["schemas"]), "extensions": catalog["extensions"],
                     "public_relations": sorted(catalog["schemas"]["public"]["relations"]),
                     "catalog_digest": api.catalog_digest(catalog)}


def dump_case(run: Run) -> tuple[dict, dict]:
    dumped = run.api.pg_dump_database(PAIR["source"]["container"], USER, "zeus", ARCHIVE)
    file_sha = hashlib.sha256((run.host_dump / Path(ARCHIVE).name).read_bytes()).hexdigest()
    assert dumped["toc_entries"] > 0
    run.label(dumped["archive_sha256"], "archive:source")
    view = {k: v for k, v in dumped.items() if k != "archive_sha256"}
    return dumped, {**view, "archive_matches_file": dumped["archive_sha256"] == file_sha,
                    "archive_sha256_length": len(dumped["archive_sha256"])}


def restore_case(run: Run, dumped: dict, catalog: dict) -> tuple[str, dict]:
    api, database, receipt = run.api, "zeus_aibox_r000001", run.root / "restore-receipt.json"
    out = {}
    result = restore(run, dumped, catalog, database, receipt)
    assert result["state"] == "renamed" and result["cached"] is False and result["schemas"] == 4
    assert result["archive_sha256"] == dumped["archive_sha256"]
    run.label(result["restore_id"], "restore:" + database)
    out["first"] = run.n(result)
    replay = restore(run, dumped, catalog, database, receipt)
    assert replay["cached"] is True and replay["restore_id"] == result["restore_id"]
    out["replay"] = run.n(replay)
    out["occupied"] = run.refused(lambda: restore(run, dumped, catalog, database, run.root / "other-receipt.json"))
    assert out["occupied"]["refused"] and "target_occupied" in out["occupied"]["detail"]
    target_catalog = api.pg_catalog(dsn("target", "postgres"), database)
    compared = api.compare_catalogs(catalog, target_catalog, D1_MAP)
    assert compared["match"]
    assert set(target_catalog["schemas"]) == {"public", "zeus_aibox_control", "zeus_aibox_harness",
                                              "zeus_aibox_interface", HISTORICAL}
    assert target_catalog["schemas"]["public"]["relations"] == {}
    seq = target_catalog["schemas"][HISTORICAL]["sequences"]
    assert seq and seq[0][0] == "rehearsal_seq" and seq[0][2] == "7"
    out["catalog_match"] = compared
    out["target_schemas"] = sorted(target_catalog["schemas"])
    out["target_extensions"] = target_catalog["extensions"]
    out["target_catalog_digest"] = api.catalog_digest(target_catalog)
    stored = json.loads(receipt.read_text())
    assert stored["restore_id"] == result["restore_id"]
    out["receipt_file"] = run.n(stored)
    return database, out


def canonical_case(run: Run, database: str) -> dict:
    api, out, receipts = run.api, {}, []
    for src_schema, dst_schema in D1_MAP.items():
        left = canonical_inventory(run, "source", "zeus", src_schema)
        right = canonical_inventory(run, "target", database, dst_schema)
        compared = api.pg_compare_schema(left, right, D1_MAP, src_schema)
        # The Codex condition: the restored schema's canonical documents EQUAL the source's.
        assert compared["receipt"]["ok"], run.n(compared["result"])
        receipts.append(compared["receipt"])
        out[src_schema] = {"target_schema": dst_schema, "receipt": receipt_view(compared["receipt"]),
                           "result": run.n(compared["result"])}
    coverage = api.pg_coverage_receipt(D1_MAP, receipts)
    assert coverage["receipt"]["ok"]
    out["coverage"] = {"receipt": receipt_view(coverage["receipt"]), "result": run.n(coverage.get("result"))}
    return out


def search_path_case(run: Run, database: str) -> dict:
    api, target = run.api, dsn("target", database)
    control_dsn = make_conninfo(target, options="-c search_path=zeus_aibox_control,public")
    api.PostgresStore(control_dsn).migrate()  # already applied history: a no-op, not a failure
    hits = api.PostgresKnowledge(control_dsn).vector_query([1.0, 0.0, 7.0], "fixture", 3)
    try:
        api.PostgresKnowledge(make_conninfo(target, options="-c search_path=zeus_aibox_control")).vector_query(
            [1.0, 0.0, 7.0], "fixture", 3)
        without_public = None
    except psycopg.errors.UndefinedObject as exc:
        without_public = type(exc).__name__
    with psycopg.connect(target) as conn:
        typed = conn.execute("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = "
                             "'zeus_aibox_harness.knowledge_nodes'::regclass AND attname = 'embedding'").fetchone()[0]
    assert [hit["id"] for hit in hits][:1] == ["control:node:0"] and without_public and typed == "vector"
    return {"migrate_noop": True, "top_hits": [hit["id"] for hit in hits], "without_public": without_public,
            "embedding_type": typed}


def registry_case(run: Run, database: str) -> dict:
    api, target = run.api, dsn("target", database)
    control_dsn = make_conninfo(target, options="-c search_path=zeus_aibox_control,public")
    root = run.root / "srv" / "zeus"
    repo, runtimes = root / "repo", {lane: root / "runtime" / "lanes" / lane for lane in LANES}
    git_env = {**os.environ, **GIT_ENV}
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=git_env)
    subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "root"],
                   check=True, env=git_env)
    for path in runtimes.values():
        api.run_root(str(path)).mkdir(parents=True)
    journal = root / "journal.jsonl"
    journal.write_text('{"event":"start","run_id":"r1"}\n{"event":"exit","run_id":"r1"}\n')
    fleet = api.Fleet(api.PostgresStore(control_dsn))
    before = fleet.registered()
    request = {"schema": api.HOST_MIGRATION_SCHEMA, "fleet": "zeus-local-fleet", "operator": "owner",
               "migration_id": "aibox-migration-001", "manifest_sha256": "a" * 64,
               "expected_config_sha256": before["config_sha256"],
               "source_repository_identity": api.checkout_identity(str(repo)),
               "lanes": [{"lane": lane,
                          "repository": {"from": "C:\\workspaces\\zeus\\worktrees\\fleet-001", "to": str(repo)},
                          "runtime": {"from": old, "to": str(runtimes[lane])},
                          "schema": {"from": LANES[lane], "to": D1_MAP[LANES[lane]]}}
                         for lane, old in (("harness", "C:\\workspaces\\zeus\\artifacts\\f2h"),
                                           ("interface", "C:\\workspaces\\zeus\\artifacts\\f2i"))],
               "recorded_at": "2026-09-25T09:00:00Z"}
    with api.PostgresStore(control_dsn).transaction() as tx:
        jobs = tx.scan(api.BUCKET_JOBS)
    proof = api.collect_host_migration_proof(request, jobs, journal=journal, host_dsn=target)
    for lane in proof.get("lanes") or []:
        identity = ((lane.get("repository") or {}).get("path_identity"))
        if identity:
            run.label(identity, "path_identity:repository")  # both lanes rebind to the one fixture repository
    migrated = fleet.migrate_host(request, proof)
    cached = fleet.migrate_host(request, proof)
    assert migrated["migrated"] and migrated["cached"] is False and cached["cached"] is True
    with api.PostgresStore(control_dsn).transaction() as tx:
        registry = tx.get(api.BUCKET_REGISTRY, "zeus-local-fleet")
        receipt_rows = tx.scan("fleet_host_migrations")
        frozen = tx.get(api.BUCKET_JOBS, "job-accepted-1")
        aliases = api.repository_aliases(fleet, tx)
    lanes = {lane["id"]: lane for lane in registry["config"]["lanes"]}
    config_bound = migrated["config_sha256"] == api.config_digest(registry["config"]) == registry["config_sha256"]
    run.label(migrated["config_sha256"], "config:migrated")
    run.label(migrated["receipt"]["id"], "receipt:host_migration")
    assert lanes["harness"]["schema"] == "zeus_aibox_harness" and lanes["interface"]["schema"] == "zeus_aibox_interface"
    assert frozen["repository"] == api.repository_identity("C:\\workspaces\\zeus\\worktrees\\fleet-001")
    assert api.resolve_repository(frozen["repository"], aliases) == api.repository_identity(str(repo))
    after = canonical_inventory(run, "target", database, "zeus_aibox_control")
    left = canonical_inventory(run, "source", "zeus", "public")
    changed = api.pg_compare_schema(left, after, D1_MAP, "public")["result"]
    changed_rows = sorted((r["bucket"], r["problem"]) for r in changed["rows"])
    assert changed_rows == sorted([("fleet_registry", "changed"), ("fleet_host_migrations", "extra")])
    return {"proof": run.n(proof), "migrated": run.n(migrated), "replay_cached": cached["cached"],
            "config_sha256_is_the_stored_config_digest": config_bound,
            "lanes": run.n({k: {f: lanes[k][f] for f in ("schema", "runtime", "repository", "redis_namespace")}
                            for k in sorted(lanes)}),
            "receipt_rows": len(receipt_rows), "frozen_repository_unchanged": True, "alias_resolves_to_target": True,
            "changed_rows": changed_rows}


def reverse_case(run: Run, database: str, catalog: dict) -> dict:
    api = run.api
    latest = api.pg_catalog(dsn("target", "postgres"), database)
    back = api.pg_dump_database(PAIR["target"]["container"], USER, database, "/dump/" + database + ".dump")
    reverse_map = api.reverse_maps({"schema_map": D1_MAP, "path_map": []})["schema_map"]
    reverse_db = "zeus_reverse_000001"
    run.label(back["archive_sha256"], "archive:target")
    reversed_ = api.pg_restore_database(PAIR["source"]["container"], USER, dsn("source", "postgres"), reverse_db,
                                        back["path"], back["archive_sha256"], latest, reverse_map,
                                        run.root / "reverse.json", reverse=True)
    assert reversed_["state"] == "renamed"
    run.label(reversed_["restore_id"], "restore:" + reverse_db)
    reverse_catalog = api.pg_catalog(dsn("source", "postgres"), reverse_db)
    bindings = {"source_catalog_is_the_latest_target_catalog":
                reversed_["source_catalog_sha256"] == api.catalog_digest(latest),
                "renamed_catalog_is_the_reversed_catalog":
                reversed_["renamed_catalog_sha256"] == api.catalog_digest(reverse_catalog)}
    run.label(reversed_["source_catalog_sha256"], "catalog:latest")
    run.label(reversed_["renamed_catalog_sha256"], "catalog:reversed")
    match = api.compare_catalogs(latest, reverse_catalog, reverse_map)
    assert match["match"] and set(reverse_catalog["schemas"]) == set(catalog["schemas"])
    against = api.compare_catalogs(catalog, reverse_catalog, {k: k for k in catalog["schemas"]})
    diffs = sorted({(d["schema"], d["section"]) for d in against["diffs"]})
    assert diffs == [("public", "relations")]
    return {"reverse_map": reverse_map, "result": run.n(reversed_), "digest_bindings": bindings,
            "latest_vs_reversed": match,
            "reversed_schemas": sorted(reverse_catalog["schemas"]), "against_original_diffs": diffs,
            "back_toc_entries": back["toc_entries"]}


def refuse_recover_case(run: Run, dumped: dict, catalog: dict) -> dict:
    api, out = run.api, {}

    def failing(argv, timeout):
        if "pg_restore" in argv and "--exit-on-error" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "injected")
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    def hollow(argv, timeout):
        if "pg_restore" in argv and "--exit-on-error" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")  # exit 0, restored nothing
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)

    database, receipt = "zeus_aibox_f000001", run.root / "receipt.json"
    out["failed"] = run.refused(lambda: restore(run, dumped, catalog, database, receipt, runner=failing))
    out["failed_receipt_state"] = json.loads(receipt.read_text())["state"]
    out["no_silent_retry"] = run.refused(lambda: restore(run, dumped, catalog, database, receipt))
    out["hollow_recover"] = run.refused(lambda: restore(run, dumped, catalog, database, receipt, recover=True,
                                                        runner=hollow))
    out["restored_is_not_partial"] = run.refused(lambda: restore(run, dumped, catalog, database, receipt,
                                                                 recover=True))
    other, other_receipt = "zeus_aibox_g000001", run.root / "other.json"
    out["other_failed"] = run.refused(lambda: restore(run, dumped, catalog, other, other_receipt, runner=failing))
    recovered = restore(run, dumped, catalog, other, other_receipt, recover=True)
    run.label(recovered["restore_id"], "restore:" + other)
    out["other_recovered"] = {"refused": None, "result": run.n(recovered)}
    out["archive_digest_mismatch"] = run.refused(lambda: api.pg_restore_database(
        PAIR["target"]["container"], USER, dsn("target", "postgres"), "zeus_aibox_h000001", dumped["path"], "0" * 64,
        catalog, D1_MAP, run.root / "bad.json"))
    out["rename_map_not_total"] = run.refused(lambda: restore(
        run, dumped, catalog, "zeus_aibox_i000001", run.root / "partial.json",
        schema_map={k: v for k, v in D1_MAP.items() if k != HISTORICAL}))
    expected = {"failed": "pg_restore_failed", "no_silent_retry": "target_occupied",
                "hollow_recover": "restore_contents_mismatch", "restored_is_not_partial": "target_occupied",
                "other_failed": "pg_restore_failed", "archive_digest_mismatch": "archive_digest_mismatch",
                "rename_map_not_total": "rename_map_not_total"}
    for key, code in expected.items():
        assert out[key]["refused"] and code in out[key]["detail"], (key, out[key])
    assert out["failed_receipt_state"] == "restore_failed"
    assert out["other_recovered"]["refused"] is None and out["other_recovered"]["result"]["state"] == "renamed"
    return out


def run(api) -> dict:
    case = Run(api)
    # The adapter resolves its canonical tool (pg-inventory, pg-compare) from the labelled checkout for the whole
    # run: its only use of the package path (host_migration `canonical_tool`).
    with api.checkout(case.checkout):
        return cases(api, case)


def cases(api, case: Run) -> dict:
    seed(api)
    catalog, catalog_view = catalog_case(case)
    dumped, dump_view = dump_case(case)
    database, restore_view = restore_case(case, dumped, catalog)
    return {
        "catalog": catalog_view,
        "dump": dump_view,
        "restore": restore_view,
        "canonical": canonical_case(case, database),
        "search_path": search_path_case(case, database),
        "registry": registry_case(case, database),
        "reverse": reverse_case(case, database, catalog),
        "refuse_recover": refuse_recover_case(case, dumped, catalog),
    }
