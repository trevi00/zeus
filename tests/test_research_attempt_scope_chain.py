"""INV-RESEARCH-ATTEMPT-SCOPE-001 (U2(b) PR-1), FLEET-U2B-SPEC rows U2B-16 and U2B-6: the fully stubbed
F4 -> F7S chain on one P1-shaped control store.

One held research intent R (the World's real two-strike lineage J_F0 -> S1) beside the P1 history: 21
historical members of the same cause (11 bound to the authorized project, Q1 the latest of them), four
resolved family dispatches, a claimed recovery, two claimed successors, their head and 15 terminal programs.
The chain is: the owner decision owes exactly ONE `research_dispatch` for R, the owner persists its launch
binding, the child reserves the cycle under that launch id, collection claims exactly the pair, a council
start and an ACCEPTED result are recorded, the owner outcome is completed, the owner's own receipt path
(assessment -> assembly -> `accept_research`) stores a schema-1 receipt naming the scope as original_capture,
and the continuation's own tick (the full consumption path, not an accept-and-recheck shortcut) consumes R once.

A write spy on the ONE control store records every committed put. Across the whole chain only the chain's own
lifecycle rows are written; every pre-existing historical family lineage, Portfolio, binding and Fleet row
keeps its canonical bytes and is never put at all. Restarts and repeats at every stage create no second claim,
adoption, dispatch or consumption; an injected fault before each commit (owner action, reservation, claim,
council result, receipt, consumption) leaves no partial row; a failure after the claim (capture fault, council
start failure, or a child lost with its cycle still owned) keeps the claim final: nothing is released or retried.

LABELLED fixtures only: the World's real MemoryStores, Fleet, finite Operation (with the `FakeExecutor`
fixture, and both executor transports made to raise if anything reached them), continuation owner, Portfolio
bindings, ResearchProgram state machine and OwnerActions coordinator. The P1 history rows, the research launch
port (`ChildPort`: the test plays the child with the persisted launch id as its cycle owner), the council run
rows and the assessor (`FakeAssessor`) are synthetic. No provider, model, network, Git capture or production
store is touched, and nothing here is evidence of a live research outcome or of a real qualification gate.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager

import pytest
from test_continuation import World, only
from test_continuation_research import receipt_for, two_strikes
from test_owner_actions import PIN, FakeAssessor, owner_policy
from test_research_attempt_scope_program import (
    COUNTS,
    HISTORICAL,
    LEADS,
    Q1,
    SCOPED,
    family_dispatch,
)
from test_research_attempt_scope_program import launch as bound_launch
from test_research_investigations import DEFINITIONS
from test_research_program import POLICY, Clock
from test_research_program_fixtures import config

from codex_harness.application.continuation import BUCKET_INTENTS, BUCKET_RESEARCH_RECEIPTS
from codex_harness.application.owner_actions import BUCKET_ACTIONS, OwnerActions
from codex_harness.application.portfolio import (
    BUCKET_BINDINGS,
    BUCKET_INVESTIGATIONS,
    Portfolio,
    family_id,
)
from codex_harness.application.research_program import (
    BUCKET_CANDIDATES,
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_HEADS,
    BUCKET_PROGRAMS,
    BUCKET_RECOVERIES,
    BUCKET_SUCCESSORS,
    ResearchProgram,
)
from codex_harness.bootstrap import organization
from codex_harness.domain import continuation as dc
from codex_harness.domain import owner_actions as do
from codex_harness.domain import research_investigations as ri
from codex_harness.domain.model import canonical, digest
from codex_harness.domain.research_program import ProgramRefused, validate_config

PROGRAM, OWNERS, REPOSITORY = "rp-scope", "owners-2", "repo-1"
NOW = "2026-09-28T00:00:00+00:00"
LEDGER = {"host": "fixture", "this_host": 0, "all_hosts": 0, "unreadable": 0}
LINEAGE = (BUCKET_DISPATCHES, BUCKET_RECOVERIES, BUCKET_SUCCESSORS, BUCKET_HEADS)


@pytest.fixture(autouse=True)
def no_executor_transport(monkeypatch):
    """Nothing in this chain may reach a real executor transport: both raise if ever constructed."""
    def unreachable(*args, **kwargs):
        raise AssertionError("an executor transport was reached in a stubbed chain")
    monkeypatch.setattr("codex_harness.adapters.executor.AppServer", unreachable)
    monkeypatch.setattr("codex_harness.adapters.executor.ClaudeCodeRuntime", unreachable)


# ----- LABELLED ports ---------------------------------------------------------------------------------------
class ChildPort:
    """LABELLED research launch port: never spawns anything. `start` records the launch id the owner persisted
    (the child's `--cycle-owner` token); the test then plays that child. `poll` reports it running until
    `finish`, then exited with its cleanup proven."""

    def __init__(self):
        self.starts, self.exited = [], set()

    def probe(self):
        return {"ok": True, "reason_code": None, "codex": None, "node": None}

    def start(self, launch, program_id, lane):
        self.starts.append((launch, program_id, lane))
        return {"cached": False}

    def finish(self, launch):
        self.exited.add(launch)

    def poll(self, launch):
        if launch not in {start[0] for start in self.starts}:
            return {"state": "absent", "owned": False, "exit_code": None, "proof": {"kind": "fenced"}}
        if launch in self.exited:
            return {"state": "exited", "owned": False, "exit_code": 0, "cleanup_confirmed": True}
        return {"state": "running", "owned": True, "exit_code": None}


class WriteSpy:
    """LABELLED write spy on the ONE control MemoryStore every port shares. Each transaction's puts are kept as
    (bucket, id) only when it commits. `fail_on(bucket)` arms ONE injected fault: the next put to that bucket
    raises inside its transaction, so the real store discards the whole draft (nothing of it commits)."""

    def __init__(self, store):
        self.committed, self.aborted, self.armed = [], [], None
        original = store.transaction

        @contextmanager
        def transaction(fail_fast: bool = False):
            puts = []
            with original(fail_fast) as tx:
                put = tx.put

                def recording(bucket, key, body):
                    if self.armed == bucket:
                        self.armed = None
                        raise RuntimeError("LABELLED injected fault before commit")
                    puts.append((bucket, key))
                    put(bucket, key, body)
                tx.put = recording
                try:
                    yield tx
                except BaseException:
                    self.aborted.append(puts)
                    raise
            self.committed.extend(puts)
        store.transaction = transaction

    def fail_on(self, bucket: str) -> None:
        self.armed = bucket

    def mark(self) -> int:
        return len(self.committed)

    def since(self, mark: int) -> list:
        return self.committed[mark:]


# ----- the P1-shaped world ------------------------------------------------------------------------------------
def rows(store) -> dict:
    with store.transaction() as tx:
        return {(r["bucket"], r["id"]): canonical(r["body"]) for r in tx.records()}


def scan(store, bucket) -> list:
    with store.transaction() as tx:
        return tx.scan(bucket)


def get(store, bucket, key):
    with store.transaction() as tx:
        return tx.get(bucket, key)


def p1_history(world, cause) -> None:
    """LABELLED synthetic P1 history of the held pair's own cause: 21 historical Fleet members bound through
    the real Portfolio (the first 11 to the authorized project), the real reconciler's cause row (it also
    gains the held pair: membership reconciliation, never a capture), four resolved family dispatches over
    scoped historical members only, a claimed recovery, two claimed successors, their head and 15 terminal
    programs whose legacy source names the cause (completed/blocked: no rival, their claims still count)."""
    status, reason = cause
    key = family_id(status, reason)
    with world.control.transaction() as tx:
        for member in HISTORICAL:
            tx.put("fleet_jobs", member, {"id": member, "status": status, "reason_code": reason})
    portfolio = Portfolio(world.control, DEFINITIONS, clock=lambda: NOW)
    for index, member in enumerate(HISTORICAL):
        portfolio.bind(member, "ops" if index < 11 else "other", "c1")
    portfolio.reconcile()
    source = {"topic": "storage", "project_ids": ["ops"], "reason_codes": [reason]}
    keys = [key, key + ".recovery-1", key + ".recovery-2", key + ".recovery-3"]
    with world.control.transaction() as tx:
        for number, dispatch in enumerate(keys):
            tx.put(BUCKET_DISPATCHES, dispatch, family_dispatch(dispatch, SCOPED[:4 + 2 * number],
                                                                "rp-hist-%02d" % (number + 1), cause=cause))
        tx.put(BUCKET_RECOVERIES, key, {
            "id": key, "investigation": key, "state": "claimed", "request_sha256": "6" * 64,
            "failed": {"program": "rp-hist-01", "cycle": "rp-hist-01:001"},
            "replacement": {"program": "rp-hist-02", "dispatch": keys[1], "cycle": "rp-hist-02:001"}})
        for version in (2, 3):
            # Each claimed successor is the exact immutable authorization its key names (the lineage reader
            # holds nothing for it): its request digest, predecessor version and dispatch chain are consistent.
            request = {"mode": ri.SUCCESSOR_MODE, "investigation": key, "labelled": "p1-fixture-%d" % version}
            tx.put(BUCKET_SUCCESSORS, ri.successor_key(key, version), {
                "id": ri.successor_key(key, version), "investigation": key, "version": version, "state": "claimed",
                "reason_code": None, "request": request, "request_sha256": digest(request),
                "proof": ri.SUCCESSOR_PROOF,
                "predecessor": {"program": "rp-hist-%02d" % version, "lineage_version": version - 1,
                                "dispatch": keys[version - 1]},
                "replacement": {"program": "rp-hist-%02d" % (version + 1), "dispatch": keys[version],
                                "cycle": "rp-hist-%02d:001" % (version + 1)}})
        tx.put(BUCKET_HEADS, key, {"id": key, "investigation": key, "version": 3, "successor": ri.successor_key(key, 3),
                                   "request_sha256": digest({"mode": ri.SUCCESSOR_MODE, "investigation": key,
                                                             "labelled": "p1-fixture-3"}),
                                   "dispatch": keys[3]})
        for number in range(1, 16):
            tx.put(BUCKET_PROGRAMS, "rp-hist-%02d" % number, {
                "id": "rp-hist-%02d" % number, "state": "completed" if number % 2 else "blocked",
                "config": {"investigation_source": dict(source)}})


class Chain:
    """The P1-shaped world with R held, the paused scoped program registered and the owner policy registered."""

    def __init__(self, tmp_path):
        self.world = world = World(tmp_path)
        world.register()
        self.root, self.successor, self.research = two_strikes(world, "op-x", "docs/a.md")
        self.pair = sorted([self.root, self.successor])
        jobs = world.jobs()
        self.cause = (jobs[self.root]["status"], jobs[self.root]["reason_code"])
        portfolio = Portfolio(world.control, DEFINITIONS, clock=lambda: NOW)
        for job in self.pair:
            portfolio.bind(job, "ops", "c1")
        p1_history(world, self.cause)
        self.scope = dc.attempt_scope_id(self.research["id"])
        self.source = {"topic": "storage", "continuation_policy": "policy-1",
                       "continuation_policy_sha256": world.controller.policy("policy-1")["policy_sha256"],
                       "families": [self.root], "project_ids": ["ops"], "reason_codes": [self.cause[1]]}
        cfg = validate_config(config("a" * 40, id=PROGRAM, attempt_scope_source=dict(self.source)), POLICY)
        ResearchProgram(world.control, clock=Clock(NOW)).register(cfg, REPOSITORY, [])
        self.port, self.assessor = ChildPort(), FakeAssessor(world)
        self.owner = self.coordinator()
        self.owner.register(owner_policy(
            schema=do.POLICY_SCHEMA_V2, id=OWNERS,
            requalification={"enabled": False, "reasons": ["reviewed_base_moved"], "max_per_family": 1},
            research={"enabled": True, "program_id": PROGRAM, "lane": "a"}), PIN)
        # Everything above is the pre-existing state the chain starts from; the spy watches from here on.
        self.before = rows(world.control)
        self.spy = WriteSpy(world.control)

    def coordinator(self) -> OwnerActions:
        """A fresh coordinator over the same store and ports (a restart keeps nothing in memory)."""
        return OwnerActions(self.world.control, continuation=self.world.controller, org=organization(),
                            lanes=self.world.lanes, assessments=self.assessor, research=self.port,
                            ledger=lambda: dict(LEDGER), clock=lambda: NOW)

    def child(self, launch) -> ResearchProgram:
        """The research child the launch started: its cycle owner token IS the persisted launch id."""
        return ResearchProgram(self.world.control, clock=Clock(NOW), token=lambda: launch)

    def actions(self, kind=None) -> list:
        return [a for a in scan(self.world.control, BUCKET_ACTIONS)
                if a.get("policy_id") == OWNERS and (kind is None or a["kind"] == kind)]

    def scope_claims(self) -> list:
        return [d for d in scan(self.world.control, BUCKET_DISPATCHES) if d.get("kind") == "attempt_scope"]

    def adoptions(self) -> int:
        return get(self.world.control, BUCKET_PROGRAMS, PROGRAM)["adoptions"]

    def own(self) -> set:
        """The pre-existing rows the chain itself moves: its program, the held intent it consumes and the
        continuation's scheduling-order record (attempt progress, never a verdict or evidence)."""
        return {(BUCKET_PROGRAMS, PROGRAM), (BUCKET_INTENTS, self.research["id"]), ("continuation_progress", "policy-1")}

    def history(self) -> dict:
        """Every other pre-existing row (lineage, Portfolio, bindings, Fleet, intents, policies), canonical bytes."""
        return {k: v for k, v in self.before.items() if k not in self.own()}

    def single(self) -> None:
        """The chain's cardinalities at any stage: one owner dispatch, at most one claim and one adoption."""
        assert len(self.actions(do.RESEARCH_DISPATCH)) == 1
        assert [d["id"] for d in self.scope_claims()] in ([], [self.scope])
        assert self.adoptions() <= 1 and len(self.port.starts) == 1


