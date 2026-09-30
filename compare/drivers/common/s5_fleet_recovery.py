"""Shared S5 scenario steps (`coordination.fleet_recovery`): M7 `Fleet.reconcile_interrupted` / `recovery`, the owner
recovery of one interrupted job (RESEARCH-S5 D7, TRACE C1; M7 tests/test_fleet_recovery.py), with hand-built evidence
and proof documents. The proof collector is the S7 adapter, so it is not part of this family.

- **Evidence.** Strict evidence refusals.
- **Order of refusals.** A missing observation. The fleet not paused. Then configuration, owner, lane and operation
  mismatches, checked in that order.
- **Proof refusals.** The schema, the task not cancelled, a live lease, a running container, a missing container
  binding, an open invocation, an unbound or open slot, and a proof that changed between the two reads.
- **Recovery.** The job becomes `failed`/`interrupted_unknown` with its receipt. An identical replay is answered from
  the receipt without observing anything, and other evidence for the job conflicts.
- **After recovery.** The recovery view, and the freed lane admits the next job.

Layer: harness (never shipped)

`api` supplies MemoryStore, `Fleet(store, clock, token)` and `validate_manifest(document)`. The compared results are
the values or refusals with their reason codes, the observation calls, and the final store records by body digest.
"""

from __future__ import annotations

import copy
import hashlib
import json

BASE = "a" * 40
ROOT = "/zeus-rebuild-s5-fleet"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}
TASK, OPERATION, RUN = "task-92b13b20", "op-1", "1a" * 16
CONTAINER, RESERVATION, SLOT = "c7" * 32, "d4" * 32, "e9" * 16


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config():
    lanes = [{"id": "a", "team": "alpha", "repository": ROOT + "/repo-a", "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": ROOT + "/rt-a"},
             {"id": "b", "team": "beta", "repository": ROOT + "/repo-b", "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": ROOT + "/rt-b"}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes}


def ticking():
    counter = iter(range(1, 100_000))
    return lambda: "2026-09-21T00:00:00.%06d+00:00" % next(counter)


def hex_tokens():
    counter = iter(range(1, 100_000))
    return lambda: "%032x" % next(counter)


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "message": str(exc)[:160]}
    return {"value": value}


def evidence(job, config_sha256, **overrides):
    document = {"schema": "urn:zeus:fleet-recovery-evidence:1", "job_id": job["id"], "operator": "owner",
                "expected": {"status": job["status"], "owner_token": job["owner_token"], "lane": job["lane"],
                             "config_sha256": config_sha256},
                "lane_operation": {"id": OPERATION, "correlation_id": "operation:" + OPERATION, "task_id": TASK,
                                   "generation": 2},
                "container": {"run_id": RUN, "role": "worker", "name": "zeus-worker-" + RUN, "id": CONTAINER},
                "invocation": {"reservation_id": RESERVATION, "status": "unsettled_unknown"},
                "machine_slot": {"id": SLOT, "outcome": "unknown"},
                "recorded_at": "2026-09-21T00:00:00+00:00"}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer] = {**document[outer], inner: value}
        else:
            document[outer] = value
    return document


