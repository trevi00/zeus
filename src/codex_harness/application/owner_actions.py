"""The server-owned pending-action coordinator (INV-OWNER-ACTIONS-001, aibox-migration-001 SPEC s14).

One thin durable owner for the three handoffs no unattended owner performed before: the independent
scoped acceptance of a held research family (G1), the exact approved delivery-plan publication for a
conducted release (G2) and the owner's actual canary of that delivery (G2). It is not a scheduler, a
reviewer, a release authority or a deployment controller. Everything decisive stays with its owner:

* `Continuation.accept_research` (validated, immutable, idempotent receipt storage) and the Fleet
  continuation tick that later releases the hold; this coordinator only assembles the receipt from the
  same authoritative reads (`Continuation.research_facts`) and one independent assessment.
* the existing guarded `decide_one` of the independent assessor, with its lease, attempt budget,
  execution budget and evidence receipt: one `owner_assessment` decision row per action, executed in a
  DB-free guardian the `assessments` port spawns once per launch identity. An existing executed
  assessment bound to exactly the same binding digest is reused instead of a new call.
* `Releases`/`HostDelivery` (`approval`, `register`, stages, merge, canary gate, rollback) and the
  incumbent `fleet_worker_operation` canary check, which reads the receipt this coordinator writes
  only from an ACTUAL finished canary operation and its independent lead review.

Durability follows the continuation rule: each action is one row in `owner_actions` (Fleet control
store) keyed by the digest of its kind and exact binding; the row names the state BEFORE the effect of
that state (`intended`, `assessing`, `invoking`, `publishing`, `published`, `requested`) and each move is
a compare-and-swap on its version, so a restart or a second coordinator reconciles instead of repeating.
No transaction is open across a lane store, Git, a process, an artifact write or the continuation's
own transactions. Rejected, unknown and refused are named terminal states: nothing here retries a model
call on a timer, and changed evidence is a NEW action while the old one keeps its history. An idle tick
writes nothing and calls nothing.

Policy v2 adds two opt-in handoffs, each to its existing owner (aibox whole-goal adjudication C1/C3):

* `delivery_requalify` - a completed plan of this policy whose delivery the controller BLOCKED as
  `reviewed_base_moved` is withdrawn through the lane's GitHub-capable `HostDelivery.withdraw` (the host was
  never touched; staleness observed now) and then requalified through `Continuation.requalify_delivery` on
  the observed current main with a persisted owner document (never a goal migration). A per-family cap
  slot is taken atomically with the move out of `intended`; the cap counts slots already held, never the
  action itself. Unobservable GitHub or main keeps the row where it is: the debt stays owned.
* `research_dispatch` - a held family the ported RO-1 rule scopes exactly gets ONE guarded
  `research-program run <program> --ticks 1` child: the provider probe runs before any resume,
  reservation or spawn, the launch id (which is also the cycle owner token) is persisted before the
  spawn, later ticks only poll, and the child's own cycle rows decide the outcome. A launch that provably
  never entered is relaunched at most once; unknown cleanup or a foreign cycle is `unknown`, never relaunched.
"""
from __future__ import annotations

import hashlib

from codex_harness.application.portfolio import BUCKET_BINDINGS, BUCKET_INVESTIGATIONS, family_id
from codex_harness.application.research_program import (
    BUCKET_CYCLES,
    BUCKET_DISPATCHES,
    BUCKET_HEADS,
    BUCKET_PROGRAMS,
    BUCKET_RECOVERIES,
    ResearchProgram,
)
from codex_harness.domain.continuation import (
    AWAITING_OWNER,
    DELIVERY,
    DELIVERY_ABSENT,
    DELIVERY_BOUND,
    DELIVERY_STALE,
    MIXED_RECEIPT_SCHEMA,
    REQUALIFICATION_REQUALIFIABLE,
    RESEARCH,
    RESEARCH_RECEIPT_SCHEMA,
    RESEARCH_REQUIRED,
    ContinuationRefused,
    bind_delivery,
    observed_attempt,
    research_attempts,
)
from codex_harness.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    BLOCKED,
    CANARY_FLEET,
    TERMINAL_STAGES,
    DeliveryRefused,
    consumption_verdict,
    descriptor_digest,
    plan_digest,
)
from codex_harness.domain.model import ContractError, canonical, digest, envelope, utcnow
from codex_harness.domain.owner_actions import (
    ASSESSED,
    ASSESSING,
    ASSESSMENT_ACTION,
    ASSESSMENT_SENDER,
    ASSESSOR,
    AUTHORITY,
    COMPLETED,
    DELIVERY_CANARY,
    DELIVERY_PLAN,
    DELIVERY_REQUALIFY,
    EVIDENCE_REF,
    INTENDED,
    INVOKING,
    LAUNCHING,
    MAX_ACTIONS_PER_TICK,
    MAX_ASSESSMENT_LAUNCHES,
    MAX_RESEARCH_LAUNCHES,
    OWNER_PHASE,
    PUBLISHED,
    PUBLISHING,
    REFUSED,
    REJECTED,
    REQUALIFY_REASON,
    REQUALIFYING,
    REQUESTED,
    RESEARCH_DISPATCH,
    RESEARCH_RECEIPT,
    RESEARCH_TRANSIENT,
    RUNNING,
    STATUS_SCHEMA,
    TERMINAL,
    TICK_SCHEMA,
    UNKNOWN,
    VERDICT_ACCEPTED,
    VERDICT_REJECTED,
    VERDICT_UNKNOWN,
    WITHDRAWING,
    OwnerActionRefused,
    action_id,
    assemble_receipt,
    assessment_decision_id,
    assessment_document,
    assessment_input,
    assessment_launch_id,
    assessment_verdict,
    build_plan,
    canary_binding,
    canary_job_id,
    canary_manifest,
    canary_outcome,
    canary_receipt,
    canary_request,
    dispatch_acceptance,
    lineage_edges,
    moved,
    new_action,
    plan_binding,
    plan_path,
    plan_ref,
    policy_digest,
    requalification_document,
    requalification_policy,
    requalification_rationale,
    requalify_binding,
    requalify_slots,
    research_binding,
    research_decision,
    research_dispatch_binding,
    research_launch_id,
    research_outcome,
    research_policy,
    reusable_assessment,
    validate_policy,
    view,
)
from codex_harness.domain.research_program import cycle_id, headroom

BUCKET_POLICIES = "owner_action_policies"
BUCKET_ACTIONS = "owner_actions"
CONTINUATION_INTENTS = "continuation_intents"
CONTINUATION_RECEIPTS = "continuation_research_receipts"
FLEET_JOBS = "fleet_jobs"
DECISIONS = "decisions_pending"
LAUNCH_RUNNING, LAUNCH_ABSENT, LAUNCH_UNKNOWN, LAUNCH_EXITED = "running", "absent", "unknown", "exited"


class ActionChanged(ContractError):
    """Another coordinator (or a restart replay) moved the action first; nothing was written here."""