# ----- stage helpers ------------------------------------------------------------------------------------------
def inert(chain, call, *args, refuses=None, returns=None) -> None:
    """A repeated or restarted step writes nothing: it refuses by name, answers busy/not due, or idles."""
    mark, before = chain.spy.mark(), rows(chain.world.control)
    if refuses is not None:
        with pytest.raises(ProgramRefused) as info:
            call(*args)
        assert info.value.reason_code == refuses
    else:
        result = call(*args)
        if returns is not None:
            assert {k: result.get(k) for k in returns} == returns, result
    assert chain.spy.since(mark) == [] and rows(chain.world.control) == before, "a repeat wrote something"
    chain.single()


def faulted(chain, bucket, call, *args) -> None:
    """LABELLED injected fault on the next put to `bucket` inside `call`: that whole transaction rolls back, so the
    store is exactly as before (no partial row of the step survives)."""
    before, aborted = rows(chain.world.control), len(chain.spy.aborted)
    chain.spy.fail_on(bucket)
    with pytest.raises(RuntimeError, match="LABELLED injected fault"):
        call(*args)
    assert chain.spy.armed is None and len(chain.spy.aborted) == aborted + 1, "the fault fired inside a transaction"
    assert rows(chain.world.control) == before, "a fault before the commit left a partial row"