def proof(**overrides):
    document = {"schema": "urn:zeus:fleet-recovery-proof:1",
                "lane_operation": {"id": OPERATION, "correlation_id": "operation:" + OPERATION},
                "task": {"id": TASK, "generation": 2, "status": "cancelled", "lease_live": False},
                "container": {"run_id": RUN, "name": "zeus-worker-" + RUN, "id": CONTAINER,
                              "bound_worktree": True, "state": "exited"},
                "invocation": {"reservation_id": RESERVATION, "status": "unsettled_unknown"},
                "machine_slot": {"id": SLOT, "outcome": "unknown", "bound_by": "ledger_purpose",
                                 "bound_operation": OPERATION, "status": "used"},
                "observed_at": "2026-09-21T00:00:01+00:00"}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        document[outer] = {**document[outer], inner: value} if inner else value
    return document


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def run(api) -> dict:
    out, observed = {}, []

    def manifest(op_id, paths):
        return api.validate_manifest({
            "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
            "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": "r"},
            "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": paths},
            "budget": {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})

    store = api.MemoryStore()
    fleet = api.Fleet(store, ticking(), hex_tokens())
    registered = fleet.register(config())
    digest_ = registered["config_sha256"]
    fleet.enqueue("a", manifest(OPERATION, ["docs/x.md"]), GOAL, [])
    fleet.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, [])
    job = fleet.admit_one()["job"]
    fleet.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "receipt_missing"})
    with store.transaction() as tx:
        job = tx.get("fleet_jobs", job["id"])
    good = evidence(job, digest_)

    for name, document in (("schema", {**good, "schema": "urn:other"}), ("job_id", {**good, "job_id": "bad id"}),
                           ("status", evidence(job, digest_, **{"expected.status": "queued"})),
                           ("container_name", evidence(job, digest_, **{"container.name": "zeus-other"})),
                           ("invocation_open", evidence(job, digest_, **{"invocation.status": "reserved"})),
                           ("extra", {**good, "extra": 1})):
        out["evidence_" + name] = call(fleet.reconcile_interrupted, document, proof())
    out["no_observation"] = call(fleet.reconcile_interrupted, good)
    out["not_paused"] = call(fleet.reconcile_interrupted, good, proof())
    fleet.pause()
    out["config_mismatch"] = call(fleet.reconcile_interrupted, evidence(job, "f" * 64), proof())
    out["owner_mismatch"] = call(fleet.reconcile_interrupted, evidence(job, digest_, **{"expected.owner_token": "0" * 32}),
                                 proof())
    out["lane_mismatch"] = call(fleet.reconcile_interrupted, evidence(job, digest_, **{"expected.lane": "b"}), proof())
    other = evidence(job, digest_, **{"lane_operation.id": "op-9", "lane_operation.correlation_id": "operation:op-9"})
    out["operation_mismatch"] = call(fleet.reconcile_interrupted, other,
                                     proof(lane_operation={"id": "op-9", "correlation_id": "operation:op-9"},
                                           machine_slot={**proof()["machine_slot"], "bound_operation": "op-9"}))
    for name, bad in (("schema", proof(schema="urn:other")),
                      ("task_not_cancelled", proof(**{"task.status": "running"})),
                      ("lease_live", proof(**{"task.lease_live": True})),
                      ("container_running", proof(**{"container.state": "running"})),
                      ("container_unbound", proof(**{"container.bound_worktree": False})),
                      ("invocation_mismatch", proof(**{"invocation.status": "reserved"})),
                      ("slot_unbound", proof(**{"machine_slot.bound_by": "guess"})),
                      ("slot_open", proof(**{"machine_slot.status": "reserved"}))):
        out["proof_" + name] = call(fleet.reconcile_interrupted, good, bad)
    out["proof_changed"] = call(fleet.reconcile_interrupted, good, proof(),
                                reread=lambda: proof(**{"container.state": "dead"}))
    out["before_records"] = records(store)

    def observe():
        observed.append("observe")
        return proof()

    def reread():
        observed.append("reread")
        return proof(observed_at="2026-09-21T00:00:02+00:00")
    out["reconciled"] = call(fleet.reconcile_interrupted, good, observe=observe, reread=reread)

    def must_not_observe():
        observed.append("observed-on-replay")
        raise RuntimeError("a replay must not observe")
    out["replay"] = call(fleet.reconcile_interrupted, copy.deepcopy(good), observe=must_not_observe)
    out["conflict"] = call(fleet.reconcile_interrupted, evidence(job, digest_, operator="someone"), proof())
    out["observed"] = list(observed)
    out["recovery"] = call(fleet.recovery, job["id"])
    out["recovery_absent"] = call(fleet.recovery, "op-2")
    out["unregistered"] = call(api.Fleet(api.MemoryStore(), ticking(), hex_tokens()).reconcile_interrupted, good,
                               proof())
    fleet.resume()
    out["admit_after"] = call(fleet.admit_one)
    out["status"] = call(fleet.status)
    out["records"] = records(store)
    return out
