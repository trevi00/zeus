"""Shared S6 scenario steps (`coordination.continuation_tick`): the M7 `Continuation.tick`/`drain` policy pass
(DESIGN-s6 §7; TRACE-s6 §6 and §8; the Codex S6 entry conditions), in the sequences of the M7 tests
(tests/test_continuation.py).

- **Registration.** An unregistered policy, and a disabled one (no lane read).
- **Initial binding.** A queued member job is bound to its session before admission, once; a non-member stays
  unbound.
- **Pin-change drain.** Under changed pinned bytes the tick refuses `policy_changed`. It settles the dispatched
  launch under its original binding and starts nothing new.
- **Admission closed.** `drain` alone reads no lane when nothing is dispatched. It waits on a running owned launch
  and settles it once it is proven ended.
- **Unknown-cleanup hold.** An ended launch without a cleanup proof keeps its Fleet unit held and writes the hold
  once. It is never relaunched.
- **Fair bounded pass.** At most MAX_ACTIONS_PER_TICK actions. An unavailable read spends no slot. The per-lane
  failure cap applies, and a lane-wide runtime outage stops the lane. The durable progress orders the next pass
  after a restart.
- **owned_elsewhere.** A job another policy's effect-owning intent routed is counted and never observed.

Layer: harness (never shipped)

`api` supplies MemoryStore, `Fleet(store, clock, token)`, `LaneEvidence(store)`,
`Continuation(store, *, fleet, lanes, conductor, validate, clock)`, `validate_manifest(document)` (bound to the
packaged provider policy) and `repository_identity(path)`. The lane evidence is seeded as LABELLED lane-store rows
of the shapes M7's Operation and conductor write (only the fields `LaneEvidence.read` and `classify` consume).
The compared results are the tick receipts, the lane-read order, the conductor calls and the final records of both
stores by body digest.
"""

from __future__ import annotations

import hashlib
import json

BASE = "a" * 40
ROOT = "/zeus-rebuild-s6-tick"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "base_revision": BASE, "bytes": 3}
IMAGE, ARCHIVE, MODEL = "zeus-worker:fixture", "d" * 64, "claude-fixture-model"
PIN = {"revision": "e" * 40, "path": "ops/continuation.json", "sha256": "f" * 64, "lane": "a"}
CANDIDATE = {"revision": "c" * 40, "tree": "7" * 40, "base": BASE}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ticking():
    counter = iter(range(1, 100_000))
    return lambda: "2026-09-30T00:00:00.%06d+00:00" % next(counter)


def tokens():
    counter = iter(range(1, 100_000))
    return lambda: "token-%04d" % next(counter)


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def config(root=ROOT, max_parallel=2):
    lanes = [{"id": "a", "team": "alpha", "repository": root + "/repo-a", "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": root + "/rt-a"},
             {"id": "b", "team": "beta", "repository": root + "/repo-b", "schema": "lane_b",
              "redis_namespace": "fleet-b", "runtime": root + "/rt-b"}]
    return {"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": max_parallel,
            "budget": {"per_host": 4, "total": 8}, "lanes": lanes}