def owner_idle(chain) -> None:
    """The running (or finished and settled) owner: this coordinator and a restarted one change nothing."""
    inert(chain, chain.owner.tick, OWNERS)
    inert(chain, chain.coordinator().tick, OWNERS)


def launched(chain) -> tuple:
    """F4: the owner decision owes exactly one research_dispatch for R; a tick persists its launch binding and
    starts the child under it. A fault on the action's first write leaves nothing and the next tick owes it."""
    world = chain.world
    scope, decision = chain.owner._research_decide(chain.research, list(world.intents().values()), PROGRAM)
    assert (decision["act"], decision["reason"]) == (True, "research_ready_resume_then_tick")
    assert scope["investigation"] == chain.scope and scope["attempts"] == chain.pair
    before, aborted = rows(world.control), len(chain.spy.aborted)
    chain.spy.fail_on(BUCKET_ACTIONS)
    waited = chain.owner.tick(OWNERS)
    assert waited["waits"][do.RESEARCH_DISPATCH + ":" + chain.research["id"]] == "RuntimeError"
    assert len(chain.spy.aborted) == aborted + 1 and rows(world.control) == before and chain.port.starts == []
    ticked = chain.owner.tick(OWNERS)
    [action] = chain.actions(do.RESEARCH_DISPATCH)
    assert ticked["created"] == [action["id"]] and action["subject"]["intent_id"] == chain.research["id"]
    assert action["binding"] == {"intent_id": chain.research["id"], "continuation_policy": "policy-1",
                                 "family": chain.root, "program_id": PROGRAM, "investigation": chain.scope,
                                 "attempts": chain.pair, "expected_cycle": 1}
    launch = do.research_launch_id(action["id"], 1)
    assert action["state"] == do.RUNNING and action["launch_id"] == launch and action["launches"] == 1
    assert chain.port.starts == [(launch, PROGRAM, "a")]
    assert get(world.control, BUCKET_PROGRAMS, PROGRAM)["state"] == "active", "the owner resumed the program"
    return action, launch


