"""Shared S8 scenario steps (`research.dispatch_recovery`): failed-dispatch recovery of M7
`application/research_program.py` `ResearchProgram.recover_dispatch` and its whole family, characterized BEFORE step 3
moves it (DESIGN-s8 §2 row `research.dispatch_recovery`; TRACE-s8 §2 "Failed-dispatch recovery").

Every case mirrors a test of M7 `tests/test_research_recovery.py` (the test name is in the case label), in four groups:

- **g1_recovery**: the pre-provider publication failure (the owner request fences the old assignment, one replacement is
  claimed and accepted), the accepted/rejected/other failed councils, active/unknown/possibly-delivered effects, a stale
  owner request, a changed scope/foreign digest/ticked replacement, the transport proof (unavailable, present, changed after
  the fence, absent on another transport, two transports, no publish call, a legacy attempt without a binding), the
  restarted requests, a failed replacement held, the `TransportProbe` completeness and run-scoped bus, and the pure
  domain transport rules. Plus two LABELLED additions (`_refuse_scope_lineage`: an attempt-scope identity is final).
- **g2_revocation**: the explicit `execution_revocation` mode: admission-first, both forced interleavings, the
  non-concurrent form of the admission/revocation race, a foreign fence, a changed message, every other precondition,
  an accepted original, the strict request, a missing/changed/corrupt retained fence, restarted revocations, a failed
  replacement held.
- **g3_successor**: the settled read-only `foreign_message` failure fixture (the REAL `CouncilRun` over a LABELLED
  two-role executor), one explicit successor, unsettled/unknown/effectful predecessors, unavailable evidence, stale pins,
  a widened scope, accepted/rejected/other failed predecessors, a broken retained chain, restarted successor requests.
- **g4_contract_successor**: the four-role contract failure (current and legacy variants), one successor, an existing
  lineage, unsettled predecessors, a wrong failure/foreign evidence/stale pin, the strict request, another contract
  error, a broken retained fence, a failed contract successor held, restarted requests.

**Not mirrored** (recorded in the result as `unreachable`, never silently dropped):
- the PostgreSQL tests (`test_postgres_*`: the step 8 `.pg` units);
- the CLI-entry tests (`test_the_cli_*`: S10);
- the two `production_wiring` tests: they need the real `RedisBus` composition (S10).
- `_follow_up` (`urn:zeus:research-dispatch-followup:1`) is not exercised by `test_research_recovery.py` (M7 covers it in
  `test_continuation_research.py`, a continuation world): only its strict-request refusals and its scope-final refusal
  are characterized here.

Layer: harness (never shipped)

"Concurrent" M7 tests become deterministic SEQUENTIAL forms (several owners, restarted `ResearchProgram` objects over the
same store, one after the other). The two forced-interleaving tests keep M7's own paused-writer threads: only their
outcomes (never a timestamp) are recorded. The REAL objects are M7's (`MemoryStore`, the Portfolio reconciler,
`ResearchProgram`, `ProgramRunner` over a real temporary Git repository, `CouncilRun`, `Workflow`, the organization, the
message contract, the outbox relay, `ExecutionEvidence`); the doubles are `s8_research_program` (pilots 58/59, unchanged)
or LABELLED here with the M7 class they mirror: the transport fault (`UnreachableBus`), the healthy relay bus
(`RecordingBus`), the transport proof (`FakeTransport`), the Redis read calls (`FakeRedis`), the role executors and the
operation `Bus`/`Collector`/`Budget`, the evidence store (`Artifacts`), the snapshot port. Every injected fault is
labelled where it is made. For every refusal the digest of the whole store before and after is recorded."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path
from unittest import mock

import s8_research_program as R

IDENTITY = {"schema": "urn:test:transport:1", "storage": "token-a"}   # LABELLED fixture transport identity
REVOCATION = "urn:zeus:research-dispatch-recovery:2"
SUCCESSOR_SCHEMA = "urn:zeus:research-dispatch-recovery:3"
CONTRACT_SCHEMA = "urn:zeus:research-dispatch-recovery:4"
SUMMARY_TOO_LONG = "council_field_invalid:improvement_lead.summary:too_long"
LONG_SUMMARY = ("SECRET-summary-body " * 400)[:6046]
BASE = "a" * 40
SOURCE_SHA = "b" * 64
SECRET = "SECRET-row-text-never-emitted"
UNREACHABLE = {
    "postgres": "unreachable: PostgreSQL (step 8 .pg units)",
    "cli": "unreachable: CLI entry (S10)",
    "wiring": "unreachable: real bus/composition (S10)"}


def investigation(api) -> str:
    return api.family_id(*R.FAMILY)


def replacement_id(api) -> str:
    return investigation(api) + ".recovery-1"


def second_id(api) -> str:
    return investigation(api) + ".recovery-2"


# ---- LABELLED doubles (M7 `tests/test_research_recovery.py` and the helpers it imports) --------------------------------
class Unreachable:
    """LABELLED. M7 `Unreachable`: every port the failed council must NEVER reach; any use raises."""

    def __getattr__(self, name):
        raise AssertionError("pre-provider failure touched " + name)


class UnreachableBus:
    """LABELLED injected transport fault. M7 `UnreachableBus`: the real message contract validates, the attempt binds the
    fixture identity, then the publish raises the adapter's delivery error. `bound=False` is the legacy bus."""

    def __init__(self, api, bound=True):
        self.api, self.attempts, self.bound = api, 0, bound

    def __getattr__(self, name):
        if name == "transport" and self.bound:
            return lambda: dict(IDENTITY)
        raise AttributeError(name)

    def validate(self, message):
        return self.api.validate_message(message)

    def publish(self, message, transport=None):
        self.attempts += 1
        raise self.api.MessageDeliveryError("TimeoutError")


class SecondBus(UnreachableBus):
    """LABELLED. M7 `SecondBus`: the same injected delivery fault on a DIFFERENT fixture transport."""

    def __getattr__(self, name):
        if name == "transport":
            return lambda: {**IDENTITY, "storage": "token-b"}
        raise AttributeError(name)


class UnidentifiedBus(UnreachableBus):
    """LABELLED. M7 `UnidentifiedBus`: a binding-capable bus whose identity read times out, so nothing is published."""

    def __getattr__(self, name):
        if name == "transport":
            def unreadable():
                raise self.api.MessageDeliveryError("TimeoutError")
            return unreadable
        raise AttributeError(name)


class RecordingBus:
    """LABELLED. M7 `RecordingBus`: a healthy transport for the global relay replay; records what it would publish."""

    def __init__(self, api):
        self.api, self.published = api, []

    def validate(self, message):
        return self.api.validate_message(message)

    def publish(self, message):
        self.published.append(message)
        return str(len(self.published)) + "-0"


class PublicationFailingCouncil:
    """M7 `PublicationFailingCouncil`: the REAL `CouncilRun` on the shared store with an unreachable transport: it claims the
    run row, writes the researcher assignment to the outbox, fails the correlation-scoped publication and ends
    `failed:publication_incomplete` before any reservation, task or provider start."""

    def __init__(self, api, store, bus=None):
        self.api, self.store, self.bus, self.receipts = api, store, bus or UnreachableBus(api), []

    def __call__(self, service, args):
        api = self.api
        manifest = api.validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), api.POLICY)
        harness = api.Harness(self.store, api.organization())
        never = Unreachable()
        run = api.CouncilRun(harness, executor=never, bus=self.bus, workflow=api.Workflow(self.store, harness.org),
                             budget=never, evidence=never, snapshot=never, artifacts=never)
        receipt = run.run(manifest, {"repository": "fixture"}, {"path": "docs/GOAL.md", "sha256": "0" * 64})
        self.receipts.append(receipt)
        return receipt


class FakeTransport:
    """LABELLED. M7 `FakeTransport`: `present` says the message is in the stream, `error` that the bus is unreachable,
    `identity`/`after` the bus identity read before/after the stream read. Records each inspected (recipient, message id)."""

    def __init__(self, present=False, error=None, identity=IDENTITY, after=None):
        self.present, self.error, self.calls = present, error, []
        self.identity, self.after = identity, identity if after is None else after

    def inspect(self, recipient, message_id):
        self.calls.append((recipient, message_id))
        if self.error is not None:
            raise self.error
        return {"before": self.identity, "absent": not self.present, "after": self.after}


class FakeRedis:
    """LABELLED. M7 `FakeRedis`: the two Redis read calls the probe uses; no writes exist."""

    def __init__(self, streams, fail=False):
        self.streams, self.fail = streams, fail

    def xlen(self, stream):
        if self.fail:
            raise ConnectionError("fixture: unreachable " + R.CANARY)
        return len(self.streams.get(stream, []))

    def xrange(self, stream, count):
        return list(self.streams.get(stream, []))[:count]


def probe(api, streams, fail=False, limit=10000):
    """M7 `probe`: the real `TransportProbe` over a LABELLED fixture bus."""
    bus = type("FixtureBus", (), {"namespace": "ns", "stream": staticmethod(lambda agent: "ns:agent:" + agent),
                                  "transport": lambda self, create=True: dict(IDENTITY)})()
    bus.client = FakeRedis(streams, fail)
    return api.TransportProbe(bus, limit=limit)


# helpers of `tests/test_autonomous.py`, `tests/test_council.py` and `tests/test_operation.py` the council fixtures use
def evidence_ref_of(api, details) -> str:
    return "sha256:" + hashlib.sha256(api.canonical(details).encode()).hexdigest()


