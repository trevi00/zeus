"""Shared S5 scenario steps (`coordination.operation`): M7 `Operation.run/claim/status` and the manifest rules
(RESEARCH-S5 D5/D6, local check (d)).

The fixtures are the labelled M7 test fixtures (tests/test_operation.py): a message bus, a fault-injected call
budget, an executor that settles the guarded row the way the real one would (with a bound evidence-inspection row),
and a collector. Each case runs on a fresh store through the side's own service, Workflow and LocalCycle.

Cases:
- **manifest:** the documented example and a few refusals; the assignment id is deterministic;
- **the two-stage success;**
- **idempotence:** the same-id replay is cached, a different binding is `configuration_mismatch`, and running and
  cycle residue refuse without a takeover;
- **failures:** worker failure, a worker exception and an incomplete evidence inspection (a failed outcome plus an
  owner handoff);
- **lead review:** a rejection;
- **budget:** ledger exhaustion and a first settlement failure;
- **collection:** a collection failure;
- **deadline:** a passed deadline;
- **status.**

Layer: harness (never shipped)

`api` supplies MemoryStore, `service(store)`, `workflow(store)`, `Operation(service, executor, bus, workflow, budget,
collector)` (the side's Operation, wired with its evidence records), `validate_manifest(document)` (bound to the
packaged provider policy), `assignment_message_id`, `envelope(...)` and `advance(seconds)`. The compared results are
the receipts by digest with their status, reason and exit code, the executor calls, the budget reservations and
settlements, and the final store records by body digest.
"""

from __future__ import annotations

import copy
import hashlib
import json

CANARY = "CANARY-must-never-be-emitted"
BASE = "a" * 40
GOAL = {"path": "docs/zeus/operations/GOAL.md", "sha256": "b" * 64, "criterion": "one-start entry point",
        "rationale": "the runbook task exercises the entry point"}
IDENTITY = {"repository": "r", "runtime": "d", "runtime_policy": "p",
            "provider": {"policy_digest": "x", "config_digest": "y"}}
BOUND_GOAL = {**GOAL, "base_revision": BASE, "bytes": 3}
PAST = "2020-01-01T00:00:00+00:00"


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest(**overrides):
    document = {"schema": "urn:zeus:operation:1", "id": "op-001", "base_revision": BASE, "goal": dict(GOAL),
                "plan": {"objective": "Add the RUNBOOK note " + CANARY, "acceptance_criteria": ["focused tests pass"],
                         "allowed_paths": ["docs/zeus/operations/operation-entrypoint-001/RUNBOOK.md"]},
                "budget": {"per_host": 4, "total": 8},
                "claude": {"model": "claude-fixture-model", "timeout_seconds": 300, "max_budget_usd": 2}}
    for key, value in overrides.items():
        outer, _, inner = key.partition(".")
        if inner:
            document[outer][inner] = value
        else:
            document[outer] = value
    return document


class Bus:
    def __init__(self):
        self.queued, self.acked, self.published = [], [], []

    def receive(self, agent, consumer):
        for entry in self.queued:
            if entry[1]["who"]["recipient"] == agent and entry[0] not in self.acked:
                return entry[0], {"body": entry[1]}
        return None

    @staticmethod
    def decode(fields):
        return fields["body"]

    def ack(self, agent, entry_id):
        self.acked.append(entry_id)

    def dead_letter(self, agent, entry_id, fields, reason):
        self.acked.append(entry_id)

    @staticmethod
    def validate(message):
        return message

    def publish(self, message):
        entry = str(len(self.published) + 1) + "-0"
        self.published.append(message)
        self.queued.append((entry, message))
        return entry


class FakeBudget:
    def __init__(self, refuse_after=None, settle_fail=None):
        self.reserved, self.settled, self.refuse_after, self.settle_fail = [], [], refuse_after, settle_fail
        self.settle_calls = 0

    def reserve(self, *, per_host, total, purpose, provider, model):
        if self.refuse_after is not None and len(self.reserved) >= self.refuse_after:
            raise self.error("ledger full (fixture)")
        slot = {"id": "slot-" + str(len(self.reserved) + 1), "reserved_at": "t", "purpose": purpose,
                "per_host": per_host, "total": total, "provider": provider, "model": model}
        self.reserved.append(slot)
        return slot

    def settle(self, slot_id, *, outcome, detail=None):
        self.settle_calls += 1
        if self.settle_fail == self.settle_calls:
            raise OSError("settle failed (fixture)")
        self.settled.append((slot_id, outcome))


