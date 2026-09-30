"""Shared S5 scenario steps (`coordination.local_cycle`): M7 `LocalCycle` (RESEARCH-S5 D3/D4, local check (c)).

- **start.** Idempotent start; a conflicting policy and invalid arguments refuse.
- **Happy path.** The queued implementation executes and its report is published. The next step handles the report,
  ACKs it and executes the review decision, and an accepted lead review leaves the cycle `awaiting_operator`.
- **Delivery order.** A report is ACKed only after it was handled and its commands were published. An undecodable
  entry and a message routed to the wrong agent are dead-lettered. A foreign, unparkable message is left un-ACKed
  and stops the cycle. An own-correlation execution notice is ACKed and stops the cycle.
- **Execution slot.** In-flight residue refuses. `max_executions` stops the cycle with `budget_exhausted`. A claim
  guard refusal, an executor exception, an unpublished result (`publication_incomplete`) and a foreign queue each
  stop the cycle. A cycle without an executor refuses.
- **handoff.** The read-only projection after the happy path.

Layer: harness (never shipped)

`api` supplies MemoryStore, `service(store)` (the side's store/org holder with `flush_outbox` and
`record_incident`), `workflow(store)`, `LocalCycle(service, executor, bus, workflow, observer)`,
`ClaimGuardRefused`, `validate_message`, `MessageDeliveryError`, `envelope(...)`, `advance(seconds)` and `org`. The
bus, the executor and the observer are fixtures shared by both sides. The compared results are the step results by
digest, the bus effects (acks, dead letters, publications) in order, the observation calls (type, outcome, reason)
and the final store records by body digest.
"""

from __future__ import annotations

import hashlib
import json


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Streams:
    """One in-memory stream per recipient. An entry is delivered once, stays pending until ACKed or dead-lettered,
    and every effect is logged in order. `fail` names message ids whose publication raises MessageDeliveryError."""

    def __init__(self, api, log):
        self.api, self.log, self.entries, self.delivered, self.fail = api, log, {}, set(), set()
        self.counter = 0

    def validate(self, message):
        return self.api.validate_message(message)

    def publish(self, message):
        self.validate(message)
        if message["message_id"] in self.fail:
            raise self.api.MessageDeliveryError("ConnectionError")
        return self.raw(message["who"]["recipient"], {"body": json.dumps(message, sort_keys=True)},
                        message["message_id"])

    def raw(self, recipient, fields, label):
        self.counter += 1
        entry_id = str(self.counter) + "-0"
        self.entries.setdefault(recipient, []).append((entry_id, fields))
        self.log.append(["publish", recipient, label, entry_id])
        return entry_id

    def receive(self, agent, consumer):
        for entry_id, fields in self.entries.get(agent, []):
            if (agent, entry_id) not in self.delivered:
                self.delivered.add((agent, entry_id))
                self.log.append(["receive", agent, entry_id])
                return entry_id, fields
        return None

    @staticmethod
    def decode(fields):
        return json.loads(fields["body"])

    def dead_letter(self, agent, entry_id, fields, reason):
        self.log.append(["dead_letter", agent, entry_id, reason[:120]])

    def ack(self, agent, entry_id):
        self.log.append(["ack", agent, entry_id])


class Executor:
    """Claims and completes through the side's own Workflow; a decision is settled as an accepted lead review.
    `mode` makes the next call refuse the claim guard or raise."""

    def __init__(self, api, store, wf, log):
        self.api, self.store, self.wf, self.log, self.mode = api, store, wf, log, None

    def execute_one(self, agent, expected=None):
        self.log.append(["execute_one", agent, sorted(expected["statuses"]) if expected else None])
        if self.mode == "guard":
            raise self.api.ClaimGuardRefused("claim guard fixture refusal")
        if self.mode == "boom":
            raise RuntimeError("fixture executor failure")
        task = self.wf.claim(agent, "cycle-owner", expected=expected)
        if task is None:
            return None
        self.api.advance(1)
        return self.wf.complete(task, {"candidate": {"revision": "a" * 40, "tree": "b" * 40, "base": "c" * 40},
                                       "summary": "fixture"})

    def decide_one(self, agent, expected=None):
        self.log.append(["decide_one", agent, sorted(expected["statuses"]) if expected else None])
        with self.store.transaction() as tx:
            row = tx.get("decisions_pending", expected["id"])
            row.update(status="succeeded", result={"accepted": True})
            tx.put("decisions_pending", row["id"], row)
        return row


class Observer:
    def __init__(self, calls):
        self.calls = calls

    def emit(self, kind, outcome, **kw):
        self.calls.append(["emit", kind, outcome, kw.get("reason_code")])

    def audit_system(self, tx, kind, outcome, **kw):
        self.calls.append(["audit", kind, outcome, kw.get("reason_code")])


def step(cycle, cycle_id):
    try:
        value = cycle.step(cycle_id)
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"action": value.get("action"), "reason": value.get("reason"),
            "status": value["cycle"]["status"], "executions": value["cycle"]["executions"],
            "stopped_reason": value["cycle"]["stopped_reason"], "digest": canonical_digest(value)}


def attempt(fn, *args):
    try:
        value = fn(*args)
    except Exception as exc:
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": canonical_digest(value)}