def research_answer():
    """M7 `test_autonomous.RESEARCH`."""
    return {"sources": [{"id": "s1", "path": "docs/contracts.md", "sha256": SOURCE_SHA, "locator": "git", "revision": BASE,
                         "read_scope": "all"}],
            "claims": [{"id": "c1", "kind": "fact", "text": "advisory lock " + R.CANARY, "source_ids": ["s1"]}],
            "questions": [{"id": "q1", "question": "where is the runbook?", "blocking": True, "status": "answered",
                           "claim_ids": ["c1"]}],
            "ssot": {"searched_paths": ["docs"], "searched_symbols": ["RUNBOOK"],
                     "authoritative_definition": "docs/zeus/operations", "callers": [], "evidence": ["tests/test_dge.py"],
                     "unknowns": ["contention"], "decision": "improve", "rationale": "extend the runbook",
                     "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}},
            "needs_user": False, "user_question": None}


ATTACKER_FINDINGS = [{"id": "f1", "criterion": "focused tests pass", "severity": "minor", "scenario": "style",
                      "claim_ids": ["c1"], "trigger": None, "impact": None, "mitigation": None}]
PROPOSER = {"summary": "bind the plan", "claim_ids": ["c1"]}
DBA_REPORT = {"summary": "task-known succeeded; op-missing absent at snapshot; run-odd unknown", "claim_ids": ["c1"],
              "unknowns": ["run-odd stage is not interpretable"]}
IMPROVEMENT = {"summary": "reuse the runbook path", "decision": "improve", "rationale": "extend rather than fork",
               "transition": {"compatibility": "additive", "rollback": "revert", "retirement": "none"}, "claim_ids": ["c1"],
               "findings": ATTACKER_FINDINGS}
DB_ROWS = {("tasks", "task-known"): {"id": "task-known", "status": "succeeded", "agent": "worker:implementation",
                                     "error": SECRET},
           ("autonomous_runs", "run-odd"): {"id": "run-odd", "status": "running", "stage": "not a token!"}}


class Artifacts:
    """LABELLED. M7 `test_autonomous.Artifacts`: a content-addressed in-memory stand-in for `FileArtifacts` (put/document with
    integrity)."""

    def __init__(self, api):
        self.api, self.bodies = api, {}

    def put(self, body):
        key = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.bodies[key] = body
        return "sha256:" + key

    def corrupt(self, ref):
        self.bodies[ref[7:]] = self.bodies[ref[7:]] + " "   # bytes no longer hash to the reference

    def document(self, ref):
        if ref not in {"sha256:" + k for k in self.bodies}:
            raise FileNotFoundError(ref)
        body = self.bodies[ref[7:]]
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != ref[7:]:
            raise self.api.EvidenceUnavailable("evidence_corrupt")   # what the FileArtifacts-backed port raises
        return json.loads(body)


class SnapshotArtifacts:
    """LABELLED. M7 `test_council.SnapshotArtifacts`: `FileArtifacts`-shaped put(body, source) over the `Artifacts` store."""

    def __init__(self, artifacts):
        self.artifacts = artifacts

    def put(self, body, source):
        return {"ref": self.artifacts.put(body), "source": source}


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    """LABELLED. M7 `test_council.FakeConnection`: a psycopg-shaped connection double serving the fixed rows."""

    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        self.log.append(statement)
        if statement.startswith("SELECT current_database"):
            return _Cursor([("zeus", "test_schema", "18.0")])
        if statement.startswith("SELECT s.bucket"):
            buckets, ids = params
            return _Cursor([(b, i, self.rows[(b, i)]) for b, i in zip(buckets, ids) if (b, i) in self.rows])
        return _Cursor([])


class FakeSnapshotPort:
    """LABELLED. M7 `test_council.FakeSnapshotPort` (mode "ok"): the REAL `ReadOnlySnapshot` around the fake connection."""

    def __init__(self, api, clock):
        self.api, self.clock, self.calls, self.statements = api, clock, 0, []

    def observe(self, selection, **binding):
        self.calls += 1

        def connect(dsn, **kw):
            return FakeConnection(DB_ROWS, self.statements)
        return self.api.ReadOnlySnapshot("postgresql://user:" + SECRET + "@host/db", connect=connect,
                                         clock=self.clock).observe(selection, **binding)


class OperationBus:
    """LABELLED. M7 `test_operation.Bus`: an in-memory relay bus."""

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


class OperationBudget:
    """LABELLED. M7 `test_operation.FakeBudget`: the fault-injected stand-in for the machine CallBudget (never refuses)."""

    def __init__(self):
        self.reserved, self.settled = [], []

    def reserve(self, *, per_host, total, purpose, provider, model):
        slot = {"id": "slot-" + str(len(self.reserved) + 1), "reserved_at": "t", "purpose": purpose,
                "per_host": per_host, "total": total, "provider": provider, "model": model}
        self.reserved.append(slot)
        return slot

    def settle(self, slot_id, *, outcome, detail=None):
        self.settled.append((slot_id, outcome))


class OperationCollector:
    """LABELLED. M7 `test_operation.Collector`."""

    def __init__(self):
        self.calls = 0

    def collect(self):
        self.calls += 1
        return {"files": 1, "records": 3, "inserted": 3, "sink_failures": 0, "corrupt": 0}


class ReadOnlyCouncilExecutor:
    """LABELLED. M7 `ReadOnlyCouncilExecutor`: settles ONLY researcher and DBA `dge_role` tasks the way the real executor
    records them (settled accepted reservation, content-addressed execution artifact bound to the stage, the task's own
    base and its exact input evidence) and files each role's `task.result` through the outbox, as `Workflow.complete`
    does. Any other role reaching it fails."""

    ROLES = {"researcher", "dba"}

    def __init__(self, api, svc, artifacts):
        self.api, self.svc, self.artifacts, self.calls = api, svc, artifacts, []

    def answer(self, role, details, base):
        if role == "researcher":
            research = research_answer()
            return {**research, "sources": [{**research["sources"][0], "revision": base}]}
        return {"snapshot_digest": details["snapshot_digest"], **DBA_REPORT}

    def execute_one(self, agent, expected=None):
        api = self.api
        self.calls.append(agent)
        with self.svc.store.transaction() as tx:
            task = tx.get("tasks", expected["id"])
            message = task["message"]
            details, base = message["what"]["details"], message["where"]["revision"]
            role = details["role"]
            assert role in self.ROLES, "only the read-only roles may execute in this fixture"
            answer = self.answer(role, details, base)
            reservation = {"id": "res-" + task["id"], "bucket": "tasks", "task_id": task["id"], "generation": 1,
                           "attempt": 1, "invocation": 1, "stage": "dge:" + role, "status": "settled",
                           "outcome": "accepted", "usage": {"source": "provider", "total_tokens": 1}}
            tx.put("invocation_reservations", reservation["id"], reservation)
            ref = self.artifacts.put(api.canonical({
                "answer": answer, "thread_id": "thread-" + task["id"], "execution_assignment": {"provider": "codex"},
                "invocation": {"reservation": reservation["id"], "outcome": "accepted"},
                "research_binding": {"stage": "dge:" + role, "evidence_ref": evidence_ref_of(api, details),
                                     "basis_revision": base}}))
            task.update(attempt=1, generation=1, lease_owner="fixture", status="succeeded",
                        result={**answer, "execution_ref": ref, "basis_revision": base})
            tx.put("tasks", task["id"], task)
            report = api.envelope("task.result", task["agent"], message["who"]["sender"], "dge_role",
                                  {"task_id": task["id"], "result": task["result"]}, message["correlation_id"], task["id"])
            tx.put("outbox", report["message_id"], {"message": report, "sent": False})
        return task


class ContractCouncilExecutor(ReadOnlyCouncilExecutor):
    """LABELLED. M7 `ContractCouncilExecutor`: the read-only fixture plus the two leads (never the conductor or a worker);
    `improvement` overrides fields of the improvement lead's output."""

    ROLES = {"researcher", "dba", "research_lead", "improvement_lead"}

    def __init__(self, api, svc, artifacts, improvement):
        super().__init__(api, svc, artifacts)
        self.improvement = improvement

    def answer(self, role, details, base):
        if role in {"researcher", "dba"}:
            return ReadOnlyCouncilExecutor.answer(self, role, details, base)
        identities = {"snapshot_digest": details["snapshot_digest"], "report_digest": details["report_digest"]}
        if role == "research_lead":
            return {**PROPOSER, **identities}
        return {**IMPROVEMENT, **identities, **self.improvement}


def _council_run(api, store, executor, artifacts, bus):
    harness = api.Harness(store, api.organization())
    return harness, api.CouncilRun(
        harness, executor, bus, api.Workflow(store, harness.org), OperationBudget(), OperationCollector(),
        verify_sources=lambda packet: [{**s, "bytes": 1} for s in packet["sources"]], repository="r",
        evidence=artifacts, snapshot=FakeSnapshotPort(api, api.utcnow), artifacts=SnapshotArtifacts(artifacts))


class ForeignMessageCouncil:
    """M7 `ForeignMessageCouncil`: the REAL `CouncilRun` (v2) on the shared store: researcher and DBA execute through the
    LABELLED fixture executor, then a LABELLED report of another run already pending on the conductor stream stops the relay
    with `foreign_message`. `artifacts` is the execution evidence it wrote."""

    def __init__(self, api, store):
        self.api, self.store, self.artifacts, self.receipts, self.executor = api, store, Artifacts(api), [], None

    def __call__(self, service, args):
        api = self.api
        manifest = api.validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), api.POLICY)
        bus = OperationBus()
        bus.publish(api.envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": "x", "result": {}},
                                 "autonomous:other-run"))
        harness = api.Harness(self.store, api.organization())
        self.executor = ReadOnlyCouncilExecutor(api, harness, self.artifacts)
        _, run = _council_run(api, self.store, self.executor, self.artifacts, bus)
        receipt = run.run(manifest, {"repository": "fixture"}, {"path": "docs/GOAL.md", "sha256": "0" * 64})
        self.receipts.append(receipt)
        return receipt


def _pre_typed_council_output(api):
    def replay(role, output, identities, claim_ids):
        """LABELLED legacy consumer (M7 `_pre_typed_council_output`): before the typed code existed the same field check
        raised a plain ContractError, which the council mapped to the generic `debate_refused:ContractError`."""
        try:
            return api.council_output(role, output, identities, claim_ids)
        except api.CouncilFieldRefused as exc:
            raise api.ContractError("Improvement lead proposal needs a summary, a rationale and a decision") from exc
    return replay


class ContractFailureCouncil:
    """M7 `ContractFailureCouncil`: the REAL `CouncilRun` (v2) on the shared store over the LABELLED four-role executor."""

    def __init__(self, api, store, improvement=None, legacy=False):
        self.api, self.store, self.artifacts, self.receipts, self.executor = api, store, Artifacts(api), [], None
        self.improvement = {"summary": LONG_SUMMARY} if improvement is None else improvement
        self.legacy = legacy

    def __call__(self, service, args):
        api = self.api
        manifest = api.validate_any_manifest(json.loads(Path(args.file).read_text(encoding="utf-8")), api.POLICY)
        harness = api.Harness(self.store, api.organization())
        self.executor = ContractCouncilExecutor(api, harness, self.artifacts, self.improvement)
        _, run = _council_run(api, self.store, self.executor, self.artifacts, OperationBus())
        legacy = (mock.patch.object(api.council_module, "council_output", _pre_typed_council_output(api))
                  if self.legacy else nullcontext())
        with legacy:
            receipt = run.run(manifest, {"repository": "fixture"}, {"path": "docs/GOAL.md", "sha256": "0" * 64})
        self.receipts.append(receipt)
        return receipt


# ---- the worlds (M7 `failed_world`, `legacy_world`, `read_only_world`, `initial_world`, `current_world`) ---------------
def failed_world(api, ws, name, council=None, store=None):
    """rp-001 claims the investigation and its council (by default the REAL one, failing before provider entry) records
    its outcome. `council(store)` builds the council on the shared store."""
    api.reset()   # LABELLED: every world starts the harness clock and id stream afresh, so a case never shifts another
    store = store or api.MemoryStore()
    R.portfolio(api, store)
    env = R.build(api, ws, name, store=store)
    env.runner.council = council(store) if council else PublicationFailingCouncil(api, store)
    cfg = api.validate_config(R.config(env.head, investigation_source=dict(R.SOURCE)), api.POLICY)
    env.programs.register(cfg, env.identity, [])
    env.programs.resume("rp-001")
    tick = env.runner.tick("rp-001", intent="incident")
    assert tick["investigation"] == investigation(api), "fixture: the program claimed another investigation"
    return env, tick


def replacement(env, program_id="rp-002", **overrides):
    """A NEW owner-authorized program with the same authority; registered paused, never ticked."""
    api = env.api
    cfg = api.validate_config(R.config(env.head, id=program_id, investigation_source=dict(R.SOURCE), **overrides), api.POLICY)
    env.programs.register(cfg, env.identity, [])
    return cfg, api.config_digest(cfg, env.identity)


