"""Shared S6 scenario steps (`coordination.owner_actions_research`): the M7 `OwnerActions` scheduler and its two
research families (DESIGN-s6 §7; TRACE-s6 §9), in the sequences of the M7 tests (tests/test_owner_actions.py,
tests/test_owner_actions_recovery.py T3-*).

- **scheduler.** `register` (cached replay, conflicting pin or content, invalid documents), `status` projections, and
  `tick`: an unregistered policy, a registered policy under a changed pin (`policy_changed`), a disabled one, a missing
  continuation policy, a delivery target mismatch, an idle tick (nothing written, no port called), an absent research
  block and an absent research port.
- **G1** (flow `held`, kind `research_receipt`). The accepted assessment assembles the exact receipt and the continuation
  tick releases the hold once; a rejected or blocked assessment is a named terminal state; an unfinished assessment is
  relaunched at most once, then unknown; a guardian that never spawned is relaunched once under a new launch identity; a
  lost start response after the decision is recognized; a restarted coordinator resumes after the model and after the
  receipt with no second call; an executed exact-binding decision is reused (and the pure reuse rules); a changed attempt
  refuses the stale action; no accepted research yet is a named wait; a success persisted before the launch exits
  completes only after the proof; an unproven cleanup or settlement after a verdict is a named unknown.
- **C3** (flow `research_paused`, owner policy v2 with the research block, kind `research_dispatch`). The provider
  unavailable refuses before any resume, reservation or spawn; the probe ok resumes the program, persists the launch id
  before the start and starts once; later ticks only poll; a collection-only cycle is `research_cycle_empty`; a foreign
  cycle is never ours; a launch that never entered is relaunched once, then unknown; an owned crashed cycle keeps the
  program busy; every other outcome shape of `research_outcome`; every row of the ported RO-1 decision table, from the
  recorded state and through the tick; discovery is idempotent across restarts and a second coordinator.

Layer: harness (never shipped)

The starting states are the RECORDED, labelled rows of `compare/fixtures/s6/research.json` (flows `held` and
`research_paused`), loaded by `s6_research.load` (extended here by subclassing). `api` is the `s6_research` API plus
`OwnerActions(store, **ports)`, `organization()`, `canonical` and `owner_domain` (the M7 `domain.owner_actions` names). The
doubles are LABELLED and never a real call: `Assessor` (M7 `tests/test_owner_actions.py::FakeAssessor`: `context`,
`document`, `start`, `decide`, `poll`, with `verdict`, `spawn_fails`, `lost`; `decide` writes the decision row and an
execution receipt the way the executor commits them; artifact puts go through the labelled evidence port),
`Research` (the probe/start/poll shapes of `tests/test_owner_actions_recovery.py::InProcessResearch`; it never runs a
ProgramRunner, since the research application code moves in S8: `start` only records what the store showed at that
moment) and the ledger, the counts of `tests/test_research_program_fixtures.py::FakeBudget().counts()` as a dict. Where a
case needs the child's own cycle rows they are LABELLED rows of the shapes `ResearchProgram.reserve_cycle` (a cycle with
status `collecting` and its owner token, `active_cycle` and `next_cycle` on the program row) and `complete_cycle`/`_close`
(status `completed` or `failed`, `finished_at`, `cycles` counted, `active_cycle` cleared, `last_tick_at`) write, and the
dispatch claim row of the shape the recorded `held` flow holds. The compared results are the ticks' receipts, the
owner-action rows, the decision rows, the stored receipts, what each double saw, and the digests of both stores.
"""

from __future__ import annotations

import copy
import hashlib

import s6_research as R
from s6_tick import call, canonical_digest, records

PIN = {"revision": "e" * 40, "path": "ops/owner-actions.json", "sha256": "d" * 64, "lane": "a"}
POLICIES, ACTIONS, DECISIONS = "owner_action_policies", "owner_actions", "decisions_pending"
PROGRAMS, CYCLES, DISPATCHES = "research_programs", "research_program_cycles", R.DISPATCHES
PROGRAM = "rp-b2"
RESEARCH_BLOCK = {"enabled": True, "program_id": PROGRAM, "lane": "a"}
FAMILY_ROW = "aab8c6d6d16bbfa008306c149b180badc63918ee202f2b74479ad210824e0be8"
# The counts of `FakeBudget().counts()` (tests/test_research_program_fixtures.py): a LABELLED synthetic reading.
LEDGER = {"host": "fixture", "this_host": 0, "all_hosts": 0, "unreadable": 0}
REPORT = "LABELLED fixture accepted research report text for the assessor (not a real report)\n"
COMPLETED_CYCLE, FAILED_CYCLE, COLLECTING = "completed", "failed", "collecting"


# ---- the labelled doubles ---------------------------------------------------------------------------------
class Artifacts:
    """LABELLED trusted artifact store: `put(text, kind)` holds the text in the evidence port under its digest."""

    def __init__(self, evidence):
        self.evidence, self.kinds = evidence, []

    def put(self, text, kind):
        self.kinds.append(kind)
        return {"ref": self.evidence.put(text)}