def manifest(api, op_id, path="docs/a.md"):
    return api.validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit", "rationale": "fixture goal"},
        "plan": {"objective": "Implement the fixture item", "acceptance_criteria": ["ok"], "allowed_paths": [path]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": MODEL, "timeout_seconds": 120, "max_budget_usd": 1.0}})


def policy_document(api, policy_id="policy-1", enabled=True):
    return {"schema": "urn:zeus:continuation-policy:1", "id": policy_id, "enabled": enabled,
            "repository": api.repository_identity(ROOT + "/repo-a"), "lanes": ["a"],
            "goals": [{"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit"}],
            "allowed_paths": ["docs/a.md", "docs/b.md", "docs/c.md"], "acceptance_criteria": ["ok"],
            "session_archive_sha256": ARCHIVE, "qualified": {"model": MODEL, "image": IMAGE, "profile": "worker-v1"},
            "delivery_target": "fleet-host", "max_corrections": 3}


def cleanup_proof(launch, token):
    """The shape of the guardian's durable `cleanup.json` (LABELLED: written by this fixture)."""
    return {"schema": "urn:zeus:conductor-guardian:1", "kind": "cleanup", "launch": launch, "token": token,
            "spawned": True, "exit_code": 0, "timed_out": False, "stopped": False, "confirmed": True,
            "parent": {"confirmed": True, "exit_code": 0, "method": None},
            "tree": {"confirmed": True, "exit_code": None, "method": "process_group"}}


class Conductor:
    """LABELLED fixture of the owned-child conductor port (M7 tests' ConductorFixture; no process, no model).
    `start` records the call; `finish` writes the succeeded review_conductor row and the Releases record the
    child's decision would. `poll` reports the launch as the real port observes it (`cleanup=False`: a guardian
    that ended without proving parent-and-tree cleanup)."""

    def __init__(self, lane_store, pending=True):
        self.lane_store, self.pending, self.cleanup = lane_store, pending, True
        self.calls, self.launches, self.jobs, self.tokens = [], {}, {}, {}

    def start(self, lane_id, job, launch, token):
        self.calls.append(job["id"])
        self.jobs[launch], self.tokens[launch] = job, token
        self.launches[launch] = "running"
        if not self.pending:
            self.finish(launch)
        return {"pid": 4242}

    def finish(self, launch):
        job = self.jobs[launch]
        with self.lane_store.transaction() as tx:
            operation = tx.get("operations", job["id"])
            lead = tx.get("decisions_pending", operation["decision_id"])
            decision_id = "cond-" + job["id"]
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "conductor", "phase": "review_conductor", "status": "succeeded",
                "attempt": 1, "input": lead["input"],
                "message": {"correlation_id": operation["correlation_id"],
                            "what": {"details": {"decision_id": lead["id"]}}},
                "result": {"accepted": True, "reason": "fixture", "execution_ref": "sha256:" + "9" * 64,
                           "deployment": {"status": "queued", "release_id": "rel-" + job["id"]}}})
            tx.put("releases", "rel-" + job["id"], {"id": "rel-" + job["id"], "candidate": dict(CANDIDATE)})
        self.launches[launch] = "exited"

    def running(self):
        return sorted(launch for launch, state in self.launches.items() if state == "running")

    def poll(self, lane_id, launch):
        state = self.launches.get(launch)
        if state is None:
            return {"state": "absent", "owned": False, "exit_code": None,
                    "proof": {"kind": "fenced", "launch": launch, "claim": "fenced"}}
        if state == "running":
            return {"state": state, "owned": True, "exit_code": None}
        if not self.cleanup:
            return {"state": "unknown", "owned": False, "exit_code": None, "cleanup_confirmed": False,
                    "reason_code": "guardian_ended_without_proof"}
        return {"state": state, "owned": True, "exit_code": 0, "cleanup_confirmed": True,
                "proof": cleanup_proof(launch, self.tokens[launch])}


class Lanes:
    """The `lanes(lane_id)` port over one lane store: every read is logged by job id; `failing` job ids raise
    (a lane store outage for that read only)."""

    def __init__(self, api, store):
        self.api, self.store, self.reads, self.failing = api, store, [], set()

    def __call__(self, lane_id):
        assert lane_id == "a"
        lanes = self

        class Lane:
            def __init__(self):
                self.inner = lanes.api.LaneEvidence(lanes.store)
                self.sessions = None

            def read(self, job, target=None):
                lanes.reads.append(job["id"])
                if job["id"] in lanes.failing:
                    raise ConnectionError("lane store unavailable (injected)")
                return self.inner.read(job, target)

            def bind(self, document):
                return self.inner.bind(document)

            def bound(self, operation_id):
                return self.inner.bound(operation_id)

        return Lane()


