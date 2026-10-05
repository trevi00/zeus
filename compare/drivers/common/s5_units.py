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


# ----- S11 AU-REC-2: five more single-block units (the call names the method; a read-only unit records what it answers) -----
LEAD, WORKER = "lead:improvement", "worker:implementation"
OPERATION, TASK, RUN = "op-1", "task-92b13b20", "1a" * 16
CONTAINER, RESERVATION, SLOT = "c7" * 32, "d4" * 32, "e9" * 16
MOVED = "/zeus-rebuild-s5-moved"


def answer(fn, *args, **kwargs):
    """`attempt` that keeps the value: the characterized result of a unit that answers (or refuses) without a write."""
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
        document[outer] = {**document[outer], inner: value} if inner else value
    return document


def recovery_proof(**overrides):
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


def interrupted(api, case, *, pause=True):
    """A registered, paused fleet holding one job finalized `unknown` (the interrupted job), and the config digest."""
    f = bare_fleet(api, case.store)
    digest_ = f.register(config())["config_sha256"]
    f.enqueue("a", manifest(api, OPERATION), GOAL, [])
    job = f.admit_one()["job"]
    f.finalize(job["id"], job["owner_token"], {"status": "unknown", "reason_code": "receipt_missing"})
    if pause:
        f.pause()
    with case.store.transaction() as tx:
        job = tx.get("fleet_jobs", job["id"])
    return f, job, digest_


def reconcile_interrupted(api, name, *, failure=False, replay=False, stale=False, paused=True, changed=False):
    case = Case(api, name)
    f, job, digest_ = interrupted(api, case, pause=paused)
    good = evidence(job, digest_)
    reread = (lambda: recovery_proof(**{"container.state": "dead"})) if changed else \
        (lambda: recovery_proof(observed_at="2026-09-21T00:00:02+00:00"))
    if replay:
        f.reconcile_interrupted(good, recovery_proof(), reread=reread)
    case.since()
    if failure:
        case.store.arm("fleet_jobs")
    document = evidence(job, digest_, **{"expected.owner_token": "0" * 32}) if stale else good
    return case.result(answer(f.reconcile_interrupted, document, recovery_proof(), reread=reread))


def relocation(digest_, **overrides):
    document = {"schema": "urn:zeus:fleet-relocation:1", "fleet": "fleet-1", "operator": "owner",
                "expected_config_sha256": digest_,
                "moves": [{"lane": "a", "repository": {"from": ROOT + "/repo-a", "to": MOVED + "/repo-a"},
                           "runtime": {"from": ROOT + "/rt-a", "to": MOVED + "/rt-a"}}],
                "copy_manifest": {"path": MOVED + "/copy-manifest.json", "sha256": "c" * 64, "entries": 12},
                "recorded_at": "2026-09-22T00:00:00+00:00"}
    document.update(overrides)
    return document


def relocation_proof():
    return {"schema": "urn:zeus:fleet-relocation-proof:1", "runner": {"state": "stopped"},
            "copy_manifest": {"sha256": "c" * 64, "entries": 12, "verified": 12, "bound": True,
                              "ownership": "resolved_paths"},
            "lanes": [{"id": "a", "active_runs": 0,
                       "repository": {"independent": True, "source_identity": "r" * 64, "target_identity": "r" * 64},
                       "runtime": {"writable": True},
                       "queued_bindings": [{"job_id": "op-q", "base_present": True, "goal_matches": True}]}],
            "observed_at": "2026-09-22T00:00:01+00:00"}


def relocate(api, name, *, failure=False, replay=False, stale=False, paused=True, conflict=False):
    case = Case(api, name)
    f = bare_fleet(api, case.store)
    digest_ = f.register(config())["config_sha256"]
    f.enqueue("a", manifest(api, "op-q"), GOAL, [])
    if paused:
        f.pause()
    if replay or conflict:
        f.relocate(relocation(digest_), relocation_proof())
    case.since()
    if failure:
        case.store.arm("fleet_registry")  # the registry row is the unit's last write
    request = relocation(digest_, operator="someone-else") if conflict else relocation("f" * 64 if stale else digest_)
    return case.result(answer(f.relocate, request, relocation_proof()))


def review_state(api, case, *, correlation="corr-gate", inspected=True, verdict="all_checked", bound=True):
    """A pending review decision, its succeeded candidate task and the inspection row the gate requires (hand-built)."""
    result = {"candidate": {"revision": "c" * 40, "tree": "d" * 40, "base": "e" * 40}, "summary": "s"}
    if inspected:
        result["evidence_inspection"] = {"inspection_id": "inspection-1"}
    with case.store.transaction() as tx:
        tx.put("tasks", "task-1", {"id": "task-1", "status": "succeeded", "agent": WORKER, "generation": 2,
                                   "attempt": 1, "result": result, "message": {"correlation_id": correlation}})
        tx.put("decisions_pending", "decision-1", {
            "id": "decision-1", "status": "pending", "phase": "review_lead", "actor": LEAD, "input": result,
            "message": {"correlation_id": correlation, "what": {"details": {"task_id": "task-1"}}}})
        tx.put("evidence_inspections", "inspection-1", {
            "id": "inspection-1", "verdict": verdict, "policy_hash": "p" * 64,
            "denominator": {"claims": 1, "checked": 1 if verdict == "all_checked" else 0, "unchecked": 0 if verdict == "all_checked" else 1},
            "binding": {"task_id": "task-1", "generation": 2 if bound else 7, "attempt": 1, "source_revision": "c" * 40}})