class Assessor:
    """LABELLED assessment port (M7 FakeAssessor). `verdict` is what the guarded decision commits when a launch runs:
    True / False (accepted / rejected), "blocked", "retry" (a failed attempt left for the executor's retry budget) or None
    (the launch keeps running). `spawn_fails` raises before any guardian exists; `lost` spawns and decides but loses the
    start response."""

    def __init__(self, world, verdict=True, *, spawn_fails=0, lost=False):
        self.world, self.verdict, self.spawn_fails, self.lost = world, verdict, spawn_fails, lost
        self.starts, self.launches, self.contexts, self.documents, self.polls = [], {}, 0, [], 0

    def context(self, binding, found):
        self.contexts += 1
        return {"report": REPORT, "report_digest": hashlib.sha256(REPORT.encode()).hexdigest(), "evidence_refs": [],
                "members": found["members"]}

    def document(self, document):
        self.documents.append(document)
        return self.world.artifacts.put(self.world.api.canonical(document), "owner-assessment")["ref"]

    def start(self, launch, decision_id, correlation_id):
        if self.spawn_fails:
            self.spawn_fails -= 1
            raise OSError("guardian could not be spawned (labelled injected fault)")
        self.starts.append((launch, decision_id))
        self.launches[launch] = "running"
        if self.verdict is not None:
            self.decide(decision_id)
            self.launches[launch] = "exited"
        if self.lost:
            self.lost = False
            raise TimeoutError("start response lost after the guardian decided (labelled injected fault)")
        return {"pid": 4242}

    def decide(self, decision_id, verdict=None):
        verdict = self.verdict if verdict is None else verdict
        ref = self.world.artifacts.put("LABELLED fixture assessor execution receipt " + decision_id,
                                       "owner-assessment-execution")["ref"]
        with self.world.control.transaction() as tx:
            row = tx.get(DECISIONS, decision_id)
            if verdict == "retry":
                row.update(status="retry", attempt=1, error="labelled injected provider failure")
            elif verdict == "blocked":
                row.update(status="blocked", attempt=1, result={"accepted": False, "blocked": True,
                                                                "execution_ref": ref, "reason": "blocked"})
            else:
                row.update(status="succeeded", attempt=1, result={"accepted": verdict, "execution_ref": ref,
                                                                  "reason": "labelled fixture verdict"})
            tx.put(DECISIONS, decision_id, row)

    def poll(self, launch):
        # The launch directory's observation shapes; `exit_code` is the assess child's own exit (0 only when it owned
        # the claim and settled every call reservation).
        self.polls += 1
        state = self.launches.get(launch)
        if state is None:
            return {"state": "absent", "owned": False, "proof": {"kind": "fenced"}}
        if state == "running":
            return {"state": "running", "owned": True}
        if state == "unknown":
            return {"state": "unknown", "owned": False, "exit_code": None, "cleanup_confirmed": False}
        if state == "timeout":
            return {"state": "timeout", "owned": False, "exit_code": None, "cleanup_confirmed": True}
        return {"state": "exited", "owned": False, "exit_code": 1 if state == "unsettled" else 0,
                "cleanup_confirmed": True}

    def seen(self):
        return {"contexts": self.contexts, "starts": [list(s) for s in self.starts], "documents": len(self.documents),
                "polls": self.polls}


class Research:
    """LABELLED research launch port. `probe` answers `ok` (or a refusal); `start` NEVER runs a program tick (the
    research application code moves in S8): it records the launch and what the store showed at that moment (the owner
    action's state and launch id, the program state); `poll` answers in the guardian's observation shapes."""

    def __init__(self, world, *, ok=True):
        self.world, self.ok = world, ok
        self.starts, self.launches, self.probes, self.polls, self.seen_at_start = [], {}, 0, 0, []

    def probe(self):
        self.probes += 1
        return {"ok": self.ok, "reason_code": None if self.ok else "codex_unresolved", "codex": None, "node": None}

    def start(self, launch, program_id, lane):
        if launch in self.launches:
            return {"cached": True}
        self.starts.append(launch)
        self.launches[launch] = "running"
        rows = [a for a in R.scan(self.world.control, ACTIONS).values() if a.get("kind") == "research_dispatch"]
        program = R.get(self.world.control, PROGRAMS, program_id)
        self.seen_at_start.append({
            "launch": launch, "program": program_id, "lane": lane,
            "action_states": sorted([a["state"], a.get("launch_id") == launch] for a in rows),
            "program_state": (program or {}).get("state"), "active_cycle": (program or {}).get("active_cycle")})
        return {"cached": False, "pid": 4242}

    def poll(self, launch):
        self.polls += 1
        state = self.launches.get(launch)
        if state is None:
            return {"state": "absent", "owned": False, "proof": {"kind": "fenced"}}
        if state == "running":
            return {"state": "running", "owned": True}
        if state == "unknown":
            return {"state": "unknown", "owned": False, "cleanup_confirmed": False}
        return {"state": "exited", "owned": False, "exit_code": 0, "cleanup_confirmed": True}

    def seen(self):
        return {"probes": self.probes, "starts": list(self.starts), "polls": self.polls,
                "seen_at_start": copy.deepcopy(self.seen_at_start)}


