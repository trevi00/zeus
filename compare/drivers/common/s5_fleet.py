"""Shared S5 scenario steps (`coordination.fleet`): M7 `Fleet` registry, enqueue, admission, finalization, execution
units and budget grants (RESEARCH-S5 D7/D8/D11, local check (e)), in the sequences of the M7 tests
(tests/test_fleet.py).

- **Registry.** Config refusals (a few), an idempotent register and registration conflicts.
- **enqueue.** Refusals, idempotence and binding conflicts.
- **Admission.** Path conflicts across two lanes of one repository. Lane exclusivity, dependency waiting and
  capacity. The budget_exhausted and paused reasons, persisted per job. Only the owner finalizes. An `unknown` outcome
  keeps its lane and slot.
- **Execution units.** They share one capacity with jobs; a replay is cached; `unit_conflict`. Only an exact cleanup
  or fenced proof releases a unit, exactly once; `settlement_conflict`.
- **authorize_budget.** Refusals and the idle-only grant.
- **Reads.** `status`, `reconciliation_required`, `units` and `held_units`.

Layer: harness (never shipped)

`api` supplies MemoryStore, `Fleet(store, clock, token)`, `validate_manifest(document)` (bound to the packaged
provider policy) and `validate_config`. Paths are fixed absolute labels (never created). The compared results are the
values or refusals (refusals carry their reason code) and the final store records by body digest.
"""

from __future__ import annotations

import hashlib
import json

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
ROOT = "/zeus-rebuild-s5-fleet"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}
UNIT_A, UNIT_B, UNIT_C = "1" * 64, "2" * 64, "3" * 64


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config(root=ROOT, **overrides):
    lanes = [{"id": "a", "team": "alpha", "repository": root + "/repo-a", "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": root + "/rt-a"},
             {"id": "b", "team": "beta", "repository": root + "/repo-b", "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": root + "/rt-b"}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes, **overrides}


def cleanup(unit, token, **overrides):
    return {"kind": "cleanup", "launch": unit, "token": token, "confirmed": True, "exit_code": 0,
            "timed_out": False, "parent": {"confirmed": True}, "tree": {"confirmed": True}, **overrides}


def ticking():
    counter = iter(range(1, 100_000))
    return lambda: "2026-09-18T00:00:00.%06d+00:00" % next(counter)


def tokens():
    counter = iter(range(1, 100_000))
    return lambda: "token-%04d" % next(counter)


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