class World:
    """One Fleet (control store), one lane store, the conductor fixture and one controller."""

    def __init__(self, api, *, enabled=True, pending=True, max_parallel=2):
        self.api, self.clock = api, ticking()
        self.control, self.lane_store = api.MemoryStore(), api.MemoryStore()
        self.fleet = api.Fleet(self.control, self.clock, tokens())
        self.fleet.register(config(max_parallel=max_parallel))
        self.conductor = Conductor(self.lane_store, pending=pending)
        self.lanes = Lanes(api, self.lane_store)
        self.runtime_down = False
        self.document = policy_document(api, enabled=enabled)
        self.controller = self.build()

    def runtime(self, lane_id):
        if self.runtime_down:
            raise ConnectionError("runtime identity unreadable (injected)")
        return {"image": IMAGE, "profile": "worker-v1", "session_archive_sha256": ARCHIVE}

    def build(self):
        return self.api.Continuation(self.control, fleet=self.fleet, lanes=self.lanes, conductor=self.conductor,
                                     validate=self.api.validate_manifest, clock=self.clock)

    def register(self, document=None):
        return self.controller.register(document or self.document, PIN)

    def tick(self, policy_id="policy-1", pin=None, controller=None):
        return (controller or self.controller).tick(policy_id, pin_sha256=pin or PIN["sha256"],
                                                    runtime=self.runtime)

    def terminal(self, op_id, status, path="docs/a.md", reason_code=None):
        """Enqueue, admit and finalize one Fleet job, then seed its lane rows (LABELLED shapes)."""
        self.fleet.enqueue("a", manifest(self.api, op_id, path), GOAL, [])
        job = self.fleet.admit_one()["job"]
        assert job is not None and job["id"] == op_id, job
        code = reason_code or {"accepted": "accepted", "rejected": "lead_rejected"}.get(status, "operation_failed")
        self.fleet.finalize(job["id"], job["owner_token"], {"status": status, "reason_code": code, "exit_code": 0,
                                                             "owner_handoff": None, "calls": {}})
        task_id, decision_id = "task-" + op_id, "dec-" + op_id
        with self.lane_store.transaction() as tx:
            tx.put("operations", op_id, {"id": op_id, "status": status, "reason_code": code, "task_id": task_id,
                                         "decision_id": decision_id, "correlation_id": "corr-" + op_id})
            tx.put("tasks", task_id, {"id": task_id, "status": "succeeded", "generation": 1, "attempt": 1,
                                      "result": {"candidate": dict(CANDIDATE)}})
            tx.put("decisions_pending", decision_id, {
                "id": decision_id, "actor": "lead:improvement", "phase": "review_lead", "status": "succeeded",
                "input": {"candidate": dict(CANDIDATE)},
                "result": {"accepted": status == "accepted", "execution_ref": "sha256:" + "8" * 64}})
        return op_id

    def queued(self, op_id, path="docs/a.md"):
        self.fleet.enqueue("a", manifest(self.api, op_id, path), GOAL, [])
        return op_id

    def state(self):
        return {"control": records(self.control), "lane": records(self.lane_store),
                "conductor": {"calls": list(self.conductor.calls), "running": self.conductor.running()},
                "reads": list(self.lanes.reads)}


def call(fn, *args, **kwargs):
    try:
        value = fn(*args, **kwargs)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None),
                "message": str(exc)[:160]}
    return {"value": value}


def launch_of(world, op_id):
    return next(launch for launch, job in world.conductor.jobs.items() if job["id"] == op_id)


def registration(api) -> dict:
    out = {}
    world = World(api)
    out["unregistered"] = call(world.tick)
    out["unregistered_state"] = world.state()
    world = World(api, enabled=False)
    world.terminal("op-disabled", "failed")
    out["disabled_register"] = call(world.register)
    out["disabled"] = call(world.tick)
    out["disabled_state"] = world.state()
    return out


def initial_binding(api) -> dict:
    world = World(api)
    world.register()
    world.queued("op-member")
    world.queued("op-outside", path="docs/z.md")
    first = call(world.tick)
    second = call(world.tick)
    return {"first": first, "second": second, "state": world.state()}


def pin_change_drain(api) -> dict:
    world = World(api)
    world.register()
    world.terminal("op-a", "accepted")
    dispatched = call(world.tick)
    world.terminal("op-b", "accepted")
    world.conductor.finish(launch_of(world, "op-a"))
    changed = call(world.tick, pin="0" * 64)
    after = world.state()
    same = call(world.tick)
    return {"dispatched": dispatched, "changed": changed, "after_change": after, "same_pin": same,
            "state": world.state()}