class CrashOnAccept:
    """LABELLED injected fault: the process dies right after the receipt was persisted (the existing API never answers)."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def policy(self, policy_id):
        return self.inner.policy(policy_id)

    def research_facts(self, document):
        return self.inner.research_facts(document)

    def accept_research(self, document):
        self.calls += 1
        raise RuntimeError("coordinator crashed before the existing API answered (injected)")


# ---- the world ---------------------------------------------------------------------------------------------
class OWorld(R.RWorld):
    """`s6_research.RWorld` plus the labelled artifact store, assessor and research launcher, and one `OwnerActions`
    over the same control store."""

    def __init__(self, api, flow, *, verdict=True, spawn_fails=0, lost=False, probe_ok=True, ledger=None):
        super().__init__(api, flow)
        self.artifacts = Artifacts(self.evidence)
        self.assessor = Assessor(self, verdict, spawn_fails=spawn_fails, lost=lost)
        self.research = Research(self, ok=probe_ok)
        self.ledger = ledger or (lambda: dict(LEDGER))
        self.owner = self.owners()

    def owners(self, **ports):
        ports = {"continuation": self.controller, "org": self.api.organization(), "lanes": self.lanes,
                 "assessments": self.assessor, "research": self.research, "ledger": self.ledger,
                 "artifacts": self.artifacts, "clock": self.clock, **ports}
        return self.api.OwnerActions(self.control, **ports)

    def owner_tick(self, owner=None, policy="owners-1", **kwargs):
        return (owner or self.owner).tick(policy, **kwargs)

    def snapshot(self):
        return {"control": canonical_digest(records(self.control)), "lane": canonical_digest(records(self.lane_store))}


def load(api, flow, **options):
    return OWorld(api, flow, **options)


# ---- documents ---------------------------------------------------------------------------------------------
def policy_v1(api, **overrides):
    """The version-1 owner policy of `tests/test_owner_actions.py::owner_policy`."""
    return {"schema": api.owner_domain.POLICY_SCHEMA, "id": "owners-1", "enabled": True, "continuation_policy": "policy-1",
            "assessment": {"model_label": "labelled-fixture-assessor"},
            "delivery": {"target_id": "fleet-host", "repository": "github:zeus-owner/zeus-harness",
                         "required_checks": ["ci / required"], "canary_check_id": "startup_identity",
                         "ci_timeout_seconds": 300, "consumption_timeout_seconds": 120},
            "canary": None, **overrides}


def policy_v2(api, *, research=RESEARCH_BLOCK, policy_id="owners-002", **overrides):
    """The version-2 owner policy of `tests/test_owner_actions_recovery.py::owner_policy` (requalification enabled)."""
    document = policy_v1(api, id=policy_id, schema=api.owner_domain.POLICY_SCHEMA_V2, **overrides)
    document["requalification"] = {"enabled": True, "reasons": ["reviewed_base_moved"], "max_per_family": 1}
    document["research"] = research
    return document


def registered(world, document=None, owner=None, pin=None):
    owner = owner or world.owner
    owner.register(document or policy_v1(world.api), pin or PIN)
    return owner


# ---- reading ----------------------------------------------------------------------------------------------
def owner_rows(world):
    return sorted(R.scan(world.control, ACTIONS).values(), key=lambda r: (str(r.get("created_at")), r["id"]))


def only_action(world):
    rows = owner_rows(world)
    assert len(rows) == 1, rows
    return rows[0]


def decisions(world):
    return [row for row in R.scan(world.control, DECISIONS).values() if row.get("phase") == world.api.owner_domain.OWNER_PHASE]


def stored_receipts(world):
    return {k: {"receipt_sha256": v.get("receipt_sha256"), "coverage": v.get("coverage"),
                "evidence_refs": (v.get("receipt") or {}).get("evidence_refs")}
            for k, v in sorted(R.scan(world.control, R.RECEIPTS).items())}


def brief(row):
    keys = ("id", "kind", "state", "reason_code", "version", "launches", "launch_id", "decision_id", "verdict", "decided",
            "reused", "assessment_ref", "receipt_sha256", "accepted", "outcome", "probe", "child_lane", "execution_ref",
            "subject", "policy_id")
    return {k: row.get(k) for k in keys if row.get(k) is not None}


def shot(world):
    """Owner actions (brief), decision rows, stored receipts, the research intent's state and what each double saw."""
    return {"actions": [brief(r) for r in owner_rows(world)],
            "decisions": [{"id": d["id"], "status": d["status"], "attempt": d.get("attempt")} for d in decisions(world)],
            "receipts": stored_receipts(world), "research_intent": R.intents(world).get(
                world.ids["research_intent"], {}).get("state"),
            "assessor": world.assessor.seen(), "research": world.research.seen()}


def settle(owner, ticks=6, policy="owners-1"):
    return [owner.tick(policy) for _ in range(ticks)]


def unchanged(world, fn):
    """Run `fn`; report whether it left both stores' records identical."""
    before = world.snapshot()
    out = fn()
    return out, before == world.snapshot()


def program_row(world, program_id=PROGRAM):
    return R.get(world.control, PROGRAMS, program_id)


# ---- scheduler ----------------------------------------------------------------------------------------------
def scheduler(api) -> dict:
    out = {}
    world = load(api, "research_paused")
    # unregistered: a receipt, nothing written, no port called
    result, same = unchanged(world, lambda: call(world.owner_tick))
    out["unregistered"] = {"tick": result, "records_unchanged": same, "seen": shot(world)}
    # disabled
    world = load(api, "research_paused")
    out["disabled_register"] = call(world.owner.register, policy_v1(api, enabled=False), PIN)
    result, same = unchanged(world, lambda: call(world.owner_tick))
    out["disabled"] = {"tick": result, "records_unchanged": same, "seen": shot(world)}
    # a registered policy under a changed pin, and the matching pin
    world = load(api, "research_paused")
    registered(world)
    result, same = unchanged(world, lambda: call(world.owner_tick, pin_sha256="0" * 64))
    out["policy_changed"] = {"tick": result, "records_unchanged": same}
    out["pin_matches"] = call(world.owner_tick, pin_sha256=PIN["sha256"])
    # the continuation policy missing (unregistered id, and no continuation port)
    world = load(api, "research_paused")
    world.owner.register(policy_v1(api, continuation_policy="policy-9"), PIN)
    result, same = unchanged(world, lambda: call(world.owner_tick))
    out["continuation_policy_missing"] = {"tick": result, "records_unchanged": same}
    world = load(api, "research_paused")
    registered(world, owner=world.owners(continuation=None))
    out["continuation_port_absent"] = call(world.owner_tick, world.owners(continuation=None))
    # a delivery target mismatch
    world = load(api, "research_paused")
    document = policy_v1(api, id="owners-2", delivery={**policy_v1(api)["delivery"], "target_id": "elsewhere"})
    world.owner.register(document, PIN)
    result, same = unchanged(world, lambda: call(world.owner_tick, policy="owners-2"))
    out["delivery_target_mismatch"] = {"tick": result, "records_unchanged": same}
    # an idle tick writes nothing and calls no port
    world = load(api, "research_paused")
    registered(world)
    result, same = unchanged(world, lambda: call(world.owner_tick))
    out["idle"] = {"tick": result, "records_unchanged": same, "seen": shot(world)}
    result, same = unchanged(world, lambda: [call(world.owner_tick) for _ in range(3)])
    out["idle_again"] = {"ticks": result, "records_unchanged": same, "seen": shot(world)}
    # a v2 policy without its research block, and with the block but no research port
    world = load(api, "research_paused")
    world.owner.register(policy_v2(api, research=None), PIN)
    result, same = unchanged(world, lambda: call(world.owner_tick, policy="owners-002"))
    out["research_block_absent"] = {"tick": result, "records_unchanged": same, "seen": shot(world)}
    world = load(api, "research_paused")
    portless = world.owners(research=None)
    portless.register(policy_v2(api), PIN)
    result, same = unchanged(world, lambda: call(world.owner_tick, portless, policy="owners-002"))
    out["research_port_absent"] = {"tick": result, "records_unchanged": same, "seen": shot(world)}
    out["register"] = register(api)
    out["status"] = status(api)
    return out


