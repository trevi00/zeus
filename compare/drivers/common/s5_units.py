"""Shared S5 scenario steps (`effects.admission_unit[.pg]`): the §2.9 admission and completion units of the coordination
core, observed through the S0 recorder (RESEARCH-S5 D1/D5/D7/D11, local check (e); REBUILD-DESIGN-v2 §2.9).

Units: `Workflow.handle` (decision + next command + inbox), `Operation.claim` (operation + local cycle +
assignment), `Fleet.admit_one` (dispatch + persisted reasons), `Workflow.complete` (outcome + report + event) and
`Fleet.finalize`. Discriminators:
- **(a)** a failure injected at the unit's last write leaves nothing of the unit (atomic rollback);
- **(b)** a stale writer (the fence advanced by another owner, or a stale owner token) commits nothing;
- **(c)** a same-key replay adds no authority write;
- **(d)** the executor is entered at depth 0. The bus publish of the relay is recorded at the depth it happens
  (G1: M7 publishes inside the delivery unit; characterized, not changed).

Layer: harness (never shipped)

`api` supplies `backend(name)` (`.store`, `.rows()`, `.drop()`: MemoryStore, or a fresh schema on the labelled
disposable PostgreSQL), `reset()`, `advance(seconds)`, `workflow(store)`, `service(store)`,
`operation(service)` (the side's Operation without executor), `LocalCycle`, `Fleet(store, clock, token)`,
`validate_manifest`, `validate_message`, `advance_fence(tx, bucket, row_id, generation, owner)`, `envelope(...)` and
`recording(store)` (the S0 RecordingStore). The compared results are the unit outcomes, the durable writes (bucket
and status), the recorder violations, the effect depths and the durable rows read back from the backend.
"""

from __future__ import annotations

import json

BASE = "a" * 40
ROOT = "/zeus-rebuild-s5-fleet"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


class Injected(RuntimeError):
    pass


class FaultTransaction:
    def __init__(self, inner, plan):
        self._inner, self._plan = inner, plan

    def put(self, bucket, key, body):
        if self._plan.get("bucket") == bucket and self._plan.get("armed"):
            self._plan["armed"] = False
            raise Injected("injected failure at " + bucket)
        return self._inner.put(bucket, key, body)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FaultStore:
    """Arms one failure at the next put into `plan["bucket"]`; everything else passes through."""

    def __init__(self, inner):
        self._inner, self.plan = inner, {}

    def arm(self, bucket):
        self.plan = {"bucket": bucket, "armed": True}

    def transaction(self, *args, **kwargs):
        store = self

        class Unit:
            def __enter__(self):
                self._context = store._inner.transaction(*args, **kwargs)
                return FaultTransaction(self._context.__enter__(), store.plan)

            def __exit__(self, *exc):
                return self._context.__exit__(*exc)
        return Unit()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def attempt(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:160]}
    return {"ok": True}


class Case:
    def __init__(self, api, name):
        api.reset()
        self.api, self.backend = api, api.backend(name)
        self.recording = api.recording(self.backend.store)
        self.store = FaultStore(self.recording)
        self.mark = 0

    def since(self):
        self.mark = len(self.recording.recorder.events)

    def result(self, outcome):
        recorder = self.recording.recorder
        events = recorder.events[self.mark:]
        outcomes = recorder.unit_outcomes()
        units = sorted({e["unit"] for e in events if e["kind"] == "BEGIN"}, key=lambda u: int(u[1:]))
        durable = [e for e in recorder.durable_writes(self.mark)]
        out = {"outcome": outcome, "units": [outcomes.get(u, "OPEN") for u in units],
               "durable_writes": sorted({(e["bucket"], e["status"] or "") for e in durable}),
               "durable_units": len({e["unit"] for e in durable}),
               "violations": sorted({v["kind"] for v in recorder.violations}),
               "effects": [[e["name"], e["depth"]] for e in events if e["kind"] == "effect"],
               "rows": self.backend.rows()}
        self.backend.drop()
        return json.loads(json.dumps(out))