def request(env, config_sha256, program_id="rp-002", **failed):
    with env.store.transaction() as tx:
        dispatch = tx.get(env.api.BUCKET_DISPATCHES, investigation(env.api))
    pinned = {k: dispatch[k] for k in ("program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}
    return {"schema": "urn:zeus:research-dispatch-recovery:1", "investigation": investigation(env.api),
            "failed": {**pinned, **failed}, "replacement": {"program": program_id, "config_sha256": config_sha256}}


def history(env) -> dict:
    """Every record of the failed attempt that must stay exactly as it was."""
    api = env.api
    with env.store.transaction() as tx:
        outbox = [o for o in tx.scan("outbox") if o["message"]["correlation_id"] == "autonomous:rp-001.c001"]
        return deepcopy({"dispatch": tx.get(api.BUCKET_DISPATCHES, investigation(api)),
                         "run": tx.get("autonomous_runs", "rp-001.c001"), "cycle": tx.get(api.BUCKET_CYCLES, "rp-001:001"),
                         "outbox": outbox, "attempts": sorted(tx.scan("outbox_attempts"), key=lambda a: a["id"]),
                         "program": tx.get(api.BUCKET_PROGRAMS, "rp-001"),
                         "candidates": [c for c in tx.scan(api.BUCKET_CANDIDATES) if c["program"] == "rp-001"]})


def replacement_runner(env, status="accepted"):
    """The existing runner for the replacement program on the SAME store and repository."""
    runner = R.build(env.api, env.ws, "replacement-runner", store=env.store, root=env.root, head=env.head,
                     status=status).runner
    return runner


def legacy_world(api, ws, name, store=None):
    return failed_world(api, ws, name, council=lambda s: PublicationFailingCouncil(api, s, UnreachableBus(api, bound=False)),
                        store=store)


def assignment(env) -> dict:
    [item] = history(env)["outbox"]
    return item


def revocation(env, config_sha256, program_id="rp-002", **revoke):
    item = assignment(env)
    pinned = {"message_id": item["message"]["message_id"], "source_sha256": env.api.digest(item)}
    return {**request(env, config_sha256, program_id), "schema": REVOCATION, "mode": "execution_revocation",
            "revoke": {**pinned, **revoke}}


def late_delivery(env):
    """The ORIGINAL assignment reaching the real workflow admission after the fact (a delayed consumer of an old stream
    entry). Returns the refusal, or the task if it was admitted."""
    api = env.api
    try:
        return api.Workflow(env.store, api.organization()).submit(deepcopy(assignment(env)["message"]))
    except api.ContractError as exc:
        return exc


def no_execution(env) -> bool:
    with env.store.transaction() as tx:
        return (tx.scan("tasks") == [] and tx.scan("invocation_reservations") == []
                and tx.get("autonomous_runs", "rp-001.c001")["starts"] == {"reserved": 0, "settled": 0, "slots": []})


def fence_of(env):
    with env.store.transaction() as tx:
        return tx.get("execution_fences", "tasks:" + assignment(env)["message"]["message_id"])


def untouched(env) -> bool:
    """A refused request writes nothing: no lineage row, no fence."""
    with env.store.transaction() as tx:
        return tx.scan(env.api.BUCKET_RECOVERIES) == [] and tx.scan("outbox_quarantine") == []


def read_only_world(api, ws, name, store=None):
    """rp-001 revoked -> rp-002 claims `.recovery-1` -> the real council settles researcher + DBA and fails
    `foreign_message`."""
    env, _ = legacy_world(api, ws, name, store=store)
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    runner = R.build(api, ws, name + "-ro-runner", store=env.store, root=env.root, head=env.head).runner
    council = ForeignMessageCouncil(api, env.store)
    runner.council = council
    tick = runner.tick("rp-002", intent="incident")
    assert tick["investigation"] == investigation(api) and tick["result"] == "failed", tick
    assert council.receipts[0]["reason_code"] == "foreign_message"
    return env, council, runner


def successor_request(env, replacement_sha256, program_id="rp-003", **pinned):
    api = env.api
    with env.store.transaction() as tx:
        dispatch = tx.get(api.BUCKET_DISPATCHES, replacement_id(api))
        lineage = tx.get(api.BUCKET_RECOVERIES, investigation(api))
        program = tx.get(api.BUCKET_PROGRAMS, "rp-002")
    old = {"dispatch": replacement_id(api), "lineage_version": 1, "lineage_request_sha256": lineage["request_sha256"],
           "program": "rp-002", "config_sha256": program["config_sha256"],
           **{k: dispatch[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}
    return {"schema": SUCCESSOR_SCHEMA, "mode": "settled_read_only_successor", "investigation": investigation(api),
            "predecessor": {**old, **pinned}, "replacement": {"program": program_id, "config_sha256": replacement_sha256}}


def predecessor_history(env) -> dict:
    """Every record of the failed read-only predecessor and of the original recovery that must stay."""
    api = env.api
    correlation = "autonomous:rp-002.c001"
    with env.store.transaction() as tx:
        tasks = sorted([t for t in tx.scan("tasks") if t["message"]["correlation_id"] == correlation], key=lambda t: t["id"])
        ids = {t["id"] for t in tasks}
        return deepcopy({"run": tx.get("autonomous_runs", "rp-002.c001"), "tasks": tasks,
                         "reservations": sorted([r for r in tx.scan("invocation_reservations") if r["task_id"] in ids],
                                                key=lambda r: r["id"]),
                         "dispatch": tx.get(api.BUCKET_DISPATCHES, replacement_id(api)),
                         "cycle": tx.get(api.BUCKET_CYCLES, "rp-002:001"),
                         "program": tx.get(api.BUCKET_PROGRAMS, "rp-002"),
                         "recovery": tx.get(api.BUCKET_RECOVERIES, investigation(api)),
                         "fences": tx.scan("execution_fences"), "original": tx.get(api.BUCKET_DISPATCHES, investigation(api)),
                         "outbox": sorted([o for o in tx.scan("outbox") if o["message"]["correlation_id"] == correlation],
                                          key=lambda o: o["message"]["message_id"])})


def no_successor(env) -> bool:
    api = env.api
    with env.store.transaction() as tx:
        return (tx.scan(api.BUCKET_SUCCESSORS) == [] and tx.scan(api.BUCKET_HEADS) == []
                and len(tx.scan("outbox_quarantine")) == 1 and tx.get(api.BUCKET_DISPATCHES, second_id(api)) is None)


def contract_request(env, replacement_sha256, program_id="rp-002", *, program="rp-001", dispatch=None, version=0,
                     check=SUMMARY_TOO_LONG, failure=None, **pinned):
    api = env.api
    dispatch = dispatch or investigation(api)
    with env.store.transaction() as tx:
        row, config = tx.get(api.BUCKET_DISPATCHES, dispatch), tx.get(api.BUCKET_PROGRAMS, program)
        [task] = [t for t in tx.scan("tasks") if t["agent"] == "lead:improvement"
                  and t["message"]["correlation_id"] == "autonomous:" + row["run_id"]]
        lineage = tx.get(api.BUCKET_RECOVERIES, investigation(api))
    old = {"dispatch": dispatch, "lineage_version": version,
           "lineage_request_sha256": None if version == 0 else lineage["request_sha256"],
           "program": program, "config_sha256": config["config_sha256"],
           **{k: row[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}
    bound = {"role": "improvement_lead", "task_id": task["id"], "execution_ref": task["result"]["execution_ref"],
             "check": check}
    return {"schema": CONTRACT_SCHEMA, "mode": "settled_contract_failure_successor", "investigation": investigation(api),
            "predecessor": {**old, **pinned}, "failure": {**bound, **(failure or {})},
            "replacement": {"program": program_id, "config_sha256": replacement_sha256}}


def run_history(env, run_id="rp-001.c001", dispatch=None) -> dict:
    """Every record of the failed contract-failure predecessor that must stay exactly as it was."""
    api = env.api
    dispatch = dispatch or investigation(api)
    correlation = "autonomous:" + run_id
    with env.store.transaction() as tx:
        tasks = sorted([t for t in tx.scan("tasks") if t["message"]["correlation_id"] == correlation], key=lambda t: t["id"])
        ids = {t["id"] for t in tasks}
        return deepcopy({"run": tx.get("autonomous_runs", run_id), "tasks": tasks,
                         "reservations": sorted([r for r in tx.scan("invocation_reservations") if r["task_id"] in ids],
                                                key=lambda r: r["id"]),
                         "dispatch": tx.get(api.BUCKET_DISPATCHES, dispatch),
                         "recovery": tx.get(api.BUCKET_RECOVERIES, investigation(api)),
                         "session": tx.get("dge_sessions", run_id + ".design"),
                         "events": sorted(tx.scan("dge_events"), key=lambda e: e["id"]),
                         "outbox": sorted([o for o in tx.scan("outbox") if o["message"]["correlation_id"] == correlation],
                                          key=lambda o: o["message"]["message_id"])})


def no_contract_successor(env) -> bool:
    api = env.api
    with env.store.transaction() as tx:
        return (tx.scan(api.BUCKET_SUCCESSORS) == [] and tx.scan(api.BUCKET_HEADS) == []
                and tx.get(api.BUCKET_DISPATCHES, second_id(api)) is None
                and tx.get(api.BUCKET_DISPATCHES, replacement_id(api)) is None)


def initial_world(api, ws, name, store=None, **council):
    """rp-001 claims the investigation (its INITIAL dispatch, no lineage) and the real council fails at the improvement
    lead."""
    env, tick = failed_world(api, ws, name, council=lambda s: ContractFailureCouncil(api, s, **council), store=store)
    assert tick["result"] == "failed", tick
    return env, env.runner.council


def current_world(api, ws, name, **council):
    """rp-001 revoked -> rp-002 claims `.recovery-1` -> the real council fails at the improvement lead."""
    env, _ = legacy_world(api, ws, name)
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    runner = R.build(api, ws, name + "-cur-runner", store=env.store, root=env.root, head=env.head).runner
    runner.council = ContractFailureCouncil(api, env.store, **council)
    tick = runner.tick("rp-002", intent="incident")
    assert tick["investigation"] == investigation(api) and tick["result"] == "failed", tick
    return env, runner.council


# ---- observations --------------------------------------------------------------------------------------------------------
def refused(env, fn, *args):
    """A call expected to refuse (M7 `refused`): the refusal code and field, whether the text carried the canary, and the
    digest of the whole store before and after (a refusal writes nothing)."""
    before = R.store_digest(env.store)
    result = R.call(env.ws, fn, *args)
    after = R.store_digest(env.store)
    if "raised" in result:
        out = {"raised": result["raised"], "reason_code": result.get("reason_code"), "field": result.get("field")}
        if "reason_code" not in result:
            out["message"] = result.get("message")
        out["canary_in_message"] = R.CANARY in result.get("message", "")
    else:
        out = {"returned": result["value"]}
    return {**out, "store_before": before, "store_after": after, "nothing_written": before == after}


def code(env, fn, *args):
    """The reason code only (a refusal), for the loop cases whose digests are recorded by the surrounding case."""
    result = R.call(env.ws, fn, *args)
    return result.get("reason_code") if "raised" in result else {"returned": result["value"]}


def rows(env, bucket):
    with env.store.transaction() as tx:
        return tx.scan(bucket)


def row(env, bucket, key):
    with env.store.transaction() as tx:
        return tx.get(bucket, key)


def state_of(env, key=None):
    found = row(env, env.api.BUCKET_RECOVERIES, key or investigation(env.api))
    return None if found is None else found["state"]


def dispatch_views(env) -> dict:
    return {d["id"]: {k: d.get(k) for k in ("current", "result", "program", "run_id", "recovery")}
            for d in env.programs.dispatches()}


def lineage_summary(env) -> dict:
    api = env.api
    return {"recoveries": [{k: r.get(k) for k in ("id", "state", "reason_code", "proof")} for r in rows(env, api.BUCKET_RECOVERIES)],
            "quarantine": len(rows(env, "outbox_quarantine")), "fences": len(rows(env, "execution_fences")),
            "successors": [{k: r.get(k) for k in ("id", "version", "state", "proof")} for r in rows(env, api.BUCKET_SUCCESSORS)],
            "heads": [{k: r.get(k) for k in ("version", "dispatch")} for r in rows(env, api.BUCKET_HEADS)],
            "dispatches": sorted(r["id"] for r in rows(env, api.BUCKET_DISPATCHES))}


def tick_view(tick: dict) -> dict:
    return {k: tick.get(k) for k in ("investigation", "result", "run_id", "selected", "reason_code")}


def relay_once(env, correlation_id=None, bus=None):
    api = env.api
    bus = bus or RecordingBus(api)
    kwargs = {} if correlation_id is None else {"correlation_id": correlation_id}
    counted = api.relay(env.store, api.organization(), bus, **kwargs)
    return {"published": counted["published"], "quarantined_existing": counted.get("quarantined_existing"),
            "bus_published": len(bus.published)}


# ---- G1 --------------------------------------------------------------------------------------------------------------------
def g1_recovery(api, ws):
    out = {}
    inv = investigation(api)
    out["m7_scope"] = {"investigation": inv, "replacement_dispatch": replacement_id(api),
                       "second_dispatch": second_id(api), "identity": IDENTITY,
                       "mirrors": "tests/test_research_recovery.py lines 196-760 (non-PG, non-CLI)",
                       "postgres": UNREACHABLE["postgres"], "cli": UNREACHABLE["cli"], "wiring": UNREACHABLE["wiring"]}

    # ---- test_the_fixture_is_a_real_pre_provider_publication_failure
    env, tick = failed_world(api, ws, "g1-fixture")
    with env.store.transaction() as tx:
        run = tx.get("autonomous_runs", "rp-001.c001")
        [outbox] = tx.scan("outbox")
        dispatch = tx.get(api.BUCKET_DISPATCHES, inv)
        facts = {"tick": tick_view(tick), "bus_attempts": env.runner.council.bus.attempts,
                 "run": {k: run.get(k) for k in ("status", "stage", "reason_code", "starts", "roles")},
                 "outbox_sent": outbox["sent"], "tasks": len(tx.scan("tasks")), "reservations": len(tx.scan("invocation_reservations")),
                 "attempt_statuses": [a["status"] for a in tx.scan("outbox_attempts")],
                 "dispatch": {k: dispatch.get(k) for k in ("result", "result_reason")},
                 "program_state": tx.get(api.BUCKET_PROGRAMS, "rp-001")["state"]}
    out["test_the_fixture_is_a_real_pre_provider_publication_failure"] = {
        **facts, "resume": refused(env, env.programs.resume, "rp-001")}

    # ---- test_one_owner_request_fences_the_old_assignment_and_one_replacement_is_claimed_and_accepted
    env, _ = failed_world(api, ws, "g1-complete")
    before = history(env)
    _, sha = replacement(env)
    transport = FakeTransport()
    result = env.programs.recover_dispatch(request(env, sha), transport)
    message_id = before["outbox"][0]["message"]["message_id"]
    case = {"result": result, "transport_calls": transport.calls, "message_id": message_id}
    with env.store.transaction() as tx:
        fence = tx.get("outbox_delivery", message_id)
        [kept] = tx.scan("outbox_quarantine")
        case["fence"] = {k: fence.get(k) for k in ("status", "attempts")}
        case["quarantine"] = {"reason": kept["reason"], "source_is_the_outbox_item": kept["source"] == before["outbox"][0]}
    case["history_untouched_after_fence"] = history(env) == before
    case["global_relay_after_the_fix"] = relay_once(env)
    views = dispatch_views(env)
    case["status_before_claim"] = {"dispatches": views, "original_recovery_state": env.programs.status("rp-001")["recoveries"][0]["state"],
                                   "replacement_state": env.programs.status("rp-002")["state"],
                                   "history_untouched": history(env) == before}
    env.programs.resume("rp-002")
    runner = replacement_runner(env)
    tick = runner.tick("rp-002", intent="incident")
    case["replacement_tick"] = tick_view(tick)
    views = {d["id"]: d for d in env.programs.dispatches()}
    old, new = views[inv], views[replacement_id(api)]
    case["views_after_claim"] = {
        "old": {k: old.get(k) for k in ("current", "result", "program")},
        "new": {k: new.get(k) for k in ("current", "result", "program", "run_id", "recovery")},
        "supersedes_matches_failed_pins": new["supersedes"] == {"dispatch": inv, **{k: before["dispatch"][k] for k in (
            "program", "cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}}
    lineage = row(env, api.BUCKET_RECOVERIES, inv)
    case["lineage_after_claim"] = {"state": lineage["state"], "cycle": lineage["replacement"]["cycle"]}
    case["history_untouched_after_claim"] = history(env) == before
    status = env.programs.status("rp-002")
    case["status_counts"] = {"rp-002": {"accepted": status["investigations"]["accepted"],
                                        "dispatched": status["adoptions"]["dispatched"]},
                             "rp-001_failed": env.programs.status("rp-001")["investigations"]["failed"]}
    again = env.programs.recover_dispatch(request(env, sha), FakeTransport(error=AssertionError("not read")))
    case["identical_request_again"] = {"cached": again["cached"], "state": again["state"],
                                       "dispatches": len(env.programs.dispatches()), "councils": len(runner.council.manifests)}
    out["test_one_owner_request_fences_the_old_assignment_and_one_replacement_is_claimed_and_accepted"] = case

    # ---- test_accepted_rejected_or_other_failed_councils_are_never_recoverable
    for status in ("accepted", "rejected", "failed"):
        env, _ = failed_world(api, ws, "g1-never-" + status, council=lambda store, status=status: R.Council(api, store, status=status))
        _, sha = replacement(env)
        out["test_accepted_rejected_or_other_failed_councils_are_never_recoverable[%s]" % status] = {
            "recover": refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport()),
            "untouched": untouched(env)}

    # ---- test_active_unknown_or_possibly_delivered_effects_refuse_and_write_nothing
    for label, change in EFFECTS:
        env, _ = failed_world(api, ws, "g1-effect-" + label)
        _, sha = replacement(env)
        message_id = history(env)["outbox"][0]["message"]["message_id"]
        change(env, message_id)
        transport = FakeTransport()
        out["test_active_unknown_or_possibly_delivered_effects_refuse_and_write_nothing[%s]" % label] = {
            "recover": refused(env, env.programs.recover_dispatch, request(env, sha), transport),
            "transport_calls": transport.calls, "untouched": untouched(env)}

    # ---- test_a_stale_owner_request_naming_another_attempt_refuses
    for label, pin in (("run_id", {"run_id": "rp-001.c002"}), ("manifest_sha256", {"manifest_sha256": "f" * 64}),
                       ("cycle", {"cycle": "rp-001:002"}), ("snapshot_sha256", {"snapshot_sha256": "e" * 64})):
        env, _ = failed_world(api, ws, "g1-stale-" + label)
        _, sha = replacement(env)
        out["test_a_stale_owner_request_naming_another_attempt_refuses[%s]" % label] = {
            "recover": refused(env, env.programs.recover_dispatch, request(env, sha, **pin), FakeTransport()),
            "untouched": untouched(env)}

    # ---- test_a_changed_scope_foreign_digest_or_ticked_replacement_refuses
    env, _ = failed_world(api, ws, "g1-scope")
    widened, wide_sha = replacement(env, "rp-wide", max_adoptions=2)
    case = {"widened": refused(env, env.programs.recover_dispatch, request(env, wide_sha, "rp-wide"), FakeTransport())}
    other = {**R.SOURCE, "reason_codes": ["store_timeout", "other_code"]}
    cfg = api.validate_config(R.config(env.head, id="rp-other", investigation_source=other), api.POLICY)
    env.programs.register(cfg, env.identity, [])
    other_sha = api.config_digest(cfg, env.identity)
    case["other_authority"] = refused(env, env.programs.recover_dispatch, request(env, other_sha, "rp-other"), FakeTransport())
    _, sha = replacement(env)
    case["foreign_digest"] = refused(env, env.programs.recover_dispatch, request(env, "d" * 64), FakeTransport())
    env.programs.resume("rp-002")
    case["ticked_replacement"] = refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport())
    case["replacement_is_the_failed_program"] = refused(env, env.programs.recover_dispatch, request(env, sha, "rp-001"), FakeTransport())
    case["untouched"] = untouched(env)
    case["widened_max_adoptions"] = widened["max_adoptions"]
    out["test_a_changed_scope_foreign_digest_or_ticked_replacement_refuses"] = case

    # ---- test_an_unavailable_transport_refuses_keeps_the_fence_and_a_later_proof_authorizes_once
    env, _ = failed_world(api, ws, "g1-unavailable")
    before = history(env)
    _, sha = replacement(env)
    case = {"unavailable": refused(env, env.programs.recover_dispatch, request(env, sha),
                                   FakeTransport(error=TimeoutError(R.CANARY))),
            "lineage_state": state_of(env), "current_while_fenced": dispatch_views(env)[inv]["current"]}
    env.programs.resume("rp-002")
    tick = replacement_runner(env).tick("rp-002", intent="incident")
    case["replacement_tick_selects_the_investigation"] = tick["selected"] == "inv-" + inv[:24]
    case["replacement_dispatch_row"] = row(env, api.BUCKET_DISPATCHES, replacement_id(api))
    case["history_untouched"] = history(env) == before
    case["later_proof_after_the_replacement_ticked"] = refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport())
    env, _ = failed_world(api, ws, "g1-unavailable-then-proof")   # LABELLED addition: the later proof without the tick
    _, sha = replacement(env)
    refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport(error=TimeoutError(R.CANARY)))
    later = env.programs.recover_dispatch(request(env, sha), FakeTransport())
    case["later_proof_authorizes"] = {"state": later["state"], "proof": later["proof"], "cached": later["cached"],
                                      "lineage": lineage_summary(env)}
    out["test_an_unavailable_transport_refuses_keeps_the_fence_and_a_later_proof_authorizes_once"] = case

    # ---- test_a_message_present_on_the_transport_is_a_durable_refusal
    env, _ = failed_world(api, ws, "g1-present")
    _, sha = replacement(env)
    case = {"present": refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport(present=True))}
    transport = FakeTransport()
    case["repeat"] = refused(env, env.programs.recover_dispatch, request(env, sha), transport)
    case["repeat_transport_calls"] = transport.calls
    lineage = row(env, api.BUCKET_RECOVERIES, inv)
    case["row"] = {"state": lineage["state"], "reason_code": lineage["reason_code"],
                   "outbox_fence": row(env, "outbox_delivery", lineage["fence"]["outbox"])["status"]}
    out["test_a_message_present_on_the_transport_is_a_durable_refusal"] = case

    # ---- test_a_publication_change_after_the_fence_refuses_the_authorization
    env, _ = failed_world(api, ws, "g1-racing")
    _, sha = replacement(env)
    message_id = history(env)["outbox"][0]["message"]["message_id"]

    class Racing(FakeTransport):
        def inspect(self, recipient, message_id_):
            with env.store.transaction() as tx:   # LABELLED injected race: a delivery record appears
                delivery = tx.get("outbox_delivery", message_id)
                tx.put("outbox_delivery", message_id, {**delivery, "status": "delivered", "delivered_entry_id": "9-0"})
            return super().inspect(recipient, message_id_)

    out["test_a_publication_change_after_the_fence_refuses_the_authorization"] = {
        "recover": refused(env, env.programs.recover_dispatch, request(env, sha), Racing()), "lineage_state": state_of(env)}

    # ---- test_concurrent_and_restarted_requests_and_ticks_create_one_replacement (SEQUENTIAL form)
    env, _ = failed_world(api, ws, "g1-restarted")
    _, sha = replacement(env)
    document = request(env, sha)
    results = [api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, FakeTransport()) for _ in range(4)]
    case = {"cached_flags": [r["cached"] for r in results], "all_recovered": all(r["recovered"] for r in results),
            "lineage": lineage_summary(env)}
    restarted = api.ResearchProgram(env.store, clock=env.clock)
    case["restarted_cached"] = restarted.recover_dispatch(document, FakeTransport())["cached"]
    case["other_program_conflicts"] = refused(env, restarted.recover_dispatch,
                                              {**document, "replacement": {"program": "rp-003", "config_sha256": sha}},
                                              FakeTransport())
    cfg = api.validate_config(R.config(env.head, id="rp-003", investigation_source=dict(R.SOURCE)), api.POLICY)
    env.programs.register(cfg, env.identity, [])
    env.programs.resume("rp-003")
    case["third_program_tick"] = tick_view(replacement_runner(env).tick("rp-003", intent="incident"))
    env.programs.resume("rp-002")
    runners = [replacement_runner(env) for _ in range(2)]
    ticks = [r.tick("rp-002", intent="incident") for r in runners]   # SEQUENTIAL form of the two concurrent runners
    case["two_ticks"] = [tick_view(t) for t in ticks]
    case["claimed_ticks"] = len([t for t in ticks if t.get("investigation") == inv])
    case["councils"] = sum(len(r.council.manifests) for r in runners)
    case["dispatch_ids"] = sorted(r["id"] for r in rows(env, api.BUCKET_DISPATCHES))
    out["test_concurrent_and_restarted_requests_and_ticks_create_one_replacement"] = case

    # ---- test_a_failed_replacement_is_held_and_never_opens_a_second_recovery
    env, _ = failed_world(api, ws, "g1-held")
    _, sha = replacement(env)
    document = request(env, sha)
    env.programs.recover_dispatch(document, FakeTransport())
    env.programs.resume("rp-002")
    tick = replacement_runner(env, status="failed").tick("rp-002", intent="incident")
    case = {"tick": tick_view(tick), "program_state": env.programs.status("rp-002")["state"],
            "views": dispatch_views(env)[replacement_id(api)]}
    _, next_sha = replacement(env, "rp-004")
    case["second_recovery"] = refused(env, env.programs.recover_dispatch,
                                      {**document, "replacement": {"program": "rp-004", "config_sha256": next_sha}},
                                      FakeTransport())
    case["identical_request"] = env.programs.recover_dispatch(document, FakeTransport())["state"]
    out["test_a_failed_replacement_is_held_and_never_opens_a_second_recovery"] = case
    out["test_postgres_concurrent_requests_record_one_lineage_and_one_replacement"] = {"unreachable": UNREACHABLE["postgres"]}

    # ---- the transport probe (adapter entry and transport probe)
    body = json.dumps({"message_id": "m-1"})

    def absent(p):
        observed = p.inspect("lead:researcher", "m-1")
        return {"absent": observed["absent"], "before_is_after_is_identity": observed["before"] == observed["after"] == IDENTITY}
    case = {"empty": absent(probe(api, {})),
            "other_message": absent(probe(api, {"ns:agent:lead:researcher": [("1-0", {"body": json.dumps({"message_id": "m-2"})})]})),
            "in_recipient_stream": absent(probe(api, {"ns:agent:lead:researcher": [("1-0", {"body": body})]})),
            "in_dead_letter": absent(probe(api, {"ns:dead-letter": [("1-0", {"body": body, "reason": "x"})]}))}
    case["unbounded"] = R.call(ws, probe(api, {"ns:agent:lead:researcher": [("1-0", {})] * 3}, limit=2).inspect, "lead:researcher", "m-1")
    case["redis_error"] = R.call(ws, probe(api, {}, fail=True).inspect, "lead:researcher", "m-1")
    out["test_the_transport_probe_reads_the_recipient_and_dead_letter_streams_completely_or_refuses"] = case

    configured = probe(api, {})
    scoped = type("ScopedBus", (), {"namespace": "ns:run:x", "stream": staticmethod(lambda agent: "ns:run:x:agent:" + agent),
                                    "transport": lambda self, create=True: {**IDENTITY, "namespace": "ns:run:x"}})()
    scoped.client = FakeRedis({"ns:run:x:agent:lead:researcher": [("1-0", {"body": body})]})
    observed = api.TransportProbe(configured.bus, scoped=scoped).inspect("lead:researcher", "m-1")
    tokenless = type("Tokenless", (), {"transport": lambda self, create=True: {**IDENTITY, "storage": None}})()
    other = api.TransportProbe(configured.bus, scoped=tokenless).inspect("lead:researcher", "m-1")
    out["test_the_probe_reads_the_run_scoped_bus_only_when_that_run_owns_a_storage_token"] = {
        "scoped": {"absent": observed["absent"], "namespace": observed["before"]["namespace"]},
        "tokenless": {"absent": other["absent"], "reads_the_configured_bus": other["before"] == IDENTITY}}
    out["test_the_cli_entry_reads_the_owner_file_and_refuses_an_unreachable_bus"] = {"unreachable": UNREACHABLE["cli"]}

    # ---- original transport ownership
    env, _ = failed_world(api, ws, "g1-bound")
    [attempt] = history(env)["attempts"]
    _, sha = replacement(env)
    result = env.programs.recover_dispatch(request(env, sha), FakeTransport())
    out["test_the_failed_attempt_committed_its_transport_and_the_fence_pins_it"] = {
        "attempt": {"status": attempt["status"], "transport": attempt["transport"]},
        "fence_transport": result["fence"]["transport"], "proof": result["proof"]}

    env, _ = failed_world(api, ws, "g1-legacy", council=lambda s: PublicationFailingCouncil(api, s, UnreachableBus(api, bound=False)))
    _, sha = replacement(env)
    transport = FakeTransport()
    out["test_a_legacy_attempt_without_a_binding_refuses_as_unknown_and_writes_nothing"] = {
        "attempt_has_transport": "transport" in history(env)["attempts"][0],
        "recover": refused(env, env.programs.recover_dispatch, request(env, sha), transport),
        "transport_calls": transport.calls, "untouched": untouched(env)}

    for label, view in (("another_server", {"identity": {**IDENTITY, "storage": "token-b"}}),
                        ("no_token", {"identity": {**IDENTITY, "storage": None}}),
                        ("changed_during_read", {"after": {**IDENTITY, "storage": "token-b"}}),
                        ("another_namespace", {"identity": {**IDENTITY, "namespace": "other"}})):
        env, _ = failed_world(api, ws, "g1-other-" + label)
        before = history(env)
        _, sha = replacement(env)
        case = {"other": refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport(**view)),
                "lineage_state": state_of(env), "replacement_dispatch": row(env, api.BUCKET_DISPATCHES, replacement_id(api)),
                "original_current": dispatch_views(env)[inv]["current"]}
        unreadable = FakeTransport()
        unreadable.identity = None
        case["unreadable"] = refused(env, env.programs.recover_dispatch, request(env, sha), unreadable)
        case["bound_transport"] = env.programs.recover_dispatch(request(env, sha), FakeTransport())["state"]
        case["history_untouched"] = history(env) == before
        out["test_absence_on_any_other_transport_refuses_keeps_the_fence_and_the_bound_one_authorizes_once[%s]" % label] = case

    env, _ = failed_world(api, ws, "g1-two-transports")
    message_id = history(env)["outbox"][0]["message"]["message_id"]
    api.relay(env.store, api.organization(), SecondBus(api), correlation_id="autonomous:rp-001.c001")   # a later attempt elsewhere
    with env.store.transaction() as tx:
        attempts = [a for a in tx.scan("outbox_attempts") if a["outbox_id"] == message_id]
        bindings = sorted(a["transport"]["storage"] for a in attempts)
        kept = tx.get("outbox_delivery", message_id)["transport"] == IDENTITY
    _, sha = replacement(env)
    transport = FakeTransport()
    out["test_attempts_on_two_different_transports_refuse_before_any_fence"] = {
        "attempt_storages": bindings, "first_binding_kept": kept,
        "recover": refused(env, env.programs.recover_dispatch, request(env, sha), transport),
        "transport_calls": transport.calls, "untouched": untouched(env)}

    env, _ = failed_world(api, ws, "g1-no-publish", council=lambda s: PublicationFailingCouncil(api, s, UnidentifiedBus(api)))
    _, sha = replacement(env)
    transport = FakeTransport(error=AssertionError("not read"))
    result = env.programs.recover_dispatch(request(env, sha), transport)
    out["test_no_publish_call_needs_no_probe"] = {
        "attempt_statuses": [a["status"] for a in history(env)["attempts"]], "publish_calls": env.runner.council.bus.attempts,
        "result": result, "transport_calls": transport.calls}

    out["test_production_wiring_lost_reply_on_a_then_empty_b_refuses_before_any_replacement"] = {"unreachable": UNREACHABLE["wiring"]}
    out["test_production_wiring_changed_database_namespace_server_or_storage_refuse_and_a_authorizes"] = {"unreachable": UNREACHABLE["wiring"]}
    out["test_domain_transport_rules_are_pure_and_fail_closed"] = domain_transport_rules(api, ws)

    # ---- LABELLED additions (no M7 test): `_refuse_scope_lineage` (INV-RESEARCH-ATTEMPT-SCOPE-001)
    out["added_scope_lineage_is_final"] = scope_lineage(api, ws)
    out["added_followup_strict_request"] = followup_strict(api, ws)
    return out


def domain_transport_rules(api, ws):
    b = {**IDENTITY, "storage": "token-b"}
    case = {"no_attempts": api.attempted_transport([]),
            "unbound_statuses": api.attempted_transport([{"status": "superseded_before_publish"},
                                                         {"status": "transport_unavailable"}]),
            "same_binding_twice": api.attempted_transport([{"status": "retry", "transport": IDENTITY}] * 2) == IDENTITY}
    for label, attempts in (("no_binding", [{"status": "retry"}]),
                            ("tokenless_binding", [{"status": "retry", "transport": {**IDENTITY, "storage": None}}]),
                            ("two_bindings", [{"status": "retry", "transport": IDENTITY}, {"status": "retry", "transport": b}])):
        case["attempted_transport_" + label] = R.call(ws, api.attempted_transport, attempts)
    case["proof_absent"] = api.check_transport_proof(IDENTITY, {"before": IDENTITY, "absent": True, "after": IDENTITY})
    case["proof_present"] = api.check_transport_proof(IDENTITY, {"before": IDENTITY, "absent": False, "after": IDENTITY})
    for label, observation in (("none", None), ("absent_is_text", {"before": IDENTITY, "absent": "yes", "after": IDENTITY}),
                               ("another_transport", {"before": b, "absent": True, "after": b})):
        case["proof_" + label] = R.call(ws, api.check_transport_proof, IDENTITY, observation)
    return case


def scope_lineage(api, ws):
    """LABELLED. `_refuse_scope_lineage` first in every entry: an attempt-scope identity, or a dispatch of kind
    `attempt_scope`, is refused `attempt_scope_final` and nothing is fenced or written."""
    env, _ = failed_world(api, ws, "g1-scope-final")
    _, sha = replacement(env)
    inv = investigation(api)
    document = request(env, sha)
    case = {}
    prefix = api.ATTEMPT_SCOPE_PREFIX
    case["scope_identity_transport_mode"] = refused(env, env.programs.recover_dispatch, {**document, "investigation": prefix + "x"},
                                                    FakeTransport())
    with env.store.transaction() as tx:   # LABELLED synthetic row: the dispatch is an attempt-scope claim
        original = tx.get(api.BUCKET_DISPATCHES, inv)
        tx.put(api.BUCKET_DISPATCHES, inv, {**original, "kind": api.ATTEMPT_SCOPE})
    case["scope_dispatch_transport_mode"] = refused(env, env.programs.recover_dispatch, document, FakeTransport())
    case["scope_dispatch_revocation_mode"] = refused(env, env.programs.recover_dispatch,
                                                     {**document, "schema": REVOCATION, "mode": "execution_revocation",
                                                      "revoke": {"message_id": "m-1", "source_sha256": "a" * 64}}, None)
    case["untouched"] = untouched(env)
    return case


def followup_strict(api, ws):
    """LABELLED. The `urn:zeus:research-dispatch-followup:1` entry (`_follow_up`) reached with an invalid request refuses
    `ProgramRefused` before any read; the accepted-evidence world itself belongs to M7 `test_continuation_research.py`."""
    env, _ = failed_world(api, ws, "g1-followup")
    case = {"empty": refused(env, env.programs.recover_dispatch, {"schema": api.FOLLOWUP_SCHEMA}, None),
            "mode_only": refused(env, env.programs.recover_dispatch,
                                 {"schema": api.FOLLOWUP_SCHEMA, "mode": "accepted_evidence_followup"}, None)}
    return case


def _put(bucket, key, body):
    def change(env, message_id):
        with env.store.transaction() as tx:
            tx.put(bucket, key.replace("{id}", message_id), {**body, "task_id": message_id} if "task_id" in body else body)
    return change


def _later_publication(env, message_id):
    relay_once(env)   # the global relay delivered it after the failure


def _in_flight(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: a publisher crashed mid-publish
        tx.put("outbox_attempts", "attempt-crashed", {"id": "attempt-crashed", "outbox_id": message_id,
                                                      "status": "started", "number": 2})


def _provider_slot(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the run row reports a reserved start
        run = tx.get("autonomous_runs", "rp-001.c001")
        run["starts"] = {"reserved": 1, "settled": 0, "slots": [{"id": "res-x", "settled": False}]}
        tx.put("autonomous_runs", run["id"], run)


def _disposition(env, message_id):
    # LABELLED injected fault: the owner recorded a disposition on the investigation
    env.api.Portfolio(env.store, R.DEFINITIONS).disposition(investigation(env.api), "researched", ["sha256:" + "1" * 64])


EFFECTS = (
    ("task_exists", _put("tasks", "{id}", {"id": "task", "status": "queued"})),
    ("invocation_exists", _put("invocation_reservations", "res-1", {"id": "res-1", "task_id": None})),
    ("residue", _put("dge_sessions", "rp-001.c001.design", {"id": "rp-001.c001.design"})),
    ("later_publication", _later_publication),
    ("in_flight", _in_flight),
    ("provider_slot", _provider_slot),
    ("disposition", _disposition))


# ---- G2 --------------------------------------------------------------------------------------------------------------------
def _drop_fence(env):
    key = "tasks:" + assignment(env)["message"]["message_id"]
    with env.store.lock:   # LABELLED injected fault: the fence row was lost (partial restore)
        env.store.data.pop(("execution_fences", key))


def _rewrite(**changes):
    def fault(env):
        with env.store.transaction() as tx:   # LABELLED injected fault: the fence row was rewritten
            key = "tasks:" + assignment(env)["message"]["message_id"]
            tx.put("execution_fences", key, {**tx.get("execution_fences", key), **changes})
    return fault


def _corrupt_row(env):
    with env.store.transaction() as tx:   # LABELLED injected fault: the lineage evidence was edited
        found = tx.get(env.api.BUCKET_RECOVERIES, investigation(env.api))
        found["revocation"]["owner"] = "someone-else"
        tx.put(env.api.BUCKET_RECOVERIES, investigation(env.api), found)


def _task_appeared(env):
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: a task row appeared anyway
        tx.put("tasks", message_id, {"id": message_id, "status": "queued"})


def _moved_quarantine(env):
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: the outbox fence was released
        tx.put("outbox_delivery", message_id, {**tx.get("outbox_delivery", message_id), "status": "retry"})


RETAINED_FENCE_FAULTS = (
    ("drop_fence", _drop_fence), ("owner", _rewrite(owner="someone-else")), ("generation", _rewrite(generation=2)),
    ("at", _rewrite(at="2000-01-01T00:00:00+00:00")), ("corrupt_row", _corrupt_row), ("task_appeared", _task_appeared),
    ("moved_quarantine", _moved_quarantine))


def g2_revocation(api, ws):
    out = {"m7_scope": {"mirrors": "tests/test_research_recovery.py lines 763-1103 (non-PG, non-CLI)"}}
    inv = investigation(api)

    # ---- test_explicit_revocation_blocks_the_late_original_and_authorizes_exactly_one_replacement
    env, _ = legacy_world(api, ws, "g2-explicit")
    before = history(env)
    _, sha = replacement(env)
    case = {"attempt_has_transport": "transport" in before["attempts"][0], "attempt_status": before["attempts"][0]["status"],
            "strict_mode_refuses": refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport()),
            "untouched": untouched(env), "fence_before": fence_of(env)}
    transport = FakeTransport(error=AssertionError("revocation never reads a transport"))
    result = env.programs.recover_dispatch(revocation(env, sha), transport)
    case["transport_calls"] = transport.calls
    case["result"] = result
    fence = fence_of(env)
    case["fence"] = {k: fence.get(k) for k in ("generation", "owner", "at")}
    case["fence_owner_matches_request"] = fence["owner"] == "research-dispatch-recovery:" + result["request_sha256"]
    case["late_delivery"] = repr_refusal(env, late_delivery(env))
    case["no_execution"] = no_execution(env)
    case["relay_after_revocation"] = relay_once(env)
    case["history_untouched"] = history(env) == before
    case["old_mode_after_revocation"] = refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport())
    env.programs.resume("rp-002")
    runner = replacement_runner(env)
    case["replacement_tick"] = tick_view(runner.tick("rp-002", intent="incident"))
    case["state_after_claim"] = state_of(env)
    case["other_program_conflicts"] = refused(env, env.programs.recover_dispatch, revocation(env, sha, "rp-003"), FakeTransport())
    again = api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(revocation(env, sha), None)
    case["replay"] = {"cached": again["cached"], "state": again["state"], "fence_unchanged": fence_of(env) == fence}
    case["late_delivery_after_claim"] = repr_refusal(env, late_delivery(env))
    case["no_execution_after_claim"] = no_execution(env)
    case["councils"] = len(runner.council.manifests)
    case["history_untouched_after_claim"] = history(env) == before
    out["test_explicit_revocation_blocks_the_late_original_and_authorizes_exactly_one_replacement"] = case

    # ---- test_admission_first_refuses_the_revocation_and_authorizes_nothing
    env, _ = legacy_world(api, ws, "g2-admission-first")
    _, sha = replacement(env)
    task = late_delivery(env)
    out["test_admission_first_refuses_the_revocation_and_authorizes_nothing"] = {
        "admission_status": task["status"], "revoke": refused(env, env.programs.recover_dispatch, revocation(env, sha), None),
        "untouched": untouched(env), "fence": fence_of(env)}

    # ---- test_forced_interleavings_leave_exactly_one_winner (M7's own paused-writer threads; outcomes only)
    for first in ("admission", "revocation"):
        out["test_forced_interleavings_leave_exactly_one_winner[%s]" % first] = forced_interleaving(api, ws, first)

    # ---- test_a_concurrent_race_between_admission_and_revocation_never_yields_both (NON-CONCURRENT forms)
    for first in ("admission", "revocation"):
        env, _ = legacy_world(api, ws, "g2-race-" + first)
        _, sha = replacement(env)
        document = revocation(env, sha)
        outcome = {}

        def admit():
            outcome["admission"] = late_delivery(env)

        def revoke():
            try:
                outcome["revocation"] = env.programs.recover_dispatch(document, None)
            except api.ProgramRefused as exc:
                outcome["revocation"] = exc
        for step in ((admit, revoke) if first == "admission" else (revoke, admit)):
            step()
        admitted, authorized = isinstance(outcome["admission"], dict), isinstance(outcome["revocation"], dict)
        out["test_a_concurrent_race_between_admission_and_revocation_never_yields_both[%s_first]" % first] = {
            "admitted": admitted, "authorized": authorized, "exactly_one_wins": admitted != authorized,
            "revocation": (outcome["revocation"]["state"] if authorized else outcome["revocation"].reason_code),
            "lineage": lineage_summary(env)}

    # ---- test_an_existing_foreign_fence_is_not_this_revocation
    env, _ = legacy_world(api, ws, "g2-foreign-fence")
    _, sha = replacement(env)
    message_id = assignment(env)["message"]["message_id"]
    with env.store.transaction() as tx:   # LABELLED injected fault: an arbitrary fence for the identity
        api.execution_fence_advance(tx, "tasks", message_id, 1, "someone-else")
    out["test_an_existing_foreign_fence_is_not_this_revocation"] = {
        "revoke": refused(env, env.programs.recover_dispatch, revocation(env, sha), None), "untouched": untouched(env)}

    # ---- test_a_changed_message_refuses_before_any_fence
    for label, revoke in (("source_sha256", {"source_sha256": "f" * 64}), ("message_id", {"message_id": "0f0f0f0f-other-message"})):
        env, _ = legacy_world(api, ws, "g2-changed-" + label)
        _, sha = replacement(env)
        out["test_a_changed_message_refuses_before_any_fence[%s]" % label] = {
            "revoke": refused(env, env.programs.recover_dispatch, revocation(env, sha, **revoke), None),
            "untouched": untouched(env), "fence": fence_of(env)}

    # ---- test_revocation_keeps_every_other_precondition
    for label, change in EFFECTS:
        if label in {"later_publication", }:
            continue    # M7 does not parametrize the late publication for the revocation mode
        env, _ = legacy_world(api, ws, "g2-pre-" + label)
        _, sha = replacement(env)
        document = revocation(env, sha)
        change(env, assignment(env)["message"]["message_id"])
        out["test_revocation_keeps_every_other_precondition[%s]" % label] = {
            "revoke": refused(env, env.programs.recover_dispatch, document, None),
            "untouched": untouched(env), "fence": fence_of(env)}

    # ---- test_an_accepted_original_or_a_changed_scope_refuses_revocation
    env, _ = failed_world(api, ws, "g2-accepted", council=lambda store: R.Council(api, store, status="accepted"))
    _, sha = replacement(env)
    document = {**request(env, sha), "schema": REVOCATION, "mode": "execution_revocation",
                "revoke": {"message_id": "m-1", "source_sha256": "a" * 64}}
    case = {"accepted_original": refused(env, env.programs.recover_dispatch, document, None)}
    env, _ = legacy_world(api, ws, "g2-scope")
    _, wide = replacement(env, "rp-wide", max_adoptions=2)
    case["changed_scope"] = refused(env, env.programs.recover_dispatch, revocation(env, wide, "rp-wide"), None)
    case["untouched"] = untouched(env)
    case["fence"] = fence_of(env)
    out["test_an_accepted_original_or_a_changed_scope_refuses_revocation"] = case

    # ---- test_the_revocation_request_is_strict
    strict = {"mode_transport_proof": lambda d: {**d, "mode": "transport_proof"},
              "no_revoke": lambda d: {k: v for k, v in d.items() if k != "revoke"},
              "revoke_only_message_id": lambda d: {**d, "revoke": {"message_id": d["revoke"]["message_id"]}},
              "schema_v1": lambda d: {**d, "schema": "urn:zeus:research-dispatch-recovery:1"}}
    for label, change in strict.items():
        env, _ = legacy_world(api, ws, "g2-strict-" + label)
        _, sha = replacement(env)
        out["test_the_revocation_request_is_strict[%s]" % label] = {
            "revoke": refused(env, env.programs.recover_dispatch, change(revocation(env, sha)), None)}

    # ---- test_a_missing_changed_or_corrupt_retained_fence_holds_replay_and_the_replacement_claim
    for label, fault in RETAINED_FENCE_FAULTS:
        env, _ = legacy_world(api, ws, "g2-retained-" + label)
        _, sha = replacement(env)
        document = revocation(env, sha)
        env.programs.recover_dispatch(document, None)
        fault(env)
        restarted = api.ResearchProgram(env.store, clock=env.clock)
        case = {"replay": refused(env, restarted.recover_dispatch, document, None)}
        env.programs.resume("rp-002")
        tick = replacement_runner(env).tick("rp-002", intent="incident")
        case["replacement_tick"] = tick_view(tick)
        case["no_claim_of_the_investigation"] = tick.get("investigation") is None and tick["selected"] != "inv-" + inv[:24]
        case["replacement_dispatch_row"] = row(env, api.BUCKET_DISPATCHES, replacement_id(api))
        case["lineage_state"] = state_of(env)
        out["test_a_missing_changed_or_corrupt_retained_fence_holds_replay_and_the_replacement_claim[%s]" % label] = case

    # ---- test_concurrent_and_restarted_revocations_record_one_lineage_one_fence_one_quarantine (SEQUENTIAL)
    env, _ = legacy_world(api, ws, "g2-restarted")
    _, sha = replacement(env)
    document = revocation(env, sha)
    results = [api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None) for _ in range(4)]
    out["test_concurrent_and_restarted_revocations_record_one_lineage_one_fence_one_quarantine"] = {
        "cached_flags": [r["cached"] for r in results], "lineage": lineage_summary(env),
        "restarted_cached": api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None)["cached"]}

    # ---- test_a_failed_replacement_after_revocation_is_held
    env, _ = legacy_world(api, ws, "g2-failed-replacement")
    _, sha = replacement(env)
    env.programs.recover_dispatch(revocation(env, sha), None)
    env.programs.resume("rp-002")
    case = {"tick": tick_view(replacement_runner(env, status="failed").tick("rp-002", intent="incident"))}
    _, next_sha = replacement(env, "rp-004")
    case["second_revocation"] = refused(env, env.programs.recover_dispatch, revocation(env, next_sha, "rp-004"), None)
    case["late_delivery"] = repr_refusal(env, late_delivery(env))
    case["no_execution"] = no_execution(env)
    out["test_a_failed_replacement_after_revocation_is_held"] = case
    out["test_the_cli_revocation_builds_no_bus"] = {"unreachable": UNREACHABLE["cli"]}
    out["test_postgres_revocation_and_admission_serialize_to_one_winner"] = {"unreachable": UNREACHABLE["postgres"]}
    return out


def repr_refusal(env, refusal):
    """A late delivery's outcome: the contract refusal (type and whether the text says the identity was used before), or the
    admitted task."""
    if isinstance(refusal, env.api.ContractError):
        return {"refused": type(refusal).__name__, "used_before": "used before" in str(refusal),
                "text": env.ws.scrub(str(refusal))[:200]}
    return {"admitted": refusal.get("status")}


def forced_interleaving(api, ws, first):
    """M7 `test_forced_interleavings_leave_exactly_one_winner`: both orders forced through the one writer transaction; the
    first writer is paused INSIDE its transaction while the other is started; the loser refuses and leaves no partial
    state. Only outcomes are recorded (the clock reads of two threads are not ordered)."""
    env, _ = legacy_world(api, ws, "g2-forced-" + first)
    _, sha = replacement(env)
    entered, release, outcome = threading.Event(), threading.Event(), {}
    workflow = api.Workflow(env.store, api.organization())
    original = env.store.transaction
    # Both inputs are read before the pause is installed: each call then opens exactly ONE writer transaction.
    document, message = revocation(env, sha), deepcopy(assignment(env)["message"])

    @contextmanager
    def holding():   # LABELLED injected pause inside the first writer's transaction
        with original() as tx:
            entered.set()
            release.wait(5)
            yield tx

    def admit():
        try:
            outcome["admission"] = workflow.submit(deepcopy(message))
        except api.ContractError as exc:
            outcome["admission"] = exc

    def revoke():
        try:
            outcome["revocation"] = api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None)
        except api.ProgramRefused as exc:
            outcome["revocation"] = exc
    runs = {"admission": admit, "revocation": revoke}
    env.store.transaction = holding
    winner = threading.Thread(target=runs[first])
    winner.start()
    assert entered.wait(5)
    env.store.transaction = original
    loser = threading.Thread(target=runs["revocation" if first == "admission" else "admission"])
    loser.start()
    release.set()
    winner.join(10)
    loser.join(10)
    with env.store.transaction() as tx:
        tasks, recoveries = tx.scan("tasks"), tx.scan(api.BUCKET_RECOVERIES)
    if first == "admission":
        return {"admission_status": outcome["admission"]["status"], "tasks": len(tasks),
                "revocation_reason": outcome["revocation"].reason_code, "recoveries": len(recoveries),
                "fence": fence_of(env)}
    return {"revocation_state": outcome["revocation"]["state"], "recoveries": len(recoveries),
            "admission_refused": isinstance(outcome["admission"], api.ContractError), "tasks": len(tasks),
            "no_execution": no_execution(env)}


