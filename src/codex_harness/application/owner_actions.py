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
"""
from __future__ import annotations

import hashlib
import re

from codex_harness.application.portfolio import family_id
from codex_harness.domain.continuation import (
    AWAITING_OWNER,
    DELIVERY,
    DELIVERY_ABSENT,
    DELIVERY_BOUND,
    DELIVERY_STALE,
    MIGRATION_SOURCE_STATES,
    MIXED_RECEIPT_SCHEMA,
    RESEARCH,
    RESEARCH_RECEIPT_SCHEMA,
    RESEARCH_REQUIRED,
    ContinuationRefused,
    bind_delivery,
    migration_resume,
    migration_source,
    observed_attempt,
    research_attempts,
)
from codex_harness.domain.host_delivery import (
    AWAITING_CONSUMPTION,
    CANARY_FLEET,
    MIGRATION_ACTIVE,
    MIGRATION_REGISTERED,
    MIGRATION_RESERVING,
    TERMINAL_STAGES,
    DeliveryRefused,
    consumption_verdict,
    descriptor_digest,
    migration_lineage_digest,
    migration_request_id,
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
    EVIDENCE_REF,
    INTENDED,
    INVOKING,
    MAX_ACTIONS_PER_TICK,
    MAX_ASSESSMENT_LAUNCHES,
    OWNER_PHASE,
    PUBLISHED,
    PUBLISHING,
    REFUSED,
    REJECTED,
    REQUESTED,
    RESEARCH_RECEIPT,
    STATUS_SCHEMA,
    TERMINAL,
    TICK_SCHEMA,
    UNKNOWN,
    VERDICT_ACCEPTED,
    VERDICT_REJECTED,
    VERDICT_UNKNOWN,
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
    plan_id_for,
    plan_path,
    plan_ref,
    policy_digest,
    research_binding,
    reusable_assessment,
    validate_policy,
    view,
)

BUCKET_POLICIES = "owner_action_policies"
BUCKET_ACTIONS = "owner_actions"
CONTINUATION_INTENTS = "continuation_intents"
CONTINUATION_RECEIPTS = "continuation_research_receipts"
FLEET_JOBS = "fleet_jobs"
DECISIONS = "decisions_pending"
# INV-OWNER-ACTIONS-MIGRATION-001: the control half of an evaluator migration. A bucket of its own, keyed
# by the rejected SOURCE release, that a coordinator of an older release never scans (its `_advance`
# only knows the three action kinds), so no new kind is ever written into `owner_actions`.
BUCKET_MIGRATIONS = "owner_action_migrations"
# The effective delivery binding of a migrated continuation intent, keyed by intent id. The conductor's
# own `release_id` on the intent stays untouched as provenance.
CONTINUATION_BINDINGS = "continuation_effective_bindings"
LANE_MIGRATIONS = "host_delivery_migrations"
EVALUATOR_MIGRATION = "evaluator_migration"
MIGRATION_DOCUMENT_FIELDS = frozenset({"policy_id", "intent_id", "lane", "target_id", "source_release_id",
                                       "source_policy_hash", "candidate_revision", "old_plan_id", "old_plan_sha256",
                                       "approval", "evidence", "actor"})
MIGRATION_APPROVAL_FIELDS = frozenset({"source_release_id", "base", "evaluator_revision", "evaluator_tree",
                                       "patch_sha256", "paths", "evidence", "approved_by"})
# INV-RELEASE-ENVIRONMENT-REVERIFY-001: the second migration kind, an environment reverification of an
# already migrated (and then rejected) successor. The document carries `kind`; an absent `kind` is the
# evaluator migration with its exact old shape, request and identity. The approval is exactly the
# Releases approval shape and must name the same source/plan/intent/policy/target/lane as the document.
ENVIRONMENT_REVERIFICATION = "environment_reverification"
MIGRATION_KINDS = frozenset({EVALUATOR_MIGRATION, ENVIRONMENT_REVERIFICATION})
ENVIRONMENT_APPROVAL_FIELDS = frozenset({"kind", "source_release_id", "source_policy_hash", "old_plan_id",
                                         "old_plan_sha256", "intent_id", "policy_id", "target_id", "lane",
                                         "fix_evidence", "controller_revision", "approved_by"})
_FIX_EVIDENCE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION40 = re.compile(r"^[0-9a-f]{40}$")
# Control states, each naming the step BEFORE its effect: `intended` (lane stage owed), `staged` (lane
# receipt recorded; successor plan action owed), `planning` (successor DELIVERY_PLAN action exists; its
# publication, canary request and held registration owed), `bound` (continuation effective binding
# recorded; the lane readiness acknowledgement owed).
M_STAGED, M_PLANNING, M_BOUND = "staged", "planning", "bound"
MIGRATION_TRANSITIONS = {INTENDED: {M_STAGED, REFUSED, UNKNOWN}, M_STAGED: {M_PLANNING, REFUSED, UNKNOWN},
                         M_PLANNING: {M_BOUND, REFUSED, UNKNOWN}, M_BOUND: {COMPLETED, REFUSED, UNKNOWN}}
# Lane refusals that name a transient condition, never a verdict: the row waits where it is. The
# controller-code preflight (INV-RELEASE-ENVIRONMENT-REVERIFY-001) waits too: code that changed after
# the request never consumes the one successor, and the approved deployed code stages it later.
MIGRATION_RETRYABLE = frozenset({"migration_unobservable", "migration_controller_running",
                                 "migration_controller_code_unavailable", "migration_controller_code_mismatch"})
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
    incumbent operation-manifest validator."""

    def __init__(self, store, *, continuation=None, org=None, lanes=None, deliveries=None, publisher=None,
                 assessments=None, targets=None, fleet=None, validate=None, clock=utcnow):
        self.store, self.continuation, self.org, self.lanes = store, continuation, org, lanes
        self.deliveries, self.publisher, self.assessments = deliveries, publisher, assessments
        self.targets, self.fleet, self.validate, self.clock = targets, fleet, validate, clock

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
            migrations = tx.scan(BUCKET_MIGRATIONS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            rows = [row for row in rows if row.get("policy_id") == policy_id]
            migrations = [row for row in migrations if row.get("policy_id") == policy_id]
        views = [view(row) for row in sorted(rows, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["kind"] + ":" + row["state"]] = counts.get(row["kind"] + ":" + row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"],
                              "policy_sha256": row["policy_sha256"], "pin": row["pin"]} for row in policies],
                "actions": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held": [row for row in views if row["state"] in {UNKNOWN, REJECTED, REFUSED}][-50:],
                "migrations": [_migration_status(row) for row in
                               sorted(migrations, key=lambda r: (str(r.get("created_at")), r["id"]))][-50:]}

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
        migrated = self._advance_migrations(row, continuation, waits)
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
        actions = migrated + actions
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
            migrating = [r for r in tx.scan(BUCKET_MIGRATIONS) if r.get("policy_id") == row["id"]]
        busy = {(a["kind"], (a.get("subject") or {}).get("intent_id")) for a in actions if a["state"] not in TERMINAL}
        # An intent under an open evaluator migration gets its plan ONLY from that migration.
        busy |= {(DELIVERY_PLAN, (m.get("subject") or {}).get("intent_id")) for m in migrating
                 if m["state"] not in TERMINAL}
        created = []
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
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
                   DELIVERY_CANARY: self._advance_canary}[action["kind"]]
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
                    "target": tx.get("host_delivery_targets", target_id),
                    "migrations": tx.scan(LANE_MIGRATIONS)}

    def _plan_binding(self, row: dict, intent: dict, *, migration: dict | None = None) -> dict | None:
        """A plan is owed only for a conducted delivery intent whose release is approved for exactly this
        target and has no delivery yet, while no other delivery is in flight on that target.

        `migration` (the control migration row, INV-OWNER-ACTIONS-MIGRATION-001) binds the plan to that
        migration's staged SUCCESSOR release instead of the conductor's release; only that migration's
        own lane reservation does not make the target busy for it."""
        if self.deliveries is None or self.publisher is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        policy = row["policy"]
        target_id = policy["delivery"]["target_id"]
        if intent.get("delivery_target") != target_id:
            return None
        release_id = intent.get("release_id") if migration is None else migration["successor_release_id"]
        rows = self._lane_rows(intent["lane"], target_id, release_id)
        release = rows["release"]
        if not isinstance(release, dict):
            raise OwnerActionRefused("release_missing", "release_id")
        candidate = release.get("candidate") or {}
        # The superseded source intent carries the same candidate revision: a successor binds only the
        # deliveries of its own release.
        scope = rows["intents"] if migration is None else [
            r for r in rows["intents"] if r.get("release_id") == release.get("id")]
        bound = bind_delivery(scope, target_id, release.get("id"), candidate.get("revision"), release)
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
        # A staged/registered lane migration reserves its target for every plan but its own successor.
        own = None if migration is None else migration["migration_id"]
        if any(m.get("target_id") == target_id and m.get("state") in MIGRATION_RESERVING
               and m.get("migration_id") != own for m in rows["migrations"]):
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
        migration = (action.get("subject") or {}).get("migration")
        try:
            if isinstance(migration, dict):
                # The migration's own successor plan registers HELD until the control acknowledgement.
                registered = delivery.register_migration_plan(loaded["plan"], loaded["pin"],
                                                              migration["migration_id"])
            else:
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

    # ===== H1: the owner's evaluator migration of a rejected, merged delivery ========================
    # INV-OWNER-ACTIONS-MIGRATION-001: an ordered durable outbox across the control store and the lane
    # store, never one transaction across both. Each step re-reads its durable inputs, calls one
    # idempotent lane/control effect and records its receipt by a version CAS; a lost response or a
    # restart replays the same step. A lane refusal is REFUSED with the lane's reason; an outage waits.
    def request_migration(self, document) -> dict:
        """Record ONE owner-only migration request per rejected source release (control store).

        The document is validated against the control records: the owner policy, the continuation
        delivery intent naming exactly this release/target/lane, and the ORIGINAL completed DELIVERY_PLAN
        action of `old_plan_id` (kept untouched as history). The identical document replays; any other
        document for the same source refuses `migration_conflict`."""
        document = _migration_document(document)
        source, kind = document["source_release_id"], _kind(document)
        request = {"old_plan_id": document["old_plan_id"], "old_plan_sha256": document["old_plan_sha256"],
                   "source_release_id": source, "source_policy_hash": document["source_policy_hash"],
                   "candidate_revision": document["candidate_revision"], "target_id": document["target_id"],
                   "actor": document["actor"], "approval": document["approval"]}
        if kind != EVALUATOR_MIGRATION:
            request["kind"] = kind      # absent for the evaluator kind: its request identity is unchanged
        request = {"migration_id": migration_request_id(request), **request}
        controller = None
        if kind == ENVIRONMENT_REVERIFICATION:
            with self.store.transaction() as tx:
                known = tx.get(BUCKET_MIGRATIONS, source) is not None
            if not known:
                controller = self._require_controller_code(document)
        now = self.clock()
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_MIGRATIONS, source)
            if old is not None:
                if old.get("document") != document:
                    raise OwnerActionRefused("migration_conflict", "source_release_id")
                return {**_migration_view(old), "cached": True}
            policy_row = tx.get(BUCKET_POLICIES, document["policy_id"])
            intent = tx.get(CONTINUATION_INTENTS, document["intent_id"])
            plans = [r for r in tx.scan(BUCKET_ACTIONS)
                     if r.get("kind") == DELIVERY_PLAN and r.get("plan_id") == document["old_plan_id"]]
            _check_migration_source(document, policy_row, intent, plans)
            if kind == ENVIRONMENT_REVERIFICATION:
                _check_environment_source(document, intent, tx.get(CONTINUATION_BINDINGS, document["intent_id"]),
                                          tx.get)
            identity = digest(["owner-action", kind, {"source_release_id": source}])
            row = {"id": source, "action_id": identity, "kind": kind, "state": INTENDED,
                   "document": document, "document_sha256": digest(document), "request": request,
                   "migration_id": request["migration_id"], "policy_id": document["policy_id"],
                   "old_action_id": plans[0]["id"],
                   # The exact source intent (policy, lane, target, release, route, state, version) every
                   # later step re-checks; only the finalizing step may resume it, and only this snapshot.
                   "source_intent": migration_source(intent),
                   "subject": {"intent_id": document["intent_id"], "lane": document["lane"],
                               "source_release_id": source, "old_plan_id": document["old_plan_id"]},
                   "reason_code": None, "created_at": now, "updated_at": now, "version": 1,
                   "history": [{"state": INTENDED, "at": now, "reason_code": None}]}
            if controller is not None:
                row["controller_code"] = controller      # the preflight's resolution, not the request's
            tx.put(BUCKET_MIGRATIONS, source, row)
        return {**_migration_view(row), "cached": False}

    def _require_controller_code(self, document: dict) -> str:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001 creation preflight at the owner/lane boundary, before the
        request row exists: the lane's trusted port resolves the ACTUAL running controller code and it
        must be the approved revision. A refusal writes nothing, so the source, its intent and the one
        source-keyed request identity stay unused for the approved deployed code."""
        if self.deliveries is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        try:
            return self.deliveries(document["lane"]).require_controller_code(
                document["approval"]["controller_revision"])
        except DeliveryRefused as exc:
            raise OwnerActionRefused(exc.reason_code, "controller_revision") from exc

    def migration(self, source_release_id: str) -> dict | None:
        """Read-only projection of one migration row; None when absent."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_MIGRATIONS, source_release_id)
        return None if row is None else _migration_view(row)

    def _advance_migrations(self, policy_row: dict, continuation: dict, waits: dict) -> list:
        with self.store.transaction() as tx:
            rows = sorted((r for r in tx.scan(BUCKET_MIGRATIONS)
                           if r.get("policy_id") == policy_row["id"] and r["state"] not in TERMINAL),
                          key=lambda r: (str(r.get("created_at")), r["id"]))
        effects = []
        for row in rows[:MAX_ACTIONS_PER_TICK]:
            try:
                effect = self._advance_migration(policy_row, row)
            except ActionChanged:
                effect = None
            except (ContractError, OSError, RuntimeError, ValueError) as exc:
                waits[row["action_id"]] = getattr(exc, "reason_code", None) or type(exc).__name__
                effect = None
            if effect is not None:
                effects.append(effect)
        return effects

    def _migration_move(self, row: dict, target: str, reason_code: str | None = None, *, extra=None,
                        **fields) -> dict:
        """Compare-and-swap on the migration row's version, under its own transition table."""
        if target not in MIGRATION_TRANSITIONS.get(row["state"], set()):
            raise OwnerActionRefused("invalid_transition", row["state"] + "->" + target)
        now = self.clock()
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_MIGRATIONS, row["id"])
            if not (isinstance(current, dict) and current.get("version") == row.get("version")):
                raise ActionChanged(row["id"])
            history = (list(current.get("history") or []) + [{"state": target, "at": now,
                                                               "reason_code": reason_code}])[-32:]
            moved_row = {**current, **fields, "state": target, "reason_code": reason_code, "updated_at": now,
                         "version": int(current.get("version") or 0) + 1, "history": history}
            if extra is not None:
                extra(tx)
            tx.put(BUCKET_MIGRATIONS, moved_row["id"], moved_row)
        return moved_row

    @staticmethod
    def _migration_effect(row: dict) -> dict:
        return {"action": row["action_id"], "kind": _kind(row), "state": row["state"],
                "reason_code": row["reason_code"]}

    def _lane_refused(self, row: dict, exc: DeliveryRefused) -> dict:
        if exc.reason_code in MIGRATION_RETRYABLE:
            raise exc
        return self._migration_effect(self._migration_move(row, REFUSED, exc.reason_code))

    def _advance_migration(self, policy_row: dict, row: dict) -> dict | None:
        if self.deliveries is None or self.publisher is None:
            raise OwnerActionRefused("delivery_ports_unconfigured", "deliveries")
        state, lane = row["state"], row["subject"]["lane"]
        delivery = self.deliveries(lane)
        if state == INTENDED:
            try:
                record = delivery.stage_migration(row["request"])
            except DeliveryRefused as exc:
                return self._lane_refused(row, exc)
            receipt = _stage_receipt(row, record)
            if receipt is None:
                return self._migration_effect(self._migration_move(row, UNKNOWN, "migration_receipt_mismatch"))
            return self._migration_effect(self._migration_move(
                row, M_STAGED, "migration_staged", lane_receipt=receipt, lane_receipt_sha256=digest(receipt),
                successor_release_id=receipt["successor_release_id"]))
        if state == M_STAGED:
            return self._plan_successor(policy_row, row)
        if state == M_PLANNING:
            return self._bind_successor(row, delivery)
        if state == M_BOUND:
            return self._finalize(row, delivery)
        return None

    def _current_intent(self, row: dict) -> dict:
        """The continuation intent, re-read; it must still be exactly the recorded source snapshot
        (policy, lane, target, release, route, state AND version)."""
        with self.store.transaction() as tx:
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
        if not _source_unchanged(row, intent):
            raise OwnerActionRefused("migration_intent_changed", "intent_id")
        return intent

    def _plan_successor(self, policy_row: dict, row: dict) -> dict:
        """Create the migration's successor DELIVERY_PLAN action in the SAME control transaction that
        records it on the migration row: both or neither."""
        try:
            intent = self._current_intent(row)
        except OwnerActionRefused as exc:
            return self._migration_effect(self._migration_move(row, REFUSED, exc.reason_code))
        migration = {"migration_id": row["migration_id"], "successor_release_id": row["successor_release_id"]}
        binding = self._plan_binding(policy_row, intent, migration=migration)
        if binding is None:
            return self._migration_effect(self._migration_move(row, UNKNOWN, "migration_plan_not_owed"))
        identity = action_id(DELIVERY_PLAN, binding)
        subject = {"intent_id": intent["id"], "lane": row["subject"]["lane"],
                   "migration": {"migration_action_id": row["action_id"], "migration_id": row["migration_id"],
                                 "source_release_id": row["id"],
                                 "successor_release_id": row["successor_release_id"]}}
        now = self.clock()

        def create(tx):
            existing = tx.get(BUCKET_ACTIONS, identity)
            if existing is None:
                tx.put(BUCKET_ACTIONS, identity, new_action(DELIVERY_PLAN, binding, policy_row, subject, now))
            elif existing.get("subject") != subject:
                raise OwnerActionRefused("migration_plan_conflict", "plan_id")

        return self._migration_effect(self._migration_move(
            row, M_PLANNING, "successor_plan_intended", extra=create, plan_action_id=identity,
            plan_id=plan_id_for(identity)))

    def _bind_successor(self, row: dict, delivery) -> dict | None:
        """Once the successor plan is published, read back, its canary request filed and its registration
        HELD in the lane, record the continuation's effective binding (CAS on the intent)."""
        with self.store.transaction() as tx:
            plan_action = tx.get(BUCKET_ACTIONS, row["plan_action_id"])
        if not isinstance(plan_action, dict):
            return self._migration_effect(self._migration_move(row, UNKNOWN, "migration_plan_action_missing"))
        if plan_action["state"] in {REFUSED, UNKNOWN, REJECTED}:
            target = REFUSED if plan_action["state"] == REFUSED else UNKNOWN
            return self._migration_effect(self._migration_move(
                row, target, "successor_plan_" + str(plan_action.get("reason_code") or plan_action["state"])))
        if plan_action["state"] != COMPLETED:
            return None     # the existing tick is publishing/registering it
        with delivery.store.transaction() as tx:
            record = tx.get(LANE_MIGRATIONS, row["subject"]["old_plan_id"])
            target = tx.get("host_delivery_targets", row["document"]["target_id"])
        if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
                and record.get("state") in {MIGRATION_REGISTERED, MIGRATION_ACTIVE}
                and record.get("plan_id") == plan_action["plan_id"]
                and record.get("plan_sha256") == plan_action["plan_sha256"]
                and record.get("successor_release_id") == row["successor_release_id"]):
            raise OwnerActionRefused("migration_registration_unobserved", "plan_id")
        if plan_action["plan"]["canary_check_id"] == CANARY_FLEET and (
                self.targets is None or target is None
                or self.targets.request(target, plan_action["plan_id"]) != _request_of(plan_action)):
            raise OwnerActionRefused("migration_canary_request_missing", "plan_id")
        try:
            self._current_intent(row)
        except OwnerActionRefused as exc:
            return self._migration_effect(self._migration_move(row, REFUSED, exc.reason_code))
        effective = {"intent_id": row["subject"]["intent_id"], "source_release_id": row["id"],
                     "successor_release_id": row["successor_release_id"], "old_plan_id": row["subject"]["old_plan_id"],
                     "plan_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
                     "plan_sha256": plan_action["plan_sha256"], "migration_id": row["migration_id"],
                     "migration_action_id": row["action_id"], "revision": row["document"]["candidate_revision"],
                     "target_id": row["document"]["target_id"]}

        def bind(tx):
            intent = tx.get(CONTINUATION_INTENTS, effective["intent_id"])
            if not _source_unchanged(row, intent):
                raise OwnerActionRefused("migration_intent_changed", "intent_id")
            old = tx.get(CONTINUATION_BINDINGS, effective["intent_id"])
            if old is None and _kind(row) == EVALUATOR_MIGRATION:
                tx.put(CONTINUATION_BINDINGS, effective["intent_id"], {
                    "id": effective["intent_id"], "binding": effective, "binding_sha256": digest(effective),
                    "at": self.clock()})
            elif isinstance(old, dict) and old.get("binding") == effective:
                return
            elif (_kind(row) == ENVIRONMENT_REVERIFICATION and isinstance(old, dict)
                  and (old.get("binding") or {}).get("successor_release_id") == row["id"]
                  and (old.get("binding") or {}).get("plan_id") == row["subject"]["old_plan_id"]):
                # INV-RELEASE-ENVIRONMENT-REVERIFY-001: the second hop replaces exactly the binding whose
                # successor is this source; the replaced binding is kept (digest + body) as the prior hop.
                tx.put(CONTINUATION_BINDINGS, effective["intent_id"], {
                    "id": effective["intent_id"], "binding": effective, "binding_sha256": digest(effective),
                    "previous": {"binding": old.get("binding"), "binding_sha256": old.get("binding_sha256")},
                    "at": self.clock()})
            else:
                raise OwnerActionRefused("migration_binding_conflict", "intent_id")

        return self._migration_effect(self._migration_move(
            row, M_BOUND, "continuation_bound", extra=bind, effective=effective,
            effective_sha256=digest(effective)))

    def _finalize(self, row: dict, delivery) -> dict:
        """The durable readiness acknowledgement (INV-OWNER-ACTIONS-MIGRATION-001). The step FIRST
        re-observes the whole ready record, each from its own owner and never inside a control-store
        transaction: the successor DELIVERY_PLAN action (completed, the recorded plan id/hash), the
        effective binding and the exact source intent snapshot, the lane migration record (registered,
        same plan id/hash), the published Git pin (the action's plan and bytes hash) and the plan-scoped
        canary request (`not_requested` for a non-fleet canary). Anything missing, unreadable, replaced
        or mismatched is a named `migration_readiness_*` wait: the row stays `bound` and no ack is sent.
        A lane record already active with the identical ack (a lost finalize response) completes without
        any further readiness read or effect."""
        with self.store.transaction() as tx:
            plan_action = tx.get(BUCKET_ACTIONS, row["plan_action_id"])
            bound = tx.get(CONTINUATION_BINDINGS, row["subject"]["intent_id"])
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
        effective = row["effective"]
        if not (isinstance(plan_action, dict) and plan_action.get("state") == COMPLETED
                and plan_action.get("id") == effective["plan_action_id"]
                and plan_action.get("plan_id") == effective["plan_id"]
                and plan_action.get("plan_sha256") == effective["plan_sha256"]):
            raise OwnerActionRefused("migration_readiness_plan_action", "plan_id")
        if not (isinstance(bound, dict) and bound.get("binding") == effective):
            raise OwnerActionRefused("migration_readiness_binding", "intent_id")
        if not _source_unchanged(row, intent):
            raise OwnerActionRefused("migration_readiness_source_intent", "intent_id")
        ack = migration_ack(row, plan_action)
        with delivery.store.transaction() as tx:
            record = tx.get(LANE_MIGRATIONS, row["subject"]["old_plan_id"])
            target = tx.get("host_delivery_targets", row["document"]["target_id"])
        if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
                and record.get("plan_id") == plan_action["plan_id"]
                and record.get("plan_sha256") == plan_action["plan_sha256"]
                and record.get("successor_release_id") == row["successor_release_id"]
                and record.get("state") in {MIGRATION_REGISTERED, MIGRATION_ACTIVE}):
            raise OwnerActionRefused("migration_readiness_lane_record", "plan_id")
        if record["state"] == MIGRATION_ACTIVE:
            if record.get("ack") != ack:
                raise OwnerActionRefused("migration_readiness_ack_conflict", "ack")
            return self._complete(row, plan_action, ack, {"cached": True, "state": MIGRATION_ACTIVE}, None)
        ready = {"plan_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
                 "plan_sha256": plan_action["plan_sha256"], "bytes_sha256": self._observe_pin(row, plan_action),
                 "canary_request_id": self._observe_request(plan_action, target),
                 "binding_sha256": digest(effective), "source_intent": row["source_intent"],
                 "lane_record": {"state": record["state"], "request_sha256": record.get("request_sha256")}}
        if ready["canary_request_id"] != ack["canary_request_id"]:
            raise OwnerActionRefused("migration_readiness_canary_request_replaced", "plan_id")
        try:
            result = delivery.finalize_migration(row["migration_id"], ack)
        except DeliveryRefused as exc:
            return self._lane_refused(row, exc)
        if not (isinstance(result, dict) and result.get("state") == MIGRATION_ACTIVE
                and result.get("plan_id") == ack["plan_id"] and result.get("plan_sha256") == ack["plan_sha256"]):
            return self._migration_effect(self._migration_move(row, UNKNOWN, "migration_ack_unconfirmed"))
        return self._complete(row, plan_action, ack, {"cached": result.get("cached"), "state": result.get("state")},
                              ready)

    def _observe_pin(self, row: dict, plan_action: dict) -> str:
        """The published pin, read back now: exactly the action's plan and bytes hash."""
        try:
            loaded = self.publisher(row["subject"]["lane"]).load(plan_action["commit"], plan_action["path"])
        except (ContractError, OSError, RuntimeError, ValueError, KeyError, TypeError):
            raise OwnerActionRefused("migration_readiness_pin_unreadable", "plan_id") from None
        if not (isinstance(loaded, dict) and loaded.get("plan") == plan_action["plan"]
                and (loaded.get("pin") or {}).get("sha256") == plan_action["bytes_sha256"]):
            raise OwnerActionRefused("migration_readiness_pin_mismatch", "plan_id")
        return plan_action["bytes_sha256"]

    def _observe_request(self, plan_action: dict, target) -> str:
        """The plan-scoped canary request, read now; `not_requested` only for a non-fleet canary."""
        if plan_action["plan"]["canary_check_id"] != CANARY_FLEET:
            return "not_requested"
        if self.targets is None or not isinstance(target, dict):
            raise OwnerActionRefused("migration_readiness_canary_unconfigured", "targets")
        try:
            observed = self.targets.request(target, plan_action["plan_id"])
        except (ContractError, OSError, RuntimeError, ValueError):
            raise OwnerActionRefused("migration_readiness_canary_request_unreadable", "plan_id") from None
        if observed is None:
            raise OwnerActionRefused("migration_readiness_canary_request_missing", "plan_id")
        if observed != _request_of(plan_action):
            raise OwnerActionRefused("migration_readiness_canary_request_replaced", "plan_id")
        return digest(observed)

    def _complete(self, row: dict, plan_action: dict, ack: dict, finalized: dict, ready) -> dict:
        """bound -> completed, and in the SAME control transaction the one authorized resume of exactly
        the recorded source intent (PAUSED -> the delivery-observing state); a moved source refuses
        `migration_source_changed` inside it and nothing is written (the row stays bound, a wait)."""
        lineage = lineage_of(row, plan_action)
        now = self.clock()

        def resume(tx):
            intent = tx.get(CONTINUATION_INTENTS, row["subject"]["intent_id"])
            resumed = migration_resume(intent, row["source_intent"],
                                       {"migration_action_id": row["action_id"], **lineage}, now)
            if resumed is not None:
                tx.put(CONTINUATION_INTENTS, resumed["id"], resumed)

        return self._migration_effect(self._migration_move(
            row, COMPLETED, "migration_finalized", extra=resume, ack=ack, lineage=lineage, finalized=finalized,
            readiness=ready, source_resumed=row["source_intent"].get("state") != AWAITING_OWNER))