def run(api) -> dict:
    out = {}

    def manifest(op_id, paths, budget=None):
        return api.validate_manifest({
            "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
            "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": CANARY},
            "plan": {"objective": CANARY, "acceptance_criteria": ["ok"], "allowed_paths": paths},
            "budget": budget or {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})

    def fleet(**overrides):
        f = api.Fleet(api.MemoryStore(), ticking(), tokens())
        f.register(config(**overrides))
        return f

    lane = config()["lanes"]
    for name, overrides in (("schema", {"schema": "urn:zeus:fleet:2"}), ("parallel_zero", {"max_parallel": 0}),
                            ("parallel_three", {"max_parallel": 3}), ("budget", {"budget": {"per_host": 4, "total": 2}}),
                            ("no_lanes", {"lanes": []}), ("dup_lane", {"lanes": [lane[0], {**lane[1], "id": "a"}]}),
                            ("public_schema", {"lanes": [{**lane[0], "schema": "public"}]}),
                            ("relative_repo", {"lanes": [{**lane[0], "repository": "relative/repo"}]}),
                            ("nested_runtime", {"lanes": [lane[0], {**lane[1], "runtime": ROOT + "/rt-a/inner"}]}),
                            ("extra_field", {"token": "x"})):
        out["config_" + name] = call(api.validate_config, config(**overrides))
    out["config_valid"] = call(api.validate_config, config())

    store = api.MemoryStore()
    out["register"] = call(api.Fleet(store, ticking(), tokens()).register, config())
    out["register_again"] = call(api.Fleet(store, ticking(), tokens()).register, config())
    out["register_conflict"] = call(api.Fleet(store, ticking(), tokens()).register, config(max_parallel=1))
    out["unregistered_enqueue"] = call(api.Fleet(api.MemoryStore(), ticking(), tokens()).enqueue, "a",
                                       manifest("op", ["docs/x.md"]), GOAL, [])

    # enqueue
    f = fleet()
    out["enqueue_lane_unknown"] = call(f.enqueue, "z", manifest("op-1", ["docs/x.md"]), GOAL, [])
    out["enqueue_budget_mismatch"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"], {"per_host": 1, "total": 8}),
                                          GOAL, [])
    out["enqueue_dependency_missing"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"]), GOAL, ["absent"])
    out["enqueue_dependency_self"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"]), GOAL, ["op-1"])
    out["enqueue"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    out["enqueue_again"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    out["enqueue_binding_conflict_lane"] = call(f.enqueue, "b", manifest("op-1", ["docs/x.md"]), GOAL, [])
    out["enqueue_binding_conflict_goal"] = call(f.enqueue, "a", manifest("op-1", ["docs/x.md"]),
                                                {**GOAL, "criterion": "changed"}, [])
    out["enqueue_records"] = records(f.store)

    # admission over two lanes of one repository: a case-insensitive directory prefix conflicts
    shared_config = config()
    shared_config["lanes"][1]["repository"] = shared_config["lanes"][0]["repository"]
    shared = api.Fleet(api.MemoryStore(), ticking(), tokens())
    shared.register(shared_config)
    shared.enqueue("a", manifest("op-1", ["docs/guide"]), GOAL, [])
    shared.enqueue("b", manifest("op-2", ["Docs/Guide/x.md"]), GOAL, [])
    shared.enqueue("b", manifest("op-3", ["src/free.py"]), GOAL, [])
    out["shared_admit"] = [call(shared.admit_one) for _ in range(3)]
    out["shared_status"] = call(shared.status)

    # lanes, dependencies, capacity, budget, pause, finalize, unknown
    f = fleet()
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    f.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, [])
    f.enqueue("b", manifest("op-3", ["docs/x.md"]), GOAL, ["op-1"])
    f.enqueue("b", manifest("op-4", ["docs/z.md"]), GOAL, [])
    one = f.admit_one()
    out["admit_1"] = {"value": one}
    out["admit_budget_exhausted"] = call(f.admit_one, budget_exhausted=True)
    out["pause"] = call(f.pause)
    out["admit_paused"] = call(f.admit_one)
    out["resume"] = call(f.resume)
    four = f.admit_one()
    out["admit_2"] = {"value": four}
    out["admit_full"] = call(f.admit_one)
    out["finalize_owner_mismatch"] = call(f.finalize, "op-1", "not-the-owner", {"status": "failed", "reason_code": "x"})
    out["finalize_not_dispatching"] = call(f.finalize, "op-2", "t", {"status": "failed", "reason_code": "x"})
    out["finalize_not_terminal"] = call(f.finalize, "op-1", one["job"]["owner_token"], {"status": "running"})
    out["finalize_failed"] = call(f.finalize, "op-1", one["job"]["owner_token"],
                                  {"status": "failed", "reason_code": "exception:ValueError:" + CANARY, "exit_code": 1})
    out["finalize_unknown"] = call(f.finalize, "op-4", four["job"]["owner_token"],
                                   {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0})
    two = f.admit_one()
    out["admit_3"] = {"value": two}
    out["reconciliation_required"] = call(f.reconciliation_required)
    out["finalize_accepted"] = call(f.finalize, "op-2", two["job"]["owner_token"],
                                    {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0,
                                     "calls": {"reserved": 2, "settled": 2}})
    out["admit_4"] = call(f.admit_one)
    out["status"] = call(f.status)
    out["admission_records"] = records(f.store)

    # execution units share capacity with jobs
    f = fleet(max_parallel=1)
    f.enqueue("a", manifest("op-1", ["docs/a.md"]), GOAL, [])
    held = f.reserve_unit(UNIT_A, "conductor", "b", "intent-1")
    out["unit_reserve"] = {"value": held}
    out["unit_blocks_job"] = call(f.admit_one)
    out["unit_replay"] = call(f.reserve_unit, UNIT_A, "conductor", "b", "intent-1")
    out["unit_conflict"] = call(f.reserve_unit, UNIT_A, "conductor", "b", "intent-2")
    out["unit_invalid_id"] = call(f.reserve_unit, "xyz", "conductor", "b", "intent-9")
    out["unit_invalid_kind"] = call(f.reserve_unit, UNIT_C, "worker", "b", "intent-9")
    token = held["token"]
    for name, proof in (("tree_unconfirmed", cleanup(UNIT_A, token, tree={"confirmed": False})),
                        ("parent_unconfirmed", cleanup(UNIT_A, token, parent={"confirmed": False})),
                        ("unconfirmed", cleanup(UNIT_A, token, confirmed=False)),
                        ("other_unit", cleanup(UNIT_B, token)), ("other_token", cleanup(UNIT_A, "other")),
                        ("fenced_without_claim", {"kind": "fenced", "launch": UNIT_A}),
                        ("exit_kind", {"kind": "exit", "launch": UNIT_A}), ("none", None)):
        out["settle_" + name] = call(f.settle_unit, UNIT_A, token, proof)
    out["settle_stale_token"] = call(f.settle_unit, UNIT_A, "stale-token", cleanup(UNIT_A, token))
    out["held_after_refusals"] = call(f.held_units)

    def failing_commit(tx, unit):
        raise ConnectionError("commit failed (injected)")
    out["settle_failed_commit"] = call(f.settle_unit, UNIT_A, token, cleanup(UNIT_A, token), within=failing_commit)
    writes = []
    out["settle"] = call(f.settle_unit, UNIT_A, token, cleanup(UNIT_A, token),
                         within=lambda tx, unit: writes.append(unit["id"]))
    out["settle_replay"] = call(f.settle_unit, UNIT_A, token, cleanup(UNIT_A, token),
                                within=lambda tx, unit: writes.append(unit["id"]))
    out["settle_writes"] = writes
    out["settle_conflict"] = call(f.settle_unit, UNIT_A, token, cleanup(UNIT_A, token, exit_code=1))
    job = f.admit_one()["job"]
    out["unit_after_job"] = call(f.reserve_unit, UNIT_B, "conductor", "b", "intent-2")
    f.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "outcome_uncertain"})
    out["unit_after_unknown"] = call(f.reserve_unit, UNIT_B, "conductor", "b", "intent-2")
    out["units"] = call(f.units)
    out["unit_records"] = records(f.store)
    paused = fleet()
    paused.pause()
    out["unit_paused"] = call(paused.reserve_unit, UNIT_C, "conductor", "a", "intent-3")
    fenced_fleet = fleet()
    fenced_token = fenced_fleet.reserve_unit(UNIT_B, "conductor", "a", "intent-2")["token"]
    out["settle_fenced"] = call(fenced_fleet.settle_unit, UNIT_B, fenced_token,
                                {"kind": "fenced", "launch": UNIT_B, "claim": "fenced"})

    # budget grants: refusals without a write, then the idle-only grant
    f = fleet()
    for name, kwargs in (("expected_mismatch", dict(per_host=6, total=12, expected_total=7)),
                         ("decrease", dict(per_host=3, total=12, expected_total=8)),
                         ("no_increase", dict(per_host=4, total=8, expected_total=8)),
                         ("invalid", dict(per_host=0, total=8, expected_total=8))):
        out["grant_" + name] = call(f.authorize_budget, **kwargs)
    out["grant_unregistered"] = call(api.Fleet(api.MemoryStore(), ticking(), tokens()).authorize_budget, 6, 12, 8)
    f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
    out["grant_not_idle"] = call(f.authorize_budget, 6, 12, 8)
    idle = fleet()
    idle.enqueue("a", manifest("op-0", ["docs/x.md"]), GOAL, [])
    idle.finalize("op-0", idle.admit_one()["job"]["owner_token"],
                  {"status": "rejected", "reason_code": "lead_rejected", "exit_code": 1})
    idle.pause()
    out["grant"] = call(idle.authorize_budget, 6, 12, 8)
    out["grants"] = call(idle.budget_grants)
    out["grant_resume"] = call(idle.resume)
    out["grant_stale_job"] = call(idle.enqueue, "a", manifest("op-5", ["docs/q.md"]), GOAL, [])
    out["grant_records"] = records(idle.store)
    out["canary_absent"] = CANARY not in json.dumps(out)
    return out