# ---- G3 --------------------------------------------------------------------------------------------------------------------
def _task_status(status):
    def fault(env, council):
        with env.store.transaction() as tx:   # LABELLED injected fault on the predecessor's DBA task
            [task] = [t for t in tx.scan("tasks") if t["agent"] == "lead:dba"]
            tx.put("tasks", task["id"], {**task, "status": status})
    return fault


def _reservation_unknown(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a reservation never settled
        found = tx.scan("invocation_reservations")[0]
        tx.put("invocation_reservations", found["id"], {**found, "status": "unsettled_unknown"})


def _implementation_started(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an operation residue exists
        tx.put("operations", "rp-002.c001.impl", {"id": "rp-002.c001.impl", "status": "running"})


def _other_role(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a non-read-only role task of the run
        message = env.api.envelope("task.assign", "conductor", "lead:research", "dge_role", {"role": "research_lead"},
                                   "autonomous:rp-002.c001")
        tx.put("tasks", message["message_id"], {"id": message["message_id"], "agent": "lead:research",
                                                "status": "succeeded", "message": message, "result": {}})


def _terminated(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an unresolved termination record
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:researcher")
        tx.put("observation_terminations", "term-1", {"id": "term-1", "task_id": task["id"]})


def _marked(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an actual-shaped marker, keyed by its digest id
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:researcher")
        record_id = env.api.Observer.termination_id({"id": task["id"], "_bucket": "tasks"})
        tx.put("observation_terminations", record_id, {"record_id": record_id, "status": "unconfirmed",
                                                        "task_id": task["id"], "bucket": "tasks"})


def _answer_changed(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: the stored answer is not the artifact's
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
        tx.put("tasks", task["id"], {**task, "result": {**task["result"], "summary": "rewritten"}})


def _corrupt_artifact(env, council):
    with env.store.transaction() as tx:
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
    council.artifacts.corrupt(task["result"]["execution_ref"])   # LABELLED injected fault


def _unsent_foreign_role(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an unsent assignment to a non-read-only lead
        message = env.api.envelope("task.assign", "conductor", "lead:research", "dge_role", {"role": "research_lead"},
                                   "autonomous:rp-002.c001")
        tx.put("outbox", message["message_id"], {"message": message, "sent": False})


def _drop_original_fence_ro(env, council):
    _drop_fence(env)


READ_ONLY_FAULTS = (
    ("task_running", _task_status("running")), ("task_failed", _task_status("failed")),
    ("reservation_unknown", _reservation_unknown), ("implementation_started", _implementation_started),
    ("other_role", _other_role), ("unsent_foreign_role", _unsent_foreign_role), ("terminated", _terminated),
    ("marked", _marked), ("answer_changed", _answer_changed), ("corrupt_artifact", _corrupt_artifact),
    ("drop_fence", _drop_original_fence_ro))


def _unsent_report(env):
    """LABELLED: one more DBA report of the predecessor run committed to the outbox and never attempted (no delivery row, no
    attempt), the shape a relay stopped before publishing leaves behind."""
    with env.store.transaction() as tx:
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
        report = env.api.envelope("task.result", "lead:dba", "conductor", "dge_role", {"task_id": task["id"], "result": {}},
                                  "autonomous:rp-002.c001")
        tx.put("outbox", report["message_id"], {"message": report, "sent": False})
    return report["message_id"]


def _move_quarantine(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the successor's outbox fence was released
        tx.put("outbox_delivery", message_id, {**tx.get("outbox_delivery", message_id), "status": "retry"})


def _change_task(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: a bound predecessor execution changed
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:researcher")
        tx.put("tasks", task["id"], {**task, "status": "retry"})


def _corrupt_successor(env, message_id):
    with env.store.transaction() as tx:   # LABELLED injected fault: the authorization row was edited
        found = tx.get(env.api.BUCKET_SUCCESSORS, investigation(env.api) + ":2")
        tx.put(env.api.BUCKET_SUCCESSORS, found["id"], {**found, "predecessor": {**found["predecessor"], "lineage_version": 7}})


def _drop_head(env, message_id):
    with env.store.lock:   # LABELLED injected fault: the versioned head was lost (partial restore)
        env.store.data.pop((env.api.BUCKET_HEADS, investigation(env.api)))


def _drop_original_fence(env, message_id):
    _drop_fence(env)


CHAIN_FAULTS = (("move_quarantine", _move_quarantine), ("change_task", _change_task),
                ("corrupt_successor", _corrupt_successor), ("drop_head", _drop_head),
                ("drop_original_fence", _drop_original_fence))


def g3_successor(api, ws):
    out = {"m7_scope": {"mirrors": "tests/test_research_recovery.py lines 1106-1568 (non-PG, non-CLI)"}}
    inv = investigation(api)
    second = second_id(api)

    # ---- test_the_fixture_is_the_real_shaped_settled_read_only_foreign_message_failure
    env, council, _ = read_only_world(api, ws, "g3-fixture")
    facts = predecessor_history(env)
    run = facts["run"]
    case = {"executor_calls": council.executor.calls,
            "run": {k: run.get(k) for k in ("status", "reason_code", "stage")},
            "starts": {k: run["starts"][k] for k in ("reserved", "settled")}, "roles": sorted(run["roles"]),
            "task_statuses": [t["status"] for t in facts["tasks"]],
            "reservation_statuses": [r["status"] for r in facts["reservations"]],
            "dispatch": {k: facts["dispatch"].get(k) for k in ("result", "result_reason")},
            "recovery_state": facts["recovery"]["state"], "program_state": facts["program"]["state"],
            "resume": refused(env, env.programs.resume, "rp-002")}
    _, sha = replacement(env, "rp-003")
    case["revocation_conflicts"] = refused(env, env.programs.recover_dispatch, revocation(env, sha, "rp-003"), None)
    out["test_the_fixture_is_the_real_shaped_settled_read_only_foreign_message_failure"] = case

    # ---- test_one_explicit_successor_of_the_exact_failed_head_is_claimed_once_and_history_is_kept
    env, council, runner = read_only_world(api, ws, "g3-one")
    before = predecessor_history(env)
    _, sha = replacement(env, "rp-003")
    document = successor_request(env, sha)
    result = env.programs.recover_dispatch(document, FakeTransport(error=AssertionError("never read")), council.artifacts)
    case = {"result": result, "history_untouched": predecessor_history(env) == before}
    views = {d["id"]: d for d in env.programs.dispatches()}
    case["current_flags"] = {replacement_id(api): views[replacement_id(api)]["current"], inv: views[inv]["current"]}
    status = env.programs.status("rp-003")
    case["status_current"] = status["current"]
    case["status_successors"] = [s["id"] for s in status["successors"]]
    case["original_recovery_state"] = env.programs.status("rp-002")["recoveries"][0]["state"]
    env.programs.resume("rp-003")
    runner.council = R.Council(api, env.store, status="accepted")
    case["successor_tick"] = tick_view(runner.tick("rp-003", intent="incident"))
    views = {d["id"]: d for d in env.programs.dispatches()}
    case["views_after_claim"] = {"ids": sorted(views), "second_current": views[second]["current"],
                                 "second_recovery": views[second]["recovery"],
                                 "supersedes": views[second]["supersedes"]}
    case["history_untouched_after_claim"] = predecessor_history(env) == before
    case["successor_state"] = row(env, api.BUCKET_SUCCESSORS, inv + ":2")["state"]
    again = api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)
    case["identical_request"] = {"cached": again["cached"], "state": again["state"]}
    _, other = replacement(env, "rp-004")
    case["another_for_the_same_head"] = refused(env, env.programs.recover_dispatch, successor_request(env, other, "rp-004"), None,
                                                council.artifacts)
    with env.store.transaction() as tx:
        head = tx.get(api.BUCKET_HEADS, inv)
        accepted = tx.get(api.BUCKET_DISPATCHES, second)
        program = tx.get(api.BUCKET_PROGRAMS, "rp-003")
    next_request = {**successor_request(env, other, "rp-004"), "predecessor": {
        "dispatch": second, "lineage_version": 2, "lineage_request_sha256": head["request_sha256"], "program": "rp-003",
        "config_sha256": program["config_sha256"],
        **{k: accepted[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}}
    case["successor_of_the_accepted_successor"] = refused(env, env.programs.recover_dispatch, next_request, None, council.artifacts)
    case["councils"] = len(runner.council.manifests)
    out["test_one_explicit_successor_of_the_exact_failed_head_is_claimed_once_and_history_is_kept"] = case

    # ---- test_unsettled_unknown_effectful_or_unproven_predecessors_refuse_and_write_nothing
    for label, fault in READ_ONLY_FAULTS:
        env, council, _ = read_only_world(api, ws, "g3-fault-" + label)
        _, sha = replacement(env, "rp-003")
        document = successor_request(env, sha)
        if fault is _drop_original_fence_ro:
            fault(env, council)
        else:
            fault(env, council)
        out["test_unsettled_unknown_effectful_or_unproven_predecessors_refuse_and_write_nothing[%s]" % label] = {
            "recover": refused(env, env.programs.recover_dispatch, document, None, council.artifacts),
            "no_successor": no_successor(env)}

    # ---- test_unavailable_evidence_stale_pins_and_widened_scope_refuse_and_write_nothing
    env, council, _ = read_only_world(api, ws, "g3-pins")
    _, sha = replacement(env, "rp-003")
    case = {"no_evidence_port": refused(env, env.programs.recover_dispatch, successor_request(env, sha), None, None)}
    empty = api.ExecutionEvidence(Artifacts(api))   # the REAL port over an empty LABELLED store: no such artifact
    case["empty_evidence"] = refused(env, env.programs.recover_dispatch, successor_request(env, sha), None, empty)
    for label, pin in (("lineage_request_sha256", {"lineage_request_sha256": "f" * 64}),
                       ("manifest_sha256", {"manifest_sha256": "f" * 64}), ("config_sha256", {"config_sha256": "f" * 64}),
                       ("cycle", {"cycle": "rp-002:002"})):
        case["pin_" + label] = refused(env, env.programs.recover_dispatch, successor_request(env, sha, **pin), None, council.artifacts)
    for label, pin in (("lineage_version_2", {"lineage_version": 2}), ("dispatch_is_the_investigation", {"dispatch": inv})):
        case["not_a_head_" + label] = refused(env, env.programs.recover_dispatch, successor_request(env, sha, **pin), None,
                                              council.artifacts)
    _, wide = replacement(env, "rp-wide", max_adoptions=2)
    case["widened_scope"] = refused(env, env.programs.recover_dispatch, successor_request(env, wide, "rp-wide"), None, council.artifacts)
    case["no_successor"] = no_successor(env)
    out["test_unavailable_evidence_stale_pins_and_widened_scope_refuse_and_write_nothing"] = case

    # ---- test_accepted_rejected_or_other_failed_predecessors_are_never_succeeded
    for status in ("accepted", "rejected", "failed"):
        env, _ = legacy_world(api, ws, "g3-never-" + status)
        _, sha = replacement(env)
        env.programs.recover_dispatch(revocation(env, sha), None)
        env.programs.resume("rp-002")
        tick = replacement_runner(env, status=status).tick("rp-002", intent="incident")
        _, sha3 = replacement(env, "rp-003")
        out["test_accepted_rejected_or_other_failed_predecessors_are_never_succeeded[%s]" % status] = {
            "tick_claimed": tick["investigation"] == inv,
            "recover": refused(env, env.programs.recover_dispatch, successor_request(env, sha3), None,
                               ForeignMessageCouncil(api, env.store).artifacts),
            "no_successor": no_successor(env)}

    # ---- test_a_broken_retained_chain_holds_replay_and_the_successor_claim
    for label, fault in CHAIN_FAULTS:
        env, council, runner = read_only_world(api, ws, "g3-chain-" + label)
        message_id = _unsent_report(env)
        _, sha = replacement(env, "rp-003")
        document = successor_request(env, sha)
        result = env.programs.recover_dispatch(document, None, council.artifacts)
        case = {"fence": [{**f, "outbox_is_the_unsent_report": f["outbox"] == message_id} for f in result["fence"]],
                "relay_with_the_report_fenced": relay_once(env)}
        fault(env, message_id)
        case["replay"] = refused(env, api.ResearchProgram(env.store, clock=env.clock).recover_dispatch, document, None, None)
        env.programs.resume("rp-003")
        runner.council = R.Council(api, env.store, status="accepted")
        tick = runner.tick("rp-003", intent="incident")
        case["successor_tick"] = tick_view(tick)
        case["successor_dispatch_row"] = row(env, api.BUCKET_DISPATCHES, second)
        case["successor_state"] = row(env, api.BUCKET_SUCCESSORS, inv + ":2")["state"]
        out["test_a_broken_retained_chain_holds_replay_and_the_successor_claim[%s]" % label] = case

    # ---- test_concurrent_and_restarted_successor_requests_record_one_row_one_head (SEQUENTIAL)
    env, council, _ = read_only_world(api, ws, "g3-restarted")
    _unsent_report(env)
    _, sha = replacement(env, "rp-003")
    document = successor_request(env, sha)
    results = [api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, council.artifacts)
               for _ in range(4)]
    out["test_concurrent_and_restarted_successor_requests_record_one_row_one_head"] = {
        "cached_flags": [r["cached"] for r in results], "lineage": lineage_summary(env),
        "restarted_cached": api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)["cached"]}
    out["test_the_cli_successor_reads_the_executor_artifact_store_and_builds_no_bus"] = {"unreachable": UNREACHABLE["cli"]}
    out["test_postgres_successor_requests_serialize_to_one_authorization"] = {"unreachable": UNREACHABLE["postgres"]}
    return out


# ---- G4 --------------------------------------------------------------------------------------------------------------------
def _ctask_status(status):
    def fault(env, council):
        with env.store.transaction() as tx:   # LABELLED injected fault on the predecessor's improvement task
            [task] = [t for t in tx.scan("tasks") if t["agent"] == "lead:improvement"]
            tx.put("tasks", task["id"], {**task, "status": status})
    return fault


def _creservation_unknown(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a reservation never settled
        found = tx.scan("invocation_reservations")[0]
        tx.put("invocation_reservations", found["id"], {**found, "status": "unsettled_unknown"})


def _cconductor_entry(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a conductor role task of the run
        message = env.api.envelope("task.assign", "conductor", "conductor", "dge_role", {"role": "conductor"},
                                   "autonomous:rp-001.c001")
        tx.put("tasks", message["message_id"], {"id": message["message_id"], "agent": "conductor",
                                                "status": "succeeded", "message": message, "result": {}})


def _cworker_entry(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an implementation operation residue exists
        tx.put("operations", "rp-001.c001.impl", {"id": "rp-001.c001.impl", "status": "running"})


def _cterminated(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: an unresolved termination record
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:research")
        tx.put("observation_terminations", "term-1", {"id": "term-1", "task_id": task["id"]})


def _cmissing_artifact(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: the failed role's artifact is gone
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:improvement")
    council.artifacts.bodies.pop(task["result"]["execution_ref"][7:])


def _ccorrupt_artifact(env, council):
    with env.store.transaction() as tx:
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:improvement")
    council.artifacts.corrupt(task["result"]["execution_ref"])   # LABELLED injected fault


def _cdecision_recorded(env, council):
    with env.store.transaction() as tx:   # LABELLED injected fault: a conductor decision exists in the session
        session = tx.get("dge_sessions", "rp-001.c001.design")
        tx.put("dge_sessions", "rp-001.c001.design", {**session, "decision_event_id": "evt-x"})


CONTRACT_FAULTS = (
    ("task_running", _ctask_status("running")), ("task_failed", _ctask_status("failed")),
    ("reservation_unknown", _creservation_unknown), ("conductor_entry", _cconductor_entry), ("worker_entry", _cworker_entry),
    ("decision_recorded", _cdecision_recorded), ("terminated", _cterminated), ("missing_artifact", _cmissing_artifact),
    ("corrupt_artifact", _ccorrupt_artifact))

CONTRACT_STRICT = (
    ("role_conductor", {"failure": {"role": "conductor"}}),
    ("role_dba_check_dba", {"failure": {"role": "dba", "check": "council_field_invalid:dba.summary:too_long"}}),
    ("check_legacy_code", {"failure": {"check": "debate_refused:ContractError"}}),
    ("check_dba_summary", {"failure": {"check": "council_field_invalid:dba.summary:too_long"}}),
    ("execution_ref_not_a_ref", {"failure": {"execution_ref": "not-a-ref"}}), ("failure_extra", {"failure": {"extra": 1}}),
    ("version_0_with_lineage_sha", {"predecessor": {"lineage_request_sha256": "a" * 64}}),
    ("predecessor_dispatch_replacement", {"predecessor": {"dispatch": "<REPLACEMENT>"}}),
    ("mode_read_only", {"mode": "settled_read_only_successor"}), ("replacement_is_the_failed_program", {"replacement": {"program": "rp-001"}}))


def g4_contract_successor(api, ws):
    out = {"m7_scope": {"mirrors": "tests/test_research_recovery.py lines 1611-2069 (non-PG, non-CLI)"}}
    inv = investigation(api)
    second = second_id(api)
    replacement_dispatch = replacement_id(api)

    # ---- test_the_fixture_is_the_actual_shaped_settled_four_role_contract_failure
    for legacy in (False, True):
        env, council = initial_world(api, ws, "g4-fixture-%s" % legacy, legacy=legacy)
        facts = run_history(env)
        run = facts["run"]
        case = {"executor_calls": council.executor.calls,
                "run": {k: run.get(k) for k in ("status", "reason_code", "stage")},
                "starts": {k: run["starts"][k] for k in ("reserved", "settled")}, "roles": sorted(run["roles"]),
                "task_statuses": [t["status"] for t in facts["tasks"]],
                "reservation_statuses": [r["status"] for r in facts["reservations"]],
                "session": {k: facts["session"].get(k) for k in ("version", "decision_event_id")},
                "dispatch": {k: facts["dispatch"].get(k) for k in ("result", "result_reason")},
                "recovery": facts["recovery"], "resume": refused(env, env.programs.resume, "rp-001")}
        _, sha = replacement(env)
        case["strict_transport_mode"] = refused(env, env.programs.recover_dispatch, request(env, sha), FakeTransport())
        out["test_the_fixture_is_the_actual_shaped_settled_four_role_contract_failure[%s]" % ("legacy" if legacy else "current")] = case

    # ---- test_one_explicit_successor_of_the_initial_contract_failure_is_claimed_once_and_history_is_kept
    for legacy in (False, True):
        env, council = initial_world(api, ws, "g4-one-%s" % legacy, legacy=legacy)
        before = run_history(env)
        _, sha = replacement(env)
        document = contract_request(env, sha)
        result = env.programs.recover_dispatch(document, FakeTransport(error=AssertionError("never read")), council.artifacts)
        answer = council.artifacts.document(document["failure"]["execution_ref"])["answer"]
        case = {"result": result, "output_sha256_is_the_artifact_digest": result["failure"]["output_sha256"] == api.digest(answer),
                "summary_length": len(answer["summary"]), "secret_in_result": "SECRET-summary-body" in json.dumps(result),
                "history_untouched": run_history(env) == before}
        with env.store.transaction() as tx:
            head = tx.get(api.BUCKET_HEADS, inv)
            case["recovery_held"] = api.Continuation._recovery_held(tx, inv)
            case["recovery_1_unused"] = tx.get(api.BUCKET_DISPATCHES, replacement_dispatch) is None
        case["head_previous"] = head["previous"]
        env.programs.resume("rp-002")
        runner = replacement_runner(env)
        case["successor_tick"] = tick_view(runner.tick("rp-002", intent="incident"))
        views = {d["id"]: d for d in env.programs.dispatches()}
        case["views_after_claim"] = {"ids": sorted(views), "second_current": views[second]["current"],
                                     "initial_current": views[inv]["current"], "supersedes": views[second]["supersedes"]}
        case["history_untouched_after_claim"] = run_history(env) == before
        case["identical_request"] = api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)["cached"]
        _, other = replacement(env, "rp-003")
        case["another_for_the_same_head"] = refused(env, env.programs.recover_dispatch, contract_request(env, other, "rp-003"), None,
                                                    council.artifacts)
        case["councils"] = len(runner.council.manifests)
        out["test_one_explicit_successor_of_the_initial_contract_failure_is_claimed_once_and_history_is_kept[%s]" % (
            "legacy" if legacy else "current")] = case

    # ---- test_an_existing_lineage_current_dispatch_contract_failure_has_one_successor
    env, council = current_world(api, ws, "g4-lineage")
    before = run_history(env, "rp-002.c001", replacement_dispatch)
    _, sha = replacement(env, "rp-003")
    document = contract_request(env, sha, "rp-003", program="rp-002", dispatch=replacement_dispatch, version=1)
    with env.store.transaction() as tx:
        original = tx.get(api.BUCKET_DISPATCHES, inv)
    stale = {**document, "predecessor": {**document["predecessor"], "dispatch": inv, "lineage_version": 0,
                                         "lineage_request_sha256": None, "program": "rp-001",
                                         **{k: original[k] for k in ("cycle", "run_id", "manifest_sha256", "snapshot_sha256")}}}
    case = {"stale_initial_pin": refused(env, env.programs.recover_dispatch, stale, None, council.artifacts)}
    result = env.programs.recover_dispatch(document, None, council.artifacts)
    case["result"] = {k: result.get(k) for k in ("version", "state", "recovered", "cached", "mode", "proof")}
    case["replacement_dispatch"] = result["replacement"]["dispatch"]
    case["history_untouched"] = run_history(env, "rp-002.c001", replacement_dispatch) == before
    case["original_recovery_state"] = env.programs.status("rp-002")["recoveries"][0]["state"]
    env.programs.resume("rp-003")
    case["successor_tick"] = tick_view(replacement_runner(env).tick("rp-003", intent="incident"))
    case["current_flags"] = {d["id"]: d["current"] for d in env.programs.dispatches()}
    out["test_an_existing_lineage_current_dispatch_contract_failure_has_one_successor"] = case

    # ---- test_unsettled_unknown_effectful_or_unproven_contract_predecessors_refuse_and_write_nothing
    for label, fault in CONTRACT_FAULTS:
        env, council = initial_world(api, ws, "g4-fault-" + label)
        _, sha = replacement(env)
        document = contract_request(env, sha)
        fault(env, council)
        out["test_unsettled_unknown_effectful_or_unproven_contract_predecessors_refuse_and_write_nothing[%s]" % label] = {
            "recover": refused(env, env.programs.recover_dispatch, document, None, council.artifacts),
            "no_contract_successor": no_contract_successor(env)}

    # ---- test_a_wrong_failure_foreign_evidence_or_stale_pin_refuses_and_writes_nothing
    env, council = initial_world(api, ws, "g4-wrong")
    _, sha = replacement(env)
    with env.store.transaction() as tx:
        dba = next(t for t in tx.scan("tasks") if t["agent"] == "lead:dba")
    case = {}
    for label, failure in (("rationale_too_long", {"check": "council_field_invalid:improvement_lead.rationale:too_long"}),
                           ("summary_empty", {"check": "council_field_invalid:improvement_lead.summary:empty"}),
                           ("dba_task", {"task_id": dba["id"]}),
                           ("dba_execution_ref", {"execution_ref": dba["result"]["execution_ref"]}),
                           ("unknown_execution_ref", {"execution_ref": "sha256:" + "e" * 64})):
        case["failure_" + label] = refused(env, env.programs.recover_dispatch, contract_request(env, sha, failure=failure), None,
                                           council.artifacts)
    for label, pin in (("manifest_sha256", {"manifest_sha256": "f" * 64}), ("config_sha256", {"config_sha256": "f" * 64}),
                       ("cycle", {"cycle": "rp-001:002"}), ("run_id", {"run_id": "rp-001.c002"})):
        case["pin_" + label] = refused(env, env.programs.recover_dispatch, contract_request(env, sha, **pin), None, council.artifacts)
    case["no_evidence_port"] = refused(env, env.programs.recover_dispatch, contract_request(env, sha), None, None)
    case["empty_evidence"] = refused(env, env.programs.recover_dispatch, contract_request(env, sha), None,
                                     api.ExecutionEvidence(Artifacts(api)))
    _, wide = replacement(env, "rp-wide", max_adoptions=2)
    case["widened_scope"] = refused(env, env.programs.recover_dispatch, contract_request(env, wide, "rp-wide"), None, council.artifacts)
    case["no_contract_successor"] = no_contract_successor(env)
    out["test_a_wrong_failure_foreign_evidence_or_stale_pin_refuses_and_writes_nothing"] = case

    # ---- test_the_contract_request_is_strict
    for label, change in CONTRACT_STRICT:
        env, council = initial_world(api, ws, "g4-strict-" + label)
        _, sha = replacement(env)
        base = contract_request(env, sha)
        applied = {k: ({**base[k], **{kk: (replacement_dispatch if vv == "<REPLACEMENT>" else vv) for kk, vv in v.items()}}
                       if isinstance(v, dict) else v) for k, v in change.items()}
        out["test_the_contract_request_is_strict[%s]" % label] = {
            "recover": refused(env, env.programs.recover_dispatch, {**base, **applied}, None, council.artifacts),
            "no_contract_successor": no_contract_successor(env)}

    # ---- test_another_contract_error_or_a_read_only_failure_is_not_this_contract_failure
    env, council = initial_world(api, ws, "g4-other-error", improvement={"claim_ids": ["c404"]})
    _, sha = replacement(env)
    case = {"recorded_reason": run_history(env)["run"]["reason_code"],
            "recover": refused(env, env.programs.recover_dispatch, contract_request(env, sha), None, council.artifacts),
            "no_contract_successor": no_contract_successor(env)}
    other, ro_council, _ = read_only_world(api, ws, "g4-read-only")
    _, sha3 = replacement(other, "rp-003")
    document = {**successor_request(other, sha3), "schema": CONTRACT_SCHEMA, "mode": "settled_contract_failure_successor",
                "failure": {"role": "improvement_lead", "task_id": "t-1", "execution_ref": "sha256:" + "a" * 64,
                            "check": SUMMARY_TOO_LONG}}
    case["read_only_predecessor"] = refused(other, other.programs.recover_dispatch, document, None, ro_council.artifacts)
    out["test_another_contract_error_or_a_read_only_failure_is_not_this_contract_failure"] = case

    # ---- test_a_broken_retained_fence_holds_replay_the_claim_and_the_scoped_receipt_consumer
    env, council = initial_world(api, ws, "g4-broken-fence")
    with env.store.transaction() as tx:   # LABELLED: one more unsent report of the predecessor run, never attempted
        task = next(t for t in tx.scan("tasks") if t["agent"] == "lead:improvement")
        report = api.envelope("task.result", "lead:improvement", "conductor", "dge_role", {"task_id": task["id"], "result": {}},
                              "autonomous:rp-001.c001")
        tx.put("outbox", report["message_id"], {"message": report, "sent": False})
    _, sha = replacement(env)
    document = contract_request(env, sha)
    result = env.programs.recover_dispatch(document, None, council.artifacts)
    case = {"report_is_fenced": report["message_id"] in [f["outbox"] for f in result["fence"]],
            "relay_with_the_report_fenced": relay_once(env)}
    _move_quarantine(env, report["message_id"])   # LABELLED injected fault: the fence was released
    case["replay"] = refused(env, api.ResearchProgram(env.store, clock=env.clock).recover_dispatch, document, None, None)
    with env.store.transaction() as tx:
        case["scoped_receipt_consumer_held"] = api.Continuation._recovery_held(tx, inv)
    env.programs.resume("rp-002")
    tick = replacement_runner(env).tick("rp-002", intent="incident")
    case["successor_tick"] = tick_view(tick)
    case["successor_dispatch_row"] = row(env, api.BUCKET_DISPATCHES, second)
    case["successor_state"] = row(env, api.BUCKET_SUCCESSORS, inv + ":2")["state"]
    out["test_a_broken_retained_fence_holds_replay_the_claim_and_the_scoped_receipt_consumer"] = case

    # ---- test_a_failed_contract_successor_stays_held
    env, council = initial_world(api, ws, "g4-held")
    _, sha = replacement(env)
    document = contract_request(env, sha)
    env.programs.recover_dispatch(document, None, council.artifacts)
    env.programs.resume("rp-002")
    tick = replacement_runner(env, status="failed").tick("rp-002", intent="incident")
    case = {"tick": tick_view(tick), "resume": refused(env, env.programs.resume, "rp-002"),
            "identical_request": api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)["state"]}
    _, other = replacement(env, "rp-003")
    case["another_for_the_same_key"] = refused(env, env.programs.recover_dispatch, contract_request(env, other, "rp-003"), None,
                                               council.artifacts)
    case["successors"] = len(rows(env, api.BUCKET_SUCCESSORS))
    case["second_result"] = row(env, api.BUCKET_DISPATCHES, second)["result"]
    out["test_a_failed_contract_successor_stays_held"] = case

    # ---- test_concurrent_and_restarted_contract_requests_record_one_row_one_head (SEQUENTIAL)
    env, council = initial_world(api, ws, "g4-restarted")
    _, sha = replacement(env)
    document = contract_request(env, sha)
    results = [api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, council.artifacts)
               for _ in range(4)]
    out["test_concurrent_and_restarted_contract_requests_record_one_row_one_head"] = {
        "cached_flags": [r["cached"] for r in results], "lineage": lineage_summary(env),
        "restarted_cached": api.ResearchProgram(env.store, clock=env.clock).recover_dispatch(document, None, None)["cached"]}
    out["test_the_cli_contract_successor_reads_the_artifact_store_and_builds_no_bus"] = {"unreachable": UNREACHABLE["cli"]}
    out["test_postgres_contract_successor_requests_serialize_to_one_authorization"] = {"unreachable": UNREACHABLE["postgres"]}
    return out


# ---- the run -------------------------------------------------------------------------------------------------------------
GROUPS = (("g1_recovery", g1_recovery), ("g2_revocation", g2_revocation), ("g3_successor", g3_successor),
          ("g4_contract_successor", g4_contract_successor))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        return result
    finally:
        ws.close()