def _request_of(plan_action: dict) -> dict:
    """The one canary request a published plan files: a function of its immutable action row only."""
    return canary_request(plan_action, plan_action["plan"], plan_action["plan_sha256"], plan_action["published_at"])


def _kind(document: dict) -> str:
    """The migration kind of a document or control row; absent is the evaluator migration."""
    return document.get("kind") or EVALUATOR_MIGRATION


def _migration_document(document) -> dict:
    """The exact owner-only migration document shape (INV-OWNER-ACTIONS-MIGRATION-001). An optional
    `kind` selects the environment reverification (INV-RELEASE-ENVIRONMENT-REVERIFY-001); an explicit
    `evaluator_migration` is normalized away so the evaluator document keeps its one identity."""
    if not isinstance(document, dict) or set(document) - {"kind"} != MIGRATION_DOCUMENT_FIELDS:
        raise OwnerActionRefused("migration_document_invalid", "document")
    if "kind" in document:
        if document["kind"] not in MIGRATION_KINDS:
            raise OwnerActionRefused("migration_document_invalid", "kind")
        if document["kind"] == EVALUATOR_MIGRATION:
            document = {k: v for k, v in document.items() if k != "kind"}
    for key in MIGRATION_DOCUMENT_FIELDS - {"approval"}:
        if type(document[key]) is not str or not document[key]:
            raise OwnerActionRefused("migration_document_invalid", key)
    if not EVIDENCE_REF.fullmatch(document["evidence"]):
        raise OwnerActionRefused("migration_document_invalid", "evidence")
    approval = document["approval"]
    if _kind(document) == ENVIRONMENT_REVERIFICATION:
        _check_environment_approval(document, approval)
        return document
    if not isinstance(approval, dict) or set(approval) != MIGRATION_APPROVAL_FIELDS:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if approval["source_release_id"] != document["source_release_id"] or approval["evidence"] != document["evidence"]:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    return document


