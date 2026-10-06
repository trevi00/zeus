"""C3 research dispatch.

Layer: application
Context: coordination
Owns: no bucket of its own
Does not own: the program resume (research's ResearchPrograms
    port), the guarded child (research launcher), the cycle rows (the child's)
Entry points: ResearchLaunchFamily
Contracts: INV-OWNER-ACTIONS-001, INV-RESEARCH-ATTEMPT-SCOPE-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.owner_actions.state import (
    BUCKET_ACTIONS,
    BUCKET_BINDINGS,
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_HEADS,
    BUCKET_INVESTIGATIONS,
    BUCKET_PROGRAMS,
    BUCKET_RECOVERIES,
    BUCKET_SUCCESSORS,
    CONTINUATION_INTENTS,
    CONTINUATION_POLICIES,
    CONTINUATION_RECEIPTS,
    FLEET_JOBS,
    LAUNCH_ABSENT,
    LAUNCH_RUNNING,
    LAUNCH_UNKNOWN,
    _launch_view,
    _probe_view,
)
from codex_harness.coordination.domain.continuation import (
    ATTEMPT_SCOPE_PREFIX,
    RESEARCH_REQUIRED,
    attempt_scope_id,
    research_attempts,
)
from codex_harness.coordination.domain.owner_actions import (
    INTENDED,
    LAUNCHING,
    MAX_RESEARCH_LAUNCHES,
    REFUSED,
    RESEARCH_DISPATCH,
    RESEARCH_TRANSIENT,
    RUNNING,
    TERMINAL,
    UNKNOWN,
    OwnerActionRefused,
    research_decision,
    research_dispatch_binding,
    research_launch_id,
    research_outcome,
    research_policy,
)
from codex_harness.intake.domain.portfolio import family_id
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import utcnow
from codex_harness.research.domain.research_attempt_scope import SOURCE_NAME as SCOPE_SOURCE
from codex_harness.research.domain.research_program import cycle_id, headroom


class ResearchLaunchFamily:
    """C3: one guarded research-program tick for a held family the RO-1 rule scopes exactly."""

    def __init__(self, store, *, clock=utcnow, ledger=None, research=None, programs=None, actions=None):
        self.store = store
        self.clock = clock
        self.ledger = ledger
        self.research = research
        self.programs = programs
        self.actions = actions

    # ===== C3: asynchronous guarded research dispatch ================================================
    def _research_scope(self, intent: dict, intents: list, program_id: str) -> dict:
        """The held family's exact attempt set and its one investigation, and every durable row the ported
        RO-1 rule reads, in ONE control-store read; the ledger is read outside it.

        A program opted in with `attempt_scope_source` (INV-RESEARCH-ATTEMPT-SCOPE-001) claims under the
        intent's own `attempt-scope.<intent id>` (its Portfolio cause row is `family_investigation`). Its
        continuation intents, receipts, registered policies and research successors are read in that SAME
        transaction, and the attempt set is re-derived from those intents: the caller's older read is
        never taken for one snapshot with the claim rows."""
        attempts = sorted({a["job"] for a in research_attempts(intents, intent)})
        with self.store.transaction() as tx:
            rows = {name: tx.scan(name) for name in (BUCKET_PROGRAMS, BUCKET_DISPATCHES, BUCKET_RECOVERIES,
                                                     BUCKET_HEADS, BUCKET_INVESTIGATIONS, FLEET_JOBS, BUCKET_BINDINGS)}
            program = next((r for r in rows[BUCKET_PROGRAMS] if r.get("id") == program_id), None)
            scoped = isinstance(program, dict) and isinstance((program.get("config") or {}).get(SCOPE_SOURCE), dict)
            if scoped:
                rows.update({name: tx.scan(name) for name in (CONTINUATION_POLICIES, CONTINUATION_INTENTS,
                                                              CONTINUATION_RECEIPTS, BUCKET_SUCCESSORS)})
        if scoped:
            current = [r for r in rows[CONTINUATION_INTENTS] if isinstance(r, dict)
                       and r.get("policy_id") == intent.get("policy_id")]
            intent = next((r for r in current if r.get("id") == intent["id"]), None)
            if intent is None:
                raise OwnerActionRefused("research_intent_not_held", "intent_id")
            attempts = sorted({a["job"] for a in research_attempts(current, intent)})
        jobs = {job["id"]: job for job in rows[FLEET_JOBS] if isinstance(job, dict) and job.get("id") in attempts}
        if set(jobs) != set(attempts):
            raise OwnerActionRefused("research_attempt_unavailable", "attempts")
        families = {family_id(job.get("status"), job.get("reason_code")) for job in jobs.values()}
        if len(families) != 1:
            raise OwnerActionRefused("research_scope_mixed", "attempts")
        room = None
        if isinstance(program, dict) and self.ledger is not None:
            try:
                room = headroom((program.get("config") or {}).get("budget"), self.ledger())
            except Exception:  # an unreadable ledger is uncertainty: wait, never tick
                room = None
        found = {"attempts": attempts, "investigation": families.pop(), "program": program, "room": room,
                 "rows": {"research_programs": rows[BUCKET_PROGRAMS],
                          "research_investigation_dispatches": rows[BUCKET_DISPATCHES],
                          "research_dispatch_recoveries": rows[BUCKET_RECOVERIES],
                          "research_dispatch_heads": rows[BUCKET_HEADS],
                          "portfolio_investigations": rows[BUCKET_INVESTIGATIONS], "fleet_jobs": rows[FLEET_JOBS],
                          "portfolio_bindings": rows[BUCKET_BINDINGS]}}
        if scoped:
            found.update(investigation=attempt_scope_id(intent["id"]), family_investigation=found["investigation"])
            found["rows"].update({"continuation_policies": rows[CONTINUATION_POLICIES],
                                  "continuation_intents": rows[CONTINUATION_INTENTS],
                                  "continuation_research_receipts": rows[CONTINUATION_RECEIPTS],
                                  "research_dispatch_successors": rows[BUCKET_SUCCESSORS]})
        return found

    def _research_decide(self, intent: dict, intents: list, program_id: str) -> tuple:
        scope = self._research_scope(intent, intents, program_id)
        decision = research_decision(program_id=program_id, investigation=scope["investigation"],
                                     attempts=scope["attempts"], rows=scope["rows"], room=scope["room"],
                                     now=self.clock(), family_investigation=scope.get("family_investigation"))
        return scope, decision

    def discover(self, row: dict, block: dict, intent: dict, intents: list) -> list:
        if self.research is None:
            raise OwnerActionRefused("research_ports_unconfigured", "research")
        scope, decision = self._research_decide(intent, intents, block["program_id"])
        if not decision["act"]:
            if decision["reason"] == "research_dispatch_claimed":
                return []       # F5 reached: the research receipt path names its own wait
            raise OwnerActionRefused(decision["reason"], "research")
        with self.store.transaction() as tx:
            pending = [a for a in tx.scan(BUCKET_ACTIONS) if a.get("kind") == RESEARCH_DISPATCH
                       and a["state"] not in TERMINAL and a["binding"]["program_id"] == block["program_id"]]
        if pending:
            raise OwnerActionRefused("research_dispatch_in_flight", "research")
        binding = research_dispatch_binding(intent, block, scope["investigation"], scope["attempts"],
                                            decision["detail"]["expected_cycle"])
        return self.actions.create(row, RESEARCH_DISPATCH, binding, {"intent_id": intent["id"], "lane": intent.get("lane")})

    def advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        if self.research is None:
            raise OwnerActionRefused("research_ports_unconfigured", "research")
        state = action["state"]
        if state == INTENDED:
            return self._begin_dispatch(policy_row, continuation, action)
        if state == LAUNCHING:
            return self._launch_dispatch(action)
        if state == RUNNING:
            return self._observe_dispatch(action)
        return None

    def _begin_dispatch(self, policy_row: dict, continuation: dict, action: dict) -> dict:
        """Re-decided now; the provider probe precedes any resume, reservation or spawn; then the launch id
        is persisted (LAUNCHING) BEFORE the spawn."""
        binding = action["binding"]
        block = research_policy(policy_row["policy"])
        if block is None or block["program_id"] != binding["program_id"]:
            return self.actions.effect(self.actions.move(action, REFUSED, "research_policy_changed"))
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, binding["intent_id"])
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
            receipt = tx.get(CONTINUATION_RECEIPTS, binding["intent_id"])
        if not (isinstance(intent, dict) and intent.get("state") == RESEARCH_REQUIRED) or receipt is not None:
            return self.actions.effect(self.actions.move(action, REFUSED, "research_intent_not_held"))
        scope, decision = self._research_decide(intent, intents, binding["program_id"])
        if not decision["act"]:
            if decision["reason"] in RESEARCH_TRANSIENT:
                raise OwnerActionRefused(decision["reason"], "research")
            return self.actions.effect(self.actions.move(action, REFUSED, decision["reason"]))
        if (scope["investigation"], scope["attempts"], decision["detail"]["expected_cycle"]) != (
                binding["investigation"], binding["attempts"], binding["expected_cycle"]):
            return self.actions.effect(self.actions.move(action, REFUSED, "research_binding_changed"))
        try:
            probe = self.research.probe()
        except Exception as exc:
            probe = {"ok": False, "reason_code": "research_provider_probe_failed", "error_type": type(exc).__name__}
        if not (isinstance(probe, dict) and probe.get("ok") is True):
            # Before any resume, reservation or spawn: nothing is counted, nothing is left owned.
            return self.actions.effect(self.actions.move(action, REFUSED, "research_provider_unavailable",
                                           probe=_probe_view(probe)))
        if "resume" in decision["steps"]:
            # R2: research's owner operation in its own unit, through the ResearchPrograms port (DESIGN-s6 §5).
            require(self.programs is not None, "Research program resume is not wired")
            self.programs.resume(binding["program_id"])
        row = self.actions.move(action, LAUNCHING, "research_launch_intended", launches=1,
                         launch_id=research_launch_id(action["id"], 1), child_lane=block["lane"],
                         probe=_probe_view(probe))
        return self._launch_dispatch(row)

    def _launch_dispatch(self, action: dict) -> dict:
        """ONE spawn per launch id (the port's exclusive marker makes a lost response or a restart
        `cached`); the tick never waits for the child."""
        self.research.start(action["launch_id"], action["binding"]["program_id"], action["child_lane"])
        return self.actions.effect(self.actions.move(action, RUNNING, "research_launched"))

    def _observe_dispatch(self, action: dict) -> dict | None:
        binding = action["binding"]
        launch = self.research.poll(action["launch_id"])
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            return None
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is False:
            return self.actions.effect(self.actions.move(action, UNKNOWN, "research_launch_unknown", launch=_launch_view(launch)))
        scoped = str(binding["investigation"]).startswith(ATTEMPT_SCOPE_PREFIX)
        with self.store.transaction() as tx:
            program = tx.get(BUCKET_PROGRAMS, binding["program_id"])
            cycle = tx.get(BUCKET_CYCLES, cycle_id(binding["program_id"], binding["expected_cycle"]))
            dispatch = tx.get(BUCKET_DISPATCHES, binding["investigation"])
            # INV-RESEARCH-ATTEMPT-SCOPE-001: a scoped claim is ours only as exactly the held intent's current
            # attempt pairs, derived from the intent rows of this same read.
            intent = tx.get(CONTINUATION_INTENTS, binding["intent_id"]) if scoped else None
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == binding["continuation_policy"]] \
                if scoped else []
        attempts = None
        if isinstance(intent, dict):
            try:
                attempts = research_attempts(intents, intent)
            except (KeyError, TypeError):     # an unreadable lineage proves no capture: never ours
                attempts = None
        if state == LAUNCH_ABSENT:
            untouched = isinstance(program, dict) and program.get("active_cycle") is None \
                and program.get("next_cycle") == binding["expected_cycle"] and cycle is None
            if untouched and int(action.get("launches") or 0) < MAX_RESEARCH_LAUNCHES:
                # Fenced before it entered and the program provably unchanged: ONE bounded relaunch.
                sequence = int(action["launches"]) + 1
                row = self.actions.move(action, LAUNCHING, "research_relaunched", launches=sequence,
                                 launch_id=research_launch_id(action["id"], sequence))
                return self._launch_dispatch(row)
            return self.actions.effect(self.actions.move(action, UNKNOWN, "research_launch_unknown", launch=_launch_view(launch)))
        outcome = research_outcome(binding, action["launch_id"], program, cycle, dispatch, attempts=attempts)
        return self.actions.effect(self.actions.move(action, outcome["state"], outcome["reason_code"],
                                       outcome={"launch": _launch_view(launch),
                                                "cycle": (cycle or {}).get("id") if isinstance(cycle, dict) else None,
                                                "dispatch_result": (dispatch or {}).get("result")
                                                if isinstance(dispatch, dict) else None}))
