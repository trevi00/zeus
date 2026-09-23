"""Durable conductor continuation over the existing Fleet, lanes and owners (INV-CONTINUATION-001).

A thin coordinator, not a second executor, scheduler, reviewer or release authority. It owns two
buckets in the Fleet control store - `continuation_policies` (one registered Git-pinned owner
policy per id) and `continuation_intents` (one durable intent per routed observation) - and one in
each lane store, `continuation_bindings` (the trusted document a lane Operation claim attaches to
its assignment). Everything else is reached through its existing owner:

* `Fleet.enqueue` admits a successor (same id on every replay; the Fleet's own lanes, paths,
  pause and ledger decide when it runs) and finite `zeus operate run` executes it unchanged.
* `WorkerSessions.record_review` moves the logical session on the committed independent review
  decision row; the executor resumes it natively only from `correction_ready`.
* The conductor port runs the existing guarded `Executor.decide_one("conductor", expected=...)`
  for exactly the pending conductor row; the Releases/ReleaseQueue records it writes are read back.
* HostDelivery and the approved backlog stay the owners of delivery and of the next item; the
  controller records the handoff and observes their durable result.
* The existing Portfolio investigation is the research owner after two distinct similar failures.

One tick is a few short store transactions with every external effect strictly between them: no
transaction is open across a lane store, Git, a process or the Fleet's own transaction. Each effect
is preceded by a durable intent state and followed by its observed evidence, and each state change
is a compare-and-swap on the intent version, so two controllers and a restart converge on one
intent, one successor id and one dispatch. An idle tick writes nothing and calls nothing.
"""
from __future__ import annotations

from codex_harness.domain.continuation import (
    ADMITTED,
    AUTHORITY,
    AWAITING_OWNER,
    BINDING_SCHEMA,
    COMPLETED,
    CONDUCTOR,
    CORRECTION,
    DELIVERY,
    DISPATCHED,
    EVIDENCE_REPAIR,
    INTENDED,
    MAX_HISTORY,
    NEXT_ITEM,
    PAUSED,
    PUBLISHED,
    RECOVERY,
    RECOVERY_REQUIRED,
    REFUSED,
    RESEARCH,
    RESEARCH_REQUIRED,
    RETURNED,
    ROUTE_OWNERS,
    STATUS_SCHEMA,
    SUCCESSOR_ROUTES,
    TICK_SCHEMA,
    ContinuationRefused,
    attempt_of,
    blocked_families,
    check_scope,
    classify,
    evidence_digest,
    fair_order,
    intent_id,
    needs_research,
    policy_digest,
    refuse,
    successor_id,
    successor_manifest,
    transition,
    validate_binding,
    validate_policy,
    view,
)
from codex_harness.domain.model import ContractError, utcnow

BUCKET_POLICIES = "continuation_policies"
BUCKET_INTENTS = "continuation_intents"
LANE_BINDINGS = "continuation_bindings"
FLEET_JOBS = "fleet_jobs"
INVESTIGATIONS = "portfolio_investigations"
EVENT_TRANSITION = "operations.continuation_transition"
EVENT_BLOCKED = "operations.continuation_blocked"
TERMINAL_JOBS = frozenset({"accepted", "rejected", "failed", "exhausted", "unknown"})
MARKERS = frozenset({"unconfirmed", "pending_reconciliation"})
DELIVERY_ACTIVE = "active"
DELIVERY_HALTED = frozenset({"rolled_back", "failed", "blocked"})


class IntentChanged(ContractError):
    """Another controller (or a restart replay) moved the intent first; nothing was written here."""