def reserved(chain, launch) -> dict:
    """The child reserves the ONE cycle bound to that launch (a fault first rolls the reservation back whole)."""
    faulted(chain, BUCKET_PROGRAMS, chain.child(launch).reserve_cycle, PROGRAM, REPOSITORY)
    result = chain.child(launch).reserve_cycle(PROGRAM, REPOSITORY)
    cycle = result["cycle"]
    attempts = dc.research_attempts(list(chain.world.intents().values()), chain.research)
    assert [a["job"] for a in attempts] == chain.pair
    assert cycle["id"] == PROGRAM + ":001" and cycle["owner"] == launch
    assert cycle["attempt_scope_target"] == {"scope": chain.scope, "intent_id": chain.research["id"],
                                             "attempts_sha256": digest(attempts)}
    return cycle


def claimed(chain, launch, cycle) -> dict:
    """Collection claims exactly the pair, with attractive leads waiting (a fault first rolls it back whole)."""
    items = [dict(item) for item in LEADS]
    faulted(chain, BUCKET_PROGRAMS, chain.child(launch).record_collection, cycle["id"], launch, {}, items, COUNTS)
    assert chain.scope_claims() == [] and chain.adoptions() == 0
    recorded = chain.child(launch).record_collection(cycle["id"], launch, {}, items, COUNTS)
    assert recorded["candidate"]["id"] == "as-" + chain.research["id"]
    assert recorded["cycle"]["attempt_scope"]["claimed"] == chain.scope
    [row] = chain.scope_claims()
    attempts = dc.research_attempts(list(chain.world.intents().values()), chain.research)
    assert row["id"] == row["investigation"] == chain.scope and row["program"] == PROGRAM
    assert row["cycle"] == cycle["id"] and row["state"] == "claimed"
    assert row["job_ids"] == chain.pair and row["job_ids_total"] == 2 and row["job_ids_sha256"] == digest(chain.pair)
    assert row["scope"] == {"schema": "urn:zeus:research-attempt-scope:1", "intent_id": chain.research["id"],
                            "continuation_policy": "policy-1", "policy_sha256": chain.source["continuation_policy_sha256"],
                            "family": chain.root, "family_investigation": family_id(*chain.cause),
                            "attempts": attempts, "attempts_sha256": digest(attempts)}
    assert not set(HISTORICAL) & set(row["job_ids"]) and Q1 not in canonical(row), "no historical member captured"
    leads = [c for c in chain.child(launch).candidates(PROGRAM) if c["source"] != "investigation"]
    assert len(leads) == 2 and all(c["claimed_cycle"] is None for c in leads), "leads are discovery only"
    assert chain.adoptions() == 1
    return row