def manifest(api, op_id):
    return api.validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": "r"},
        "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": ["docs/" + op_id + ".md"]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})


def fleet(api, store):
    counter, stamp = iter(range(1, 100_000)), iter(range(1, 100_000))
    f = api.Fleet(store, lambda: "2026-09-21T00:00:00.%06d+00:00" % next(stamp), lambda: "%032x" % next(counter))
    lanes = [{"id": lane, "team": lane, "repository": ROOT + "/repo-" + lane, "schema": "lane_" + lane,
              "redis_namespace": "fleet-" + lane, "runtime": ROOT + "/rt-" + lane} for lane in ("a", "b")]
    f.register({"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
                "budget": {"per_host": 4, "total": 8}, "lanes": lanes})
    return f


def handle(api, name, *, failure=False, replay=False):
    case = Case(api, name)
    wf = api.workflow(case.store)
    with case.store.transaction() as tx:
        tx.put("hooks", "hook-1", {"id": "hook-1", "status": "required", "fingerprint": "f" * 64})
    message = api.envelope("hook.required", "lead:improvement", "conductor", "implement_hook",
                           {"hook_id": "hook-1", "evidence_refs": []}, "corr-hook")
    if replay:
        wf.handle(message)
    case.since()
    if failure:
        case.store.arm("workflow_inbox")
    return case.result(attempt(wf.handle, message))


def claim(api, name, *, failure=False, replay=False):
    case = Case(api, name)
    operation = api.operation(api.service(case.store))
    document = manifest(api, "op-1")
    identity = {"repository": "r", "runtime": "d", "runtime_policy": "p",
                "provider": {"policy_digest": "x", "config_digest": "y"}}
    if replay:
        operation.claim(document, identity, GOAL)
        with case.store.transaction() as tx:
            row = tx.get("operations", "op-1")
            row["status"] = "accepted"
            tx.put("operations", "op-1", row)
    case.since()
    if failure:
        case.store.arm("outbox")
    return case.result(attempt(operation.claim, document, identity, GOAL))


def admit(api, name, *, failure=False, replay=False):
    case = Case(api, name)
    f = fleet(api, case.store)
    f.enqueue("a", manifest(api, "op-1"), GOAL, [])
    f.enqueue("a", manifest(api, "op-2"), GOAL, [])
    if replay:
        f.admit_one()
    case.since()
    if failure:
        case.store.arm("fleet_jobs")
    return case.result(attempt(f.admit_one))