class OwnerActions:
    """`store` is the Fleet control store (continuation intents, research rows, owner actions).

    Ports, each optional; an absent port leaves its actions waiting under a named reason:
    `continuation` the existing `Continuation` owner; `org` the organization that authorizes the
    assessment decision envelope; `lanes(lane_id)` the lane's `LaneEvidence`; `deliveries(lane_id)` the
    lane's `HostDelivery`; `publisher(lane_id)` the Git plan publisher of that lane's repository;
    `assessments` the independent-assessment port (`context`, `document`, `start`, `poll`); `targets`
    the target-file port over the incumbent state files (`startup`, and the plan-scoped `request`,
    `write_request`, `write_receipt`); `fleet` the Fleet admitting the owner's canary; `validate` the
    incumbent operation-manifest validator.

    Policy v2 ports: `withdrawals(lane_id)` the lane's GitHub-capable `HostDelivery` (the same one
    `host-delivery withdraw --lane` builds); `mainline(lane_id)` the lane's remote-main reader;
    `requalify(document)` the existing `Continuation.requalify_delivery` with its pin, runtime and
    mainline verification; `artifacts` the trusted content-addressed store the rationale is put in;
    `research` the guarded research-tick port (`probe`, `start`, `poll`); `ledger()` the machine call
    ledger counts the program's headroom is read from."""

    def __init__(self, store, *, continuation=None, org=None, lanes=None, deliveries=None, publisher=None,
                 assessments=None, targets=None, fleet=None, validate=None, clock=utcnow, withdrawals=None,
                 mainline=None, requalify=None, artifacts=None, research=None, ledger=None):
        self.store, self.continuation, self.org, self.lanes = store, continuation, org, lanes
        self.deliveries, self.publisher, self.assessments = deliveries, publisher, assessments
        self.targets, self.fleet, self.validate, self.clock = targets, fleet, validate, clock
        self.withdrawals, self.mainline, self.requalify, self.artifacts = withdrawals, mainline, requalify, artifacts
        self.research, self.ledger = research, ledger

    # ----- registry -------------------------------------------------------------------------------
    def register(self, document, pin: dict) -> dict:
        """Register the owner's Git-pinned policy once; the identical policy at the same pin replays."""
        policy = validate_policy(document)
        sha = policy_digest(policy)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_POLICIES, policy["id"])
            if old is not None:
                if not (old["policy_sha256"] == sha and old["pin"] == pin):
                    raise OwnerActionRefused("policy_conflict", "id")
                return {"registered": True, "cached": True, "id": policy["id"], "policy_sha256": sha}
            tx.put(BUCKET_POLICIES, policy["id"], {"id": policy["id"], "policy": policy, "policy_sha256": sha,
                                                   "pin": dict(pin), "registered_at": self.clock()})
        return {"registered": True, "cached": False, "id": policy["id"], "policy_sha256": sha}

    def status(self, policy_id: str | None = None) -> dict:
        """Read-only projection: every action's kind, state, reason and identities; store reads only."""
        with self.store.transaction() as tx:
            policies = tx.scan(BUCKET_POLICIES)
            rows = tx.scan(BUCKET_ACTIONS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            rows = [row for row in rows if row.get("policy_id") == policy_id]
        views = [view(row) for row in sorted(rows, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["kind"] + ":" + row["state"]] = counts.get(row["kind"] + ":" + row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"],
                              "policy_sha256": row["policy_sha256"], "pin": row["pin"]} for row in policies],
                "actions": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held": [row for row in views if row["state"] in {UNKNOWN, REJECTED, REFUSED}][-50:]}

    # ----- one bounded tick -------------------------------------------------------------------------
    def tick(self, policy_id: str, *, pin_sha256: str | None = None) -> dict:
        """Discover owed actions and advance at most `MAX_ACTIONS_PER_TICK` of them by one step each."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_POLICIES, policy_id)
        if row is None:
            return self._receipt(policy_id, "unregistered", reason_code="policy_unregistered")
        if pin_sha256 is not None and row["pin"].get("sha256") != pin_sha256:
            return self._receipt(policy_id, "refused", reason_code="policy_changed")
        if not row["policy"]["enabled"]:
            return self._receipt(policy_id, "disabled", reason_code="policy_disabled")
        continuation = None if self.continuation is None else self.continuation.policy(
            row["policy"]["continuation_policy"])
        if continuation is None:
            return self._receipt(policy_id, "refused", reason_code="continuation_policy_unregistered")
        if continuation["policy"]["delivery_target"] != row["policy"]["delivery"]["target_id"]:
            return self._receipt(policy_id, "refused", reason_code="delivery_target_mismatch")
        waits: dict = {}
        created = self._discover(row, continuation, waits)
        with self.store.transaction() as tx:
            open_rows = sorted((r for r in tx.scan(BUCKET_ACTIONS)
                                if r.get("policy_id") == policy_id and r["state"] not in TERMINAL),
                               key=lambda r: (str(r.get("created_at")), r["id"]))
        actions = []
        for action in open_rows[:MAX_ACTIONS_PER_TICK]:
            try:
                effect = self._advance(row, continuation, action)
            except ActionChanged:
                effect = None
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                # An outage or a refused read of THIS step: the row stays where it is and says why.
                waits[action["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
                effect = None
            if effect is not None:
                actions.append(effect)
        outcome = "progressed" if actions or created else "idle"
        return self._receipt(policy_id, outcome, actions=actions, created=created, waits=waits,
                             open=len(open_rows))

    def _receipt(self, policy_id, outcome, *, reason_code=None, actions=(), created=(), waits=None, open=0) -> dict:
        return {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": outcome, "reason_code": reason_code,
                "created": list(created), "actions": list(actions), "waits": dict(waits or {}), "open": open,
                "authority": AUTHORITY}

    # ----- discovery: the owed actions, from durable rows only ---------------------------------------
    def _discover(self, row: dict, continuation: dict, waits: dict) -> list:
        with self.store.transaction() as tx:
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
            receipts = {r["id"] for r in tx.scan(CONTINUATION_RECEIPTS)}
            actions = [r for r in tx.scan(BUCKET_ACTIONS) if r.get("policy_id") == row["id"]]
            dispatched = {(a.get("subject") or {}).get("intent_id") for a in tx.scan(BUCKET_ACTIONS)
                          if a.get("kind") == RESEARCH_DISPATCH}
        busy = {(a["kind"], (a.get("subject") or {}).get("intent_id")) for a in actions if a["state"] not in TERMINAL}
        created = []
        research = research_policy(row["policy"])
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
            # ONE guarded dispatch per held intent, whatever its outcome: a refused, empty, rejected or
            # unknown one is the owner's named exception, never a second tick (no collection-only spin).
            if research is not None and intent.get("route") == RESEARCH and intent.get("state") == RESEARCH_REQUIRED \
                    and intent["id"] not in receipts and intent["id"] not in dispatched:
                try:
                    created += self._discover_research(row, research, intent, intents)
                except (ContractError, OSError, RuntimeError, ValueError) as exc:
                    waits[RESEARCH_DISPATCH + ":" + intent["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
            try:
                if intent.get("route") == RESEARCH and intent.get("state") == RESEARCH_REQUIRED \
                        and intent["id"] not in receipts and (RESEARCH_RECEIPT, intent["id"]) not in busy:
                    found = self._research_binding(continuation, intent, intents)
                    created += self._create(row, RESEARCH_RECEIPT, found["binding"],
                                            {"intent_id": intent["id"], "lane": intent.get("lane")})
                elif intent.get("route") == DELIVERY and intent.get("state") == AWAITING_OWNER \
                        and (DELIVERY_PLAN, intent["id"]) not in busy:
                    binding = self._plan_binding(row, intent)
                    if binding is not None:
                        created += self._create(row, DELIVERY_PLAN, binding,
                                                {"intent_id": intent["id"], "lane": intent.get("lane")})
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[intent["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
        for plan in [a for a in actions if a["kind"] == DELIVERY_PLAN and a["state"] == COMPLETED
                     and (a.get("plan") or {}).get("canary_check_id") == CANARY_FLEET]:
            try:
                self._refile_request(plan)
                binding = self._canary_binding(plan)
                if binding is not None and (DELIVERY_CANARY, plan["subject"]["intent_id"]) not in busy:
                    created += self._create(row, DELIVERY_CANARY, binding, dict(plan["subject"]))
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[plan["id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
        block = requalification_policy(row["policy"])
        if block is not None:
            # A plan that already has its requalify action (in any state) is decided: no further read.
            decided = {a["binding"]["plan_id"] for a in actions if a["kind"] == DELIVERY_REQUALIFY}
            for plan in [a for a in actions if a["kind"] == DELIVERY_PLAN and a["state"] == COMPLETED]:
                if plan["plan_id"] in decided or (DELIVERY_REQUALIFY, plan["subject"]["intent_id"]) in busy:
                    continue
                try:
                    created += self._discover_requalify(row, block, plan)
                except (ContractError, OSError, RuntimeError, ValueError) as exc:
                    waits[DELIVERY_REQUALIFY + ":" + plan["id"]] = getattr(exc, "reason_code", None) \
                        or type(exc).__name__
        return created

    def _create(self, row: dict, kind: str, binding: dict, subject: dict) -> list:
        identity = action_id(kind, binding)
        with self.store.transaction() as tx:
            if tx.get(BUCKET_ACTIONS, identity) is not None:
                return []
            tx.put(BUCKET_ACTIONS, identity, new_action(kind, binding, row, subject, self.clock()))
        return [identity]

    # ----- durable moves ------------------------------------------------------------------------------
    def _move(self, action: dict, target: str, reason_code: str | None = None, *, extra=None, **fields) -> dict:
        """Compare-and-swap on the version; `extra(tx)` writes in the same transaction (a decision row)."""
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_ACTIONS, action["id"])
            if not (isinstance(current, dict) and current.get("version") == action.get("version")):
                raise ActionChanged(action["id"])
            row = moved(current, target, self.clock(), reason_code, **fields)
            if extra is not None:
                extra(tx)
            tx.put(BUCKET_ACTIONS, row["id"], row)
        return row

    @staticmethod
    def _effect(row: dict) -> dict:
        return {"action": row["id"], "kind": row["kind"], "state": row["state"], "reason_code": row["reason_code"]}

    def _advance(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        handler = {RESEARCH_RECEIPT: self._advance_research, DELIVERY_PLAN: self._advance_plan,
                   DELIVERY_CANARY: self._advance_canary, RESEARCH_DISPATCH: self._advance_dispatch,
                   DELIVERY_REQUALIFY: self._advance_requalify}[action["kind"]]
        return handler(policy_row, continuation, action)

    # ===== G1: scoped research acceptance ===========================================================
    def _research_binding(self, continuation: dict, intent: dict, intents: list) -> dict:
        """The exact receipt binding of one held intent, from the continuation's own readers. A family
        whose accepted research is not there yet, ambiguous, or needs an owner scope supplement is a
        named wait (raised), never a guess."""
        if self.lanes is None:
            raise OwnerActionRefused("lanes_unconfigured", "lanes")
        attempts = research_attempts(intents, intent)
        with self.store.transaction() as tx:
            jobs = {a["job"]: tx.get(FLEET_JOBS, a["job"]) for a in attempts}
            # A dispatch an earlier receipt of this family already consumed is that hold's history: the
            # completed research reset the family's count, so it never covers a later attempt set.
            consumed = {((r.get("receipt") or {}).get("investigation"),
                         ((r.get("receipt") or {}).get("dispatch") or {}).get("run_id"))
                        for r in tx.scan(CONTINUATION_RECEIPTS)
                        if r.get("id") != intent["id"] and (r.get("receipt") or {}).get("family") == intent["family"]}
        if not all(isinstance(job, dict) for job in jobs.values()):
            raise OwnerActionRefused("research_attempt_unavailable", "attempts")
        causes = {job_id: (job.get("status"), job.get("reason_code")) for job_id, job in jobs.items()}
        members = sorted(jobs)
        candidates = []
        for investigation in sorted({family_id(*cause) for cause in causes.values()}):
            facts = self.continuation.research_facts({
                "schema": RESEARCH_RECEIPT_SCHEMA, "policy_id": continuation["id"], "intent_id": intent["id"],
                "investigation": investigation, "attempts": [{"job": job} for job in members]})
            if facts.get("recovery_held") is not None:
                raise OwnerActionRefused("research_" + str(facts["recovery_held"]), "dispatch")
            dispatch = facts.get("dispatch")
            if isinstance(dispatch, dict) and dispatch.get("state") == "resolved" \
                    and (investigation, dispatch.get("run_id")) not in consumed \
                    and dispatch.get("result") == VERDICT_ACCEPTED \
                    and (facts.get("run_result") or {}).get("result") == VERDICT_ACCEPTED \
                    and set(members) & set(dispatch.get("job_ids") or []):
                candidates.append((investigation, facts))
        if not candidates:
            raise OwnerActionRefused("research_dispatch_pending", "dispatch")
        if len(candidates) > 1:
            raise OwnerActionRefused("research_dispatch_ambiguous", "dispatch")
        investigation, facts = candidates[0]
        dispatch = facts["dispatch"]
        mixed = len({family_id(*cause) for cause in causes.values()}) > 1
        if not mixed and not set(members) <= set(dispatch.get("job_ids") or []):
            # A partial capture needs the owner's typed scope supplement; this coordinator never writes one.
            raise OwnerActionRefused("research_scope_supplement_required", "dispatch")
        observed = {job_id: observed_attempt(job, self.lanes(job["lane"]).read(job)) for job_id, job in jobs.items()}
        rows = []
        for attempt in attempts:
            entry = {"job": attempt["job"], "evidence_sha256": attempt["evidence_sha256"],
                     "inspection": observed[attempt["job"]]["inspection"]}
            if mixed:
                status, reason = causes[attempt["job"]]
                entry.update(investigation=family_id(status, reason), status=status, reason_code=reason)
            rows.append(entry)
        binding = research_binding(intent, continuation, rows, investigation,
                                   {**dispatch, "id": dispatch.get("id", dispatch.get("investigation"))},
                                   MIXED_RECEIPT_SCHEMA if mixed else RESEARCH_RECEIPT_SCHEMA)
        return {"binding": binding, "facts": facts, "intents": intents, "intent": intent,
                "members": [{"job": job, "status": causes[job][0], "reason_code": causes[job][1],
                             "inspection": observed[job]["inspection"]} for job in members]}

    def _current_research(self, continuation: dict, action: dict) -> dict:
        """The binding recomputed NOW; an action whose binding moved on is refused, never re-pointed."""
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, action["subject"]["intent_id"])
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
        if not (isinstance(intent, dict) and intent.get("state") == RESEARCH_REQUIRED):
            raise OwnerActionRefused("research_intent_not_held", "intent_id")
        found = self._research_binding(continuation, intent, intents)
        if found["binding"] != action["binding"]:
            raise OwnerActionRefused("research_binding_changed", "binding")
        return found

    def _advance_research(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state = action["state"]
        if state == INTENDED:
            return self._begin_assessment(policy_row, continuation, action)
        if state == ASSESSING:
            return self._observe_assessment(action)
        if state == ASSESSED:
            return self._assemble(continuation, action)
        if state == INVOKING:
            return self._invoke(action)
        return None

    def _begin_assessment(self, policy_row: dict, continuation: dict, action: dict) -> dict:
        with self.store.transaction() as tx:
            decisions = [d for d in tx.scan(DECISIONS) if d.get("phase") == OWNER_PHASE]
        reused = reusable_assessment(decisions, action)
        if reused is not None:
            # An executed independent assessment already binds exactly this action: no new call. It is
            # promoted only through the same bound launch outcome as a fresh one (R1): the verdict is
            # kept as `decided` evidence and never asked for again.
            if self.assessments is None:
                raise OwnerActionRefused("assessor_unconfigured", "assessments")
            verdict = assessment_verdict(reused, action)
            bound = self._reused_launch(action, reused)
            if bound is None:
                return self._effect(self._move(action, UNKNOWN, "assessment_execution_unbound",
                                               decided=_decided(verdict), decision_id=reused["id"], reused=True))
            sequence, launch_id = bound
            row = self._move(action, ASSESSING, "assessment_reused", decided=_decided(verdict),
                             decision_id=reused["id"], launches=sequence, launch_id=launch_id, reused=True)
            return self._observe_assessment(row) or self._effect(row)
        if self.assessments is None or self.org is None:
            raise OwnerActionRefused("assessor_unconfigured", "assessments")
        try:
            found = self._current_research(continuation, action)
        except OwnerActionRefused as exc:
            return self._effect(self._move(action, REFUSED, exc.reason_code))
        context = self.assessments.context(action["binding"], found)
        if not isinstance(context, dict) or not isinstance(context.get("report"), str):
            # The assessor would judge nothing: the report bytes it must read are not there.
            return self._effect(self._move(action, UNKNOWN, "assessment_context_unavailable"))
        decision_id = assessment_decision_id(action["id"])
        launch = assessment_launch_id(action["id"], 1)
        data = assessment_input(action, context)
        message = envelope("review.result", ASSESSMENT_SENDER, ASSESSOR, ASSESSMENT_ACTION,
                           {"owner_action": action["id"], "binding_sha256": action["binding_sha256"]}, action["id"])
        self.org.authorize(message)

        def request(tx):
            # The ONE decision row, written with the intent in the same transaction: a crash leaves
            # both or neither, and the decision id is the action's own, so a replay never adds a row.
            old = tx.get(DECISIONS, decision_id)
            if old is None:
                tx.put(DECISIONS, decision_id, {"id": decision_id, "actor": ASSESSOR, "phase": OWNER_PHASE,
                                                "input": data, "message": message, "status": "pending",
                                                "attempt": 0})
            elif (old.get("input") or {}).get("binding_sha256") != action["binding_sha256"]:
                raise OwnerActionRefused("assessment_identity_conflict", "decision_id")

        row = self._move(action, ASSESSING, "assessment_scheduled", extra=request, decision_id=decision_id,
                         launches=1, launch_id=launch, correlation_id=message["correlation_id"])
        self.assessments.start(launch, decision_id, message["correlation_id"])
        return self._effect(row)

    def _observe_assessment(self, action: dict) -> dict | None:
        with self.store.transaction() as tx:
            decision = tx.get(DECISIONS, action["decision_id"])
        verdict = assessment_verdict(decision, action)
        if self.assessments is None:
            return None
        launch = self.assessments.poll(action["launch_id"])
        if verdict["verdict"] is not None:
            return self._settle_assessment(action, verdict, launch)
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            return None
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is False:
            # The guardian ended without proving its cleanup: an unknown effect, never a relaunch.
            return self._effect(self._move(action, UNKNOWN, "assessment_launch_unknown"))
        never_entered = isinstance(decision, dict) and decision.get("status") == "pending" \
            and int(decision.get("attempt") or 0) == 0
        if never_entered and int(action.get("launches") or 0) < MAX_ASSESSMENT_LAUNCHES:
            # Proven ended (or fenced) without claiming the decision: ONE more bounded launch.
            sequence = int(action["launches"]) + 1
            launch_id = assessment_launch_id(action["id"], sequence)
            row = self._move(action, ASSESSING, "assessment_relaunched", launches=sequence, launch_id=launch_id)
            self.assessments.start(launch_id, action["decision_id"], action["correlation_id"])
            return self._effect(row)
        return self._effect(self._move(action, ASSESSED, "assessment_unfinished", verdict=VERDICT_UNKNOWN))

    def _settle_assessment(self, action: dict, verdict: dict, launch: dict) -> dict | None:
        """A decided assessment is promoted only on ONE authoritative bound execution outcome (R1): its
        guardian's cleanup proof, whose exit code is the assess child's own ownership and call-ledger
        settlement result. A success persisted while the launch still runs waits; unknown cleanup, a
        timeout, an unsettled or unowned execution, or no bound execution at all ends as a named unknown
        that keeps the verdict as `decided` evidence and never asks the model again."""
        decided = _decided(verdict)
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            if action.get("decided") == decided:
                return None
            return self._effect(self._move(action, ASSESSING, "assessment_awaiting_cleanup", decided=decided))
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is not True:
            reason = "assessment_execution_unbound" if state == LAUNCH_ABSENT else "assessment_launch_unknown"
        elif state != LAUNCH_EXITED:
            reason = "assessment_launch_timeout"
        elif launch.get("exit_code") != 0:
            reason = "assessment_settlement_unresolved"
        else:
            return self._effect(self._move(action, ASSESSED, verdict["reason_code"], verdict=verdict["verdict"],
                                           execution_ref=verdict.get("execution_ref"), decided=decided))
        return self._effect(self._move(action, UNKNOWN, reason, decided=decided))

    def _reused_launch(self, action: dict, decision: dict) -> tuple | None:
        """The one launch of this action that executed `decision`: only the action's own decision row has
        launch identities; exactly one of them may have entered. Anything else is no bound execution."""
        if decision.get("id") != assessment_decision_id(action["id"]):
            return None
        entered = []
        for sequence in range(1, MAX_ASSESSMENT_LAUNCHES + 1):
            launch_id = assessment_launch_id(action["id"], sequence)
            if self.assessments.poll(launch_id).get("state") != LAUNCH_ABSENT:
                entered.append((sequence, launch_id))
        return entered[0] if len(entered) == 1 else None

    def _assemble(self, continuation: dict, action: dict) -> dict:
        verdict = action.get("verdict")
        if verdict == VERDICT_REJECTED:
            return self._effect(self._move(action, REJECTED, action.get("reason_code") or "assessment_rejected"))
        if verdict != VERDICT_ACCEPTED:
            return self._effect(self._move(action, UNKNOWN, action.get("reason_code") or "assessment_unknown"))
        try:
            found = self._current_research(continuation, action)
        except OwnerActionRefused as exc:
            return self._effect(self._move(action, REFUSED, exc.reason_code))
        if self.assessments is None:
            raise OwnerActionRefused("assessor_unconfigured", "assessments")
        document = assessment_document(action, {"verdict": verdict, "decision_id": action["decision_id"],
                                                "execution_ref": action["execution_ref"]})
        reference = self.assessments.document(document)
        facts = found["facts"]
        report = ((facts.get("acceptance") or {}).get("run") or {}).get("report") or {}
        refs = [ref for ref in (report.get("execution_ref"), action["execution_ref"])
                if type(ref) is str and EVIDENCE_REF.fullmatch(ref)]
        binding = action["binding"]
        extras = {}
        if binding["schema"] == MIXED_RECEIPT_SCHEMA:
            members = [a["job"] for a in binding["attempts"]]
            captured = sorted(set(members) & set((facts.get("dispatch") or {}).get("job_ids") or []))
            acceptance = facts.get("acceptance") or {}
            extras = {"captured": captured,
                      "lineage": lineage_edges(members, captured, found["intents"], found["intent"]),
                      "acceptance": dispatch_acceptance(acceptance.get("run"), acceptance.get("promotion"),
                                                        acceptance.get("task"))}
        receipt = assemble_receipt(binding, evidence_refs=refs, assessment_ref=reference, **extras)
        row = self._move(action, INVOKING, "receipt_assembled", receipt=receipt, receipt_sha256=digest(receipt),
                         assessment_ref=reference)
        return self._invoke(row)

    def _invoke(self, action: dict) -> dict:
        """The existing validated API with the persisted receipt; a replay is its identical, cached call."""
        try:
            result = self.continuation.accept_research(action["receipt"])
        except ContinuationRefused as exc:
            return self._effect(self._move(action, REFUSED, exc.reason_code))
        return self._effect(self._move(action, COMPLETED, "research_receipt_accepted",
                                       accepted={"cached": result.get("cached"),
                                                 "receipt_sha256": result.get("receipt_sha256"),
                                                 "coverage": result.get("coverage")}))

    # ===== G2: exact approved delivery-plan publication ===============================================
    def _lane_rows(self, lane_id: str, target_id: str, release_id: str | None) -> dict:
        delivery = self.deliveries(lane_id)
        with delivery.store.transaction() as tx:
            return {"delivery": delivery, "release": tx.get("releases", release_id) if release_id else None,
                    "intents": tx.scan("host_delivery_intents"), "plans": tx.scan("host_delivery_plans"),
                    "descriptor": tx.get("host_delivery_descriptors", target_id),
                    "target": tx.get("host_delivery_targets", target_id)}

    def _plan_binding(self, row: dict, intent: dict) -> dict | None:
        """A plan is owed only for a conducted delivery intent whose release is approved for exactly this
        target and has no delivery yet, while no other delivery is in flight on that target."""
        if self.deliveries is None or self.publisher is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        policy = row["policy"]
        target_id = policy["delivery"]["target_id"]
        if intent.get("delivery_target") != target_id:
            return None
        rows = self._lane_rows(intent["lane"], target_id, intent.get("release_id"))
        release = rows["release"]
        if not isinstance(release, dict):
            raise OwnerActionRefused("release_missing", "release_id")
        candidate = release.get("candidate") or {}
        bound = bind_delivery(rows["intents"], target_id, release.get("id"), candidate.get("revision"), release)
        if bound["binding"] == DELIVERY_BOUND:
            return None     # this exact candidate already has its delivery: nothing is owed
        if bound["binding"] not in {DELIVERY_ABSENT, DELIVERY_STALE}:
            # Ambiguous, mismatched or unknown delivery evidence is the continuation's named wait too.
            raise OwnerActionRefused("delivery_" + bound["binding"], "release_id")
        # `stale` only says the target has deliveries of OTHER revisions; none exists for this candidate.
        if rows["target"] is None:
            raise OwnerActionRefused("target_unregistered", "target_id")
        # SPEC s14.3 "no in-progress delivery on the target": every REGISTERED plan of the target counts,
        # including one no tick has given an intent yet, so a successor binds its expected predecessor
        # only after the delivery before it is terminal. Terminal is not safe-to-switch evidence; the
        # delivery's own pre-merge and switch checks still decide that (INV-OWNER-ACTIONS-001).
        stages = {r.get("plan_id") or r.get("id"): r.get("stage") for r in rows["intents"]}
        mine = [p for p in rows["plans"] if p.get("target_id") == target_id]
        if any((p.get("plan") or {}).get("release_id") == release.get("id")
               and (p.get("plan") or {}).get("revision") == candidate.get("revision") for p in mine):
            return None     # this exact candidate is already planned; its delivery is simply not started
        if any(stages.get(p.get("plan_id")) not in TERMINAL_STAGES for p in mine) or any(
                r.get("target_id") == target_id and r.get("stage") not in TERMINAL_STAGES for r in rows["intents"]):
            raise OwnerActionRefused("delivery_target_busy", "target_id")
        current = (rows["descriptor"] or {}).get("descriptor")
        binding = plan_binding(row, intent, release, None if current is None else descriptor_digest(current))
        plan = build_plan(policy, binding, action_id(DELIVERY_PLAN, binding))
        gate = rows["delivery"].approval(plan)
        if gate.get("state") != "approved":
            raise OwnerActionRefused(gate.get("reason_code") or "release_not_approved", "release_id")
        return binding

    def _advance_plan(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state, lane = action["state"], action["subject"]["lane"]
        if state == INTENDED:
            plan = build_plan(policy_row["policy"], action["binding"], action["id"])
            data = plan_json(plan)
            return self._effect(self._move(action, PUBLISHING, "plan_intended", plan=plan, plan_id=plan["plan_id"],
                                           plan_sha256=plan_digest(plan), path=plan_path(plan["plan_id"]),
                                           ref=plan_ref(plan["plan_id"]), bytes_sha256=digest_bytes(data),
                                           published_at=action["created_at"]))
        if state == PUBLISHING:
            data = plan_json(action["plan"])
            published = self.publisher(lane).publish(data, action["path"], action["ref"], action["published_at"])
            if published.get("conflict"):
                # The ref already names other content: another owner or a hand edit. Held, never overwritten.
                return self._effect(self._move(action, UNKNOWN, "plan_ref_conflict"))
            return self._effect(self._move(action, PUBLISHED, "plan_published", commit=published["revision"]))
        if state == PUBLISHED:
            return self._register(action, lane)
        return None

    def _register(self, action: dict, lane: str) -> dict:
        loaded = self.publisher(lane).load(action["commit"], action["path"])
        if loaded["plan"] != action["plan"] or loaded["pin"]["sha256"] != action["bytes_sha256"]:
            return self._effect(self._move(action, UNKNOWN, "plan_content_mismatch"))
        delivery = self.deliveries(lane)
        if action["plan"]["canary_check_id"] == CANARY_FLEET:
            # Filed BEFORE registration: the incumbent canary check then waits for the owner's actual
            # canary of exactly this plan, and only until the delivery's own consumption deadline.
            with delivery.store.transaction() as tx:
                target = tx.get("host_delivery_targets", action["plan"]["target_id"])
            if self.targets is None or target is None:
                raise OwnerActionRefused("canary_targets_unconfigured", "targets")
            self.targets.write_request(target, action["plan_id"], _request_of(action))
        try:
            registered = delivery.register(loaded["plan"], loaded["pin"])
        except DeliveryRefused as exc:
            return self._effect(self._move(action, REFUSED, exc.reason_code))
        return self._effect(self._move(action, COMPLETED, "plan_registered",
                                       registration={"plan_sha256": registered["plan_sha256"],
                                                     "cached": registered["cached"], "pin": loaded["pin"]}))

    # ===== G2: the owner's actual canary ===========================================================
    def _delivery_view(self, plan_action: dict) -> tuple:
        lane, plan = plan_action["subject"]["lane"], plan_action["plan"]
        delivery = self.deliveries(lane)
        with delivery.store.transaction() as tx:
            return (tx.get("host_delivery_intents", plan["plan_id"]),
                    tx.get("host_delivery_targets", plan["target_id"]))

    def _refile_request(self, plan_action: dict) -> None:
        """Keep a registered plan's OWN canary request filed while its delivery is open.

        This is the explicit compatibility path for plans registered while the request was one
        target-global file, where a later registration replaced it (the actual own-a98e.../own-fe54...
        state). The document is exactly the one `_register` filed, rebuilt from the immutable action
        row; nothing is written when it is already there, for a finished or foreign delivery, or to
        the former global file, and no action row changes."""
        if self.deliveries is None or self.targets is None:
            return
        intent, target = self._delivery_view(plan_action)
        if not isinstance(target, dict) or (isinstance(intent, dict) and (
                intent.get("stage") in TERMINAL_STAGES or intent.get("plan_sha256") != plan_action["plan_sha256"])):
            return
        document = _request_of(plan_action)
        if self.targets.request(target, plan_action["plan_id"]) != document:
            self.targets.write_request(target, plan_action["plan_id"], document)

    def _canary_binding(self, plan_action: dict) -> dict | None:
        """Owed once the delivery of exactly this plan awaits consumption and its candidate instance has
        reported the switched descriptor; the binding names that instance."""
        if self.deliveries is None or self.targets is None:
            return None
        intent, target = self._delivery_view(plan_action)
        if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION
                and intent.get("plan_sha256") == plan_action["plan_sha256"] and isinstance(target, dict)
                and isinstance(intent.get("descriptor"), dict)):
            return None
        verdict = consumption_verdict(intent["descriptor"], self.targets.startup(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if not verdict["consumed"]:
            return None
        return canary_binding(plan_action, intent, verdict["instance_id"])

    def _advance_canary(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        policy = policy_row["policy"]
        if self.fleet is None or self.lanes is None:
            raise OwnerActionRefused("canary_ports_unconfigured", "fleet")
        if action["state"] not in {INTENDED, REQUESTED}:
            return None
        with self.store.transaction() as tx:
            job = tx.get(FLEET_JOBS, action["job_id"]) if action["state"] == REQUESTED else None
            plan_action = next((r for r in tx.scan(BUCKET_ACTIONS) if r["kind"] == DELIVERY_PLAN
                                and r.get("plan_id") == action["binding"]["plan_id"]), None)
        if job is None and not self._canary_still_bound(plan_action, action):
            # R2: a persisted intent whose plan, delivery, descriptor or candidate instance moved on
            # (deadline, rollback, replaced instance) admits no work, neither first nor on replay.
            return self._effect(self._move(action, REFUSED, "canary_delivery_moved"))
        if action["state"] == INTENDED:
            job_id = canary_job_id(action["id"])
            manifest = canary_manifest(policy, job_id)
            if self.validate is not None:
                manifest = self.validate(manifest)
            row = self._move(action, REQUESTED, "canary_requested", job_id=job_id)
            self.fleet.enqueue(policy["canary"]["lane"], manifest, dict(policy["canary"]["goal"]), [])
            return self._effect(row)
        if job is None:
            # The admission's response was lost before the row existed: the same id admits once.
            manifest = canary_manifest(policy, action["job_id"])
            self.fleet.enqueue(policy["canary"]["lane"], self.validate(manifest) if self.validate else manifest,
                               dict(policy["canary"]["goal"]), [])
            return None
        if not self._canary_still_bound(plan_action, action):
            return self._effect(self._move(action, UNKNOWN, "canary_delivery_moved"))
        outcome = canary_outcome(job, self.lanes(job["lane"]).read(job) if job.get("status") not in {
            "queued", "dispatching"} else None)
        if outcome["state"] in {"running", "absent"}:
            return None
        if outcome["state"] == VERDICT_UNKNOWN:
            # No receipt: the delivery's own deadline rolls it back; the unknown effect stays named.
            return self._effect(self._move(action, UNKNOWN, outcome["reason_code"]))
        _, target = self._delivery_view(plan_action)
        self.targets.write_receipt(target, action["binding"]["plan_id"], canary_receipt(action, outcome, self.clock()))
        target_state = COMPLETED if outcome["state"] == VERDICT_ACCEPTED else REJECTED
        return self._effect(self._move(action, target_state, outcome["reason_code"],
                                       outcome={k: outcome.get(k) for k in ("state", "reason_code", "evidence")}))

    def _canary_still_bound(self, plan_action, action: dict) -> bool:
        """The same published plan's delivery still awaits consumption of the same descriptor and the SAME
        candidate instance is the one reporting it: work is admitted and an answer is written only for the
        instance it was taken against (R2 at admission, the result gate after it)."""
        binding = action["binding"]
        if plan_action is None or plan_action.get("plan_sha256") != binding["plan_sha256"]:
            return False
        intent, target = self._delivery_view(plan_action)
        if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION
                and intent.get("plan_sha256") == binding["plan_sha256"]
                and intent.get("target_id") == binding["target_id"]
                and intent.get("descriptor_sha256") == binding["descriptor_sha256"] and isinstance(target, dict)):
            return False
        receipt = self.targets.startup(target)
        return isinstance(receipt, dict) and receipt.get("instance_id") == binding["instance_id"] \
            and receipt.get("descriptor_sha256") == binding["descriptor_sha256"]

    # ===== C1: policy-triggered requalification of a stale reviewed base ===========================
    def _discover_requalify(self, row: dict, block: dict, plan: dict) -> list:
        """Owed only for a completed plan of THIS policy whose delivery the controller blocked for exactly
        an authorized reason, while its continuation intent can still be requalified. Nothing else."""
        lane = plan["subject"]["lane"]
        delivery = self.deliveries(lane)
        with delivery.store.transaction() as tx:
            observed = tx.get("host_delivery_intents", plan["plan_id"])
        if not (isinstance(observed, dict) and observed.get("stage") == BLOCKED
                and observed.get("reason_code") in block["reasons"]
                and observed.get("plan_sha256") == plan["plan_sha256"]):
            return []
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, plan["subject"]["intent_id"])
        if not (isinstance(intent, dict) and intent.get("route") == DELIVERY
                and intent.get("state") in REQUALIFICATION_REQUALIFIABLE):
            return []
        return self._create(row, DELIVERY_REQUALIFY, requalify_binding(plan, intent, observed),
                            {"intent_id": intent["id"], "lane": lane})

    def _advance_requalify(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
        state = action["state"]
        if state == INTENDED:
            return self._take_slot(policy_row, continuation, action)
        if state == WITHDRAWING:
            return self._withdraw(action)
        if state == REQUALIFYING:
            return self._requalify(continuation, action)
        return None

    def _take_slot(self, policy_row: dict, continuation: dict, action: dict) -> dict:
        """Before any effect: the action is still owed, its rationale is in the trusted store, and ONE cap
        slot is taken in the transaction that moves it - the count, the check and the move commit together
        (`Store.transaction` serializes writers), so two coordinators can never overshoot the family cap."""
        binding = action["binding"]
        block = requalification_policy(policy_row["policy"])
        if block is None or binding["reason"] not in block["reasons"]:
            return self._effect(self._move(action, REFUSED, "requalification_policy_disabled"))
        if binding["continuation_policy"] != continuation["id"]:
            return self._effect(self._move(action, REFUSED, "requalification_policy_foreign"))
        if self.withdrawals is None or self.requalify is None or self.mainline is None or self.artifacts is None:
            raise OwnerActionRefused("requalify_ports_unconfigured", "withdrawals")
        lane = action["subject"]["lane"]
        with self.deliveries(lane).store.transaction() as tx:
            observed = tx.get("host_delivery_intents", binding["plan_id"])
        if not (isinstance(observed, dict) and observed.get("stage") == BLOCKED
                and observed.get("reason_code") == binding["reason"]
                and observed.get("plan_sha256") == binding["plan_sha256"]):
            return self._effect(self._move(action, REFUSED, "requalification_delivery_moved"))
        rationale = requalification_rationale(action, observed)
        reference = self.artifacts.put(canonical(rationale), "owner-requalification-rationale")["ref"]
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_ACTIONS, action["id"])
            if not (isinstance(current, dict) and current.get("version") == action.get("version")):
                raise ActionChanged(action["id"])
            taken = requalify_slots(tx.scan(BUCKET_ACTIONS), binding, action["id"])
            if taken >= block["max_per_family"]:
                row = moved(current, REFUSED, self.clock(), "requalification_exhausted", slots_taken=taken)
            else:
                row = moved(current, WITHDRAWING, self.clock(), "requalification_slot_taken", cap_slot=taken + 1,
                            max_per_family=block["max_per_family"], rationale_ref=reference,
                            rationale_sha256=digest(rationale))
            tx.put(BUCKET_ACTIONS, row["id"], row)
        if row["state"] == REFUSED:
            return self._effect(row)
        return self._withdraw(row)

    def _withdraw(self, action: dict) -> dict:
        """The lane's own GitHub-capable withdrawal, citing the stored rationale. Its identical replay is
        cached; an unobservable GitHub or store raises (the row waits and the blocked plan keeps the target
        busy: that debt stays owned); a definite refusal is named."""
        binding = action["binding"]
        try:
            result = self.withdrawals(action["subject"]["lane"]).withdraw(
                binding["plan_id"], binding["plan_sha256"], REQUALIFY_REASON, action["rationale_ref"])
        except DeliveryRefused as exc:
            if exc.reason_code == "withdraw_unobservable":
                raise
            return self._effect(self._move(action, REFUSED, exc.reason_code))
        withdrawal = result.get("withdrawal") or {}
        row = self._move(action, REQUALIFYING, "delivery_withdrawn",
                         withdrawal={"cached": result.get("cached"), "previous_stage": withdrawal.get("previous_stage"),
                                     "main_effect": withdrawal.get("main_effect"),
                                     "observed_main": (withdrawal.get("observed") or {}).get("main")})
        return self._requalify(None, row)

    def _requalify(self, continuation, action: dict) -> dict:
        """The owner document is built ONCE on the main observed now and persisted before the call; every
        later attempt replays exactly those bytes (the existing API answers an identical one `cached`)."""
        binding = action["binding"]
        row = action
        if action.get("document") is None:
            policy = self.continuation.policy(binding["continuation_policy"]) if continuation is None else continuation
            if policy is None:
                raise OwnerActionRefused("continuation_policy_unregistered", "continuation_policy")
            lane = action["subject"]["lane"]
            with self.deliveries(lane).store.transaction() as tx:
                release = tx.get("releases", binding["release_id"])
            if not isinstance(release, dict):
                raise OwnerActionRefused("release_missing", "release_id")
            try:
                main = self.mainline(lane).remote_main()
            except Exception as exc:
                raise OwnerActionRefused("requalification_main_unreadable", "main_revision") from exc
            document = requalification_document(action, policy, release.get("candidate") or {}, main)
            row = self._move(action, REQUALIFYING, "requalification_document_persisted", document=document,
                             document_sha256=digest(document))
        try:
            result = self.requalify(row["document"])
        except ContinuationRefused as exc:
            if exc.reason_code in REQUALIFY_WAITS:
                raise
            return self._effect(self._move(row, REFUSED, exc.reason_code))
        return self._effect(self._move(row, COMPLETED, "requalification_recorded",
                                       requalified={"cached": result.get("cached"),
                                                    "requalification_intent": result.get("requalification_intent"),
                                                    "successor_job": result.get("successor_job")}))

    # ===== C3: asynchronous guarded research dispatch ================================================
    def _research_scope(self, intent: dict, intents: list, program_id: str) -> dict:
        """The held family's exact attempt set and its one investigation, and every durable row the ported
        RO-1 rule reads, in ONE control-store read; the ledger is read outside it."""
        attempts = sorted({a["job"] for a in research_attempts(intents, intent)})
        with self.store.transaction() as tx:
            rows = {name: tx.scan(name) for name in (BUCKET_PROGRAMS, BUCKET_DISPATCHES, BUCKET_RECOVERIES,
                                                     BUCKET_HEADS, BUCKET_INVESTIGATIONS, FLEET_JOBS, BUCKET_BINDINGS)}
        jobs = {job["id"]: job for job in rows[FLEET_JOBS] if isinstance(job, dict) and job.get("id") in attempts}
        if set(jobs) != set(attempts):
            raise OwnerActionRefused("research_attempt_unavailable", "attempts")
        families = {family_id(job.get("status"), job.get("reason_code")) for job in jobs.values()}
        if len(families) != 1:
            raise OwnerActionRefused("research_scope_mixed", "attempts")
        program = next((r for r in rows[BUCKET_PROGRAMS] if r.get("id") == program_id), None)
        room = None
        if isinstance(program, dict) and self.ledger is not None:
            try:
                room = headroom((program.get("config") or {}).get("budget"), self.ledger())
            except Exception:  # an unreadable ledger is uncertainty: wait, never tick
                room = None
        return {"attempts": attempts, "investigation": families.pop(), "program": program, "room": room,
                "rows": {"research_programs": rows[BUCKET_PROGRAMS],
                         "research_investigation_dispatches": rows[BUCKET_DISPATCHES],
                         "research_dispatch_recoveries": rows[BUCKET_RECOVERIES],
                         "research_dispatch_heads": rows[BUCKET_HEADS],
                         "portfolio_investigations": rows[BUCKET_INVESTIGATIONS], "fleet_jobs": rows[FLEET_JOBS],
                         "portfolio_bindings": rows[BUCKET_BINDINGS]}}

    def _research_decide(self, intent: dict, intents: list, program_id: str) -> tuple:
        scope = self._research_scope(intent, intents, program_id)
        decision = research_decision(program_id=program_id, investigation=scope["investigation"],
                                     attempts=scope["attempts"], rows=scope["rows"], room=scope["room"],
                                     now=self.clock())
        return scope, decision

    def _discover_research(self, row: dict, block: dict, intent: dict, intents: list) -> list:
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
        return self._create(row, RESEARCH_DISPATCH, binding, {"intent_id": intent["id"], "lane": intent.get("lane")})

    def _advance_dispatch(self, policy_row: dict, continuation: dict, action: dict) -> dict | None:
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
            return self._effect(self._move(action, REFUSED, "research_policy_changed"))
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, binding["intent_id"])
            intents = [r for r in tx.scan(CONTINUATION_INTENTS) if r.get("policy_id") == continuation["id"]]
            receipt = tx.get(CONTINUATION_RECEIPTS, binding["intent_id"])
        if not (isinstance(intent, dict) and intent.get("state") == RESEARCH_REQUIRED) or receipt is not None:
            return self._effect(self._move(action, REFUSED, "research_intent_not_held"))
        scope, decision = self._research_decide(intent, intents, binding["program_id"])
        if not decision["act"]:
            if decision["reason"] in RESEARCH_TRANSIENT:
                raise OwnerActionRefused(decision["reason"], "research")
            return self._effect(self._move(action, REFUSED, decision["reason"]))
        if (scope["investigation"], scope["attempts"], decision["detail"]["expected_cycle"]) != (
                binding["investigation"], binding["attempts"], binding["expected_cycle"]):
            return self._effect(self._move(action, REFUSED, "research_binding_changed"))
        try:
            probe = self.research.probe()
        except Exception as exc:
            probe = {"ok": False, "reason_code": "research_provider_probe_failed", "error_type": type(exc).__name__}
        if not (isinstance(probe, dict) and probe.get("ok") is True):
            # Before any resume, reservation or spawn: nothing is counted, nothing is left owned.
            return self._effect(self._move(action, REFUSED, "research_provider_unavailable",
                                           probe=_probe_view(probe)))
        if "resume" in decision["steps"]:
            ResearchProgram(self.store, clock=self.clock).resume(binding["program_id"])
        row = self._move(action, LAUNCHING, "research_launch_intended", launches=1,
                         launch_id=research_launch_id(action["id"], 1), child_lane=block["lane"],
                         probe=_probe_view(probe))
        return self._launch_dispatch(row)

    def _launch_dispatch(self, action: dict) -> dict:
        """ONE spawn per launch id (the port's exclusive marker makes a lost response or a restart
        `cached`); the tick never waits for the child."""
        self.research.start(action["launch_id"], action["binding"]["program_id"], action["child_lane"])
        return self._effect(self._move(action, RUNNING, "research_launched"))

    def _observe_dispatch(self, action: dict) -> dict | None:
        binding = action["binding"]
        launch = self.research.poll(action["launch_id"])
        state = launch.get("state")
        if state == LAUNCH_RUNNING:
            return None
        if state == LAUNCH_UNKNOWN or launch.get("cleanup_confirmed") is False:
            return self._effect(self._move(action, UNKNOWN, "research_launch_unknown", launch=_launch_view(launch)))
        with self.store.transaction() as tx:
            program = tx.get(BUCKET_PROGRAMS, binding["program_id"])
            cycle = tx.get(BUCKET_CYCLES, cycle_id(binding["program_id"], binding["expected_cycle"]))
            dispatch = tx.get(BUCKET_DISPATCHES, binding["investigation"])
        if state == LAUNCH_ABSENT:
            untouched = isinstance(program, dict) and program.get("active_cycle") is None \
                and program.get("next_cycle") == binding["expected_cycle"] and cycle is None
            if untouched and int(action.get("launches") or 0) < MAX_RESEARCH_LAUNCHES:
                # Fenced before it entered and the program provably unchanged: ONE bounded relaunch.
                sequence = int(action["launches"]) + 1
                row = self._move(action, LAUNCHING, "research_relaunched", launches=sequence,
                                 launch_id=research_launch_id(action["id"], sequence))
                return self._launch_dispatch(row)
            return self._effect(self._move(action, UNKNOWN, "research_launch_unknown", launch=_launch_view(launch)))
        outcome = research_outcome(binding, action["launch_id"], program, cycle, dispatch)
        return self._effect(self._move(action, outcome["state"], outcome["reason_code"],
                                       outcome={"launch": _launch_view(launch),
                                                "cycle": (cycle or {}).get("id") if isinstance(cycle, dict) else None,
                                                "dispatch_result": (dispatch or {}).get("result")
                                                if isinstance(dispatch, dict) else None}))


def _request_of(plan_action: dict) -> dict:
    """The one canary request a published plan files: a function of its immutable action row only."""
    return canary_request(plan_action, plan_action["plan"], plan_action["plan_sha256"], plan_action["published_at"])


# Requalification refusals that are an outage or another owner's open work, never a verdict on this action:
# the row stays where it is and the next tick replays the same persisted document.
REQUALIFY_WAITS = frozenset({"requalification_main_unreadable", "policy_unavailable", "requalification_family_open"})


def _probe_view(probe) -> dict:
    probe = probe if isinstance(probe, dict) else {}
    return {k: probe.get(k) for k in ("ok", "reason_code", "error_type", "codex", "node")}


def _launch_view(launch: dict) -> dict:
    return {k: launch.get(k) for k in ("state", "exit_code", "cleanup_confirmed", "reason_code")}


def _decided(verdict: dict) -> dict:
    """The executed decision's verdict as retained evidence; it is not a promotion by itself."""
    return {k: verdict.get(k) for k in ("verdict", "reason_code", "decision_id", "execution_ref")}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_json(plan: dict) -> bytes:
    """The exact bytes a plan is published as: canonical JSON and one newline."""
    return (canonical(plan) + "\n").encode("utf-8")


__all__ = ["BUCKET_ACTIONS", "BUCKET_POLICIES", "ActionChanged", "OwnerActions", "digest_bytes", "plan_json"]