# ---- one lane store -----------------------------------------------------------------------------
class LaneEvidence:
    """Reads and the two narrow effects on ONE lane store. Every method is its own short
    transaction; `sessions` is the lane's `WorkerSessions` owner (None: no session effect)."""

    def __init__(self, store, sessions=None):
        self.store, self.sessions = store, sessions

    def read(self, job: dict) -> dict:
        """The decisive lane evidence of one terminal job, from store reads only."""
        with self.store.transaction() as tx:
            operation = tx.get("operations", job["operation_id"])
            binding = tx.get(LANE_BINDINGS, job["operation_id"])
            evidence = {"operation": operation, "binding": binding, "task": None, "lead": None,
                        "conductor": None, "delivery": None, "session": None, "markers": []}
            if not isinstance(operation, dict):
                return evidence
            # An evidence-refused operation names its candidate task only in its owner handoff.
            handoff = operation.get("owner_handoff") if isinstance(operation.get("owner_handoff"), dict) else {}
            task_id = operation.get("task_id") or handoff.get("task_id")
            decision_id = operation.get("decision_id")
            if isinstance(task_id, str):
                evidence["task"] = tx.get("tasks", task_id)
            if isinstance(decision_id, str):
                evidence["lead"] = tx.get("decisions_pending", decision_id)
            owned = {task_id, decision_id} - {None}
            evidence["markers"] = sorted(
                record.get("record_id") or record.get("task_id") for record in tx.scan("observation_terminations")
                if isinstance(record, dict) and record.get("status") in MARKERS and record.get("task_id") in owned)
            if operation.get("status") == "accepted" and isinstance(decision_id, str):
                conductor = [row for row in tx.scan("decisions_pending")
                             if row.get("phase") == "review_conductor"
                             and ((row.get("message") or {}).get("what") or {}).get("details", {}).get(
                                 "decision_id") == decision_id]
                evidence["conductor"] = conductor[0] if conductor else None
                result = (evidence["conductor"] or {}).get("result") or {}
                release_id = (result.get("deployment") or {}).get("release_id") or result.get("release_id")
                if isinstance(release_id, str):
                    deliveries = [row for row in tx.scan("host_delivery_intents") if row.get("release_id") == release_id]
                    evidence["delivery"] = sorted(deliveries, key=lambda row: str(row.get("updated_at")))[-1] \
                        if deliveries else {"release_id": release_id, "stage": None}
            session = (binding or {}).get("session") if isinstance(binding, dict) else None
            if isinstance(session, dict):
                evidence["session"] = tx.get("worker_sessions", session["task_id"])
        return evidence

    def bind(self, document: dict) -> dict:
        """Write the trusted binding once; the identical document replays, any other refuses."""
        document = validate_binding(document)
        with self.store.transaction() as tx:
            old = tx.get(LANE_BINDINGS, document["operation_id"])
            if old is not None:
                refuse(old == document, "binding_conflict", field="operation_id")
                return {"bound": True, "cached": True}
            if tx.get("operations", document["operation_id"]) is not None:
                # The operation already claimed without this binding: it cannot be attached late.
                raise ContinuationRefused("operation_already_claimed", "operator", "operation_id")
            tx.put(LANE_BINDINGS, document["operation_id"], document)
        return {"bound": True, "cached": False}

    def bound(self, operation_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(LANE_BINDINGS, operation_id)

    def record_review(self, task_id: str, decision_id: str) -> dict | None:
        """The session owner reads the committed decision row itself; a duplicate is a no-op."""
        if self.sessions is None:
            return None
        return self.sessions.record_review(task_id, decision_id)


# ---- the coordinator ----------------------------------------------------------------------------
class Continuation:
    """`store` is the Fleet control store. `lanes(lane_id)` returns that lane's `LaneEvidence`.
    `fleet` is the existing `Fleet`. `conductor(lane_id, job)` is the guarded conductor dispatch
    port (None: the conductor route waits for its owner). `validate(manifest)` is the existing
    operation manifest validator the adapter binds to the packaged provider policy."""

    def __init__(self, store, fleet=None, lanes=None, conductor=None, validate=None, observer=None, clock=utcnow):
        self.store, self.fleet, self.lanes, self.conductor = store, fleet, lanes, conductor
        self.validate, self.observer, self.clock = validate, observer, clock

    # ----- registry -----------------------------------------------------------------------
    def register(self, document, pin: dict) -> dict:
        policy = validate_policy(document)
        sha = policy_digest(policy)
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_POLICIES, policy["id"])
            if old is not None:
                refuse(old["policy_sha256"] == sha and old["pin"] == pin, "policy_conflict", field="id")
                return {"registered": True, "cached": True, "id": policy["id"], "policy_sha256": sha}
            tx.put(BUCKET_POLICIES, policy["id"], {"id": policy["id"], "policy": policy, "policy_sha256": sha,
                                                   "pin": dict(pin), "registered_at": self.clock()})
        return {"registered": True, "cached": False, "id": policy["id"], "policy_sha256": sha}

    def policy(self, policy_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET_POLICIES, policy_id)

    def status(self, policy_id: str | None = None) -> dict:
        """Read-only projection: intents with route, state, cause, next owner/action, evidence
        references and predecessor/successor links. No manifest text, transcript or credential."""
        with self.store.transaction() as tx:
            policies = tx.scan(BUCKET_POLICIES)
            intents = tx.scan(BUCKET_INTENTS)
        if policy_id is not None:
            policies = [row for row in policies if row["id"] == policy_id]
            intents = [row for row in intents if row.get("policy_id") == policy_id]
        views = [view(row) for row in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"]))]
        counts: dict = {}
        for row in views:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {"schema": STATUS_SCHEMA, "authority": AUTHORITY,
                "policies": [{"id": row["id"], "enabled": row["policy"]["enabled"], "policy_sha256": row["policy_sha256"],
                              "pin": row["pin"]} for row in policies],
                "intents": views[-200:], "truncated": len(views) > 200, "counts": counts,
                "held_families": blocked_families(intents)}

    # ----- one tick -----------------------------------------------------------------------
    def tick(self, policy_id: str, *, pin_sha256: str | None = None, runtime=None) -> dict:
        """One bounded pass. `pin_sha256` is the digest of the pinned policy bytes re-read by the
        adapter this tick; `runtime(lane_id)` names the lane's actual image/profile/archive identity."""
        result = {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "idle", "actions": [],
                  "skipped": [], "reason_code": None}
        row = self.policy(policy_id)
        if row is None:
            return {**result, "outcome": "disabled", "reason_code": "policy_unregistered"}
        policy = row["policy"]
        if not policy["enabled"]:
            return {**result, "outcome": "disabled", "reason_code": "policy_disabled"}
        if pin_sha256 is not None and pin_sha256 != row["pin"].get("sha256"):
            return {**result, "outcome": "refused", "reason_code": "policy_changed", "next_owner": "operator"}
        sha = row["policy_sha256"]
        with self.store.transaction() as tx:
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
            intents = [intent for intent in tx.scan(BUCKET_INTENTS) if intent.get("policy_id") == policy_id]
        self._bind_initial(policy, sha, jobs, intents, runtime, result)
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
            if intent["state"] in {INTENDED, PUBLISHED, ADMITTED, DISPATCHED, RETURNED, AWAITING_OWNER,
                                   RESEARCH_REQUIRED}:
                self._guarded(result, intent["id"], lambda i=intent: self._advance(policy, sha, i, jobs))
        with self.store.transaction() as tx:
            intents = [intent for intent in tx.scan(BUCKET_INTENTS) if intent.get("policy_id") == policy_id]
        for candidate in fair_order(self._candidates(policy, jobs, intents), intents):
            self._guarded(result, candidate["job_id"],
                          lambda c=candidate: self._observe(policy, sha, c, jobs, intents, runtime))
        if result["actions"]:
            result["outcome"] = "progressed"
        elif result["skipped"]:
            result["outcome"] = "blocked"
        return result

    def _guarded(self, result, subject, action) -> None:
        """One subject's work; a lost race or a named refusal is recorded, never raised past the tick,
        so one family's outage never stops another family's progress."""
        try:
            done = action()
        except IntentChanged:
            result["skipped"].append({"subject": subject, "reason_code": "intent_changed"})
            return
        except ContinuationRefused as exc:
            result["skipped"].append({"subject": subject, "reason_code": exc.reason_code, "next_owner": exc.owner})
            return
        except Exception as exc:  # a lane store, Git or Fleet outage: the intent stays for the next tick
            result["skipped"].append({"subject": subject, "reason_code": "unavailable",
                                      "error_type": type(exc).__name__})
            return
        if isinstance(done, dict) and "history" in done:
            # A stored intent row is never printed: only its identity, state and route leave.
            done = {"subject": done["id"], "effect": done["state"], "route": done["route"]}
        if done:
            result["actions"].append(done)

    # ----- candidates ---------------------------------------------------------------------
    @staticmethod
    def _family_of(job_id: str, intents: list) -> tuple[str, str | None]:
        for intent in intents:
            if intent.get("successor_job") == job_id:
                return intent["family"], intent["id"]
        return job_id, None

    def _candidates(self, policy: dict, jobs: dict, intents: list) -> list:
        """Terminal jobs of the policy lanes with no intent for their current decisive evidence.
        Jobs whose origin intent already exists are re-read only when their row changed."""
        seen = {(intent["origin_job"], intent.get("job_updated_at")) for intent in intents}
        out = []
        for job in jobs.values():
            if job.get("lane") not in policy["lanes"] or job.get("status") not in TERMINAL_JOBS:
                continue
            if (job["id"], job.get("updated_at")) in seen and not self._reclassifiable(job, intents):
                continue
            family, predecessor = self._family_of(job["id"], intents)
            out.append({"job_id": job["id"], "family": family, "predecessor": predecessor,
                        "finished_at": job.get("finished_at")})
        return out

    @staticmethod
    def _reclassifiable(job: dict, intents: list) -> bool:
        """An accepted job moves on through conductor -> delivery -> next item as its lane evidence
        changes, and a failure held for research is routed again once the research resolved; every
        other terminal job is routed exactly once per job row."""
        mine = [intent for intent in intents if intent["origin_job"] == job["id"]]
        return bool(mine) and all(intent["state"] == COMPLETED for intent in mine) and not any(
            intent["route"] in {NEXT_ITEM, *SUCCESSOR_ROUTES} for intent in mine)

    # ----- initial session binding --------------------------------------------------------
    def _bind_initial(self, policy, sha, jobs, intents, runtime, result) -> None:
        """Bind a newly queued policy job to its own logical session BEFORE admission, so the first
        execution already runs as a task session. A successor is bound by its own intent instead."""
        successors = {intent.get("successor_job") for intent in intents}
        for job in sorted(jobs.values(), key=lambda j: j["id"]):
            if job.get("status") != "queued" or job.get("lane") not in policy["lanes"] or job["id"] in successors:
                continue
            try:
                check_scope(policy, job, runtime(job["lane"]) if runtime else None)
            except ContinuationRefused:
                continue  # outside this policy: the job keeps its exact legacy behaviour
            lane = self.lanes(job["lane"])

            def bind(job=job, lane=lane):
                if lane.bound(job["id"]) is not None:
                    return None
                lane.bind({"schema": BINDING_SCHEMA, "operation_id": job["id"], "policy_sha256": sha,
                           "intent_id": None, "family": job["id"], "route": None,
                           "session": {"task_id": job["id"], "repository": job["repository"]},
                           "workspace": None, "predecessor": None})
                return {"subject": job["id"], "effect": "session_bound"}
            self._guarded(result, job["id"], bind)

    # ----- a new observation --------------------------------------------------------------
    def _observe(self, policy, sha, candidate, jobs, intents, runtime):
        job = jobs[candidate["job_id"]]
        lane = self.lanes(job["lane"])
        evidence = lane.read(job)
        family = candidate["family"]
        routed = classify(job, evidence)
        route = routed["route"]
        base = {"policy_id": policy["id"], "policy_sha256": sha, "origin_job": job["id"], "lane": job["lane"],
                "family": family, "predecessor_intent": candidate["predecessor"],
                "job_updated_at": job.get("updated_at")}
        if route is None:
            if routed["reason_code"] in {"not_terminal", "conductor_running"}:
                return None
            return self._create({**base, "route": "refusal", "state": REFUSED, "reason_code": routed["reason_code"],
                                 "next_owner": routed.get("owner", "operator"),
                                 "evidence_sha256": evidence_digest(job, evidence, "refusal")}, attempt_of(evidence))
        try:
            check_scope(policy, job, runtime(job["lane"]) if runtime else None)
        except ContinuationRefused as exc:
            return self._create({**base, "route": route, "state": REFUSED, "reason_code": exc.reason_code,
                                 "next_owner": exc.owner, "evidence_sha256": evidence_digest(job, evidence, route)},
                                attempt_of(evidence))
        evidence_sha = evidence_digest(job, evidence, route)
        if route == RECOVERY:
            return self._create({**base, "route": RECOVERY, "state": RECOVERY_REQUIRED,
                                 "reason_code": routed["reason_code"], "next_owner": ROUTE_OWNERS[RECOVERY],
                                 "evidence_sha256": evidence_sha, "evidence_refs": evidence["markers"]},
                                attempt_of(evidence))
        if route in SUCCESSOR_ROUTES:
            if needs_research(intents, family, evidence_sha):
                return self._create({**base, "route": RESEARCH, "state": RESEARCH_REQUIRED,
                                     "reason_code": "two_distinct_failures", "next_owner": ROUTE_OWNERS[RESEARCH],
                                     "evidence_sha256": evidence_sha,
                                     "family_jobs": sorted({i["origin_job"] for i in intents if i["family"] == family}
                                                           | {job["id"]})}, attempt_of(evidence))
            successors = [i for i in intents if i["family"] == family and i["route"] in SUCCESSOR_ROUTES
                          and i["state"] != REFUSED]
            if len(successors) >= policy["max_corrections"]:
                return self._create({**base, "route": route, "state": REFUSED, "reason_code": "correction_budget_exhausted",
                                     "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt_of(evidence))
            return self._successor(policy, sha, base, job, evidence, route, routed, evidence_sha, lane)
        if route == CONDUCTOR:
            created = self._create({**base, "route": CONDUCTOR, "state": INTENDED, "reason_code": routed["reason_code"],
                                    "next_owner": ROUTE_OWNERS[CONDUCTOR], "evidence_sha256": evidence_sha},
                                   attempt_of(evidence))
            if created["state"] != INTENDED:
                return None  # an existing intent: its own state is advanced by `_advance`
            return self._dispatch(created, job) or created
        # DELIVERY: the conductor accepted; the release is queued for its existing owners.
        delivery = evidence.get("delivery") or {}
        created = self._create({**base, "route": DELIVERY, "state": AWAITING_OWNER, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[DELIVERY], "evidence_sha256": evidence_sha,
                                "release_id": delivery.get("release_id"), "delivery_target": policy["delivery_target"],
                                "evidence_refs": [ref for ref in (((evidence.get("conductor") or {}).get("result") or {})
                                                                  .get("execution_ref"),) if ref]},
                               attempt_of(evidence))
        if created["state"] != AWAITING_OWNER:
            return None
        return self._advance_delivery(created, evidence) or created

    def _successor(self, policy, sha, base, job, evidence, route, routed, evidence_sha, lane):
        """Intent first (with the complete successor identity), then the lane binding, then the
        existing Fleet admission - each step replayable to the same result after a lost response."""
        operation = evidence["operation"]
        task = evidence.get("task") or {}
        candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task, dict) else {}
        attempt = attempt_of(evidence)
        key = intent_id(job["id"], attempt, evidence_sha, route)
        successor = successor_id(key)
        decision = evidence.get("conductor") if routed["reason_code"] == "conductor_rejected" else evidence.get("lead")
        references = {"predecessor_job": job["id"], "candidate_revision": candidate.get("revision"),
                      "candidate_tree": candidate.get("tree"),
                      "review_decision": (decision or {}).get("id") if route == CORRECTION else None,
                      "review_execution_ref": ((decision or {}).get("result") or {}).get("execution_ref")
                      if route == CORRECTION else None,
                      "inspection": ((operation.get("owner_handoff") or {}).get("inspection") or {}).get("id")
                      if route == EVIDENCE_REPAIR else None}
        manifest = successor_manifest(job["manifest"], route, successor, references)
        if self.validate is not None:
            try:
                manifest = self.validate(manifest)
            except ContractError:
                # Recorded once for this evidence: the existing validator decides, nothing is trimmed.
                return self._create({**base, "route": route, "state": REFUSED, "reason_code": "successor_manifest_refused",
                                     "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt, key=key)
        # The logical session of a family is keyed by its root job (see `_bind_initial`). Only a
        # correction of a session the owner moved to `correction_ready` on THIS review decision is
        # eligible for native resume; everything else is an explicit fresh evidence handoff.
        session, mode = None, "fresh_evidence_handoff"
        binding = evidence.get("binding") if isinstance(evidence.get("binding"), dict) else {}
        logical = {"task_id": base["family"], "repository": job["repository"]}
        if route == CORRECTION and isinstance(decision, dict) and lane.sessions is not None:
            try:
                row = lane.record_review(logical["task_id"], decision["id"])
            except ContractError as exc:  # missing session, candidate mismatch: never a resume
                mode = "fresh_evidence_handoff:" + str(getattr(exc, "reason", "refused"))
            else:
                if isinstance(row, dict) and row.get("state") == "correction_ready":
                    session, mode = logical, "native_resume_eligible"
        workspace = None
        if isinstance(task.get("id"), str) and candidate.get("revision") and candidate.get("base"):
            workspace = {"origin_task_id": (binding.get("workspace") or {}).get("origin_task_id") or task["id"],
                         "head": candidate["revision"], "base": candidate["base"]}
        document = {"schema": BINDING_SCHEMA, "operation_id": successor, "policy_sha256": sha, "intent_id": key,
                    "family": base["family"], "route": route, "session": session, "workspace": workspace,
                    "predecessor": {"job_id": job["id"], "task_id": task.get("id"),
                                    "candidate_revision": candidate.get("revision"),
                                    "decision_id": (decision or {}).get("id") if route == CORRECTION else None,
                                    "review_execution_ref": references["review_execution_ref"],
                                    "inspection_id": references["inspection"]}}
        created = self._create({**base, "route": route, "state": INTENDED, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[route], "evidence_sha256": evidence_sha,
                                "successor_job": successor, "manifest": manifest, "binding": document,
                                "session_mode": mode,
                                "evidence_refs": [ref for ref in (references["review_execution_ref"],) if ref]},
                               attempt, key=key)
        return self._publish(created)

    # ----- effects ------------------------------------------------------------------------
    def _publish(self, intent: dict) -> dict | None:
        if intent["state"] not in {INTENDED, PUBLISHED}:
            return None
        lane = self.lanes(intent["lane"])
        if intent["state"] == INTENDED:
            lane.bind(intent["binding"])
            intent = self._move(intent, PUBLISHED)
        if intent["state"] == PUBLISHED:
            refuse(self.fleet is not None, "fleet_unconfigured")
            with self.store.transaction() as tx:
                origin = tx.get(FLEET_JOBS, intent["origin_job"])
            self.fleet.enqueue(intent["lane"], intent["manifest"], origin["goal"], [])
            with self.store.transaction() as tx:
                admitted = tx.get(FLEET_JOBS, intent["successor_job"])
            refuse(admitted is not None and admitted.get("manifest_sha256") is not None, "admission_unconfirmed", "fleet")
            intent = self._move(intent, ADMITTED)
        return {"subject": intent["id"], "effect": intent["state"], "route": intent["route"],
                "successor_job": intent.get("successor_job")}

    def _dispatch(self, intent: dict, job: dict) -> dict | None:
        """The pre-effect state commits BEFORE the guarded conductor call; the executor's own
        expected-row guard and fence make any second dispatcher a no-claim, never a second call."""
        if self.conductor is None:
            moved = self._move(intent, AWAITING_OWNER, reason_code="conductor_port_unconfigured")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        intent = self._move(intent, DISPATCHED)
        try:
            outcome = self.conductor(intent["lane"], job)
        except Exception as exc:
            moved = self._move(intent, RECOVERY_REQUIRED, reason_code="conductor_effect_unknown",
                               next_owner=ROUTE_OWNERS[RECOVERY], error_type=type(exc).__name__)
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        return self._settle_conductor(intent, job, outcome)

    def _settle_conductor(self, intent, job, outcome=None) -> dict | None:
        evidence = self.lanes(intent["lane"]).read(job)
        conductor = evidence.get("conductor") or {}
        status = conductor.get("status")
        if status == "succeeded":
            moved = self._move(intent, RETURNED, evidence_refs=[r for r in ((conductor.get("result") or {})
                                                                            .get("execution_ref"),) if r])
            moved = self._move(moved, COMPLETED)
            return {"subject": moved["id"], "effect": "conductor_decided", "route": CONDUCTOR}
        if status == "running":
            return None
        if status in {None, "pending"} and int(conductor.get("attempt") or 0) == 0:
            # Provably not entered (no claim, no attempt): the owner may dispatch it again.
            moved = self._move(intent, AWAITING_OWNER, reason_code="conductor_not_claimed")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        moved = self._move(intent, RECOVERY_REQUIRED, reason_code="conductor_" + str(status),
                           next_owner=ROUTE_OWNERS[RECOVERY])
        return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}

    def _advance_delivery(self, intent, evidence) -> dict | None:
        stage = (evidence.get("delivery") or {}).get("stage")
        if stage == DELIVERY_ACTIVE:
            moved = self._move(intent, COMPLETED, reason_code="delivery_active")
            nxt = self._create({key: intent[key] for key in ("policy_id", "policy_sha256", "origin_job", "lane", "family",
                                                             "job_updated_at")}
                               | {"route": NEXT_ITEM, "state": AWAITING_OWNER, "reason_code": "item_completed",
                                  "next_owner": ROUTE_OWNERS[NEXT_ITEM], "predecessor_intent": moved["id"],
                                  "evidence_sha256": intent["evidence_sha256"]},
                               {"generation": 0, "attempt": 0})
            return {"subject": moved["id"], "effect": "delivered", "route": DELIVERY, "next": nxt["id"]}
        if stage in DELIVERY_HALTED:
            moved = self._move(intent, PAUSED, reason_code="delivery_" + stage, next_owner="host_delivery")
            return {"subject": moved["id"], "effect": moved["state"], "route": DELIVERY}
        return None

    def _advance(self, policy, sha, intent, jobs):
        if intent["route"] in SUCCESSOR_ROUTES and intent["state"] in {INTENDED, PUBLISHED}:
            return self._publish(intent)
        if intent["route"] in SUCCESSOR_ROUTES and intent["state"] == ADMITTED:
            successor = jobs.get(intent["successor_job"])
            if successor is None or successor.get("status") not in TERMINAL_JOBS:
                return None
            moved = self._move(intent, RETURNED, reason_code="successor_" + successor["status"])
            moved = self._move(moved, COMPLETED)
            return {"subject": moved["id"], "effect": "successor_returned", "route": intent["route"]}
        job = jobs.get(intent["origin_job"])
        if intent["route"] == CONDUCTOR and job is not None:
            if intent["state"] == DISPATCHED:
                return self._settle_conductor(intent, job)
            if intent["state"] == AWAITING_OWNER and self.conductor is not None:
                evidence = self.lanes(intent["lane"]).read(job)
                conductor = evidence.get("conductor") or {}
                if conductor.get("status") in {None, "pending"} and int(conductor.get("attempt") or 0) == 0:
                    return self._dispatch(self._move(intent, INTENDED), job)
            return None
        if intent["route"] == DELIVERY and intent["state"] == AWAITING_OWNER and job is not None:
            return self._advance_delivery(intent, self.lanes(intent["lane"]).read(job))
        if intent["route"] == RESEARCH and intent["state"] == RESEARCH_REQUIRED:
            with self.store.transaction() as tx:
                investigations = tx.scan(INVESTIGATIONS)
            members = set(intent.get("family_jobs") or [])
            researched = [row for row in investigations if row.get("state") == "researched"
                          and members & set(row.get("job_ids") or []) and row.get("evidence_refs")]
            if not researched:
                return None
            moved = self._move(intent, COMPLETED, reason_code="researched",
                               evidence_refs=sorted({ref for row in researched for ref in row["evidence_refs"]}))
            return {"subject": moved["id"], "effect": "research_resolved", "route": RESEARCH}
        return None

    # ----- durable intent writes ----------------------------------------------------------
    def _create(self, fields: dict, attempt: dict, key: str | None = None) -> dict:
        key = key or intent_id(fields["origin_job"], attempt, fields["evidence_sha256"], fields["route"])
        now = self.clock()
        row = {"id": key, "successor_job": None, "evidence_refs": [], "session_mode": None, **fields,
               **attempt, "version": 1, "created_at": now, "updated_at": now,
               "history": [{"state": fields["state"], "reason_code": fields.get("reason_code"), "at": now}]}
        transition(None, row["state"])
        with self.store.transaction() as tx:
            old = tx.get(BUCKET_INTENTS, key)
            if old is not None:
                return old  # the same observation again: a replay, never a second intent
            tx.put(BUCKET_INTENTS, key, row)
        self._emit(None, row)
        return row

    def _move(self, intent: dict, target: str, **fields) -> dict:
        """Compare-and-swap on the intent version; a moved intent raises `IntentChanged`."""
        with self.store.transaction() as tx:
            current = tx.get(BUCKET_INTENTS, intent["id"])
            if current is None or current.get("version") != intent.get("version"):
                raise IntentChanged(intent["id"])
            previous = current["state"]
            current["state"] = transition(previous, target)
            now = self.clock()
            current.update({k: v for k, v in fields.items() if k != "error_type"}, version=current["version"] + 1,
                           updated_at=now)
            current["history"] = (current.get("history") or [])[-(MAX_HISTORY - 1):] + [
                {"state": target, "previous": previous, "reason_code": current.get("reason_code"),
                 "error_type": fields.get("error_type"), "at": now}]
            tx.put(BUCKET_INTENTS, intent["id"], current)
        self._emit(previous, current)
        return current

    def _emit(self, previous, row) -> None:
        """After the commit, through the existing Observer port: identifiers and codes only."""
        if self.observer is None:
            return
        common = {"intent_id": row["id"], "family": row["family"], "route": row["route"], "state": row["state"],
                  "origin_job": row["origin_job"], "successor_job": row.get("successor_job"),
                  "next_owner": str(row.get("next_owner") or "none"), "next_action": view(row)["next_action"]}
        reason = row.get("reason_code") if isinstance(row.get("reason_code"), str) else None
        if row["state"] in {RESEARCH_REQUIRED, RECOVERY_REQUIRED, PAUSED, REFUSED}:
            self.observer.emit(EVENT_BLOCKED, "unknown" if row["state"] == RECOVERY_REQUIRED else "blocked",
                               severity="warning", reason_code=_code(reason), attributes=common)
            return
        self.observer.emit(EVENT_TRANSITION, "observed", reason_code=_code(reason),
                           attributes={**common, "previous_state": previous})


def _code(reason):
    if not isinstance(reason, str):
        return None
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in reason)[:80]
    return cleaned if cleaned[:1].isalpha() else None


__all__ = ["BUCKET_INTENTS", "BUCKET_POLICIES", "LANE_BINDINGS", "Continuation", "IntentChanged", "LaneEvidence"]
