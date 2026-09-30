"""Shared S5 scenario steps (`coordination.fleet_relocation`): M7 `Fleet.relocate`, `relocations` and `migrate_host`
(RESEARCH-S5 D7, TRACE C1; M7 tests/test_fleet_relocation.py and test_fleet_host_migration.py), with hand-built
request and proof documents. The host-observation collectors are S7 adapters, so they are not part of this family.

- **relocate.**
  - Request refusals.
  - A missing observation; not paused; not idle; a CAS digest mismatch; a fleet mismatch.
  - Config refusals: a source mismatch and a target in use.
  - Proof refusals: runner, copy manifest, active lane run, independence, identity, runtime, queued bindings and
    bases, and a proof that changed between the reads.
  - The committed move, with its receipt and new digest.
  - An identical replay answered from the receipt without observing; a conflicting request.
  - The relocations view.
  - After the move, a job frozen at the old repository still conflicts by path with a job enqueued at the new one
    (alias resolution).
- **migrate_host.**
  - Request refusals.
  - Incomplete lanes and a source-binding mismatch.
  - Proof refusals: identity and schema.
  - The committed migration and its cached replay; a conflicting request.

Layer: harness (never shipped)

`api` supplies MemoryStore, `Fleet(store, clock, token)` and `validate_manifest(document)`. The compared results are
the values or refusals with their reason codes, the observation calls and the final store records by body digest.
"""

from __future__ import annotations

import copy
import hashlib
import json

BASE = "a" * 40
ROOT = "/zeus-rebuild-s5-fleet"
NEW = "/zeus-rebuild-s5-moved"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "message": str(exc)[:160]}
    return {"value": value}


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def lanes():
    return [{"id": lane, "team": lane, "repository": ROOT + "/repo-" + lane, "schema": "lane_" + lane,
             "redis_namespace": "fleet-" + lane, "runtime": ROOT + "/rt-" + lane} for lane in ("a", "b")]


def request(digest_, **overrides):
    document = {"schema": "urn:zeus:fleet-relocation:1", "fleet": "fleet-1", "operator": "owner",
                "expected_config_sha256": digest_,
                "moves": [{"lane": "a", "repository": {"from": ROOT + "/repo-a", "to": NEW + "/repo-a"},
                           "runtime": {"from": ROOT + "/rt-a", "to": NEW + "/rt-a"}}],
                "copy_manifest": {"path": NEW + "/copy-manifest.json", "sha256": "c" * 64, "entries": 12},
                "recorded_at": "2026-09-22T00:00:00+00:00"}
    document.update(overrides)
    return document


def proof(queued=("op-q",), **overrides):
    document = {"schema": "urn:zeus:fleet-relocation-proof:1", "runner": {"state": "stopped"},
                "copy_manifest": {"sha256": "c" * 64, "entries": 12, "verified": 12, "bound": True,
                                  "ownership": "resolved_paths"},
                "lanes": [{"id": "a", "active_runs": 0,
                           "repository": {"independent": True, "source_identity": "r" * 64,
                                          "target_identity": "r" * 64},
                           "runtime": {"writable": True},
                           "queued_bindings": [{"job_id": job, "base_present": True, "goal_matches": True}
                                               for job in queued]}],
                "observed_at": "2026-09-22T00:00:01+00:00"}
    lane = document["lanes"][0]
    for key, value in overrides.items():
        if key in lane:
            lane[key] = value
        else:
            document[key] = value
    return document


def migration(digest_, **overrides):
    document = {"schema": "urn:zeus:fleet-host-migration:1", "fleet": "fleet-1", "operator": "owner",
                "migration_id": "move-1", "manifest_sha256": "d" * 64, "expected_config_sha256": digest_,
                "source_repository_identity": "e" * 64,
                "lanes": [{"lane": lane, "repository": {"from": ROOT + "/repo-" + lane, "to": NEW + "/repo-" + lane},
                           "runtime": {"from": ROOT + "/rt-" + lane, "to": NEW + "/rt-" + lane},
                           "schema": {"from": "lane_" + lane, "to": "moved_" + lane}} for lane in ("a", "b")],
                "recorded_at": "2026-09-22T00:00:00+00:00"}
    document.update(overrides)
    return document