def register(api) -> dict:
    out = {}
    world = load(api, "research_paused")
    document = policy_v1(api)
    out["first"] = call(world.owner.register, document, PIN)
    stored = R.get(world.control, POLICIES, "owners-1")
    out["stored"] = {"policy_sha256": stored["policy_sha256"], "pin": stored["pin"], "policy": stored["policy"]}
    before = world.snapshot()
    out["replay"] = call(world.owner.register, document, PIN)
    out["replay_second_coordinator"] = call(world.owners().register, document, PIN)
    out["replay_unchanged"] = before == world.snapshot()
    out["other_pin"] = call(world.owner.register, document, {**PIN, "sha256": "c" * 64})
    out["other_content"] = call(world.owner.register, policy_v1(api, enabled=False), PIN)
    out["conflicts_unchanged"] = before == world.snapshot()
    out["v2"] = call(world.owner.register, policy_v2(api), PIN)
    v2 = R.get(world.control, POLICIES, "owners-002")
    out["v2_stored"] = v2["policy"]
    invalid = {
        "schema_unknown": {"schema": "urn:zeus:owner-actions:9"},
        "extra_field": {"extra": True},
        "v1_with_research": {"research": None},
        "enabled_not_bool": {"enabled": 1},
        "no_continuation": {"continuation_policy": ""},
    }
    bad = {}
    for name, change in invalid.items():
        bad[name] = call(world.owner.register, {**policy_v1(api), **change}, PIN)
    for name, change in {
            "research_program_path": {"research": {"enabled": True, "program_id": "../x", "lane": "a"}},
            "research_lane_missing": {"research": {"enabled": True, "program_id": PROGRAM}},
            "requalification_reason": {"requalification": {"enabled": True, "reasons": ["merged_tree_mismatch"],
                                                          "max_per_family": 1}},
            "requalification_cap": {"requalification": {"enabled": True, "reasons": ["reviewed_base_moved"],
                                                       "max_per_family": 4}}}.items():
        bad[name] = call(world.owner.register, {**policy_v2(api, policy_id="owners-3"), **change}, PIN)
    out["invalid"] = bad
    out["registered_after_invalid"] = sorted(R.scan(world.control, POLICIES))
    return out


def status(api) -> dict:
    out = {}
    world = load(api, "held", verdict=False)
    out["before_policy"] = call(world.owner.status)
    registered(world)
    out["registered"] = call(world.owner.status)
    world.owner.tick("owners-1")
    out["assessing"] = call(world.owner.status, "owners-1")
    settle(world.owner, 4)
    out["rejected"] = call(world.owner.status, "owners-1")
    out["all"] = call(world.owner.status)
    out["unknown_policy"] = call(world.owner.status, "owners-9")
    world = load(api, "held")
    registered(world)
    world.owner.tick("owners-1")
    settle(world.owner, 4)
    out["completed"] = call(world.owner.status, "owners-1")
    world.tick()
    out["after_continuation"] = call(world.owner.status, "owners-1")
    before = world.snapshot()
    call(world.owner.status)
    out["status_writes_nothing"] = before == world.snapshot()
    return out


# ---- G1: scoped research acceptance (flow held) -----------------------------------------------------------------
def accepted(api) -> dict:
    world = load(api, "held")
    research_id = world.ids["research_intent"]
    before_rows = R.research_rows(world)
    old_jobs = R.jobs(world)
    owner = registered(world)
    out = {"start": R.view(world)}
    out["ticks"] = settle(owner)
    action = only_action(world)
    out["action"] = action
    out["decision"] = decisions(world)
    out["stored_receipt"] = R.scan(world.control, R.RECEIPTS)[research_id]
    out["receipt_from_action"] = out["stored_receipt"]["receipt"] == action["receipt"]
    out["intent_before_continuation"] = R.intents(world)[research_id]["state"]
    out["continuation"] = call(world.tick)
    out["after_continuation"] = R.view(world)
    out["research_rows_unchanged"] = before_rows == R.research_rows(world)
    out["failure_verdicts_unchanged"] = all(R.jobs(world)[k] == old_jobs[k] for k in old_jobs)
    # duplicate wakeups: this coordinator, a second one, a restart
    before = world.snapshot()
    settle(owner, 3)
    settle(world.owners(), 3)
    out["duplicate_wakeups_unchanged"] = before == world.snapshot()
    out["seen"] = shot(world)
    out["state"] = world.snapshot()
    return out


def terminal_verdicts(api) -> dict:
    out = {}
    for name, verdict in (("rejected", False), ("blocked", "blocked")):
        world = load(api, "held", verdict=verdict)
        owner = registered(world)
        out[name] = {"ticks": settle(owner)}
        out[name]["action"] = brief(only_action(world))
        out[name]["seen"] = shot(world)
        out[name]["continuation"] = call(world.tick)
        out[name]["intent_after"] = R.intents(world)[world.ids["research_intent"]]["state"]
        before = world.snapshot()
        settle(owner, 4)
        out[name]["further_wakeups_unchanged"] = before == world.snapshot()
        out[name]["assessor_after"] = world.assessor.seen()
    return out


def unfinished(api) -> dict:
    world = load(api, "held", verdict="retry")
    owner = registered(world)
    out = {"ticks": settle(owner, 3)}
    out["action"] = brief(only_action(world))
    out["seen"] = shot(world)
    before = world.snapshot()
    settle(owner, 3)
    out["further_wakeups_unchanged"] = before == world.snapshot()
    return out


def never_spawned(api) -> dict:
    world = load(api, "held", spawn_fails=1)
    owner = registered(world)
    out = {"first": owner.tick("owners-1")}
    out["after_first"] = {"action": brief(only_action(world)), "decisions": len(decisions(world)),
                          "seen": shot(world)["assessor"]}
    out["ticks"] = settle(owner)
    out["action"] = brief(only_action(world))
    out["seen"] = shot(world)
    out["launch_ids"] = [only_action(world).get("launch_id")]
    return out