def council(chain, launch, cycle, result="accepted") -> None:
    """The stubbed council: a start bound to its run and manifest, the council's synthetic run row, the result."""
    child, run_id = chain.child(launch), PROGRAM + ".c001"
    child.record_capture(cycle["id"], launch, {"revision": "c" * 40, "ref": "refs/zeus/research/scope",
                                               "path": "docs/research/scope.json", "sha256": "e" * 64})
    inert(chain, child.record_capture, cycle["id"], launch, {"revision": "c" * 40}, refuses="cycle_state_changed")
    owner_idle(chain)
    child.record_council_start(cycle["id"], launch, run_id, "d" * 64, "sha256:" + "e" * 64)
    inert(chain, child.record_council_start, cycle["id"], launch, run_id, "d" * 64, "sha256:" + "e" * 64,
          refuses="cycle_state_changed")
    owner_idle(chain)
    [row] = chain.scope_claims()
    assert (row["state"], row["run_id"], row["manifest_sha256"]) == ("dispatched", run_id, "d" * 64)
    with chain.world.control.transaction() as tx:    # LABELLED: the row the council's promotion would write
        tx.put("autonomous_runs", run_id, {"id": run_id, "status": result, "stage": "promotion",
                                           "manifest_sha256": "d" * 64, "reason_code": "fixture_" + result})
    verdict = {"result": result, "reason_code": "fixture", "row_status": result}
    faulted(chain, BUCKET_PROGRAMS, child.record_council_result, cycle["id"], launch, verdict)
    assert chain.scope_claims()[0]["state"] == "dispatched", "the fault left the claim unresolved, not half-written"
    child.record_council_result(cycle["id"], launch, verdict)
    inert(chain, child.record_council_result, cycle["id"], launch, verdict, refuses="cycle_state_changed")