def _check_environment_approval(document: dict, approval) -> None:
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: exactly the Releases approval shape, consistent with the
    document in every shared identity; refused before any read or effect."""
    if not isinstance(approval, dict) or set(approval) != ENVIRONMENT_APPROVAL_FIELDS:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if any(type(value) is not str or not value for value in approval.values()):
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if approval["kind"] != ENVIRONMENT_REVERIFICATION:
        raise OwnerActionRefused("migration_approval_invalid", "kind")
    for key in ("source_release_id", "source_policy_hash", "old_plan_id", "old_plan_sha256", "intent_id",
                "policy_id", "target_id", "lane"):
        if approval[key] != document[key]:
            raise OwnerActionRefused("migration_approval_invalid", key)
    if not _FIX_EVIDENCE.fullmatch(approval["fix_evidence"]):
        raise OwnerActionRefused("migration_approval_invalid", "fix_evidence")
    if not _REVISION40.fullmatch(approval["controller_revision"]):
        raise OwnerActionRefused("migration_approval_invalid", "controller_revision")


def _check_environment_source(document: dict, intent: dict, bound, get) -> None:
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: the source of an environment reverification is the
    SUCCESSOR of a completed evaluator migration of this very intent: the intent's effective binding
    names it (and the old plan) and the migration row of the conductor's release is completed. The
    conductor's `release_id` on the intent stays the provenance (the first hop's source)."""
    binding = (bound or {}).get("binding") if isinstance(bound, dict) else None
    if not (isinstance(binding, dict) and binding.get("successor_release_id") == document["source_release_id"]
            and binding.get("plan_id") == document["old_plan_id"]
            and binding.get("source_release_id") == intent.get("release_id")
            and binding.get("target_id") == document["target_id"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")
    first = get(BUCKET_MIGRATIONS, binding["source_release_id"])
    if not (isinstance(first, dict) and first.get("state") == COMPLETED and _kind(first) == EVALUATOR_MIGRATION
            and first.get("successor_release_id") == document["source_release_id"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")


def _check_migration_source(document: dict, policy_row, intent, plans: list) -> None:
    """The control records the document must name exactly; the original plan action stays history."""
    if not isinstance(policy_row, dict):
        raise OwnerActionRefused("policy_unregistered", "policy_id")
    policy = policy_row["policy"]
    if policy["delivery"]["target_id"] != document["target_id"]:
        raise OwnerActionRefused("delivery_target_mismatch", "target_id")
    if not (isinstance(intent, dict) and intent.get("route") == DELIVERY
            and intent.get("state") in MIGRATION_SOURCE_STATES and type(intent.get("version")) is int
            and intent.get("policy_id") == policy["continuation_policy"]
            # an environment reverification's source is the intent's effective successor, checked apart
            and (_kind(document) == ENVIRONMENT_REVERIFICATION
                 or intent.get("release_id") == document["source_release_id"])
            and intent.get("delivery_target") == document["target_id"] and intent.get("lane") == document["lane"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")
    if len(plans) != 1:
        raise OwnerActionRefused("migration_plan_action_missing", "old_plan_id")
    plan = plans[0]
    binding = plan.get("binding") or {}
    if not (plan.get("state") == COMPLETED and plan.get("policy_id") == document["policy_id"]
            and plan.get("plan_sha256") == document["old_plan_sha256"]
            and (plan.get("subject") or {}).get("intent_id") == document["intent_id"]
            and binding.get("release_id") == document["source_release_id"]
            and binding.get("revision") == document["candidate_revision"]
            and binding.get("policy_hash") == document["source_policy_hash"]
            and binding.get("target_id") == document["target_id"]):
        raise OwnerActionRefused("migration_plan_action_mismatch", "old_plan_id")


def _source_unchanged(row: dict, intent) -> bool:
    """The recorded source snapshot still names exactly this intent; a row without one never proceeds."""
    document, recorded = row["document"], row.get("source_intent")
    return (isinstance(intent, dict) and isinstance(recorded, dict) and migration_source(intent) == recorded
            and (_kind(document) == ENVIRONMENT_REVERIFICATION
                 or intent.get("release_id") == document["source_release_id"])
            and intent.get("delivery_target") == document["target_id"] and intent.get("lane") == document["lane"]
            and intent.get("route") == DELIVERY)


def _stage_receipt(row: dict, record) -> dict | None:
    """The lane's stage receipt, exactly hash-linked to this row's request; None on any mismatch."""
    request = row["request"]
    if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
            and record.get("request_sha256") == digest(request)
            and record.get("source_release_id") == request["source_release_id"]
            and record.get("target_id") == request["target_id"]
            and record.get("old_plan_id", request["old_plan_id"]) == request["old_plan_id"]
            and record.get("state") in {"staged", MIGRATION_REGISTERED, MIGRATION_ACTIVE}
            and type(record.get("successor_release_id")) is str and record["successor_release_id"]
            and record["successor_release_id"] != request["source_release_id"]):
        return None
    return {"migration_id": record["migration_id"], "request_sha256": record["request_sha256"],
            "source_release_id": record["source_release_id"], "successor_release_id": record["successor_release_id"],
            "target_id": record["target_id"], "old_plan_id": request["old_plan_id"]}


def lineage_of(row: dict, plan_action: dict) -> dict:
    return {"source_release_id": row["id"], "successor_release_id": row["successor_release_id"],
            "old_plan_id": row["subject"]["old_plan_id"], "plan_id": plan_action["plan_id"],
            "migration_id": row["migration_id"]}


def migration_ack(row: dict, plan_action: dict) -> dict:
    """The readiness acknowledgement: a function of durable control rows only, so a replay is identical."""
    fleet = plan_action["plan"]["canary_check_id"] == CANARY_FLEET
    return {"control_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
            "plan_sha256": plan_action["plan_sha256"], "request_sha256": row["lane_receipt"]["request_sha256"],
            "canary_request_id": digest(_request_of(plan_action)) if fleet else "not_requested",
            "lineage_sha256": migration_lineage_digest(**lineage_of(row, plan_action))}


def _migration_status(row: dict) -> dict:
    """R-OBS: one migration's owner-facing status (read-only): state, its phase history and last reason,
    the lineage identities and the effective owner (policy/lane) of the source intent."""
    subject = row.get("subject") or {}
    return {"source_release_id": row.get("id"), "kind": _kind(row), "state": row.get("state"),
            "reason_code": row.get("reason_code"),
            "phases": [{"state": h.get("state"), "reason_code": h.get("reason_code"), "at": h.get("at")}
                       for h in (row.get("history") or [])][-8:],
            "successor_release_id": row.get("successor_release_id"), "plan_id": row.get("plan_id"),
            "intent_id": subject.get("intent_id"), "source_intent_state": (row.get("source_intent") or {}).get("state"),
            "owner": {"policy_id": row.get("policy_id"), "lane": subject.get("lane")},
            "version": row.get("version")}


def _migration_view(row: dict) -> dict:
    shown = {k: row.get(k) for k in ("id", "action_id", "kind", "state", "reason_code", "migration_id",
                                     "document_sha256", "policy_id", "subject", "old_action_id",
                                     "successor_release_id", "plan_action_id", "plan_id", "lane_receipt_sha256",
                                     "effective_sha256", "created_at", "updated_at", "version")}
    for key in ("ack", "lineage"):
        if row.get(key) is not None:
            shown[key] = row[key]
    return shown


def _decided(verdict: dict) -> dict:
    """The executed decision's verdict as retained evidence; it is not a promotion by itself."""
    return {k: verdict.get(k) for k in ("verdict", "reason_code", "decision_id", "execution_ref")}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_json(plan: dict) -> bytes:
    """The exact bytes a plan is published as: canonical JSON and one newline."""
    return (canonical(plan) + "\n").encode("utf-8")


__all__ = ["BUCKET_ACTIONS", "BUCKET_MIGRATIONS", "BUCKET_POLICIES", "CONTINUATION_BINDINGS", "ENVIRONMENT_REVERIFICATION",
           "EVALUATOR_MIGRATION",
           "MIGRATION_DOCUMENT_FIELDS", "ActionChanged", "OwnerActions", "digest_bytes", "lineage_of",
           "migration_ack", "plan_json"]