def lost_response(api) -> dict:
    world = load(api, "held", lost=True)
    owner = registered(world)
    out = {"ticks": settle(owner)}
    out["action"] = brief(only_action(world))
    out["seen"] = shot(world)
    return out


def restarted(api) -> dict:
    world = load(api, "held", verdict=None)     # the guardian is still running at the "crash"
    research_id = world.ids["research_intent"]
    owner = registered(world)
    out = {"first": owner.tick("owners-1")}
    [decision] = decisions(world)
    world.assessor.decide(decision["id"], True)      # the model finished while no coordinator watched
    world.assessor.launches = {k: "exited" for k in world.assessor.launches}
    crashing = CrashOnAccept(world.controller)
    out["crashed"] = settle(world.owners(continuation=crashing), 3)
    out["crash_calls"] = crashing.calls
    out["after_crash"] = {"action": only_action(world), "receipts": stored_receipts(world)}
    persisted = only_action(world)["receipt"]
    out["restart"] = settle(world.owners(), 2)
    out["action"] = brief(only_action(world))
    out["receipt_is_persisted"] = R.scan(world.control, R.RECEIPTS)[research_id]["receipt"] == persisted
    out["seen"] = shot(world)
    return out


def lose_action_row(world, action):
    """A LABELLED injected loss of one owner-action row (a MemoryStore fault: the transaction API has no delete)."""
    with world.control.transaction() as tx:
        del tx.data[ACTIONS, action["id"]]


def reused(api) -> dict:
    out = {}
    world = load(api, "held")
    first = world.assessor
    owner = registered(world)
    owner.tick("owners-1")     # schedules and (fixture) executes the one assessment
    action = only_action(world)
    lose_action_row(world, action)
    second = Assessor(world)
    second.launches = first.launches      # the same launch directories (the executed launch's proof)
    world.assessor = second
    out["ticks"] = settle(world.owners(assessments=second))
    out["action"] = brief(only_action(world))
    out["seen"] = shot(world)
    out["first_starts"] = len(first.starts)
    # after a restart the reused decision passes the same launch gate, without a new call
    matrix = {}
    for launch in ("running", "unknown", "unsettled", None):
        world = load(api, "held")
        first = world.assessor
        registered(world)
        world.owner.tick("owners-1")
        lose_action_row(world, only_action(world))
        second = Assessor(world)
        second.launches = {} if launch is None else {k: launch for k in first.launches}
        world.assessor = second
        ticks = settle(world.owners(assessments=second), 3)
        entry = {"ticks": ticks, "action": only_action(world), "seen": shot(world)}
        if launch == "running":
            second.launches = {k: "exited" for k in second.launches}
            entry["completed_ticks"] = settle(world.owners(assessments=second))
            entry["completed_action"] = brief(only_action(world))
            entry["completed_seen"] = shot(world)
        matrix[str(launch)] = entry
    out["after_restart"] = matrix
    # a reused decision without this action's launch identity is unbound
    world = load(api, "held")
    first = world.assessor
    registered(world)
    world.owner.tick("owners-1")
    action, [decision] = only_action(world), decisions(world)
    with world.control.transaction() as tx:      # LABELLED: the same executed row under a foreign id, action row lost
        tx.data[DECISIONS, "hand-run"] = {**decision, "id": "hand-run"}
        del tx.data[DECISIONS, decision["id"]]
        del tx.data[ACTIONS, action["id"]]
    second = Assessor(world)
    second.launches = dict(first.launches)
    world.assessor = second
    out["unbound"] = {"ticks": settle(world.owners(assessments=second), 2), "action": brief(only_action(world)),
                      "starts": second.starts}
    return out


def reuse_rules(api) -> dict:
    do = api.owner_domain
    row = {"id": "a" * 64, "kind": do.RESEARCH_RECEIPT, "binding_sha256": "b" * 64}
    base = {"id": "d1", "phase": do.OWNER_PHASE, "actor": do.ASSESSOR, "status": "succeeded",
            "input": {"owner_action": row["id"], "binding_sha256": row["binding_sha256"]},
            "result": {"accepted": True, "execution_ref": "sha256:" + "c" * 64}}
    out = {"exact": call(do.reusable_assessment, [base], row)}
    changes = {"running": {"status": "running"}, "other_actor": {"actor": "lead:improvement"},
               "other_phase": {"phase": "review_lead"},
               "other_binding": {"input": {"owner_action": row["id"], "binding_sha256": "f" * 64}},
               "no_execution_ref": {"result": {"accepted": True}}, "blocked": {"status": "blocked"}}
    out["changed"] = {name: call(do.reusable_assessment, [{**base, **change}], row) for name, change in changes.items()}
    out["rejected_verdict"] = call(do.assessment_verdict, {**base, "result": {
        "accepted": False, "execution_ref": "sha256:" + "c" * 64}}, row)
    out["accepted_verdict"] = call(do.assessment_verdict, base, row)
    out["absent_decision"] = call(do.assessment_verdict, None, row)
    return out


def changed_attempt(api) -> dict:
    world = load(api, "held", verdict=None)
    successor = world.ids["successor"]
    owner = registered(world)
    owner.tick("owners-1")
    stale = only_action(world)
    row = R.get(world.lane_store, "operations", successor)     # LABELLED injected change while assessing
    handoff = row["owner_handoff"]
    R.put(world.lane_store, "operations", successor, {
        **row, "owner_handoff": {**handoff, "inspection": {**handoff["inspection"], "id": "insp-replaced"}}})
    [decision] = decisions(world)
    world.assessor.decide(decision["id"], True)
    world.assessor.launches = {k: "exited" for k in world.assessor.launches}
    out = {"ticks": settle(owner, 3)}
    rows = {r["id"]: brief(r) for r in owner_rows(world)}
    out["stale"] = rows[stale["id"]]
    out["actions"] = sorted(rows)
    out["receipts"] = stored_receipts(world)
    out["continuation"] = call(world.tick)
    out["intent_after"] = R.intents(world)[world.ids["research_intent"]]["state"]
    out["seen"] = shot(world)
    return out