# ===== U2B-16 + U2B-6: the whole chain, restarts at every stage, one write spy ================================
def test_the_stubbed_owner_to_receipt_chain_claims_the_held_pair_once_consumes_it_once_and_leaves_history(tmp_path):
    chain = Chain(tmp_path)
    world, control = chain.world, chain.world.control
    history = chain.history()
    shape = Counter(bucket for bucket, _ in history)
    assert [shape[b] for b in (*LINEAGE, BUCKET_PROGRAMS, BUCKET_INVESTIGATIONS, BUCKET_BINDINGS, "fleet_jobs")] == \
        [4, 1, 2, 1, 15, 1, 23, 23], "P1: 4 dispatches, recovery, 2 successors, head, 15 programs, 21 + 2 members"
    assert get(control, BUCKET_INVESTIGATIONS, family_id(*chain.cause))["job_ids"] == sorted(HISTORICAL + chain.pair)

    # F4: one owed research_dispatch, its persisted launch binding, the child started once.
    action, launch = launched(chain)
    owner_idle(chain)

    # The child's cycle, reserved under that launch; restarts find the owned cycle busy.
    cycle = reserved(chain, launch)
    inert(chain, chain.child(launch).reserve_cycle, PROGRAM, REPOSITORY, returns={"reserved": False, "reason": "busy"})
    inert(chain, chain.child("0" * 32).reserve_cycle, PROGRAM, REPOSITORY, returns={"reserved": False, "reason": "busy"})
    owner_idle(chain)

    # F5S: exactly the pair; a repeated or restarted collection is refused and claims nothing more.
    claimed(chain, launch, cycle)
    inert(chain, chain.child(launch).record_collection, cycle["id"], launch, {}, [], COUNTS,
          refuses="cycle_state_changed")
    inert(chain, chain.child(launch).reserve_cycle, PROGRAM, REPOSITORY, returns={"reserved": False, "reason": "busy"})
    owner_idle(chain)

    # The stubbed council: start and ACCEPTED result, each repeat refused, each commit fault rolled back whole.
    council(chain, launch, cycle)
    [row] = chain.scope_claims()
    assert (row["state"], row["result"], row["reported_result"]) == ("resolved", "accepted", "accepted")
    # A restarted child under the same launch can never open a second cycle: the owner target binds the launch's
    # expected cycle, so once due it refuses before reserving (INV-RESEARCH-ATTEMPT-SCOPE-001).
    later = ResearchProgram(control, clock=Clock("2026-09-28T02:00:00+00:00"), token=lambda: launch)
    inert(chain, later.reserve_cycle, PROGRAM, REPOSITORY, refuses="attempt_scope_target_unavailable")
    inert(chain, chain.child(launch).reserve_cycle, PROGRAM, REPOSITORY,
          returns={"reserved": False, "reason": "not_due"})

    # The child exits. The owner outcome is completed; the owner's receipt path assesses (LABELLED assessor),
    # assembles and invokes `accept_research`; a fault in the receipt writer leaves no receipt and is replayed.
    chain.port.finish(launch)
    chain.spy.fail_on(BUCKET_RESEARCH_RECEIPTS)
    ticks = [chain.owner.tick(OWNERS) for _ in range(5)]
    assert chain.spy.armed is None and chain.spy.aborted[-1] == [], "the receipt write faulted before any put"
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    assert (dispatch["state"], dispatch["reason_code"]) == (do.COMPLETED, "research_dispatch_accepted")
    [receipt_action] = chain.actions(do.RESEARCH_RECEIPT)
    assert [t["waits"] for t in ticks].count({receipt_action["id"]: "RuntimeError"}) == 1
    assert (receipt_action["state"], receipt_action["reason_code"]) == (do.COMPLETED, "research_receipt_accepted")
    assert receipt_action["binding"]["investigation"] == chain.scope and receipt_action["receipt"]["schema"] == \
        dc.RESEARCH_RECEIPT_SCHEMA and receipt_action["accepted"]["coverage"] == dc.COVERAGE_ORIGINAL
    [stored] = scan(control, BUCKET_RESEARCH_RECEIPTS)
    receipt = stored["receipt"]
    assert stored["id"] == chain.research["id"] and stored["coverage"] == "original_capture"
    assert receipt == receipt_action["receipt"] and receipt["investigation"] == chain.scope
    assert [a["job"] for a in receipt["attempts"]] == chain.pair
    assert receipt["dispatch"] == {k: row[k] for k in ("program", "run_id", "manifest_sha256", "snapshot_sha256")}
    assert len(chain.assessor.starts) == 1 and len(chain.port.starts) == 1
    owner_idle(chain)
    inert(chain, world.controller.accept_research, receipt, returns={"accepted": True, "cached": True,
                                                                     "coverage": "original_capture"})
    assert world.intents()[chain.research["id"]]["state"] == dc.RESEARCH_REQUIRED, "acceptance moves nothing"

    # F7S: the continuation tick consumes R once (a fault on its compare-and-swap first leaves R held).
    held = get(control, BUCKET_INTENTS, chain.research["id"])
    chain.spy.fail_on(BUCKET_INTENTS)
    faulted_tick = world.tick()
    assert chain.spy.armed is None and {"subject": chain.research["id"], "reason_code": "unavailable",
                                        "error_type": "RuntimeError"} in faulted_tick["skipped"]
    assert get(control, BUCKET_INTENTS, chain.research["id"]) == held
    consumed = world.tick()
    assert {"subject": chain.research["id"], "effect": "research_resolved", "route": dc.RESEARCH} in consumed["actions"]
    done = world.intents()[chain.research["id"]]
    assert done["state"] == dc.COMPLETED and done["research_coverage"] == "original_capture"
    assert done["research_receipt"] == stored["receipt_sha256"] and done["reason_code"] == "research_receipt_accepted"
    repair = only(world.intents(), origin_job=chain.successor, route=dc.EVIDENCE_REPAIR)
    jobs, intents = world.jobs(), world.intents()
    for again in (world.tick(), world.tick(controller=world.build())):
        assert again["actions"] == [] or all(a.get("effect") != "research_resolved" for a in again["actions"])
    assert world.jobs() == jobs and world.intents() == intents, "no second consumption, successor or intent"
    assert [h["state"] for h in world.intents()[chain.research["id"]]["history"]].count(dc.COMPLETED) == 1
    owner_idle(chain)

    # U2B-6: every committed write is one of the chain's own lifecycle rows; history keeps its canonical bytes.
    written = set(chain.spy.committed)
    assert {key for key in written if key in chain.before} == chain.own()
    leads = {(BUCKET_CANDIDATES, PROGRAM + ":" + c["id"]) for c in chain.child(launch).candidates(PROGRAM)
             if c["source"] != "investigation"}
    [decision] = [d["id"] for d in scan(control, "decisions_pending") if d.get("phase") == do.OWNER_PHASE]
    assert {key for key in written if key not in chain.before} == {
        (BUCKET_ACTIONS, action["id"]), (BUCKET_ACTIONS, receipt_action["id"]), ("decisions_pending", decision),
        (BUCKET_CYCLES, cycle["id"]), (BUCKET_CANDIDATES, PROGRAM + ":as-" + chain.research["id"]), *leads,
        (BUCKET_DISPATCHES, chain.scope), ("autonomous_runs", PROGRAM + ".c001"),
        (BUCKET_RESEARCH_RECEIPTS, chain.research["id"]),
        # The consumption's own successor: the evidence-repair intent, its Fleet job and inherited binding.
        (BUCKET_INTENTS, repair["id"]), ("fleet_jobs", repair["successor_job"]),
        (BUCKET_BINDINGS, repair["successor_job"])}
    assert not written & set(history), "no historical lineage, Portfolio, binding or Fleet row was ever put"
    after = rows(control)
    assert {key: after.get(key) for key in history} == history, "every pre-existing row keeps its canonical bytes"
    assert [k for k in after if k[0] in LINEAGE and k not in history] == [(BUCKET_DISPATCHES, chain.scope)]