class FakeExecutor:
    def __init__(self, api, svc, worker="succeeded", verdict=True, inspection="bound", raise_error=None):
        self.api, self.svc, self.worker, self.verdict = api, svc, worker, verdict
        self.inspection, self.raise_error, self.calls = inspection, raise_error, []

    def execute_one(self, agent, expected=None):
        self.calls.append("task")
        if self.raise_error:
            raise self.raise_error
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            task.update(status=self.worker, attempt=1, generation=1, lease_owner="fixture")
            if self.worker == "succeeded":
                candidate = {"revision": "c" * 40, "base": BASE, "tree": "7" * 40, "diff_hash": "d" * 64,
                             "path": "D:/secret/" + CANARY}
                inspection_id = "insp-" + task["id"]
                binding = {"task_id": task["id"], "generation": 1, "attempt": 1,
                           "source_revision": candidate["revision"]}
                findings = [{"claim": {"kind": "project_check", "check_id": "unit", "status": "executed",
                                       "argv": ["python", "-m", "pytest", CANARY]}, "state": "checked", "cause": None},
                            {"claim": {"kind": "project_check", "check_id": "lint", "status": "missing"},
                             "state": "not_checked", "cause": "required check has no observation " + CANARY}]
                tx.put("evidence_inspections", inspection_id, {
                    "id": inspection_id, "binding": binding, "policy_hash": "ph", "findings": findings,
                    "verdict": "incomplete" if self.inspection == "incomplete" else "all_checked",
                    "denominator": {"claims": 2, "checked": 0 if self.inspection == "incomplete" else 1,
                                    "not_checked": 1}})
                task["result"] = {"summary": CANARY, "candidate": candidate, "execution_ref": "sha256:" + "e" * 64,
                                  "evidence_inspection": {"inspection_id": inspection_id, "verdict": "all_checked"}}
                report = self.api.envelope("task.result", task["agent"], "lead:improvement", "implement",
                                           {"task_id": task["id"], "result": task["result"]},
                                           task["message"]["correlation_id"])
                tx.put("outbox", report["message_id"], {"message": report, "sent": False})
            else:
                task["error"] = "provider failed: " + CANARY
            tx.put("tasks", task["id"], task)
            return task

    def decide_one(self, agent, expected=None):
        self.calls.append("decision")
        with self.svc.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            row.update(status="succeeded", result={"accepted": self.verdict, "reason": CANARY,
                                                   "execution_ref": "sha256:" + "f" * 64})
            tx.put("decisions_pending", row["id"], row)
            return row


class Collector:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def collect(self):
        self.calls += 1
        return {"files": 1, "records": 3, "inserted": 3, "sink_failures": 1 if self.fail else 0, "corrupt": 0}


def refusal(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200],
                "reason_code": getattr(exc, "reason_code", None)}
    return {"value": canonical_digest(value)}


def case(api, *, budget=None, collector=None, prepare=None, goal=None, deadline=None, **executor):
    svc = api.service(api.MemoryStore())
    fake = FakeExecutor(api, svc, **executor)
    budget = budget or FakeBudget()
    budget.error = api.ContractError
    collector = collector or Collector()
    operation = api.Operation(svc, fake, Bus(), api.workflow(svc.store), budget, collector)
    if prepare is not None:
        prepare(svc, operation)
    try:
        result = operation.run(api.validate_manifest(manifest()), IDENTITY, goal or BOUND_GOAL, deadline=deadline,
                               clock=lambda: "2026-01-01T00:00:00+00:00")
        outcome = {"status": result.get("status"), "reason_code": result.get("reason_code"),
                   "exit_code": result.get("exit_code"), "cached": result.get("cached"),
                   "digest": canonical_digest(result)}
    except Exception as exc:
        outcome = {"refused": type(exc).__name__, "message": str(exc)[:200],
                   "reason_code": getattr(exc, "reason_code", None)}
    with svc.store.transaction() as tx:
        rows = tx.records()
    return {"outcome": outcome, "calls": list(fake.calls), "reserved": len(budget.reserved),
            "settled": [list(s) for s in budget.settled], "collected": collector.calls,
            "records": sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)}, svc, operation


def run(api) -> dict:
    out = {}
    out["manifest_valid"] = refusal(api.validate_manifest, manifest())
    out["manifest_deterministic"] = (api.assignment_message_id(api.validate_manifest(manifest()))
                                     == api.assignment_message_id(api.validate_manifest(manifest())))
    for name, field, value in (("bad_schema", "schema", "urn:zeus:operation:2"), ("bad_id", "id", "../x"),
                               ("bad_goal_path", "goal.path", "../GOAL.md"),
                               ("bad_allowed", "plan.allowed_paths", ["src/../x"]),
                               ("bad_budget", "budget.total", 1), ("bad_model", "claude.model", "gpt-5"),
                               ("bad_timeout", "claude.timeout_seconds", 5)):
        out["manifest_" + name] = refusal(api.validate_manifest, manifest(**{field: value}))

    success, svc, operation = case(api)
    out["success"] = success
    out["status"] = refusal(operation.status, "op-001")
    replay = operation.run(api.validate_manifest(manifest()), IDENTITY, BOUND_GOAL)
    out["replay"] = {"status": replay.get("status"), "cached": replay.get("cached"), "digest": canonical_digest(replay)}
    out["configuration_mismatch"] = refusal(operation.run, api.validate_manifest(manifest()), IDENTITY,
                                            {**BOUND_GOAL, "bytes": 4})

    def running(svc, operation):
        operation.claim(api.validate_manifest(manifest()), IDENTITY, BOUND_GOAL)
    out["running_residue"] = case(api, prepare=running)[0]

    def cycle_residue(svc, operation):
        document = api.validate_manifest(manifest())
        with svc.store.transaction() as tx:
            tx.put("local_cycles", "operation:" + document["id"], {"id": "operation:" + document["id"]})
    out["cycle_residue"] = case(api, prepare=cycle_residue)[0]

    out["worker_failed"] = case(api, worker="failed")[0]
    out["worker_exception"] = case(api, raise_error=RuntimeError("fixture worker exception"))[0]
    out["evidence_incomplete"] = case(api, inspection="incomplete")[0]
    out["lead_rejected"] = case(api, verdict=False)[0]
    out["ledger_exhausted"] = case(api, budget=FakeBudget(refuse_after=1))[0]
    out["settlement_failed"] = case(api, budget=FakeBudget(settle_fail=1))[0]
    out["collection_failed"] = case(api, collector=Collector(fail=True))[0]
    out["deadline_expired"] = case(api, deadline=PAST)[0]
    out["canary_absent"] = CANARY not in json.dumps(copy.deepcopy(out))
    return out
