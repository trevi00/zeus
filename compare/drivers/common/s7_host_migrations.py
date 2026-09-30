"""Shared S7 scenario steps (`delivery.host_migrations`): M7's `HostMigrations`, the store-only receipt recorder of a host
migration (INV-HOST-MIGRATION-001): `plan`, `status`, `manifest`, `advance`, `checkpoint`, `completed_step`,
`intend_activation`, `record_successor`, `activation_document`, `activation_switch` and `rollback_plan`.

Layer: harness (never shipped)

`api` supplies `MemoryStore`, `HostMigrations`, the bucket names `BUCKET`, `BUCKET_TRANSITIONS`, `BUCKET_CHECKPOINTS`,
`policy` (the host-migration domain module: schemas, states, gates, `MigrationRefused`, the pure validators and id
functions the cases read), `descriptor_digest` and `DESCRIPTOR_SCHEMA` (the host-delivery domain) and `digest`. Nothing
here reads a clock or an id source: the documents carry their own `at`. Every manifest, receipt, transition, intent,
successor and lineage document is a LABELLED fixture of the shape M7's tests build (tests/test_host_migration.py,
tests/test_host_migration_successor.py); the `activation_switch` effect is a LABELLED callable that records the plan it
is handed (or raises). Nothing claims an actual Codex, GitHub, host or production verification.

- **manifest_plan**: manifest validation and its digest, every refusal by field never by value, the source `public`
  control ledger, `plan` idempotency and conflict, the unknown-migration reads.
- **advance_checkpoints**: the forward walk, the receipts that never advance, failure and resume, checkpoint replay,
  `limited_active` bound to the intent, the intent only in `restored_paused`, the rollback plan in mode R0 and R1.
- **managed_lineage**: the PH4 rows at the store level (legacy identity golden, managed lineage, field refusals, no
  fallback between the two forms, receipt bindings, drift, replay, a failing transaction, no live sampling).
- **successor_switch**: the successor rows T1, T2, T4-T10 and PH4 over the effective successor, `activation_document`
  and `activation_switch` through the labelled effect.

M7 tests NOT mirrored (they need a file, the launcher, a thread, a process or PostgreSQL; the store-level halves are
covered): test_schema_scope_allows_source_public_and_refuses_target_public (adapter `_schema`);
test_ph4_13 (monkeypatches builtins/os/subprocess/socket, unsafe inside the harness process; the recorded view carries
its coordinator half); test_writer_start_receipt_gap_is_reconciled_by_r1_never_r0 and
test_the_linux_launcher_accepts_exactly_the_coordinator_written_receipt (launcher and receipt files; the R1 store half is
the `rollback_r1` case); test_fence_refuses_every_launcher_role (files); test_t3, test_ph4_11_recording_limited_active_
writes_no_current, test_a1..a7, test_every_recovery_precondition_*, test_an_idle_host_*, test_switch_switch_interleaving_*,
test_record_switch_interleaving_*, test_a_successor_recorded_before_the_first_switch_*, test_switch_refuses_on_non_posix,
test_cli_records_a_successor_*, test_a_closed_runtime_control_only_*, test_s6_* and the launcher-process test (adapter
files, systemd, threads, the CLI, continuation); test_portable_a_second_switch_then_a_record_* (wall-clock thread
joins); the postgres_* rows (a real database). The launcher receipt BYTES (`adapter._document_bytes`) are not
characterized; the activation document itself is.
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager

H = "a" * 64
COMMIT = "b" * 40
IMAGE = "sha256:" + "c" * 64
HOST_ID = "machine-id-sha256:" + "d" * 64
MID = "aibox-migration-001"
NEXT = "e" * 40
LATER = "7" * 40
LOCK = "f" * 64
PAYLOAD = "ec8aa0a2" + "0" * 32
PLAN_ID = "managed-plan-001"
INSTANCE_ID = "5" * 32
CANARY = "canary=" + PLAN_ID + ":instance=" + INSTANCE_ID
# Values M7's tests computed from the unchanged coordinator at d795e26 over exactly these fixtures.
LEGACY_GOLDEN = {"limited_id": "9333e60f055d7f473b46f716f397bb335fe950c3cd85be9b68e6360914dc64a2",
                 "limited_bytes": "416af8adfca672fc5d39d8e2bf8be8fdc500fae4102dfa648730ff9634dd2240",
                 "network_id": "732d4b50e6d6d95b22893411b11775e4e7aa63471989fb5cd229a5252554d550",
                 "history": "3948432c3cbc156b8cb7abe6aad6b20dbef1e84d097b388fc0cbec30097f6069",
                 "row": "29ea9c6e124380adf27747580da02afdb3f19c25ded4d2ba3af401dde2865287"}
SUCCESSOR_GOLDEN = {"limited_id": "59e1d3636fefd60ba2957543e56a3c43f3effe8b56ee23e3c30905d07c3a814a",
                    "limited_bytes": "a2cea4add33dd79d87ac9267ddd63f6e76bb611f28f2fbd9a1479fa5b31039ee",
                    "history": "1dc84e211db4e68ac27f36e0bb05c865df452c750399f52a0c2bae820db3ebb7"}
# The recorded live intent (digests and ids only) of M7's test_t2.
LIVE_INTENT = {"actor": "claude-paused-activation", "at": "2026-09-25T14:50:51.353103Z",
               "host_id": "machine-id-sha256:d8d97db19abbc67e202823e2fcc0af3ee6f6fad6ddfdaf00c5cdc061d4fd35ef",
               "image": "sha256:9fb57f15a238d5e7789db44bd3036d393dc7acd6ff7d790b3f3ab48497509fce",
               "migration_id": MID,
               "profile_sha256": "cc7150678052ad3d4636a930a7fef34f5a991cfe85b633ada5dc49b830b93bda",
               "release_revision": "ced20281ba10fa3b16280cb73a20279b7e94052a"}
LIVE_MANIFEST = "69ec63f9422d49e575f09ea0a5015ed6e214098c76515bd84f2c9e0c37a841c1"
LIVE_INTENT_ID = "69221c1083fdd5ec81c7216e88a342ee11a00ffb36b4560922e91ca058b9230e"

A = None          # the api of this run
STORES = []       # every store one case created, digested with the case


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        out = {"refused": type(exc).__name__, "message": str(exc)[:200]}
        for name in ("reason_code", "field"):
            if hasattr(exc, name):
                out[name] = getattr(exc, name)
        out["secret_free"] = "hunter2" not in str(exc)
        return out
    return {"value": value}


def store_state(store) -> dict:
    with store.transaction() as tx:
        return {r["bucket"] + "/" + r["id"]: canonical_digest(r["body"]) for r in tx.records()}


def row(store, bucket=None, key=MID):
    with store.transaction() as tx:
        return tx.get(bucket or A.BUCKET, key)


def guarded(store, fn, *args, **kwargs):
    """A step and whether it wrote anything (a refusal must write nothing)."""
    before = store_state(store)
    out = call(fn, *args, **kwargs)
    return {**out, "wrote": store_state(store) != before}


def new_store(cls=None):
    store = (cls or A.MemoryStore)()
    STORES.append(store)
    return store


def coordinator(store=None):
    return A.HostMigrations(store or new_store())


def brief(view: dict) -> dict:
    return {k: view[k] for k in ("state", "transitions", "cached") if k in view}


# ---- fixtures (M7 tests/test_host_migration.py module helpers, LABELLED) ------------------------------------------

def engine(kind: str, host: str) -> dict:
    if kind == "postgres":
        return {"image": "pgvector/pgvector:pg17", "image_digest": IMAGE, "major": 17, "database": "zeus",
                "endpoint": {"kind": "docker_exec", "name": host + "-postgres"}, "extensions": ["plpgsql", "vector"]}
    return {"image": "redis:7.4-alpine", "image_digest": IMAGE, "major": 7,
            "instance": "dedicated", "endpoint": {"kind": "docker_exec", "name": host + "-redis"},
            "namespaces": ["zeus-fleet-harness", "zeus-fleet-interface"]}


def manifest(**overrides) -> dict:
    document = {
        "schema": A.policy.MANIFEST_SCHEMA, "migration_id": MID, "created_at": "2026-09-25T05:00:00Z",
        "source": {"host_id": "windows-pc", "platform": "windows",
                   "postgres": engine("postgres", "src"), "redis": engine("redis", "src")},
        "target": {"host_id": "aibox", "platform": "linux",
                   "postgres": engine("postgres", "dst"), "redis": engine("redis", "dst")},
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
        "fence": {"kind": "admission_pause_and_marker", "marker_id": MID},
        "rollback": {"location_id": "backups", "reverse_supported": True, "source_retained": True},
    }
    document.update(overrides)
    return document


def receipt(check: str, subject=None, *, ok=True, exit_code=None) -> dict:
    return {"schema": A.policy.EVIDENCE_SCHEMA, "check": check, "subject": subject,
            "exit_code": (0 if ok else 1) if exit_code is None else exit_code, "ok": ok, "result_sha256": H}


def gate_evidence(to: str, **bound) -> dict:
    evidence = {}
    for gate, kinds in A.policy.GATES.get(to, {}).items():
        evidence[gate] = bound.get(gate) or receipt(kinds[0] if kinds else A.policy.OBSERVATION, ok=kinds is not None)
    return evidence


def transition(sha: str, frm: str, to: str, *, reason=None, exit_code=0, evidence=None, identity=None) -> dict:
    return {"schema": A.policy.TRANSITION_SCHEMA, "migration_id": MID, "manifest_sha256": sha,
            "from": frm, "to": to, "actor": "claude-implementation", "host": "aibox",
            "at": "2026-09-25T05:10:00Z",
            "identity": identity or {"config_sha256": H, "commit": COMMIT, "image": IMAGE, "profile_sha256": H},
            "evidence": evidence if evidence is not None else gate_evidence(to),
            "exit_code": exit_code, "reason_code": reason}


def failure(sha, frm, to, reason):
    return transition(sha, frm, to, reason=reason, exit_code=1)


def checkpoint(step: str, input_sha: str = H, output_sha: str = H) -> dict:
    return {"schema": A.policy.CHECKPOINT_SCHEMA, "migration_id": MID, "step": step,
            "input_sha256": input_sha, "output_sha256": output_sha, "at": "2026-09-25T05:20:00Z"}


def intent_document() -> dict:
    return {"schema": A.policy.INTENT_SCHEMA, "migration_id": MID, "host_id": HOST_ID, "release_revision": COMMIT,
            "image": IMAGE, "profile_sha256": H, "actor": "owner", "at": "2026-09-25T06:00:00Z"}


def walk(c, sha, until):
    state = A.policy.PLANNED
    for to in A.policy.FORWARD[1:A.policy.FORWARD.index(until) + 1]:
        if to == A.policy.LIMITED_ACTIVE:
            c.advance(activation_transition(c, sha))
        else:
            c.advance(transition(sha, state, to))
        state = to
    return state


def activation_transition(c, sha):
    intent_id = c.status(MID)["activation_intent"]
    if intent_id is None:
        intent_id = c.intend_activation(intent_document())["intent_id"]
    return transition(sha, A.policy.RESTORED_PAUSED, A.policy.LIMITED_ACTIVE, evidence=gate_evidence(
        A.policy.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
        service_consumption=receipt("service-startup", "revision=" + COMMIT)))


def managed_descriptor() -> dict:
    return {"schema": A.DESCRIPTOR_SCHEMA, "target_id": "aibox-managed-fleet",
            "root": "/srv/zeus/managed/runtimes/" + PAYLOAD, "revision": PAYLOAD,
            "worker_image": IMAGE, "profile_digest": H, "predecessor": "9" * 64}


def lineage(**overrides) -> dict:
    document = {"owner": "managed", "descriptor": managed_descriptor(), "instance_id": INSTANCE_ID,
                "plan_id": PLAN_ID}
    document.update(overrides)
    return document


def consumed(descriptor=None) -> str:
    return "descriptor=" + A.descriptor_digest(descriptor or managed_descriptor())


def managed_transition(sha, activation_id, *, commit=COMMIT, lineage_document=None, host_activation=None,
                       service_consumption=None, canary_admission=None) -> dict:
    p = A.policy
    document = transition(sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE,
                          identity={"config_sha256": H, "commit": commit, "image": IMAGE, "profile_sha256": H},
                          evidence=gate_evidence(
                              p.LIMITED_ACTIVE,
                              host_activation=host_activation or receipt("host-activation", activation_id),
                              service_consumption=service_consumption or receipt("service-startup", consumed()),
                              canary_admission=canary_admission or receipt(p.OBSERVATION, CANARY)))
    document["lineage"] = lineage() if lineage_document is None else lineage_document
    return document


def activation_ready(store=None):
    c = coordinator(store)
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, A.policy.RESTORED_PAUSED)
    return c, sha, c.intend_activation(intent_document())["intent_id"]


def successor(predecessor_id: str, revision: str = NEXT, **overrides) -> dict:
    p = A.policy
    document = {"schema": p.SUCCESSOR_SCHEMA, "migration_id": MID, "host_id": HOST_ID,
                "predecessor_id": predecessor_id, "release_revision": revision, "image": IMAGE,
                "profile_sha256": H, "environment_lock": LOCK, "reason_code": "bootstrap-recovery",
                "evidence": {"release_identity": receipt(p.OBSERVATION, "revision=" + revision),
                             "worker_compatibility": receipt(p.OBSERVATION, "image=" + IMAGE),
                             "admission_drained": receipt(p.OBSERVATION, "fleet=paused-settled")},
                "actor": "owner", "at": "2026-09-26T09:00:00Z"}
    document.update(overrides)
    return document


def paused(store=None):
    """restored_paused with the recorded intent; the coordinator, the manifest digest and the intent id."""
    return activation_ready(store)


def on_successor():
    c, sha, intent_id = paused()
    return c, sha, intent_id, c.record_successor(successor(intent_id))["successor_id"]


class FailingStore:
    """LABELLED: the row write fails after the transition write inside the SAME transaction (M7 `FailingStore`)."""

    @staticmethod
    def make():
        base = A.MemoryStore
        bucket = A.BUCKET

        class Failing(base):
            fail = False

            @contextmanager
            def transaction(self, fail_fast: bool = False):
                with super().transaction(fail_fast) as tx:
                    put = tx.put

                    def failing(name, key, body):
                        put(name, key, body)
                        if self.fail and name == bucket:
                            raise RuntimeError("LABELLED injected store failure")
                    tx.put = failing
                    yield tx
        return Failing


class SwitchEffect:
    """LABELLED `activation_switch` effect: records each plan it is handed; raises when told to."""

    def __init__(self, raises=None):
        self.plans, self.raises = [], raises

    def __call__(self, plan):
        self.plans.append(copy.deepcopy(plan))
        if self.raises is not None:
            raise self.raises
        return {"effective_id": plan["effective_id"], "revision": plan["effective"]["release_revision"]}


# ---- manifest_plan --------------------------------------------------------------------------------------------------

def manifest_digest_order():
    first, second = coordinator(), coordinator()
    shuffled = manifest()
    shuffled["writers"] = list(reversed(shuffled["writers"]))
    a, b = first.plan(manifest()), second.plan(shuffled)
    return {"first": a["manifest_sha256"], "shuffled": b["manifest_sha256"],
            "equal": a["manifest_sha256"] == b["manifest_sha256"]}


def _manifest_mutations():
    return [
        ("secret_value_pg", lambda d: d["target"]["postgres"]["endpoint"].update(name="postgresql://zeus:" + "hunter2@db/zeus")),
        ("secret_value_redis", lambda d: d["source"]["redis"]["endpoint"].update(name="redis://:" + "hunter2@host:6379/0")),
        ("secret_field", lambda d: d["fence"].update(password="x")),
        ("major_version_mismatch", lambda d: d["target"]["postgres"].update(major=18)),
        ("namespace_rewrite", lambda d: d["target"]["redis"].update(namespaces=["zeus_aibox"])),
        ("target_redis_shared", lambda d: d["target"]["redis"].update(instance="shared")),
        ("extension_mismatch", lambda d: d["target"]["postgres"].update(extensions=["vector"])),
        ("map_not_bijective", lambda d: d["schema_map"].update(zeus_fleet_harness="zeus_aibox_control")),
        ("public_schema", lambda d: d["schema_map"].update(zeus_fleet_harness="public")),
        ("source_public_mapping", lambda d: d["schema_map"].update(public="zeus_aibox_other")),
        ("source_public_not_inventoried",
         lambda d: d.update(pg_buckets=[b for b in d["pg_buckets"] if b["schema"] != "public"])),
        ("path_overlap", lambda d: d["path_map"][1].update(to="/srv/zeus/artifacts/nested")),
        ("redis_key_outside_namespace", lambda d: d["redis_keys"][0].update(key="other:stream")),
        ("writer_disposition", lambda d: d["writers"][1].update(disposition="stop_and_fence")),
        ("rollback_unsupported", lambda d: d["rollback"].update(reverse_supported=False)),
        ("schema_unmapped", lambda d: d["pg_buckets"][0].update(schema="unmapped")),
        ("manifest_same_host", lambda d: d["target"].update(host_id="windows-pc")),
    ]


def manifest_refusals():
    out = {}
    for name, mutate in _manifest_mutations():
        document = manifest()
        mutate(document)
        c = coordinator()
        out[name] = guarded(c.store, c.plan, document)
    return out


def source_public_control_ledger():
    c = coordinator()
    view = c.plan(manifest())
    stored = c.manifest(MID)
    reverse = A.policy.reverse_maps(A.policy.validate_manifest(manifest()))
    return {"plan": view, "schema_map_public": stored["schema_map"]["public"],
            "reverse_schema_map": reverse["schema_map"],
            "reverse_artifacts": {p["id"]: [p["from"], p["to"]] for p in reverse["path_map"]}["artifacts"],
            "manifest_is_the_planned_one": stored == A.policy.validate_manifest(manifest())}


def plan_idempotent_and_conflict():
    c = coordinator()
    first = c.plan(manifest())
    second = c.plan(manifest())
    changed = manifest()
    changed["pg_buckets"][0]["count"] = 3
    conflict = guarded(c.store, c.plan, changed)
    return {"first": first, "authority_says_not_proof": "not proof" in first["authority"], "second": second,
            "conflict": conflict, "status": c.status(MID), "row": row(c.store)}


def unknown_migration_reads():
    c = coordinator()
    return {"status": call(c.status, "nope"), "manifest": call(c.manifest, "nope"),
            "rollback_plan": call(c.rollback_plan, "nope"),
            "completed_step": call(c.completed_step, "nope", "pg_restore", H),
            "activation_document": call(c.activation_document, "nope"),
            "checkpoint": guarded(c.store, c.checkpoint, checkpoint("pg_restore")),
            "intend_activation": guarded(c.store, c.intend_activation, intent_document()),
            "advance": guarded(c.store, c.advance, transition(H, "planned", "network_ready"))}


# ---- advance_checkpoints --------------------------------------------------------------------------------------------

def forward_walk():
    p = A.policy
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    out = {}
    step = transition(sha, p.PLANNED, "network_ready")
    out["first"] = brief(c.advance(step))
    out["replay"] = brief(c.advance(step))
    other = transition(sha, p.PLANNED, "network_ready",
                       evidence={"network_receipt": receipt("observation") | {"result_sha256": "e" * 64}})
    out["stale_from"] = guarded(c.store, c.advance, other)
    out["skip"] = guarded(c.store, c.advance, transition(sha, "network_ready", "draining"))
    out["missing_gate"] = guarded(c.store, c.advance, transition(
        sha, "network_ready", "staged", evidence={"target_layout": receipt("observation")}))
    out["stale_manifest"] = guarded(c.store, c.advance, transition("e" * 64, "network_ready", "staged"))
    out["walked_to"] = walk(c, sha, p.QUALIFIED)
    out["status"] = c.status(MID)
    out["row"] = row(c.store)
    return out


def bad_receipts():
    p = A.policy
    cases = [("failed", receipt("pg-coverage", ok=False)),
             ("ok_with_exit", receipt("pg-coverage", ok=True, exit_code=1)),
             ("not_ok_with_zero", receipt("pg-coverage", ok=False, exit_code=0)),
             ("one_schema_not_coverage", receipt("compare-pg")),
             ("observation_kind", receipt("observation")),
             ("hand_typed", {**receipt("pg-coverage"), "check": "hand_typed"})]
    out = {}
    for name, bad in cases:
        c = coordinator()
        sha = c.plan(manifest())["manifest_sha256"]
        walk(c, sha, "snapshot_sealed")
        evidence = gate_evidence(p.RESTORED_PAUSED, pg_comparison=bad)
        out[name] = {**guarded(c.store, c.advance, transition(sha, "snapshot_sealed", "restored_paused",
                                                                evidence=evidence)),
                     "state": c.status(MID)["state"]}
    return out


def failure_and_resume():
    p = A.policy
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, "snapshot_sealed")
    out = {"no_reason": guarded(c.store, c.advance, transition(sha, "snapshot_sealed", p.FAILED, exit_code=1))}
    out["failed"] = brief(c.advance(failure(sha, "snapshot_sealed", p.FAILED, "pg-restore-interrupted")))
    out["resume_elsewhere"] = guarded(c.store, c.advance, transition(sha, p.FAILED, "restored_paused"))
    out["resumed"] = brief(c.advance(transition(sha, p.FAILED, "snapshot_sealed")))
    out["status"] = c.status(MID)
    return out


def checkpoint_resume():
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    out = {"before_snapshot": guarded(c.store, c.checkpoint, checkpoint("pg_restore"))}
    walk(c, sha, "snapshot_sealed")
    out["first"] = c.checkpoint(checkpoint("pg_restore"))
    out["replay"] = c.checkpoint(checkpoint("pg_restore"))
    out["completed"] = c.completed_step(MID, "pg_restore", H)
    out["completed_unknown_step"] = c.completed_step(MID, "artifact_copy", H)
    out["completed_other_input"] = call(c.completed_step, MID, "pg_restore", "f" * 64)
    out["another_snapshot"] = guarded(c.store, c.checkpoint, checkpoint("pg_restore", input_sha="f" * 64))
    out["another_output"] = guarded(c.store, c.checkpoint, checkpoint("pg_restore", output_sha="f" * 64))
    out["reverse_step"] = guarded(c.store, c.checkpoint, checkpoint("reverse_pg_restore"))
    out["status"] = c.status(MID)
    return out


def limited_active_needs_intent():
    p = A.policy
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, "restored_paused")
    unbound = transition(sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE)
    out = {"no_intent": guarded(c.store, c.advance, unbound)}
    intent_id = c.intend_activation(intent_document())["intent_id"]
    out["intent_replay"] = c.intend_activation(intent_document())
    out["intent_conflict"] = guarded(c.store, c.intend_activation, {**intent_document(), "release_revision": "9" * 40})
    out["receipt_unbound"] = guarded(c.store, c.advance, unbound)
    active_only = gate_evidence(p.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
                                service_consumption=receipt("service-startup", "unit=active"))
    out["unit_active_is_not_consumption"] = guarded(c.store, c.advance, transition(
        sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE, evidence=active_only))
    other_image = activation_transition(c, sha) | {
        "identity": {"config_sha256": H, "commit": COMMIT, "image": "sha256:" + "0" * 64, "profile_sha256": H}}
    out["identity_mismatch"] = guarded(c.store, c.advance, other_image)
    out["limited_active"] = brief(c.advance(activation_transition(c, sha)))
    out["status"] = c.status(MID)
    out["document"] = c.activation_document(MID)
    return out


def intent_only_in_restored_paused():
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, "snapshot_sealed")
    return {"intent": guarded(c.store, c.intend_activation, intent_document()),
            "document": call(c.activation_document, MID),
            "rollback_plan": c.rollback_plan(MID)}


def rollback_without_intent():
    p = A.policy
    c = coordinator()
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, "restored_paused")
    c.advance(failure(sha, "restored_paused", p.ROLLBACK_REQUIRED, "canary-refused"))
    return {"plan": c.rollback_plan(MID),
            "reverse_step": guarded(c.store, c.checkpoint, checkpoint("reverse_pg_restore")),
            "wrong_gate": guarded(c.store, c.advance, transition(
                sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": receipt("gate-r1")})),
            "rolled_back": brief(c.advance(transition(
                sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": receipt("gate-r0")}))),
            "plan_after": c.rollback_plan(MID)}


def rollback_r1():
    """The store half of M7's writer-start-receipt-gap test (the launcher files are the adapter's)."""
    p = A.policy
    store = new_store()
    first = coordinator(store)
    sha = first.plan(manifest())["manifest_sha256"]
    walk(first, sha, "restored_paused")
    out = {"plan_before_intent": first.rollback_plan(MID),
           "document_before_intent": call(first.activation_document, MID)}
    first.intend_activation(intent_document())
    out["document_after_intent"] = first.activation_document(MID)
    second = coordinator(store)   # the coordinator restarted: the store is the only memory
    out["status_after_restart"] = second.status(MID)
    out["plan_r1"] = second.rollback_plan(MID)
    out["forward_restore"] = guarded(store, second.checkpoint, checkpoint("artifact_copy"))
    second.advance(failure(sha, p.RESTORED_PAUSED, p.ROLLBACK_REQUIRED, "writer-start-unknown"))
    out["document_while_rolling_back"] = guarded(store, second.activation_document, MID)
    out["gate_r0"] = guarded(store, second.advance, transition(
        sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": receipt("gate-r0")}))
    r1 = transition(sha, p.ROLLBACK_REQUIRED, p.ROLLED_BACK, evidence={"rollback_gate": receipt("gate-r1")})
    out["reverse_missing"] = guarded(store, second.advance, r1)
    out["checkpoints"] = [second.checkpoint(checkpoint(step))["recorded"] for step in p.REVERSE_STEPS]
    out["plan_completed"] = second.rollback_plan(MID)
    out["rolled_back"] = brief(second.advance(r1))
    return out


# ---- managed_lineage ------------------------------------------------------------------------------------------------

def legacy_identity_golden():
    p = A.policy
    c, sha, _ = activation_ready()
    document = activation_transition(c, sha)
    legacy = p.validate_transition(document)
    limited_bytes = hashlib.sha256(json.dumps(legacy, sort_keys=True, ensure_ascii=False,
                                              separators=(",", ":")).encode()).hexdigest()
    network = p.validate_transition(transition(sha, p.PLANNED, p.NETWORK_READY))
    out = {"lineage_key_added": "lineage" in legacy, "limited_id": p.transition_id(legacy),
           "limited_bytes": limited_bytes, "network_id": p.transition_id(network)}
    c.advance(document)
    view = c.status(MID)
    out.update(history_without_lineage=all("lineage" not in entry for entry in view["history"]),
               history=A.digest(view["history"]), row=A.digest(row(c.store)),
               activation_document=c.activation_document(MID), replay=brief(c.advance(document)))
    out["matches_m7_test_golden"] = {"limited_id": out["limited_id"] == LEGACY_GOLDEN["limited_id"],
                                     "limited_bytes": out["limited_bytes"] == LEGACY_GOLDEN["limited_bytes"],
                                     "network_id": out["network_id"] == LEGACY_GOLDEN["network_id"],
                                     "history": out["history"] == LEGACY_GOLDEN["history"],
                                     "row": out["row"] == LEGACY_GOLDEN["row"]}
    return out


def managed_lineage_binds():
    p = A.policy
    c, sha, intent_id = activation_ready()
    before = c.activation_document(MID)
    document = managed_transition(sha, intent_id)
    view = c.advance(document)
    key = view["history"][-1]["id"]
    with c.store.transaction() as tx:
        recorded = tx.get(A.BUCKET_TRANSITIONS, key)
    expected = {"owner": "managed", "descriptor": managed_descriptor(), "instance_id": INSTANCE_ID,
                "plan_id": PLAN_ID}
    legacy_shape = {k: v for k, v in recorded.items() if k != "lineage"}
    return {"view": view, "recorded": recorded, "lineage_is_expected": recorded["lineage"] == expected,
            "recorded_is_validated": recorded == p.validate_transition(document),
            "identity_commit_is_launcher_not_payload": recorded["identity"]["commit"] == COMMIT != PAYLOAD,
            "id_is_the_managed_tag": key == A.digest(["host-migration-transition-managed-v1", MID, p.RESTORED_PAUSED,
                                                       p.LIMITED_ACTIVE, sha, recorded["evidence"], expected]),
            "legacy_tag_never_names_it": p.transition_id(legacy_shape) != key,
            "activation_before": before, "activation_after": c.activation_document(MID)}


def lineage_interface():
    p = A.policy
    document = lineage()
    checked = p.validate_managed_lineage(document)
    identical = checked == document
    new_object = checked is not document and checked["descriptor"] is not document["descriptor"]
    document["descriptor"]["root"] = "/elsewhere"
    return {"equal": identical, "new_object": new_object,
            "copy_unaffected": checked["descriptor"]["root"] == managed_descriptor()["root"],
            "consumption_subject": p.managed_consumption_subject(checked),
            "consumption_is_recomputed": p.managed_consumption_subject(checked) == consumed(),
            "canary_subject": p.managed_canary_subject(checked),
            "canary_is_the_fixture": p.managed_canary_subject(checked) == CANARY,
            "receipts": [p.evidence_receipt(p.OBSERVATION, subject, 0, True, H)["subject"]
                         for subject in (consumed(), CANARY)]}


def _lineage_mutations():
    t = "transition_lineage_invalid"
    return [
        ("null", lambda d: d.update(lineage=None)),
        ("string", lambda d: d.update(lineage="managed")),
        ("list", lambda d: d.update(lineage=[lineage()])),
        ("owner_bootstrap", lambda d: d["lineage"].update(owner="bootstrap")),
        ("owner_case", lambda d: d["lineage"].update(owner="Managed")),
        ("owner_null", lambda d: d["lineage"].update(owner=None)),
        ("owner_list", lambda d: d["lineage"].update(owner=["managed"])),
        ("extra_digest_key", lambda d: d["lineage"].update(descriptor_sha256=H)),
        ("plan_id_missing", lambda d: d["lineage"].pop("plan_id")),
        ("descriptor_null", lambda d: d["lineage"].update(descriptor=None)),
        ("descriptor_string", lambda d: d["lineage"].update(descriptor=consumed())),
        ("descriptor_extra", lambda d: d["lineage"]["descriptor"].update(extra=1)),
        ("descriptor_schema", lambda d: d["lineage"]["descriptor"].update(schema="urn:zeus:host-descriptor:2")),
        ("descriptor_revision", lambda d: d["lineage"]["descriptor"].update(revision="EC8")),
        ("descriptor_worker_image", lambda d: d["lineage"]["descriptor"].update(worker_image=7)),
        ("descriptor_profile_digest", lambda d: d["lineage"]["descriptor"].update(profile_digest="x")),
        ("descriptor_root_blank", lambda d: d["lineage"]["descriptor"].update(root=" ")),
        ("descriptor_root_long", lambda d: d["lineage"]["descriptor"].update(root="/" + "r" * 400)),
        ("instance_upper", lambda d: d["lineage"].update(instance_id="A" * 32)),
        ("instance_short", lambda d: d["lineage"].update(instance_id="5" * 31)),
        ("instance_int", lambda d: d["lineage"].update(instance_id=5)),
        ("plan_id_empty", lambda d: d["lineage"].update(plan_id="")),
        ("plan_id_space", lambda d: d["lineage"].update(plan_id="plan id")),
        ("plan_id_bool", lambda d: d["lineage"].update(plan_id=True)),
        ("root_secret_value", lambda d: d["lineage"]["descriptor"].update(root="postgres://zeus:" + "hunter2@db/zeus")),
        ("secret_field", lambda d: d["lineage"].update(api_token="hunter2")),
    ], t


def lineage_field_refusals():
    out = {}
    mutations, _ = _lineage_mutations()
    for name, mutate in mutations:
        c, sha, intent_id = activation_ready()
        document = managed_transition(sha, intent_id)
        mutate(document)
        out[name] = guarded(c.store, c.advance, document)
    return out


def lineage_pure_validator():
    p = A.policy
    out = {}
    for name, value in (("none", None), ("empty", {}), ("owner_bootstrap", lineage(owner="bootstrap"))):
        out[name] = call(p.validate_managed_lineage, value)
    leaking = lineage()
    leaking["descriptor"]["root"] = "redis://:" + "hunter2@host:6379/0"
    out["secret_root"] = call(p.validate_managed_lineage, leaking)
    return out


def lineage_only_on_limited_active():
    p = A.policy
    out = {}
    for frm, to, reason in ((p.PLANNED, p.NETWORK_READY, None), (p.SNAPSHOT_SEALED, p.RESTORED_PAUSED, None),
                            (p.LIMITED_ACTIVE, p.QUALIFIED, None),
                            (p.RESTORED_PAUSED, p.FAILED, "limited-active-refused"),
                            (p.RESTORED_PAUSED, p.ROLLBACK_REQUIRED, "limited-active-refused")):
        for label, value in (("lineage", lineage()), ("null", None)):
            document = transition("a" * 64, frm, to, reason=reason, exit_code=1 if reason else 0)
            document["lineage"] = value
            out[frm + ">" + to + ":" + label] = call(p.validate_transition, document)
    return out


def neither_form_falls_back():
    p = A.policy
    c, sha, intent_id = activation_ready()
    without = managed_transition(sha, intent_id)
    del without["lineage"]
    out = {"legacy_form_revision_rule": guarded(c.store, c.advance, without),
           "managed_form_with_revision": guarded(c.store, c.advance, managed_transition(
               sha, intent_id, service_consumption=receipt("service-startup", "revision=" + COMMIT)))}
    out["legacy_still_advances"] = brief(c.advance(activation_transition(c, sha)))
    out["state"] = c.status(MID)["state"] == p.LIMITED_ACTIVE
    return out


def _receipt_cases():
    p = A.policy
    other = {**managed_descriptor(), "root": "/srv/zeus/managed/runtimes/other"}
    return [
        ("relabel_beside_good", "service_consumption",
         [receipt("service-startup", consumed()), receipt("service-startup", "revision=" + COMMIT)]),
        ("relabel_alone", "service_consumption", [receipt("service-startup", "revision=" + COMMIT)]),
        ("relabel_payload", "service_consumption", [receipt("service-startup", "revision=" + PAYLOAD)]),
        ("other_descriptor_beside_good", "service_consumption",
         [receipt("service-startup", consumed()), receipt("service-startup", consumed(other))]),
        ("bare_digest", "service_consumption", [receipt("service-startup", "descriptor=" + H)]),
        ("null_subject", "service_consumption", [receipt("service-startup", None)]),
        ("consumption_failed", "service_consumption", [receipt("service-startup", consumed(), ok=False)]),
        ("consumption_kind", "service_consumption", [receipt(p.OBSERVATION, consumed())]),
        ("canary_other_plan", "canary_admission",
         [receipt(p.OBSERVATION, CANARY), receipt(p.OBSERVATION, "canary=other-plan:instance=" + INSTANCE_ID)]),
        ("canary_other_instance", "canary_admission",
         [receipt(p.OBSERVATION, "canary=" + PLAN_ID + ":instance=" + "6" * 32)]),
        ("canary_null", "canary_admission", [receipt(p.OBSERVATION, None)]),
        ("canary_revision", "canary_admission", [receipt(p.OBSERVATION, "revision=" + COMMIT)]),
        ("canary_failed", "canary_admission", [receipt(p.OBSERVATION, CANARY, ok=False)]),
        ("canary_kind", "canary_admission", [receipt("service-startup", CANARY)]),
    ]


def receipts_name_the_binding():
    out = {}
    for name, gate, receipts in _receipt_cases():
        c, sha, intent_id = activation_ready()
        out[name] = guarded(c.store, c.advance, managed_transition(sha, intent_id, **{gate: receipts}))
    return out


def mutated_descriptor_or_host_receipt():
    c, sha, intent_id = activation_ready()
    out = {}
    for name, change in (("root", {"root": "/srv/zeus/managed/runtimes/other"}), ("revision", {"revision": "1" * 40}),
                         ("predecessor", {"predecessor": None}), ("target_id", {"target_id": "aibox-other"})):
        mutated = lineage(descriptor={**managed_descriptor(), **change})
        out["descriptor_" + name] = guarded(c.store, c.advance, managed_transition(
            sha, intent_id, lineage_document=mutated))
    out["other_plan"] = guarded(c.store, c.advance, managed_transition(
        sha, intent_id, lineage_document=lineage(plan_id="other-plan")))
    out["host_receipt_mixed"] = guarded(c.store, c.advance, managed_transition(
        sha, intent_id, host_activation=[receipt("host-activation", intent_id), receipt("host-activation", "0" * 64)]))
    moved = {**managed_descriptor(), "revision": "1" * 40, "root": "/srv/zeus/managed/runtimes/" + "1" * 40}
    out["archived_receipts_name_another_descriptor"] = guarded(c.store, c.advance, managed_transition(
        sha, intent_id, lineage_document=lineage(descriptor=moved)))
    return out


def descriptor_drift():
    out = {}
    for name, change in (("worker_image", {"worker_image": "sha256:" + "0" * 64}),
                         ("profile_digest", {"profile_digest": "0" * 64})):
        c, sha, intent_id = activation_ready()
        drifted = {**managed_descriptor(), **change}
        document = managed_transition(sha, intent_id, lineage_document=lineage(descriptor=drifted),
                                      service_consumption=receipt("service-startup", consumed(drifted)))
        out[name] = {**guarded(c.store, c.advance, document), "state": c.status(MID)["state"]}
    return out


def managed_identity_binds_activation():
    c, sha, intent_id = activation_ready()
    other_image = managed_transition(sha, intent_id)
    other_image["identity"]["image"] = "sha256:" + "0" * 64
    return {"commit_is_payload": guarded(c.store, c.advance, managed_transition(sha, intent_id, commit=PAYLOAD)),
            "other_image": guarded(c.store, c.advance, other_image), "state": c.status(MID)["state"]}


def managed_replay():
    p = A.policy
    c, sha, intent_id = activation_ready()
    out = {"stale_manifest": guarded(c.store, c.advance, managed_transition("e" * 64, intent_id))}
    stale_from = managed_transition(sha, intent_id)
    stale_from["from"] = p.SNAPSHOT_SEALED
    out["stale_from"] = guarded(c.store, c.advance, stale_from)
    document = managed_transition(sha, intent_id)
    out["first"] = brief(c.advance(document))
    after = store_state(c.store)
    out["replay"] = brief(c.advance(copy.deepcopy(document)))
    out["other_bytes"] = guarded(c.store, c.advance, {**copy.deepcopy(document), "at": "2026-09-25T05:11:00Z"})
    other_instance = "6" * 32
    out["other_lineage"] = guarded(c.store, c.advance, managed_transition(
        sha, intent_id, lineage_document=lineage(instance_id=other_instance),
        canary_admission=receipt(p.OBSERVATION, "canary=" + PLAN_ID + ":instance=" + other_instance)))
    out["legacy_afterwards"] = guarded(c.store, c.advance, activation_transition(c, sha))
    out["unchanged"] = store_state(c.store) == after
    c.advance(transition(sha, p.LIMITED_ACTIVE, p.QUALIFIED))
    later = store_state(c.store)
    out["historical_replay"] = brief(c.advance(copy.deepcopy(document)))
    out["historical_unchanged"] = store_state(c.store) == later
    return out


def legacy_replay_after_later_states():
    p = A.policy
    c, sha, _ = activation_ready()
    document = activation_transition(c, sha)
    c.advance(document)
    c.advance(transition(sha, p.LIMITED_ACTIVE, p.QUALIFIED))
    return {"replay": brief(c.advance(document)), "state": c.status(MID)["state"]}


def failed_transaction_leaves_nothing():
    store = new_store(FailingStore.make())
    c, sha, intent_id = activation_ready(store)
    before = store_state(store)
    store.fail = True
    failed = call(c.advance, managed_transition(sha, intent_id))
    out = {"failed": failed, "nothing_written": store_state(store) == before}
    store.fail = False
    view = c.advance(managed_transition(sha, intent_id))
    out["retry"] = brief(view)
    return out


def coordinator_records_archived_bindings():
    """The coordinator half of PH4-13: the recorded view and its authority text (no live state is sampled here)."""
    c, sha, intent_id = activation_ready()
    view = c.advance(managed_transition(sha, intent_id))
    return {"state": view["state"], "authority": view["authority"],
            "says_not_proof": "not proof" in view["authority"],
            "says_runtime_consumption": "runtime consumption" in view["authority"]}


# ---- successor_switch -----------------------------------------------------------------------------------------------

def successor_recorded():
    p = A.policy
    c, sha, intent_id = paused()
    before = row(c.store)
    transitions_before = store_state(c.store)
    recorded = c.record_successor(successor(intent_id))
    after = row(c.store)
    view = c.status(MID)
    document = c.activation_document(MID)
    return {"recorded": recorded, "row_history_tail": after["history"][-1],
            "unchanged_fields": {f: after[f] == before[f] for f in ("activation_intent", "state", "manifest",
                                                                   "manifest_sha256", "checkpoints")},
            "history_prefix_kept": after["history"][:-1] == before["history"],
            "only_the_row_changed": [k for k, v in store_state(c.store).items()
                                     if transitions_before.get(k) != v] == [A.BUCKET + "/" + MID],
            "activation_intent": view["activation_intent"], "activation_current": view["activation_current"],
            "activation_chain": view["activation_chain"], "state": view["state"],
            "rollback_mode": view["rollback_mode"], "mode_is_r1": view["rollback_mode"] == p.ROLLBACK_R1,
            "document": document,
            "document_names_the_successor": document["intent_id"] == recorded["successor_id"]}


def live_row():
    return {"migration_id": MID, "manifest": {}, "manifest_sha256": LIVE_MANIFEST, "state": A.policy.RESTORED_PAUSED,
            "history": [{"event": "activation_intent", "intent_id": LIVE_INTENT_ID}], "checkpoints": {},
            "activation_intent": A.policy.validate_intent({**LIVE_INTENT, "schema": A.policy.INTENT_SCHEMA})}


def live_intent_without_successor():
    store = new_store()
    with store.transaction() as tx:   # LABELLED: the live row's activation fields, not the live store
        tx.put(A.BUCKET, MID, live_row())
    c = coordinator(store)
    document = c.activation_document(MID)
    return {"document": document, "intent_id_is_live": document["intent_id"] == LIVE_INTENT_ID,
            "no_supersedes": "supersedes" not in document, "no_activation_kind": "activation_kind" not in document,
            "document_digest": canonical_digest(document), "chain": c.status(MID)["activation_chain"]}


def successor_state_intent_migration_refusals():
    p = A.policy
    store = new_store()
    c = coordinator(store)
    out = {"unknown": guarded(store, c.record_successor, successor(H))}
    sha = c.plan(manifest())["manifest_sha256"]
    walk(c, sha, p.RESTORED_PAUSED)
    out["no_intent"] = guarded(store, c.record_successor, successor(H))
    intent_id = c.intend_activation(intent_document())["intent_id"]
    c.advance(transition(sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE, evidence=gate_evidence(
        p.LIMITED_ACTIVE, host_activation=receipt("host-activation", intent_id),
        service_consumption=receipt("service-startup", "revision=" + COMMIT))))
    out["after_limited_active"] = guarded(store, c.record_successor, successor(intent_id))
    return out


def successor_field_refusals():
    out = {}
    cases = [("same_revision", {"release_revision": COMMIT}), ("image_changed", {"image": "sha256:" + "9" * 64}),
             ("profile_changed", {"profile_sha256": "9" * 64}),
             ("other_host", {"host_id": "machine-id-sha256:" + "9" * 64})]
    for name, change in cases:
        c, _, intent_id = paused()
        document = successor(intent_id, change.get("release_revision", NEXT))
        document.update(change)
        if change.get("image"):
            document["evidence"]["worker_compatibility"] = receipt(A.policy.OBSERVATION, "image=" + change["image"])
        out[name] = guarded(c.store, c.record_successor, document)
    c, _, intent_id = paused()
    out["secret_field"] = guarded(c.store, c.record_successor, {**successor(intent_id), "api_token": "hunter2"})
    out["secret_value"] = guarded(c.store, c.record_successor, successor(intent_id, actor="postgres://u:" + "hunter2@h/db"))
    return out


def successor_evidence_refusals():
    p = A.policy
    cases = [
        ("gate_missing", "admission_drained", None),
        ("gate_failing", "admission_drained", receipt(p.OBSERVATION, "fleet=paused-settled", ok=False)),
        ("gate_inconsistent", "admission_drained", receipt(p.OBSERVATION, "fleet=paused-settled", ok=True, exit_code=3)),
        ("release_identity_kind", "release_identity", receipt("host-activation", "revision=" + NEXT)),
        ("release_identity_subject", "release_identity", receipt(p.OBSERVATION, "revision=" + COMMIT)),
        ("worker_image_subject", "worker_compatibility", receipt(p.OBSERVATION, "image=sha256:" + "0" * 64)),
        ("gate_empty_list", "admission_drained", []),
    ]
    out = {}
    for name, gate, value in cases:
        c, _, intent_id = paused()
        document = successor(intent_id)
        if value is None:
            del document["evidence"][gate]
        else:
            document["evidence"][gate] = value
        out[name] = {**guarded(c.store, c.record_successor, document),
                     "current_is_intent": c.status(MID)["activation_current"] == intent_id}
    return out


def successor_replay():
    c, _, intent_id = paused()
    first = c.record_successor(successor(intent_id))
    again = c.record_successor(successor(intent_id))
    events = [e for e in c.status(MID)["history"] if e.get("event") == "activation_successor"]
    return {"first": first, "again": again, "again_is_first_cached": again == {**first, "recorded": False, "cached": True},
            "events": len(events)}


def successor_cas():
    c, _, intent_id = paused()
    first = c.record_successor(successor(intent_id))
    before = store_state(c.store)
    out = {"first": first,
           "second_of_same_head": guarded(c.store, c.record_successor, successor(intent_id, LATER)),
           "superseded_head": guarded(c.store, c.record_successor, successor("0" * 64, LATER)),
           "unchanged": store_state(c.store) == before}
    second = c.record_successor(successor(first["successor_id"], LATER))
    out["chained"] = second
    out["current_is_second"] = c.status(MID)["activation_current"] == second["successor_id"]
    out["third_of_first"] = guarded(c.store, c.record_successor, successor(first["successor_id"], "8" * 40))
    return out


def limited_active_binds_effective():
    p = A.policy
    c, sha, intent_id = paused()
    head = c.record_successor(successor(intent_id))["successor_id"]
    identity = {"config_sha256": H, "commit": NEXT, "image": IMAGE, "profile_sha256": H}

    def limited(activation_id, revision, ident=identity):
        return transition(sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE, identity=ident, evidence=gate_evidence(
            p.LIMITED_ACTIVE, host_activation=receipt("host-activation", activation_id),
            service_consumption=receipt("service-startup", "revision=" + revision)))
    return {"intent_receipt": guarded(c.store, c.advance, limited(intent_id, NEXT)),
            "superseded_revision": guarded(c.store, c.advance, limited(head, COMMIT)),
            "superseded_identity": guarded(c.store, c.advance, limited(head, NEXT, {**identity, "commit": COMMIT})),
            "limited_active": brief(c.advance(limited(head, NEXT))),
            "document": c.activation_document(MID)}


def rollback_successor():
    p = A.policy
    c, _, intent_id = paused()
    plan_before = c.rollback_plan(MID)
    first = c.record_successor(successor(intent_id))["successor_id"]
    back = c.record_successor(successor(first, COMMIT, reason_code="successor_rollback"))
    view = c.status(MID)
    document = c.activation_document(MID)
    return {"back": back, "activation_intent_is_original": view["activation_intent"] == intent_id,
            "current_is_back": view["activation_current"] == back["successor_id"],
            "revisions": [r["release_revision"] for r in view["activation_chain"]],
            "plan_unchanged": c.rollback_plan(MID) == plan_before, "plan_mode": plan_before["mode"],
            "mode_is_r1": plan_before["mode"] == p.ROLLBACK_R1,
            "document": document, "supersedes_first": document["supersedes"] == first,
            "new_head_not_old_receipt": document["intent_id"] != intent_id,
            "intent_row_unchanged": row(c.store)["activation_intent"] == p.validate_intent(intent_document())}


def successor_legacy_limited_golden():
    p = A.policy
    c, sha, _, head = on_successor()
    document = transition(sha, p.RESTORED_PAUSED, p.LIMITED_ACTIVE,
                          identity={"config_sha256": H, "commit": NEXT, "image": IMAGE, "profile_sha256": H},
                          evidence=gate_evidence(p.LIMITED_ACTIVE, host_activation=receipt("host-activation", head),
                                                 service_consumption=receipt("service-startup", "revision=" + NEXT)))
    legacy = p.validate_transition(document)
    out = {"lineage_key_added": "lineage" in legacy, "limited_id": p.transition_id(legacy),
           "limited_bytes": hashlib.sha256(json.dumps(legacy, sort_keys=True, ensure_ascii=False,
                                                      separators=(",", ":")).encode()).hexdigest()}
    c.advance(document)
    out["history"] = A.digest(c.status(MID)["history"])
    out["activation_document"] = c.activation_document(MID)
    out["matches_m7_test_golden"] = {"limited_id": out["limited_id"] == SUCCESSOR_GOLDEN["limited_id"],
                                     "limited_bytes": out["limited_bytes"] == SUCCESSOR_GOLDEN["limited_bytes"],
                                     "history": out["history"] == SUCCESSOR_GOLDEN["history"]}
    return out


def successor_managed_payload():
    p = A.policy
    c, sha, _, head = on_successor()
    document = managed_transition(sha, head, commit=NEXT)
    view = c.advance(document)
    entry = view["history"][-1]
    with c.store.transaction() as tx:
        recorded = tx.get(A.BUCKET_TRANSITIONS, entry["id"])
    activation = c.activation_document(MID)
    return {"payload_is_neither_launcher_revision": PAYLOAD not in (COMMIT, NEXT), "state": view["state"],
            "current_is_head": view["activation_current"] == head,
            "lineage_is_validated": entry["lineage"] == p.validate_managed_lineage(lineage()),
            "identity_commit": recorded["identity"]["commit"],
            "descriptor_revision": recorded["lineage"]["descriptor"]["revision"],
            "host_subjects": sorted({r["subject"] for r in recorded["evidence"]["host_activation"]}),
            "consumption_subjects": sorted({r["subject"] for r in recorded["evidence"]["service_consumption"]}),
            "canary_subjects": sorted({r["subject"] for r in recorded["evidence"]["canary_admission"]}),
            "activation": activation}


def successor_relabels():
    out = {}
    for case in ("identity_payload", "identity_intent", "host_intent", "revision_relabel"):
        c, sha, intent_id, head = on_successor()
        document = {
            "identity_payload": lambda: managed_transition(sha, head, commit=PAYLOAD),
            "identity_intent": lambda: managed_transition(sha, head, commit=COMMIT),
            "host_intent": lambda: managed_transition(sha, intent_id, commit=NEXT),
            "revision_relabel": lambda: managed_transition(
                sha, head, commit=NEXT, service_consumption=receipt("service-startup", "revision=" + NEXT)),
        }[case]()
        out[case] = guarded(c.store, c.advance, document)
    return out


def superseded_head_never_qualifies():
    p = A.policy
    c, sha, _, head = on_successor()
    later = c.record_successor(successor(head, LATER))["successor_id"]
    return {"superseded_head": guarded(c.store, c.advance, managed_transition(sha, head, commit=NEXT)),
            "later_with_next": guarded(c.store, c.advance, managed_transition(sha, later, commit=NEXT)),
            "later": c.advance(managed_transition(sha, later, commit=LATER))["state"],
            "qualifies": c.status(MID)["state"] == p.LIMITED_ACTIVE}


def successor_after_limited_active():
    c, sha, intent_id, head = on_successor()
    c.advance(managed_transition(sha, head, commit=NEXT))
    before, document = store_state(c.store), c.activation_document(MID)
    new = guarded(c.store, c.record_successor, successor(head, LATER))
    replay = c.record_successor(successor(intent_id))
    return {"new": new, "replay": replay, "replay_is_the_historic": replay == {
        "recorded": False, "cached": True, "successor_id": head, "predecessor_id": intent_id},
        "unchanged": store_state(c.store) == before, "document_unchanged": c.activation_document(MID) == document}


def switch_through_the_effect():
    c, _, intent_id = paused()
    effect = SwitchEffect()
    out = {"unknown": call(A.HostMigrations(new_store()).activation_switch, MID, SwitchEffect())}
    out["intent_head"] = c.activation_switch(MID, effect)
    out["intent_plan"] = effect.plans[0]
    head = c.record_successor(successor(intent_id))["successor_id"]
    before = store_state(c.store)
    out["successor_head"] = c.activation_switch(MID, effect, expected_id=head)
    plan = effect.plans[-1]
    out["successor_plan"] = plan
    out["plan_effective_is_the_document"] = plan["effective"] == c.activation_document(MID)
    out["stale_expected"] = call(c.activation_switch, MID, effect, expected_id=intent_id)
    out["effect_calls"] = len(effect.plans)
    refusing = SwitchEffect(raises=A.policy.MigrationRefused("recovery_precondition", "unit_active:zeus-aibox-fleet.service"))
    out["effect_refuses"] = call(c.activation_switch, MID, refusing, expected_id=head)
    boom = SwitchEffect(raises=RuntimeError("LABELLED effect failure"))
    out["effect_raises"] = call(c.activation_switch, MID, boom, expected_id=head)
    out["effect_saw_the_plan"] = [len(refusing.plans), len(boom.plans)]
    out["nothing_recorded"] = store_state(c.store) == before
    return out


def switch_refusals_by_state():
    p = A.policy
    out = {}
    c, sha, _ = paused()
    walk_state = c.status(MID)["state"]
    out["restored_paused"] = call(c.activation_switch, MID, SwitchEffect())
    c.advance(activation_transition(c, sha))
    out["limited_active"] = call(c.activation_switch, MID, SwitchEffect())
    c.advance(transition(sha, p.LIMITED_ACTIVE, p.QUALIFIED))
    out["qualified"] = call(c.activation_switch, MID, SwitchEffect())
    c2 = coordinator()
    sha2 = c2.plan(manifest())["manifest_sha256"]
    walk(c2, sha2, p.RESTORED_PAUSED)
    out["no_intent"] = call(c2.activation_switch, MID, SwitchEffect())
    c2.intend_activation(intent_document())
    c2.advance(failure(sha2, p.RESTORED_PAUSED, p.ROLLBACK_REQUIRED, "writer-start-unknown"))
    out["rolling_back"] = call(c2.activation_switch, MID, SwitchEffect())
    out["first_state"] = walk_state
    return out


# ---- run ------------------------------------------------------------------------------------------------------------

GROUPS = {
    "manifest_plan": [("digest_order_independent", manifest_digest_order), ("refusals", manifest_refusals),
                      ("source_public_control_ledger", source_public_control_ledger),
                      ("plan_idempotent_and_conflict", plan_idempotent_and_conflict),
                      ("unknown_migration", unknown_migration_reads)],
    "advance_checkpoints": [("forward_walk", forward_walk), ("bad_receipts", bad_receipts),
                            ("failure_and_resume", failure_and_resume), ("checkpoint_resume", checkpoint_resume),
                            ("limited_active_needs_intent", limited_active_needs_intent),
                            ("intent_only_in_restored_paused", intent_only_in_restored_paused),
                            ("rollback_without_intent", rollback_without_intent), ("rollback_r1", rollback_r1)],
    "managed_lineage": [("legacy_identity_golden", legacy_identity_golden), ("binds_the_payload", managed_lineage_binds),
                        ("interface", lineage_interface), ("field_refusals", lineage_field_refusals),
                        ("pure_validator", lineage_pure_validator), ("only_limited_active", lineage_only_on_limited_active),
                        ("neither_form_falls_back", neither_form_falls_back),
                        ("receipts_name_the_binding", receipts_name_the_binding),
                        ("mutated_descriptor_or_host_receipt", mutated_descriptor_or_host_receipt),
                        ("descriptor_drift", descriptor_drift), ("identity_binds_activation", managed_identity_binds_activation),
                        ("managed_replay", managed_replay), ("legacy_replay_later", legacy_replay_after_later_states),
                        ("failed_transaction", failed_transaction_leaves_nothing),
                        ("archived_bindings_only", coordinator_records_archived_bindings)],
    "successor_switch": [("recorded", successor_recorded), ("live_intent_receipt", live_intent_without_successor),
                         ("state_intent_migration_refusals", successor_state_intent_migration_refusals),
                         ("field_refusals", successor_field_refusals), ("evidence_refusals", successor_evidence_refusals),
                         ("replay", successor_replay), ("cas", successor_cas),
                         ("limited_active_binds_effective", limited_active_binds_effective),
                         ("rollback_successor", rollback_successor),
                         ("legacy_limited_golden", successor_legacy_limited_golden),
                         ("managed_payload", successor_managed_payload), ("relabels", successor_relabels),
                         ("superseded_head_never_qualifies", superseded_head_never_qualifies),
                         ("after_limited_active", successor_after_limited_active),
                         ("switch_through_the_effect", switch_through_the_effect),
                         ("switch_refusals_by_state", switch_refusals_by_state)],
}


def run(api) -> dict:
    global A
    A = api
    out = {}
    for group, cases in GROUPS.items():
        out[group] = {}
        for name, fn in cases:
            STORES.clear()
            try:
                result = fn()
            except Exception as exc:  # an unexpected failure of the characterized operation is itself compared
                result = {"case_error": type(exc).__name__, "message": str(exc)[:200]}
            out[group][name] = {"steps": result, "stores": [sorted([k, v] for k, v in store_state(s).items())
                                                            for s in STORES]}
    return out