def no_accepted_research(api) -> dict:
    world = load(api, "research_paused")
    owner = registered(world)
    result, same = unchanged(world, lambda: call(world.owner_tick, owner))
    return {"tick": result, "records_unchanged": same, "seen": shot(world)}


def running_launch(api) -> dict:
    world = load(api, "held", verdict=None)     # the guardian (and its call ledger) is still running
    research_id = world.ids["research_intent"]
    owner = registered(world)
    out = {"first": owner.tick("owners-1")}
    [decision] = decisions(world)
    world.assessor.decide(decision["id"], True)      # LABELLED: the verdict row commits before the exit
    out["awaiting"] = settle(owner, 3)
    out["awaiting_action"] = only_action(world)
    out["receipts_while_running"] = stored_receipts(world)
    before = world.snapshot()
    settle(owner, 2)
    out["running_writes_nothing"] = before == world.snapshot()
    world.assessor.launches = {k: "exited" for k in world.assessor.launches}
    out["exited"] = settle(owner)
    out["action"] = brief(only_action(world))
    out["receipt_stored"] = research_id in R.scan(world.control, R.RECEIPTS)
    out["seen"] = shot(world)
    return out


def unproven(api) -> dict:
    out = {}
    for launch in ("unknown", "unsettled", "timeout"):
        for verdict in (True, False):
            world = load(api, "held", verdict=None)
            owner = registered(world)
            owner.tick("owners-1")
            [decision] = decisions(world)
            world.assessor.decide(decision["id"], verdict)
            world.assessor.launches = {k: launch for k in world.assessor.launches}    # LABELLED injected outcome
            ticks = settle(owner, 4)
            entry = {"ticks": ticks, "action": only_action(world), "seen": shot(world)}
            entry["continuation"] = call(world.tick)
            entry["intent_after"] = R.intents(world)[world.ids["research_intent"]]["state"]
            before = world.snapshot()
            settle(owner, 3)
            entry["further_wakeups_unchanged"] = before == world.snapshot()
            out["%s_%s" % (launch, "accepted" if verdict else "rejected")] = entry
    # the review probe: a succeeded bound decision, poll unknown with cleanup_confirmed false
    world = load(api, "held")
    world.assessor.poll = lambda _: {"state": "unknown", "cleanup_confirmed": False}
    owner = registered(world)
    out["probe"] = {"ticks": settle(owner, 5), "action": brief(only_action(world)), "seen": shot(world)}
    return out


def g1(api) -> dict:
    return {"accepted": accepted(api), "terminal_verdicts": terminal_verdicts(api), "unfinished": unfinished(api),
            "never_spawned": never_spawned(api), "lost_response": lost_response(api), "restarted": restarted(api),
            "reused": reused(api), "reuse_rules": reuse_rules(api), "changed_attempt": changed_attempt(api),
            "no_accepted_research": no_accepted_research(api), "running_launch": running_launch(api),
            "unproven": unproven(api),
            "unreachable": {
                "mixed_cause_family": "the schema-2 (mixed-cause) receipt needs a recorded mixed family with promotion "
                                      "rows; the recorded flows carry only same-cause families"}}


# ---- C3: research dispatch (flow research_paused) ----------------------------------------------------------------
def dispatch_world(api, *, probe_ok=True, **options):
    world = load(api, "research_paused", probe_ok=probe_ok, **options)
    world.owner.register(policy_v2(api), PIN)
    return world


def dtick(world, owner=None):
    return (owner or world.owner).tick("owners-002")


def dispatch_of_world(world):
    rows = [r for r in owner_rows(world) if r["kind"] == "research_dispatch"]
    return rows[0] if len(rows) == 1 else rows


def cycle_number(number):
    return "%s:%03d" % (PROGRAM, number)      # M7 `domain.research_program.cycle_id` (label `%03d`)


def reserve(world, owner_token):
    """LABELLED `ResearchProgram.reserve_cycle` result: the next cycle row with its owner token, `active_cycle` set and
    `next_cycle` advanced on the program row."""
    program = program_row(world)
    config, number, now = program["config"], program["next_cycle"], world.clock()
    cycle = {"id": cycle_number(number), "program": PROGRAM, "number": number, "owner": owner_token, "status": COLLECTING,
             "counts": None, "sources": None, "selection": None, "budget": None, "capture": None, "council": None,
             "result": None, "failure": None, "stop_reason": None,
             "remaining": {"cycles": config["max_cycles"] - program["cycles"] - 1,
                           "adoptions": config["max_adoptions"] - program["adoptions"]},
             "started_at": now, "updated_at": now, "finished_at": None}
    R.put(world.control, CYCLES, cycle["id"], cycle)
    R.put(world.control, PROGRAMS, PROGRAM, {**program, "active_cycle": cycle["id"], "next_cycle": number + 1,
                                             "updated_at": now})
    return cycle


def close(world, cycle, *, status=COMPLETED_CYCLE, selection=None, result=None, stop_reason=None):
    """LABELLED `ResearchProgram._close` result (via `complete_cycle`/`fail_cycle`): the cycle counted and finished, the
    program's `active_cycle` cleared."""
    program, now = program_row(world), world.clock()
    R.put(world.control, PROGRAMS, PROGRAM, {**program, "cycles": program["cycles"] + 1, "active_cycle": None,
                                             "last_tick_at": now, "updated_at": now})
    closed = {**cycle, "status": status, "selection": selection, "result": result, "stop_reason": stop_reason,
              "updated_at": now, "finished_at": now}
    R.put(world.control, CYCLES, cycle["id"], closed)
    return closed


def claim(world, cycle, result="accepted", **changes):
    """LABELLED dispatch claim row of the shape the recorded `held` flow holds, for this cycle."""
    template = next(r["body"] for r in R.FIXTURE["flows"]["held"]["control"] if r["bucket"] == DISPATCHES)
    row = {**template, "id": FAMILY_ROW, "investigation": FAMILY_ROW, "program": PROGRAM, "cycle": cycle["id"],
           "cycle_number": cycle["number"], "job_ids": sorted(world.ids["attempts"]), "result": result,
           "run_id": PROGRAM + ".c%03d" % cycle["number"], **changes}
    R.put(world.control, DISPATCHES, FAMILY_ROW, row)
    return row