def host_proof(**overrides):
    document = {"schema": "urn:zeus:fleet-host-migration-proof:1", "runner": {"state": "stopped"},
                "lanes": [{"id": lane, "active_runs": 0,
                           "repository": {"independent": True, "target_identity": "e" * 64},
                           "runtime": {"writable": True}, "schema": {"name": "moved_" + lane, "provisioned": True},
                           "queued_bindings": []} for lane in ("a", "b")],
                "observed_at": "2026-09-22T00:00:01+00:00"}
    document.update(overrides)
    return document


def run(api) -> dict:
    out, observed = {}, []

    def manifest(op_id, paths):
        return api.validate_manifest({
            "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
            "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": "r"},
            "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": paths},
            "budget": {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})

    def fleet(shared_repository=False):
        counter, stamp = iter(range(1, 100_000)), iter(range(1, 100_000))
        f = api.Fleet(api.MemoryStore(), lambda: "2026-09-22T00:00:00.%06d+00:00" % next(stamp),
                      lambda: "%032x" % next(counter))
        document_lanes = lanes()
        if shared_repository:
            document_lanes[1]["repository"] = document_lanes[0]["repository"]
        registered = f.register({"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
                                 "budget": {"per_host": 4, "total": 8}, "lanes": document_lanes})
        return f, registered["config_sha256"]

    # relocate
    f, digest_ = fleet()
    f.enqueue("a", manifest("op-q", ["docs/q.md"]), GOAL, [])
    good = request(digest_)
    for name, document in (("schema", {**good, "schema": "urn:other"}), ("extra", {**good, "extra": 1}),
                           ("relative_to", request(digest_, moves=[{"lane": "a", "repository": {
                               "from": ROOT + "/repo-a", "to": "relative"}, "runtime": None}])),
                           ("unchanged", request(digest_, moves=[{"lane": "a", "repository": {
                               "from": ROOT + "/repo-a", "to": ROOT + "/repo-a"}, "runtime": None}])),
                           ("empty", request(digest_, moves=[{"lane": "a", "repository": None, "runtime": None}])),
                           ("entries", request(digest_, copy_manifest={"path": NEW + "/m.json", "sha256": "c" * 64,
                                                                       "entries": 0}))):
        out["request_" + name] = call(f.relocate, document, proof())
    out["no_observation"] = call(f.relocate, good)
    out["not_paused"] = call(f.relocate, good, proof())
    f.pause()
    out["digest_mismatch"] = call(f.relocate, request("f" * 64), proof())
    out["fleet_mismatch"] = call(f.relocate, request(digest_, fleet="fleet-2"), proof())
    out["source_mismatch"] = call(f.relocate, request(digest_, moves=[{"lane": "a", "repository": {
        "from": ROOT + "/elsewhere", "to": NEW + "/repo-a"}, "runtime": None}]), proof())
    out["target_in_use"] = call(f.relocate, request(digest_, moves=[{"lane": "a", "repository": {
        "from": ROOT + "/repo-a", "to": ROOT + "/repo-b/inner"}, "runtime": None}]), proof())
    for name, bad in (("schema", proof(schema="urn:other")), ("runner", proof(runner={"state": "running"})),
                      ("copy", proof(copy_manifest={"sha256": "c" * 64, "entries": 12, "verified": 11,
                                                    "bound": True, "ownership": "resolved_paths"})),
                      ("copy_names_only", proof(copy_manifest={"sha256": "c" * 64, "entries": 12, "verified": 12,
                                                               "bound": True, "ownership": "names"})),
                      ("active_run", proof(active_runs=1)),
                      ("not_independent", proof(repository={"independent": False})),
                      ("identity", proof(repository={"independent": True, "source_identity": "r" * 64,
                                                     "target_identity": "s" * 64})),
                      ("runtime", proof(runtime={"writable": False})),
                      ("bindings", proof(queued=())),
                      ("base_missing", proof(queued_bindings=[{"job_id": "op-q", "base_present": False,
                                                               "goal_matches": True}]))):
        out["proof_" + name] = call(f.relocate, good, bad)
    out["proof_changed"] = call(f.relocate, good, proof(), reread=lambda: proof(runtime={"writable": True,
                                                                                          "note": "x"}))
    f2, digest2 = fleet()
    f2.enqueue("a", manifest("op-d", ["docs/d.md"]), GOAL, [])
    f2.admit_one()
    f2.pause()
    out["not_idle"] = call(f2.relocate, request(digest2), proof(queued=()))
    before = records(f.store)

    def observe():
        observed.append("observe")
        return proof()

    def reread():
        observed.append("reread")
        return proof(observed_at="2026-09-22T00:00:02+00:00")
    out["records_before"] = before
    out["relocated"] = call(f.relocate, good, observe=observe, reread=reread)

    def must_not_observe():
        observed.append("observed-on-replay")
        raise RuntimeError("a replay must not observe")
    out["replay"] = call(f.relocate, copy.deepcopy(good), observe=must_not_observe)
    out["conflict"] = call(f.relocate, request(digest_, operator="someone-else"), proof())
    out["relocations"] = call(f.relocations)
    out["observed"] = list(observed)
    out["status"] = call(f.status)
    out["records"] = records(f.store)

    # after a move, a frozen job at the old repository still conflicts by path with a new job
    g, digest3 = fleet(shared_repository=True)
    g.enqueue("a", manifest("op-old", ["docs/guide"]), GOAL, [])
    g.pause()
    moved = request(digest3, moves=[{"lane": "a", "repository": {"from": ROOT + "/repo-a", "to": NEW + "/repo-a"},
                                     "runtime": None},
                                    {"lane": "b", "repository": {"from": ROOT + "/repo-a", "to": NEW + "/repo-a"},
                                     "runtime": None}])
    out["shared_relocated"] = call(g.relocate, moved, proof(queued=("op-old",), lanes=[
        {"id": lane, "active_runs": 0, "repository": {"independent": True, "source_identity": "r" * 64,
                                                      "target_identity": "r" * 64},
         "runtime": {"writable": True},
         "queued_bindings": [{"job_id": "op-old", "base_present": True, "goal_matches": True}] if lane == "a" else []}
        for lane in ("a", "b")]))
    g.resume()
    g.enqueue("b", manifest("op-new", ["Docs/Guide/x.md"]), GOAL, [])
    out["alias_admit_1"] = call(g.admit_one)
    out["alias_admit_2"] = call(g.admit_one)

    # migrate_host
    h, digest4 = fleet()
    good_migration = migration(digest4)
    for name, document in (("schema", {**good_migration, "schema": "urn:other"}),
                           ("schema_ident", migration(digest4, lanes=[{**good_migration["lanes"][0],
                                                                      "schema": {"from": "lane_a", "to": "Bad"}},
                                                                     good_migration["lanes"][1]])),
                           ("duplicate", migration(digest4, lanes=[good_migration["lanes"][0]] * 2))):
        out["migration_" + name] = call(h.migrate_host, document, host_proof())
    out["migration_not_paused"] = call(h.migrate_host, good_migration, host_proof())
    h.pause()
    out["migration_incomplete"] = call(h.migrate_host, migration(digest4, lanes=[good_migration["lanes"][0]]),
                                       host_proof())
    out["migration_source_mismatch"] = call(h.migrate_host, migration(digest4, lanes=[
        {**good_migration["lanes"][0], "schema": {"from": "other", "to": "moved_a"}}, good_migration["lanes"][1]]),
        host_proof())
    wrong_identity = host_proof()
    wrong_identity["lanes"][0]["repository"] = {"independent": True, "target_identity": "0" * 64}
    out["migration_identity"] = call(h.migrate_host, good_migration, wrong_identity)
    unprovisioned = host_proof()
    unprovisioned["lanes"][1]["schema"] = {"name": "moved_b", "provisioned": False}
    out["migration_unprovisioned"] = call(h.migrate_host, good_migration, unprovisioned)
    out["migrated"] = call(h.migrate_host, good_migration, host_proof())
    out["migration_replay"] = call(h.migrate_host, copy.deepcopy(good_migration), host_proof(schema="urn:other"))
    out["migration_conflict"] = call(h.migrate_host, migration(digest4, operator="someone-else"), host_proof())
    out["migration_records"] = records(h.store)
    return out