# ===== U2B-16 R: a failure after the claim keeps the scope claimed and final ==================================
def second_program(chain, program_id="rp-scope-2") -> ResearchProgram:
    """Another opted-in program with its OWN bound owner launch for R (LABELLED: the launch row is written
    through the owner's row constructors, as the program-layer tests do), registered and resumed."""
    token = bound_launch(chain.world.control, program=program_id, intent_id=chain.research["id"], jobs=chain.pair,
                         family=chain.root)
    cfg = validate_config(config("a" * 40, id=program_id, attempt_scope_source=dict(chain.source)), POLICY)
    programs = ResearchProgram(chain.world.control, clock=Clock(NOW), token=lambda: token)
    programs.register(cfg, REPOSITORY, [])
    programs.resume(program_id)
    return programs


# Per failure after the claim: the claim row's (state, result), the owner outcome, the program state, what a
# restarted child's reservation answers, the second program's selection reason and the scope receipt's refusal.
# `child_lost`: the child exits after the council start without closing its cycle (it keeps the cycle owned).
POST_CLAIM = {
    "capture": (("resolved", "failed"), (do.REJECTED, "research_cycle_failed"), "blocked", "program_blocked",
                "attempt_scope_target_ineligible", "research_receipt_invalid"),
    "council_start": (("resolved", "failed"), (do.REJECTED, "research_cycle_failed"), "blocked", "program_blocked",
                      "attempt_scope_target_ineligible", "research_not_accepted"),
    "child_lost": (("dispatched", None), (do.UNKNOWN, "research_cycle_unfinished"), "active", "busy",
                   "attempt_scope_target_ineligible", "research_unfinished"),
}