def evidence_gate(api, name, *, repeat=False, correlation="corr-gate", **state):
    case = Case(api, name)
    operation = api.operation(api.service(case.store))
    review_state(api, case, **state)
    if repeat:
        operation.evidence_gate({"id": "decision-1", "correlation_id": "corr-gate"})
    case.since()
    return case.result(answer(operation.evidence_gate, {"id": "decision-1", "correlation_id": correlation}))


def parkable(api, name, *, repeat=False, status="failed", recipient=WORKER, kind="task.result",
             correlation="operation:op-1"):
    case = Case(api, name)
    with case.store.transaction() as tx:
        tx.put("operations", OPERATION, {"id": OPERATION, "status": status, "correlation_id": "operation:op-1",
                                         "cycle_id": "operation:op-1", "assignment_message_id": "message-1"})
    message = {"type": kind, "who": {"recipient": recipient}, "correlation_id": correlation}
    if repeat:
        api.operation_finalization.parkable(case.store, message)
    case.since()
    return case.result(answer(api.operation_finalization.parkable, case.store, message))


def cancel(api, name, *, failure=None, repeat=False, actor="conductor", reason="stop"):
    case = Case(api, name)
    wf = api.workflow(case.store)
    wf.submit(api.envelope("task.assign", LEAD, WORKER, "implement", {"plan": {"objective": "x"}}, "corr-cancel"))
    api.advance(1)
    task = wf.claim(WORKER, "owner-a")
    api.advance(1)
    if repeat:
        wf.cancel(task["id"], "conductor", "stop")
    case.since()
    if failure:
        case.store.arm(failure)
    return case.result(attempt(wf.cancel, task["id"], actor, reason))


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
        "reconcile_interrupted_success": reconcile_interrupted(api, "reconcile_interrupted_success"),
        "reconcile_interrupted_a_failure_at_jobs": reconcile_interrupted(api, "reconcile_interrupted_a_failure",
                                                                         failure=True),
        "reconcile_interrupted_b_stale_owner": reconcile_interrupted(api, "reconcile_interrupted_b_stale", stale=True),
        "reconcile_interrupted_c_replay": reconcile_interrupted(api, "reconcile_interrupted_c_replay", replay=True),
        "reconcile_interrupted_not_paused": reconcile_interrupted(api, "reconcile_interrupted_not_paused",
                                                                  paused=False),
        "reconcile_interrupted_proof_changed": reconcile_interrupted(api, "reconcile_interrupted_proof_changed",
                                                                     changed=True),
        "relocate_success": relocate(api, "relocate_success"),
        "relocate_a_failure_at_registry": relocate(api, "relocate_a_failure", failure=True),
        "relocate_b_stale_digest": relocate(api, "relocate_b_stale", stale=True),
        "relocate_c_replay": relocate(api, "relocate_c_replay", replay=True),
        "relocate_not_paused": relocate(api, "relocate_not_paused", paused=False),
        "relocate_conflict": relocate(api, "relocate_conflict", conflict=True),
        "evidence_gate_success": evidence_gate(api, "evidence_gate_success"),
        "evidence_gate_c_repeat": evidence_gate(api, "evidence_gate_c_repeat", repeat=True),
        "evidence_gate_decision_mismatch": evidence_gate(api, "evidence_gate_decision_mismatch", correlation="corr-x"),
        "evidence_gate_inspection_missing": evidence_gate(api, "evidence_gate_inspection_missing", inspected=False),
        "evidence_gate_inspection_not_all_checked": evidence_gate(api, "evidence_gate_not_all_checked",
                                                                  verdict="partial"),
        "evidence_gate_binding_mismatch": evidence_gate(api, "evidence_gate_binding_mismatch", bound=False),
        "parkable_success": parkable(api, "parkable_success"),
        "parkable_c_repeat": parkable(api, "parkable_c_repeat", repeat=True),
        "parkable_owner_not_terminal": parkable(api, "parkable_owner_not_terminal", status="running"),
        "parkable_foreign_recipient": parkable(api, "parkable_foreign_recipient", recipient="conductor"),
        "parkable_unparkable_type": parkable(api, "parkable_unparkable_type", kind="status.report"),
        "parkable_foreign_correlation": parkable(api, "parkable_foreign_correlation", correlation="operation:op-9"),
        "cancel_success": cancel(api, "cancel_success"),
        "cancel_a_failure_at_tasks": cancel(api, "cancel_a_failure", failure="tasks"),
        "cancel_a_failure_at_outbox": cancel(api, "cancel_a_failure_outbox", failure="outbox"),
        "cancel_c_repeat": cancel(api, "cancel_c_repeat", repeat=True),
        "cancel_unauthorized": cancel(api, "cancel_unauthorized", actor="stranger"),
        "cancel_no_reason": cancel(api, "cancel_no_reason", reason=""),
    }