def complete(api, name, *, failure=None):
    case = Case(api, name)
    wf = api.workflow(case.store)
    wf.submit(api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": "x"}}, "corr-complete"))
    api.advance(1)
    task = wf.claim("worker:implementation", "owner-a")
    api.advance(1)
    accept = None
    if failure == "stale":
        with case.store.transaction() as tx:
            row = tx.get("tasks", task["id"])
            api.advance_fence(tx, "tasks", row["id"], row["generation"] + 1, "owner-b")
            row.update(generation=row["generation"] + 1, owner="owner-b", lease_owner="owner-b")
            tx.put("tasks", row["id"], row)
    elif failure == "accept":
        def accept(tx, row):
            raise Injected("injected failure in the acceptance write")
    case.since()
    result = {"candidate": {"revision": "c" * 40, "tree": "d" * 40, "base": "e" * 40}, "summary": "s"}
    return case.result(attempt(wf.complete, task, result, accept=accept))


def finalize(api, name, *, stale=False):
    case = Case(api, name)
    f = fleet(api, case.store)
    f.enqueue("a", manifest(api, "op-1"), GOAL, [])
    job = f.admit_one()["job"]
    case.since()
    token = "0" * 32 if stale else job["owner_token"]
    return case.result(attempt(f.finalize, "op-1", token, {"status": "accepted", "reason_code": "lead_accepted"}))


def depths(api, name):
    """(d): the executor entry and the relay's bus publish, each recorded at the depth it happens."""
    case = Case(api, name)
    recorder = case.recording.recorder
    wf = api.workflow(case.store)

    class Bus:
        def __init__(self):
            self.entries = []

        def validate(self, message):
            return api.validate_message(message)

        def publish(self, message):
            recorder.effect("bus.publish")
            self.entries.append(message)
            return "entry-" + str(len(self.entries))

        def receive(self, agent, consumer):
            return None

    class Executor:
        def execute_one(self, agent, expected=None):
            recorder.effect("executor.execute_one")
            task = wf.claim(agent, "cycle-owner", expected=expected)
            api.advance(1)
            return wf.complete(task, {"summary": "s"})

    cycle = api.LocalCycle(api.service(case.store), Executor(), Bus(), wf, None)
    cycle.start("cycle-d", "corr-d", 2)
    wf.submit(api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": "x"}}, "corr-d"))
    api.advance(1)
    case.since()
    return case.result(attempt(cycle.step, "cycle-d"))


# ----- S11 AU-REC-1: the single-block public Fleet units (one function per method; the call names the method) -----
UNIT_ID = "e" * 64


def lanes():
    return [{"id": lane, "team": lane, "repository": ROOT + "/repo-" + lane, "schema": "lane_" + lane,
             "redis_namespace": "fleet-" + lane, "runtime": ROOT + "/rt-" + lane} for lane in ("a", "b")]


def config(per_host=4):
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 2,
            "budget": {"per_host": per_host, "total": 8}, "lanes": lanes()}


def bare_fleet(api, store):
    """A Fleet with the same scripted clock and tokens as `fleet`, nothing registered."""
    counter, stamp = iter(range(1, 100_000)), iter(range(1, 100_000))
    return api.Fleet(store, lambda: "2026-09-21T00:00:00.%06d+00:00" % next(stamp), lambda: "%032x" % next(counter))


def register(api, name, *, failure=False, replay=False, conflict=False):
    case = Case(api, name)
    f = bare_fleet(api, case.store)
    if replay or conflict:
        f.register(config())
    case.since()
    if failure:
        case.store.arm("fleet_control")
    return case.result(attempt(f.register, config(per_host=3 if conflict else 4)))


def registered(api, name, *, registry=True, repeat=False):
    case = Case(api, name)
    f = fleet(api, case.store) if registry else bare_fleet(api, case.store)
    if repeat:
        f.registered()
    case.since()
    return case.result(attempt(f.registered))


def enqueue(api, name, *, failure=False, replay=False, dependency=None):
    case = Case(api, name)
    f = fleet(api, case.store)
    if replay:
        f.enqueue("a", manifest(api, "op-1"), GOAL, [])
    case.since()
    if failure:
        case.store.arm("fleet_jobs")
    return case.result(attempt(f.enqueue, "a", manifest(api, "op-1"), GOAL, dependency or []))


def authorize_budget(api, name, *, failure=False, replay=False):
    case = Case(api, name)
    f = fleet(api, case.store)
    if replay:
        f.authorize_budget(4, 9, 8)
    case.since()
    if failure:
        case.store.arm("fleet_control")
    return case.result(attempt(f.authorize_budget, 4, 9, 8))


def reserve_unit(api, name, *, failure=False, replay=False):
    case = Case(api, name)
    f = fleet(api, case.store)
    if replay:
        f.reserve_unit(UNIT_ID, "conductor", "a", "decision-1")
    case.since()
    if failure:
        case.store.arm("fleet_units")
    return case.result(attempt(f.reserve_unit, UNIT_ID, "conductor", "a", "decision-1"))


def settle_unit(api, name, *, failure=False, replay=False, stale=False):
    case = Case(api, name)
    f = fleet(api, case.store)
    token = f.reserve_unit(UNIT_ID, "conductor", "a", "decision-1")["token"]
    proof = {"kind": "cleanup", "launch": UNIT_ID, "token": token, "confirmed": True, "exit_code": 0,
             "parent": {"confirmed": True}, "tree": {"confirmed": True}}
    if replay:
        f.settle_unit(UNIT_ID, token, proof)
    case.since()
    if failure:
        case.store.arm("fleet_units")
    return case.result(attempt(f.settle_unit, UNIT_ID, "0" * 32 if stale else token, proof))


def status(api, name, *, registry=True, repeat=False):
    case = Case(api, name)
    f = fleet(api, case.store) if registry else bare_fleet(api, case.store)
    if registry:
        f.enqueue("a", manifest(api, "op-1"), GOAL, [])
    if repeat:
        f.status()
    case.since()
    return case.result(attempt(f.status))


def run(api) -> dict:
    return {
        "handle_success": handle(api, "handle_success"),
        "handle_a_failure_at_inbox": handle(api, "handle_a_failure", failure=True),
        "handle_c_replay": handle(api, "handle_c_replay", replay=True),
        "claim_success": claim(api, "claim_success"),
        "claim_a_failure_at_outbox": claim(api, "claim_a_failure", failure=True),
        "claim_c_replay": claim(api, "claim_c_replay", replay=True),
        "admit_success": admit(api, "admit_success"),
        "admit_a_failure_at_jobs": admit(api, "admit_a_failure", failure=True),
        "admit_c_again": admit(api, "admit_c_again", replay=True),
        "complete_success": complete(api, "complete_success"),
        "complete_a_failure_in_accept": complete(api, "complete_a_failure", failure="accept"),
        "complete_b_stale_fence": complete(api, "complete_b_stale", failure="stale"),
        "finalize_success": finalize(api, "finalize_success"),
        "finalize_b_stale_token": finalize(api, "finalize_b_stale", stale=True),
        "d_depths": depths(api, "d_depths"),
        "register_success": register(api, "register_success"),
        "register_a_failure_at_control": register(api, "register_a_failure", failure=True),
        "register_c_replay": register(api, "register_c_replay", replay=True),
        "register_conflict": register(api, "register_conflict", conflict=True),
        "registered_success": registered(api, "registered_success"),
        "registered_c_repeat": registered(api, "registered_c_repeat", repeat=True),
        "registered_unregistered": registered(api, "registered_unregistered", registry=False),
        "enqueue_success": enqueue(api, "enqueue_success"),
        "enqueue_a_failure_at_jobs": enqueue(api, "enqueue_a_failure", failure=True),
        "enqueue_c_replay": enqueue(api, "enqueue_c_replay", replay=True),
        "enqueue_dependency_missing": enqueue(api, "enqueue_dependency_missing", dependency=["job-x"]),
        "authorize_budget_success": authorize_budget(api, "authorize_budget_success"),
        "authorize_budget_a_failure_at_control": authorize_budget(api, "authorize_budget_a_failure", failure=True),
        "authorize_budget_c_replay": authorize_budget(api, "authorize_budget_c_replay", replay=True),
        "reserve_unit_success": reserve_unit(api, "reserve_unit_success"),
        "reserve_unit_a_failure_at_units": reserve_unit(api, "reserve_unit_a_failure", failure=True),
        "reserve_unit_c_replay": reserve_unit(api, "reserve_unit_c_replay", replay=True),
        "settle_unit_success": settle_unit(api, "settle_unit_success"),
        "settle_unit_a_failure_at_units": settle_unit(api, "settle_unit_a_failure", failure=True),
        "settle_unit_b_stale_token": settle_unit(api, "settle_unit_b_stale", stale=True),
        "settle_unit_c_replay": settle_unit(api, "settle_unit_c_replay", replay=True),
        "status_success": status(api, "status_success"),
        "status_c_repeat": status(api, "status_c_repeat", repeat=True),
        "status_unregistered": status(api, "status_unregistered", registry=False),
    }