def admission_closed(api) -> dict:
    world = World(api)
    world.register()
    world.terminal("op-idle", "failed")
    empty = call(world.controller.drain, "policy-1")
    reads_after_empty = list(world.lanes.reads)
    world.terminal("op-a", "accepted")
    dispatched = call(world.tick)
    running = call(world.controller.drain, "policy-1")
    unresolved_running = call(world.controller.unresolved, "policy-1")
    world.conductor.finish(launch_of(world, "op-a"))
    settled = call(world.controller.drain, "policy-1")
    unresolved_after = call(world.controller.unresolved, "policy-1")
    again = call(world.controller.drain, "policy-1")
    return {"empty": empty, "reads_after_empty": reads_after_empty, "dispatched": dispatched, "running": running,
            "unresolved_running": unresolved_running, "settled": settled, "unresolved_after": unresolved_after,
            "again": again, "state": world.state()}


def unknown_cleanup_hold(api) -> dict:
    world = World(api)
    world.register()
    world.terminal("op-a", "accepted")
    dispatched = call(world.tick)
    world.conductor.cleanup = False
    world.conductor.finish(launch_of(world, "op-a"))
    held = call(world.tick)
    mid = world.state()
    held_again = call(world.tick)
    restarted = world.build()
    held_restart = call(world.tick, controller=restarted)
    drained = call(restarted.drain, "policy-1")
    unresolved = call(restarted.unresolved, "policy-1")
    return {"dispatched": dispatched, "held": held, "mid": mid, "held_again": held_again,
            "held_restart": held_restart, "drained": drained, "unresolved": unresolved, "state": world.state()}


def fair_pass(api) -> dict:
    out = {}
    # Budget and restart order: job 1 read fails (no slot spent), 2-5 fill the budget, 6 waits; after a restart
    # the durable progress puts the never-attempted 6 before the least recently attempted 1.
    world = World(api)
    world.register()
    for n in range(1, 7):
        world.terminal("op-%d" % n, "failed")
    world.lanes.failing = {"op-1"}
    out["first"] = call(world.tick)
    out["first_reads"] = list(world.lanes.reads)
    world.lanes.failing = set()
    restarted = world.build()
    out["restart"] = call(world.tick, controller=restarted)
    out["restart_reads"] = list(world.lanes.reads)
    out["state"] = world.state()
    # Per-lane failure cap: four failed reads close the lane for this pass; the rest are not attempted.
    world = World(api)
    world.register()
    for n in range(1, 7):
        world.terminal("op-%d" % n, "failed")
    world.lanes.failing = {"op-1", "op-2", "op-3", "op-4"}
    out["capped"] = call(world.tick)
    out["capped_reads"] = list(world.lanes.reads)
    out["capped_state"] = world.state()
    # A lane-wide runtime outage: one unavailable skip closes the lane without spending a slot.
    world = World(api)
    world.register()
    for n in range(1, 4):
        world.terminal("op-%d" % n, "failed")
    world.queued("op-queued")
    world.runtime_down = True
    out["runtime_down"] = call(world.tick)
    out["runtime_down_reads"] = list(world.lanes.reads)
    out["runtime_down_state"] = world.state()
    return out


def owned_elsewhere(api) -> dict:
    world = World(api)
    world.register()
    other = policy_document(api, policy_id="policy-2")
    out = {"register_other": call(world.controller.register, other, PIN)}
    world.terminal("op-shared", "accepted")
    out["other_tick"] = call(world.tick, policy_id="policy-2")
    world.terminal("op-mine", "failed")
    out["mine"] = call(world.tick)
    out["status"] = call(world.controller.status, "policy-1")
    out["state"] = world.state()
    return out


def run(api) -> dict:
    return {"registration": registration(api), "initial_binding": initial_binding(api),
            "pin_change_drain": pin_change_drain(api), "admission_closed": admission_closed(api),
            "unknown_cleanup_hold": unknown_cleanup_hold(api), "fair_pass": fair_pass(api),
            "owned_elsewhere": owned_elsewhere(api)}