@pytest.mark.parametrize("stage", sorted(POST_CLAIM))
def test_a_failure_after_the_claim_keeps_the_claim_final_and_nothing_is_released_or_retried(tmp_path, stage):
    claim, outcome, state, restart, selection, scope_refusal = POST_CLAIM[stage]
    chain = Chain(tmp_path)
    world, control = chain.world, chain.world.control
    history = chain.history()
    action, launch = launched(chain)
    cycle = reserved(chain, launch)
    claimed(chain, launch, cycle)
    child = chain.child(launch)
    capture = {"revision": "c" * 40, "ref": "refs/zeus/research/scope", "path": "docs/research/scope.json"}
    if stage == "capture":
        # LABELLED injected fault AFTER the claim committed: the capture record itself cannot be written.
        faulted(chain, BUCKET_CYCLES, child.record_capture, cycle["id"], launch, capture)
        [row] = chain.scope_claims()
        assert row["state"] == "claimed" and row["job_ids"] == chain.pair and chain.adoptions() == 1, \
            "a failure after the commit keeps the claim: nothing is released"
        child.fail_cycle(cycle["id"], launch, "capture", "capture_failed")
    else:
        child.record_capture(cycle["id"], launch, capture)
        child.record_council_start(cycle["id"], launch, PROGRAM + ".c001", "d" * 64, "sha256:" + "e" * 64)
        if stage == "council_start":
            child.fail_cycle(cycle["id"], launch, "council_start", "publication_incomplete")
    [row] = chain.scope_claims()
    assert (row["state"], row["result"]) == claim and row["job_ids"] == chain.pair
    final = canonical(row)
    program = get(control, BUCKET_PROGRAMS, PROGRAM)
    assert program["state"] == state and program["adoptions"] == 1

    # The owner reads its launch's outcome; it never owes a second dispatch, launch or receipt, and the claimed
    # scope never falls back to a historical family dispatch.
    chain.port.finish(launch)
    ticked = chain.owner.tick(OWNERS)
    [dispatch] = chain.actions(do.RESEARCH_DISPATCH)
    assert (dispatch["state"], dispatch["reason_code"]) == outcome
    assert ticked["waits"] == {chain.research["id"]: "research_dispatch_pending"} and ticked["created"] == []
    owner_idle(chain)
    assert chain.actions(do.RESEARCH_RECEIPT) == [] and len(chain.port.starts) == 1
    inert(chain, child.reserve_cycle, PROGRAM, REPOSITORY, returns={"reserved": False, "reason": restart})

    # Final ownership (INV-RESEARCH-ATTEMPT-SCOPE-001: scoped failure is final, members are never released):
    # another scoped program on its own bound launch finds the scope claimed and adopts nothing.
    other = second_program(chain)
    again = other.reserve_cycle("rp-scope-2", REPOSITORY)["cycle"]
    retried = other.record_collection(again["id"], again["owner"], {}, [dict(item) for item in LEADS], COUNTS)
    assert retried["candidate"] is None and retried["cycle"]["attempt_scope"]["counts"]["claimed"] == 1
    assert retried["cycle"]["selection"]["reason"] == selection
    assert get(control, BUCKET_PROGRAMS, "rp-scope-2")["adoptions"] == 0

    # No receipt can cover R: not the failed or unfinished scope, and not a family receipt of the historical head
    # (refused because the scope claim exists, whatever that head says).
    head = get(control, BUCKET_HEADS, family_id(*chain.cause))
    documents = {"scope": receipt_for(world, chain.research, chain.scope, row),
                 "family": receipt_for(world, chain.research, family_id(*chain.cause),
                                       get(control, BUCKET_DISPATCHES, head["dispatch"]))}
    for name, document in documents.items():
        mark = chain.spy.mark()
        with pytest.raises(dc.ContinuationRefused) as info:
            world.controller.accept_research(document)
        assert info.value.reason_code == {"scope": scope_refusal, "family": "research_scope_claimed"}[name], name
        assert chain.spy.since(mark) == [], name + " wrote something"
    world.tick()
    assert world.intents()[chain.research["id"]]["state"] == dc.RESEARCH_REQUIRED
    assert scan(control, BUCKET_RESEARCH_RECEIPTS) == []

    # The final claim's bytes, and every historical row, are exactly as they were.
    assert canonical(get(control, BUCKET_DISPATCHES, chain.scope)) == final
    assert [d["id"] for d in chain.scope_claims()] == [chain.scope]
    assert not set(chain.spy.committed) & set(history)
    after = rows(control)
    assert {key: after.get(key) for key in history} == history