def launched(world, **options):
    """A world with the dispatch launched once; returns the RUNNING action row."""
    dtick(world)
    return dispatch_of_world(world)


def provider_unavailable(api) -> dict:
    world = dispatch_world(api, probe_ok=False)
    before = program_row(world)
    out = {"tick": dtick(world)}
    out["action"] = only_action(world)
    out["program_unchanged"] = program_row(world) == before
    out["program_state"] = before["state"]
    out["cycles"] = R.scan(world.control, CYCLES)
    out["seen"] = shot(world)
    out["more"] = [dtick(world) for _ in range(3)]
    out["actions_after"] = len(owner_rows(world))
    out["probes_after"] = world.research.probes
    out["seen_after"] = shot(world)
    return out


def probe_ok(api) -> dict:
    world = dispatch_world(api)
    before = program_row(world)
    out = {"tick": dtick(world), "program_before": {k: before[k] for k in ("state", "active_cycle", "cycles", "next_cycle")}}
    action = only_action(world)
    out["action"] = action
    after = program_row(world)
    out["program_after"] = {k: after[k] for k in ("state", "active_cycle", "cycles", "next_cycle")}
    out["seen"] = shot(world)
    out["later"] = [dtick(world) for _ in range(3)]
    out["later_action"] = brief(only_action(world))
    out["seen_later"] = shot(world)
    out["launch_id_stable"] = only_action(world).get("launch_id") == action["launch_id"]
    out["state"] = world.snapshot()
    return out


def collection_only(api) -> dict:
    world = dispatch_world(api)
    row = launched(world)
    cycle = reserve(world, row["launch_id"])
    close(world, cycle, selection={"candidate": None, "reason": "no_eligible_candidate"})
    world.research.launches[row["launch_id"]] = "exited"
    out = {"tick": dtick(world), "action": only_action(world), "program": program_row(world)}
    out["more"] = [dtick(world) for _ in range(3)]
    out["actions_after"] = len(owner_rows(world))
    out["seen"] = shot(world)
    return out


def foreign_cycle(api) -> dict:
    world = dispatch_world(api)
    row = launched(world)
    cycle = reserve(world, "f" * 64)      # another owner reserved the same number
    close(world, cycle, selection={"candidate": {"id": "local-note"}, "reason": "first_eligible_in_stable_order"})
    world.research.launches[row["launch_id"]] = "exited"
    out = {"tick": dtick(world), "action": brief(only_action(world))}
    out["starts"] = list(world.research.starts)
    out["more"] = [dtick(world) for _ in range(2)]
    out["action_after"] = brief(only_action(world))
    # no cycle at all: the program provably untouched, and the program moved
    world = dispatch_world(api)
    row = launched(world)
    world.research.launches[row["launch_id"]] = "exited"
    out["not_reserved"] = {"tick": dtick(world), "action": brief(only_action(world))}
    world = dispatch_world(api)
    row = launched(world)
    program = program_row(world)
    R.put(world.control, PROGRAMS, PROGRAM, {**program, "next_cycle": program["next_cycle"] + 1})    # LABELLED: moved
    world.research.launches[row["launch_id"]] = "exited"
    out["program_moved"] = {"tick": dtick(world), "action": brief(only_action(world))}
    return out


def relaunch(api) -> dict:
    world = dispatch_world(api)
    row = launched(world)
    del world.research.launches[row["launch_id"]]       # LABELLED: fenced, never entered
    out = {"first": dtick(world)}
    row = dispatch_of_world(world)
    out["after_first"] = brief(row)
    out["starts"] = list(world.research.starts)
    del world.research.launches[row["launch_id"]]
    out["second"] = dtick(world)
    out["action"] = brief(dispatch_of_world(world))
    out["starts_after"] = list(world.research.starts)
    out["more"] = [dtick(world) for _ in range(2)]
    out["seen"] = shot(world)
    # fenced, but the program is no longer provably untouched: unknown, never relaunched
    world = dispatch_world(api)
    row = launched(world)
    reserve(world, "f" * 64)
    del world.research.launches[row["launch_id"]]
    out["touched"] = {"tick": dtick(world), "action": brief(dispatch_of_world(world)),
                      "starts": list(world.research.starts)}
    return out


def owned_crash(api) -> dict:
    world = dispatch_world(api)
    row = launched(world)
    reserve(world, row["launch_id"])      # LABELLED: reserved by the child, then crashed
    world.research.launches[row["launch_id"]] = "exited"
    restarted_owner = world.owners()
    out = {"tick": dtick(world, restarted_owner), "action": brief(dispatch_of_world(world))}
    out["active_cycle"] = program_row(world)["active_cycle"]
    out["starts"] = list(world.research.starts)
    out["more"] = [dtick(world, restarted_owner) for _ in range(2)]
    out["starts_after"] = list(world.research.starts)
    # an unproven launch: unknown state, or an exit without a cleanup proof
    world = dispatch_world(api)
    row = launched(world)
    world.research.launches[row["launch_id"]] = "unknown"
    out["launch_unknown"] = {"tick": dtick(world), "action": brief(dispatch_of_world(world))}
    return out