def assign(api, wf, correlation, objective):
    message = api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": objective}}, correlation)
    wf.submit(message)
    api.advance(1)
    return message


def world(api):
    log, calls = [], []
    store = api.MemoryStore()
    wf = api.workflow(store)
    bus = Streams(api, log)
    executor = Executor(api, store, wf, log)
    cycle = api.LocalCycle(api.service(store), executor, bus, wf, Observer(calls))
    return store, wf, bus, executor, cycle, log, calls


def records(store):
    with store.transaction() as tx:
        rows = tx.records()
    return sorted([r["bucket"], r["id"], canonical_digest(r["body"])] for r in rows)


def run(api) -> dict:
    out = {}

    # start: arguments, idempotence, conflicting policy
    store, wf, bus, executor, cycle, log, calls = world(api)
    out["start_bad_id"] = attempt(cycle.start, " ", "corr-a", 3)
    out["start_bad_budget"] = attempt(cycle.start, "cycle-a", "corr-a", 0)
    out["start"] = attempt(cycle.start, "cycle-a", "corr-a", 3)
    out["start_again"] = attempt(cycle.start, "cycle-a", "corr-a", 3)
    out["start_conflict"] = attempt(cycle.start, "cycle-a", "corr-a", 4)
    out["unknown_cycle"] = step(cycle, "cycle-missing")

    # happy path: implement -> report handled and ACKed -> lead decision -> awaiting_operator
    assign(api, wf, "corr-a", "happy")
    out["happy_1"] = step(cycle, "cycle-a")
    api.advance(1)
    out["happy_2"] = step(cycle, "cycle-a")
    api.advance(1)
    out["happy_3"] = step(cycle, "cycle-a")
    out["handoff"] = attempt(cycle.handoff, "cycle-a")
    out["happy_log"], out["happy_calls"] = list(log), list(calls)
    out["happy_records"] = records(store)

    # dead letters, wrong recipient, own notice; then a foreign unparkable message stops the cycle
    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-b", "corr-b", 5)
    bus.raw("worker:implementation", {"body": "{not json"}, "garbage")
    misrouted = api.envelope("task.assign", "lead:improvement", "worker:github", "research",
                             {"source": "github", "intent": "user_request"}, "corr-b")
    bus.raw("worker:implementation", {"body": json.dumps(misrouted, sort_keys=True)}, "misrouted")
    foreign = api.envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                           {"plan": {"objective": "foreign"}}, "corr-other")
    bus.raw("worker:implementation", {"body": json.dumps(foreign, sort_keys=True)}, "foreign")
    out["foreign_step"] = step(cycle, "cycle-b")
    out["foreign_log"], out["foreign_calls"] = list(log), list(calls)

    # an own-correlation execution notice is ACKed and stops the cycle
    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-n", "corr-n", 5)
    cancelled = assign(api, wf, "corr-n", "to cancel")
    wf.cancel(cancelled["message_id"], "lead:improvement", "operator stop")
    api.service(store).flush_outbox(bus, correlation_id="corr-n")
    out["notice_step"] = step(cycle, "cycle-n")
    out["notice_log"] = list(log)

    # in-flight residue, budget, claim guard, executor exception, publication incomplete, foreign queue
    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-r", "corr-r", 1)
    with store.transaction() as tx:
        row = tx.get("local_cycles", "cycle-r")
        row["in_flight"] = {"agent": "worker:implementation", "kind": "task", "id": "other", "at": "x"}
        tx.put("local_cycles", "cycle-r", row)
    out["residue"] = step(cycle, "cycle-r")

    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-e", "corr-e", 1)
    assign(api, wf, "corr-e", "first")
    out["budget_1"] = step(cycle, "cycle-e")
    assign(api, wf, "corr-e", "second")
    out["budget_2"] = step(cycle, "cycle-e")

    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-g", "corr-g", 3)
    assign(api, wf, "corr-g", "guarded")
    executor.mode = "guard"
    out["claim_guard"] = step(cycle, "cycle-g")

    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-x", "corr-x", 3)
    assign(api, wf, "corr-x", "raises")
    executor.mode = "boom"
    out["executor_exception"] = step(cycle, "cycle-x")

    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-p", "corr-p", 3)
    assign(api, wf, "corr-p", "unpublished")
    original = executor.execute_one

    def failing_report(agent, expected=None):
        result = original(agent, expected)
        with store.transaction() as tx:
            for row in tx.scan("outbox"):
                if row["message"]["type"] == "task.result":
                    bus.fail.add(row["message"]["message_id"])
        return result
    executor.execute_one = failing_report
    out["publication_incomplete"] = step(cycle, "cycle-p")
    out["publication_calls"] = list(calls)

    store, wf, bus, executor, cycle, log, calls = world(api)
    cycle.start("cycle-q", "corr-q", 3)
    assign(api, wf, "corr-q", "mine")
    assign(api, wf, "corr-elsewhere", "theirs")
    out["foreign_queue"] = step(cycle, "cycle-q")

    store, wf, bus, executor, cycle, log, calls = world(api)
    no_executor = api.LocalCycle(api.service(store), None, None, wf, None)
    no_executor.start("cycle-z", "corr-z", 2)
    assign(api, wf, "corr-z", "no executor")
    out["no_executor"] = step(no_executor, "cycle-z")
    out["last_records"] = records(store)
    return out