def outcomes(api) -> dict:
    out = {}
    cases = {
        "accepted": lambda w, c: (close(w, c, selection={"candidate": {"id": "x"}, "reason": "r"}, result="accepted"),
                                  claim(w, c, "accepted")),
        "dispatch_rejected": lambda w, c: (close(w, c, selection={"candidate": {"id": "x"}, "reason": "r"},
                                                 result="rejected"), claim(w, c, "rejected")),
        "dispatch_unresolved": lambda w, c: (close(w, c, selection={"candidate": {"id": "x"}, "reason": "r"}),
                                             claim(w, c, None)),
        "cycle_failed_with_claim": lambda w, c: (close(w, c, status=FAILED_CYCLE, stop_reason="failed:council"),
                                                 claim(w, c, "failed")),
        "cycle_failed": lambda w, c: close(w, c, status=FAILED_CYCLE, stop_reason="failed:capture"),
        "other_candidate": lambda w, c: close(w, c, selection={"candidate": {"id": "x"}, "reason": "r"}),
    }
    for name, apply in cases.items():
        world = dispatch_world(api)
        row = launched(world)
        cycle = reserve(world, row["launch_id"])
        apply(world, cycle)
        world.research.launches[row["launch_id"]] = "exited"
        entry = {"tick": dtick(world), "action": brief(dispatch_of_world(world))}
        entry["more"] = [dtick(world) for _ in range(2)]
        entry["actions_after"] = len(owner_rows(world))
        entry["starts"] = list(world.research.starts)
        out[name] = entry
    return out


def decision_table(api) -> dict:
    """Every row of `test_the_ported_ro1_decision_table`: the pure rule over rows read from the recorded state (as the M7
    test does), and the same mutation through the tick."""
    do = api.owner_domain
    out = {}
    names = ("research_programs", "research_investigation_dispatches", "research_dispatch_recoveries",
             "research_dispatch_heads", "portfolio_investigations", "fleet_jobs", "portfolio_bindings")
    for case in ("exact", "active", "mixed", "competing", "headroom", "unreadable", "claimed", "busy", "paused_by_owner",
                 "completed", "unregistered"):
        world = dispatch_world(api)
        rows = {name: R.scan(world.control, name) for name in names}
        rows = {name: list(scanned.values()) for name, scanned in rows.items()}
        attempts, room = sorted(world.ids["attempts"]), {"ok": True, "remaining": 5}
        program = next(r for r in rows["research_programs"] if r["id"] == PROGRAM)
        if case == "active":
            program["state"] = "active"
        elif case == "mixed":
            attempts = attempts[:1]
        elif case == "competing":
            rows["research_programs"].append({**program, "id": "rp-rival", "state": "active"})
        elif case == "headroom":
            room = {"ok": False, "remaining": 0}
        elif case == "unreadable":
            room = None
        elif case == "claimed":
            rows["research_investigation_dispatches"].append({"investigation": world.ids["investigation"],
                                                              "program": "rp-rival"})
        elif case == "busy":
            program["active_cycle"] = "rp-b2:1"
        elif case == "paused_by_owner":
            program["cycles"] = 1
        elif case == "completed":
            program["state"] = "completed"
        elif case == "unregistered":
            rows["research_programs"] = []
        out[case] = {"pure": call(do.research_decision, program_id=PROGRAM, investigation=world.ids["investigation"],
                                  attempts=attempts, rows=rows, room=room, now="2026-09-26T00:00:00+00:00")}
    return out


def tick_table(api) -> dict:
    """The same table through the tick: the store mutated the way the M7 test mutates its rows (LABELLED injected
    states), then one owner wakeup."""
    out = {}

    def program_change(**change):
        def apply(world):
            R.put(world.control, PROGRAMS, PROGRAM, {**program_row(world), **change})
        return apply

    def rival(world):
        R.put(world.control, PROGRAMS, "rp-rival", {**program_row(world), "id": "rp-rival", "state": "active"})

    def claimed(world):
        R.put(world.control, DISPATCHES, "claim-rival", {"id": "claim-rival", "investigation": world.ids["investigation"],
                                                         "program": "rp-rival"})

    def mixed(world):
        job = R.get(world.control, "fleet_jobs", world.ids["attempts"][0])
        R.put(world.control, "fleet_jobs", job["id"], {**job, "reason_code": "operation_failed"})

    def unregistered(world):
        with world.control.transaction() as tx:
            del tx.data[PROGRAMS, PROGRAM]

    cases = {
        "exact": (None, {}), "active": (program_change(state="active"), {}), "mixed": (mixed, {}),
        "competing": (rival, {}), "headroom": (None, {"ledger": lambda: {**LEDGER, "this_host": 10, "all_hosts": 20}}),
        "unreadable": (None, {"ledger": _raise}), "claimed": (claimed, {}), "busy": (program_change(active_cycle="rp-b2:1"), {}),
        "paused_by_owner": (program_change(cycles=1), {}), "completed": (program_change(state="completed"), {}),
        "unregistered": (unregistered, {})}
    for name, (mutate, options) in cases.items():
        world = dispatch_world(api, **options)
        if mutate is not None:
            mutate(world)
        entry = {"tick": dtick(world), "actions": [brief(r) for r in owner_rows(world)]}
        entry["program"] = program_row(world) and {k: program_row(world)[k] for k in ("state", "active_cycle", "cycles",
                                                                                    "next_cycle")}
        entry["research"] = world.research.seen()
        out[name] = entry
    return out


def _raise():
    raise OSError("machine ledger unreadable (labelled injected fault)")


def discovery(api) -> dict:
    world = dispatch_world(api)
    out = {"first": dtick(world)}
    out["second_coordinator"] = dtick(world, world.owners())
    out["third_coordinator"] = dtick(world, world.owners())
    out["actions"] = [brief(r) for r in owner_rows(world)]
    out["starts"] = list(world.research.starts)
    out["seen"] = shot(world)
    return out


def c3(api) -> dict:
    return {"provider_unavailable": provider_unavailable(api), "probe_ok": probe_ok(api),
            "collection_only": collection_only(api), "foreign_cycle": foreign_cycle(api), "relaunch": relaunch(api),
            "owned_crash": owned_crash(api), "outcomes": outcomes(api), "decision_table": decision_table(api),
            "tick_table": tick_table(api), "discovery": discovery(api),
            "unreachable": {
                "happy_path_program_tick": "the child's ProgramRunner tick (council, capture, dispatch claim) is research "
                                           "application code that moves in S8; the cycle and claim rows above are LABELLED "
                                           "shapes, so the T3-9 chain through the receipt is not run here"}}


def run(api) -> dict:
    return {"scheduler": scheduler(api), "g1": g1(api), "c3": c3(api)}
