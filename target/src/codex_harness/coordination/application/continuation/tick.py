"""One bounded continuation policy pass.

Layer: application
Context: coordination
Owns: bucket continuation_progress
Does not own: the effects it routes to (settlement, successors, IntentStore)
Entry points: ContinuationTick
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.lanes import LaneRuntime
from codex_harness.coordination.application.continuation.state import (
    BUCKET_INTENTS,
    BUCKET_PROGRESS,
    BUCKET_RESEARCH_RECEIPTS,
    DELIVERY_ACTIVE,
    DELIVERY_HALTED,
    FLEET_JOBS,
    TERMINAL_JOBS,
    WITHDRAWN_STAGE,
    guarded,
    policy_frame,
)
from codex_harness.coordination.domain.continuation import (
    ADMITTED,
    ADMITTING_ROUTES,
    AWAITING_OWNER,
    BINDING_SCHEMA,
    COMPLETED,
    CONDUCTOR,
    DELIVERY,
    DELIVERY_ABSENT,
    DELIVERY_BOUND,
    INTENDED,
    MAX_ACTIONS_PER_TICK,
    MAX_LAUNCHES,
    NEXT_ITEM,
    PAUSED,
    PUBLISHED,
    RECOVERY,
    RECOVERY_REQUIRED,
    REFUSED,
    REQUALIFICATION,
    RESEARCH,
    RESEARCH_REQUIRED,
    RESUME,
    RETURNED,
    ROUTE_OWNERS,
    SUCCESSOR_ROUTES,
    TICK_SCHEMA,
    ContinuationRefused,
    attempt_of,
    authorization,
    check_scope,
    classify,
    delivery_tuple,
    evidence_digest,
    fair_order,
    intent_id,
    is_member,
    needs_research,
    owners,
    progress_order,
    record_attempt,
    refuse,
)


class ContinuationTick:
    """One bounded policy pass: initial session binding, the RESUME actions, and the fair bounded
    observation of terminal member jobs with their routing effects."""

    def __init__(self, store, *, conductor=None, fleet=None, lanes=None, frames=None, intents=None,
                 research=None, settlement=None, successors=None):
        self.store = store
        self.conductor = conductor
        self.fleet = fleet
        self.lanes = lanes
        self.frames = frames
        self.intents = intents
        self.research = research
        self.settlement = settlement
        self.successors = successors

    # ----- one tick -----------------------------------------------------------------------
    def tick(self, policy_id: str, *, pin_sha256: str | None = None, runtime=None) -> dict:
        """One bounded pass. `pin_sha256` is the digest of the pinned policy bytes re-read by the
        adapter this tick; `runtime(lane_id)` names the lane's actual image/profile/archive identity."""
        result = {"schema": TICK_SCHEMA, "policy_id": policy_id, "outcome": "idle", "actions": [],
                  "skipped": [], "reason_code": None, "owned_elsewhere": {"count": 0, "jobs": []}}
        row = self.frames.policy(policy_id)
        if row is None:
            return {**result, "outcome": "disabled", "reason_code": "policy_unregistered"}
        policy = row["policy"]
        if not policy["enabled"]:
            return {**result, "outcome": "disabled", "reason_code": "policy_disabled"}
        if pin_sha256 is not None and pin_sha256 != row["pin"].get("sha256"):
            # No NEW effect under changed pinned bytes; already started launches are still settled
            # under the binding they were started with.
            drained = self.settlement.drain(policy_id)
            return {**result, "outcome": "refused", "reason_code": "policy_changed", "next_owner": "operator",
                    "actions": drained["actions"], "skipped": drained["skipped"]}
        with self.store.transaction() as tx:
            jobs = {job["id"]: job for job in tx.scan(FLEET_JOBS)}
            every = tx.scan(BUCKET_INTENTS)
            policy = policy_frame(tx, row)
        intents = [intent for intent in every if intent.get("policy_id") == policy_id]
        ctx = {"policy": policy, "sha": row["policy_sha256"], "pin": row["pin"].get("sha256"),
               "runtime": LaneRuntime(runtime) if runtime else None, "jobs": jobs}
        self._bind_initial(ctx, intents, owners(every, policy_id), result)
        for intent in sorted(intents, key=lambda r: (str(r.get("created_at")), r["id"])):
            if (intent["route"], intent["state"]) in RESUME:
                guarded(result, intent["id"], lambda i=intent: self._advance(ctx, i))
        with self.store.transaction() as tx:
            every = tx.scan(BUCKET_INTENTS)
            progress = tx.get(BUCKET_PROGRESS, policy_id)
        intents = [intent for intent in every if intent.get("policy_id") == policy_id]
        # Membership and ownership first, THEN the bounded fair pass: unrelated history and another
        # policy's lineage never occupy a slot. An unavailable lane (store or runtime identity) is
        # skipped visibly without spending a slot, at most MAX_ACTIONS_PER_TICK reads per lane. Each
        # attempt is recorded durably before its read, so the next pass - any controller, after a
        # restart - tries the least recently attempted candidate first: per-job read failures never
        # hold the same reads forever.
        candidates, elsewhere = self._candidates(policy, jobs, intents, owners(every, policy_id))
        result["owned_elsewhere"] = {"count": len(elsewhere), "jobs": elsewhere[:16]}
        budget, failures = MAX_ACTIONS_PER_TICK, {}
        live, since = {candidate["job_id"] for candidate in candidates}, int((progress or {}).get("sequence") or 0)
        for candidate in progress_order(fair_order(candidates, intents, limit=None), progress):
            lane = jobs[candidate["job_id"]]["lane"]
            if budget <= 0:
                break
            if failures.get(lane, 0) >= MAX_ACTIONS_PER_TICK:
                continue
            if guarded(result, candidate["job_id"], lambda c=candidate: self._attempt(policy_id, c, live, since)
                             or self._observe(ctx, c, intents)) == "unavailable":
                runtime_down = ctx["runtime"] is not None and ctx["runtime"].failed(lane)
                failures[lane] = MAX_ACTIONS_PER_TICK if runtime_down else failures.get(lane, 0) + 1
            else:
                budget -= 1
        if result["actions"]:
            result["outcome"] = "progressed"
        elif result["skipped"]:
            result["outcome"] = "blocked"
        return result

    # ----- candidates ---------------------------------------------------------------------
    @staticmethod
    def _family_of(job_id: str, intents: list) -> tuple[str, str | None]:
        for intent in intents:
            if intent.get("successor_job") == job_id:
                return intent["family"], intent["id"]
        return job_id, None

    def _candidates(self, policy: dict, jobs: dict, intents: list, owned: dict) -> tuple[list, list]:
        """Terminal member jobs of the policy with no intent for their current decisive evidence, and
        the member jobs another policy's intent owns (`owned`, excluded and reported, never observed).
        Jobs whose origin intent already exists are re-read only when their row changed."""
        seen = {(intent["origin_job"], intent.get("job_updated_at")) for intent in intents}
        out, elsewhere = [], []
        for job in sorted(jobs.values(), key=lambda j: j["id"]):
            if job.get("status") not in TERMINAL_JOBS or not is_member(policy, job):
                continue
            if (job["id"], job.get("updated_at")) in seen and not self._reclassifiable(job, intents):
                continue
            if job["id"] in owned:
                elsewhere.append({"job": job["id"], "policy_id": owned[job["id"]]})
                continue
            family, predecessor = self._family_of(job["id"], intents)
            out.append({"job_id": job["id"], "family": family, "predecessor": predecessor,
                        "finished_at": job.get("finished_at")})
        return out, elsewhere

    @staticmethod
    def _reclassifiable(job: dict, intents: list) -> bool:
        """An accepted job moves on through conductor -> delivery -> next item as its lane evidence
        changes, and a failure held for research is routed again once the research resolved; every
        other terminal job is routed exactly once per job row."""
        mine = [intent for intent in intents if intent["origin_job"] == job["id"]]
        return bool(mine) and all(intent["state"] == COMPLETED for intent in mine) and not any(
            intent["route"] in {NEXT_ITEM, *ADMITTING_ROUTES} for intent in mine)

    def _attempt(self, policy_id: str, candidate: dict, live: set, since: int) -> None:
        """Durable selection progress in its own short transaction BEFORE the lane read: a scheduling
        attempt only, never an intent, a verdict or evidence (`domain.continuation.record_attempt`)."""
        with self.store.transaction() as tx:
            tx.put(BUCKET_PROGRESS, policy_id, record_attempt(tx.get(BUCKET_PROGRESS, policy_id), policy_id,
                                                               candidate["job_id"], live, since))

    # ----- initial session binding --------------------------------------------------------
    def _bind_initial(self, ctx, intents, owned, result) -> None:
        """Bind a newly queued policy job to its own logical session BEFORE admission, so the first
        execution already runs as a task session. A successor is bound by its own intent instead."""
        policy, runtime = ctx["policy"], ctx["runtime"]
        successors = {intent.get("successor_job") for intent in intents}
        for job in sorted(ctx["jobs"].values(), key=lambda j: j["id"]):
            if (job.get("status") != "queued" or job["id"] in successors or job["id"] in owned
                    or not is_member(policy, job)):
                continue
            try:
                check_scope(policy, job, runtime(job["lane"]) if runtime else None)
            except ContinuationRefused:
                continue  # not eligible now: the job keeps its exact legacy behaviour
            except Exception as exc:  # an unreadable runtime identity: this job only, visibly
                result["skipped"].append({"subject": job["id"], "reason_code": "unavailable",
                                          "error_type": type(exc).__name__})
                continue
            lane = self.lanes(job["lane"])

            def bind(job=job, lane=lane):
                if lane.bound(job["id"]) is not None:
                    return None
                lane.bind({"schema": BINDING_SCHEMA, "operation_id": job["id"], "policy_sha256": ctx["sha"],
                           "intent_id": None, "family": job["id"], "route": None,
                           "session": {"task_id": job["id"], "repository": job["repository"]},
                           "workspace": None, "predecessor": None})
                return {"subject": job["id"], "effect": "session_bound"}
            guarded(result, job["id"], bind)

    # ----- a new observation --------------------------------------------------------------
    def _observe(self, ctx, candidate, intents):
        policy, runtime = ctx["policy"], ctx["runtime"]
        job = ctx["jobs"][candidate["job_id"]]
        lane = self.lanes(job["lane"])
        evidence = lane.read(job, policy["delivery_target"])
        family = candidate["family"]
        routed = classify(job, evidence)
        route = routed["route"]
        base = {"policy_id": policy["id"], "policy_sha256": ctx["sha"], "origin_job": job["id"], "lane": job["lane"],
                "family": family, "predecessor_intent": candidate["predecessor"],
                "job_updated_at": job.get("updated_at")}
        if route is None:
            if routed["reason_code"] in {"not_terminal", "conductor_running"}:
                return None
            return self.intents.create({**base, "route": "refusal", "state": REFUSED, "reason_code": routed["reason_code"],
                                 "next_owner": routed.get("owner", "operator"),
                                 "evidence_sha256": evidence_digest(job, evidence, "refusal")}, attempt_of(evidence))
        current = runtime(job["lane"]) if runtime else None
        try:
            check_scope(policy, job, current)
        except ContinuationRefused as exc:
            return self.intents.create({**base, "route": route, "state": REFUSED, "reason_code": exc.reason_code,
                                 "next_owner": exc.owner, "evidence_sha256": evidence_digest(job, evidence, route)},
                                attempt_of(evidence))
        # The exact binding every later NEW effect of this intent is re-checked against.
        base["authorization"] = authorization(ctx["sha"], ctx["pin"], job, current)
        evidence_sha = evidence_digest(job, evidence, route)
        if route == RECOVERY:
            return self.intents.create({**base, "route": RECOVERY, "state": RECOVERY_REQUIRED,
                                 "reason_code": routed["reason_code"], "next_owner": ROUTE_OWNERS[RECOVERY],
                                 "evidence_sha256": evidence_sha, "evidence_refs": evidence["markers"]},
                                attempt_of(evidence))
        if route in SUCCESSOR_ROUTES:
            if needs_research(intents, family, evidence_sha):
                return self.intents.create({**base, "route": RESEARCH, "state": RESEARCH_REQUIRED,
                                     "reason_code": "two_distinct_failures", "next_owner": ROUTE_OWNERS[RESEARCH],
                                     "evidence_sha256": evidence_sha,
                                     "family_jobs": sorted({i["origin_job"] for i in intents if i["family"] == family}
                                                           | {job["id"]})}, attempt_of(evidence))
            successors = [i for i in intents if i["family"] == family and i["route"] in SUCCESSOR_ROUTES
                          and i["state"] != REFUSED]
            if len(successors) >= policy["max_corrections"]:
                return self.intents.create({**base, "route": route, "state": REFUSED, "reason_code": "correction_budget_exhausted",
                                     "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt_of(evidence))
            return self._successor(ctx, base, job, evidence, route, routed, evidence_sha, lane)
        if route == CONDUCTOR:
            created = self.intents.create({**base, "route": CONDUCTOR, "state": INTENDED, "reason_code": routed["reason_code"],
                                    "next_owner": ROUTE_OWNERS[CONDUCTOR], "evidence_sha256": evidence_sha},
                                   attempt_of(evidence))
            if created["state"] != INTENDED:
                return None  # an existing intent: its own state is advanced by `_advance`
            return self.settlement.dispatch(ctx, created, job) or created
        # DELIVERY: the conductor accepted; the release is queued for its existing owners. The
        # exact (policy target, release, candidate revision) tuple is carried by the intent and
        # re-validated against the persisted HostDelivery evidence at every reconciliation.
        delivery = evidence.get("delivery") or {}
        created = self.intents.create({**base, "route": DELIVERY, "state": AWAITING_OWNER, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[DELIVERY], "evidence_sha256": evidence_sha,
                                "release_id": delivery.get("release_id"), "delivery_target": policy["delivery_target"],
                                "delivery_binding": delivery_tuple(delivery),
                                "evidence_refs": [ref for ref in (((evidence.get("conductor") or {}).get("result") or {})
                                                                  .get("execution_ref"),) if ref]},
                               attempt_of(evidence))
        if created["state"] != AWAITING_OWNER:
            return None
        return self._advance_delivery(created, evidence) or created

    def _successor(self, ctx, base, job, evidence, route, routed, evidence_sha, lane):
        """Intent first (with the complete successor identity), then the lane binding, then the
        existing Fleet admission - each step replayable to the same result after a lost response."""
        attempt = attempt_of(evidence)
        with self.store.transaction() as tx:
            key, _ = self.intents.claim(tx, intent_id(job["id"], attempt, evidence_sha, route), base["policy_id"])
        plan = self.successors.successor_plan(ctx["sha"], base["family"], job, evidence, route, routed, key, lane,
                                    self.successors.research_handoff(base["policy_id"], base["family"], key))
        if plan is None:
            # Recorded once for this evidence: the existing validator decides, nothing is trimmed.
            return self.intents.create({**base, "route": route, "state": REFUSED, "reason_code": "successor_manifest_refused",
                                 "next_owner": "operator", "evidence_sha256": evidence_sha}, attempt, key=key)
        created = self.intents.create({**base, "route": route, "state": INTENDED, "reason_code": routed["reason_code"],
                                "next_owner": ROUTE_OWNERS[route], "evidence_sha256": evidence_sha, **plan},
                               attempt, key=key)
        return self._publish(ctx, created)

    # ----- effects ------------------------------------------------------------------------
    def _publish(self, ctx, intent: dict) -> dict | None:
        if intent["state"] not in {INTENDED, PUBLISHED}:
            return None
        lane = self.lanes(intent["lane"])
        if intent["state"] == INTENDED:
            intent = self.frames.authorize(ctx, intent)
            lane.bind(intent["binding"])
            intent = self.intents.move(intent, PUBLISHED)
        if intent["state"] == PUBLISHED:
            refuse(self.fleet is not None, "fleet_unconfigured")
            intent = self.frames.authorize(ctx, intent)
            with self.store.transaction() as tx:
                origin = tx.get(FLEET_JOBS, intent["origin_job"])
            # A requalification runs on its own base: its goal binding is the same goal bound at that
            # main (verified when the owner recorded it), never the origin's older base.
            goal = intent["goal"] if intent["route"] == REQUALIFICATION else origin["goal"]
            self.fleet.enqueue(intent["lane"], intent["manifest"], goal, [])
            # Admission is confirmed, the origin's Portfolio ownership inherited and the intent moved in
            # ONE control-store transaction (no nested one): an interruption after the enqueue leaves
            # `published`, the replay re-admits the same id and binds once, and a conflicting target
            # binding refuses without advancing the intent (SPEC "Research coverage ownership").
            with self.store.transaction() as tx:
                admitted = tx.get(FLEET_JOBS, intent["successor_job"])
                refuse(admitted is not None and admitted.get("manifest_sha256") is not None, "admission_unconfirmed",
                       "fleet")
                ownership, _ = self.successors.inherit(tx, intent)
                previous, intent = self.intents.apply(tx, intent, ADMITTED, {"ownership": ownership})
            self.intents.emit(previous, intent)
        return {"subject": intent["id"], "effect": intent["state"], "route": intent["route"],
                "successor_job": intent.get("successor_job")}

    def _advance_delivery(self, intent, evidence) -> dict | None:
        """Only the HostDelivery intent bound to this item's (target, release, candidate) moves it.
        Foreign, stale, ambiguous or mismatched evidence is a named wait: never a completion, never a
        pause of this family, and nothing is written."""
        delivery = evidence.get("delivery")
        refuse(isinstance(delivery, dict), "delivery_evidence_missing", "host_delivery", "release_id")
        refuse(delivery_tuple(delivery) == delivery_tuple(intent.get("delivery_binding")), "delivery_binding_changed",
               "host_delivery", "delivery_binding")
        if delivery["binding"] == DELIVERY_ABSENT:
            return None
        refuse(delivery["binding"] == DELIVERY_BOUND, "delivery_" + str(delivery["binding"]), "host_delivery",
               "delivery")
        plan = {"plan_id": delivery.get("plan_id"), "plan_sha256": delivery.get("plan_sha256"),
                "stage": delivery.get("stage")}
        stage = delivery.get("stage")
        # The owner withdrew exactly this plan: only its requalification document moves this intent.
        refuse(stage != WITHDRAWN_STAGE, "delivery_withdrawn", "operator", "delivery")
        if stage == DELIVERY_ACTIVE:
            moved = self.intents.move(intent, COMPLETED, reason_code="delivery_active", delivery_plan=plan)
            nxt = self.intents.create({key: intent[key] for key in ("policy_id", "policy_sha256", "origin_job", "lane", "family",
                                                             "job_updated_at")}
                               | {"route": NEXT_ITEM, "state": AWAITING_OWNER, "reason_code": "item_completed",
                                  "next_owner": ROUTE_OWNERS[NEXT_ITEM], "predecessor_intent": moved["id"],
                                  "evidence_sha256": intent["evidence_sha256"],
                                  "authorization": intent.get("authorization")},
                               {"generation": 0, "attempt": 0})
            return {"subject": moved["id"], "effect": "delivered", "route": DELIVERY, "next": nxt["id"]}
        if stage in DELIVERY_HALTED:
            moved = self.intents.move(intent, PAUSED, reason_code="delivery_" + stage, next_owner="host_delivery",
                               delivery_plan=plan)
            return {"subject": moved["id"], "effect": moved["state"], "route": DELIVERY}
        return None

    # ----- restart: one action per (route, state), domain.continuation.RESUME -------------
    def _advance(self, ctx, intent):
        action = RESUME.get((intent["route"], intent["state"]))
        if action is None:
            return None
        return getattr(self, "_resume_" + action)(ctx, intent, ctx["jobs"].get(intent["origin_job"]))

    def _resume_publish(self, ctx, intent, job):
        return self._publish(ctx, intent)

    def _resume_await_successor(self, ctx, intent, job):
        successor = ctx["jobs"].get(intent["successor_job"])
        if successor is None or successor.get("status") not in TERMINAL_JOBS:
            return None
        moved = self.intents.move(intent, RETURNED, reason_code="successor_" + successor["status"])
        return self._resume_complete(ctx, moved, job)

    def _resume_complete(self, ctx, intent, job):
        """`returned` already holds the exact committed outcome (successor status, or the conductor
        decision); completing it needs no other read and no effect."""
        moved = self.intents.move(intent, COMPLETED)
        return {"subject": moved["id"], "effect": "successor_returned" if moved["route"] in ADMITTING_ROUTES
                else "returned_completed", "route": moved["route"]}

    def _resume_dispatch(self, ctx, intent, job):
        refuse(job is not None, "origin_job_missing", "fleet", "origin_job")
        return self.settlement.dispatch(ctx, intent, job)

    def _resume_reconcile_launch(self, ctx, intent, job):
        return self.settlement.reconcile_launch(intent, ctx["jobs"])

    def _resume_redispatch(self, ctx, intent, job):
        """A conductor intent waiting because its row was not claimed (or no port was configured).
        A new launch identity is started only for a row still provably not entered, within
        `MAX_LAUNCHES`, and only after the eligibility guard."""
        if self.conductor is None or job is None:
            return None
        conductor = self.lanes(intent["lane"]).read(job).get("conductor") or {}
        status = conductor.get("status")
        if status == "running":
            return None
        if status == "succeeded":  # decided by another owner (e.g. the manual command): record it
            result = conductor.get("result") or {}
            moved = self.intents.move(intent, COMPLETED, reason_code="conductor_decided_elsewhere",
                               decision={"id": conductor.get("id"), "status": status,
                                         "accepted": result.get("accepted"), "execution_ref": result.get("execution_ref")})
            return {"subject": moved["id"], "effect": "conductor_decided", "route": CONDUCTOR}
        if not (status in {None, "pending"} and int(conductor.get("attempt") or 0) == 0):
            moved = self.intents.move(intent, RECOVERY_REQUIRED, reason_code="conductor_" + str(status),
                               next_owner=ROUTE_OWNERS[RECOVERY])
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        if int((intent.get("launch") or {}).get("sequence") or 0) >= MAX_LAUNCHES:
            moved = self.intents.move(intent, REFUSED, reason_code="conductor_launch_exhausted", next_owner="conductor")
            return {"subject": moved["id"], "effect": moved["state"], "route": CONDUCTOR}
        intent = self.frames.authorize(ctx, intent)
        return self.settlement.dispatch(ctx, self.intents.move(intent, INTENDED), job)

    def _resume_observe_delivery(self, ctx, intent, job):
        if job is None:
            return None
        return self._advance_delivery(intent, self.lanes(intent["lane"]).read(job, ctx["policy"]["delivery_target"]))

    def _resume_observe_research(self, ctx, intent, job):
        """Only the owner's stored scoped receipt for THIS intent releases the hold, and only after
        it is verified again against the current rows and lane evidence (a changed attempt, a new
        failure, a withdrawn dispatch result, an unreadable lane or evidence bytes that are now
        missing, unreadable, tampered or oversized keep the family held). A coarse
        `researched` disposition intersecting the family is evidence, never approval: it is not read
        here. The stored receipt is never edited; the intent's compare-and-swap completes it once."""
        with self.store.transaction() as tx:
            stored = tx.get(BUCKET_RESEARCH_RECEIPTS, intent["id"])
        if stored is None:
            return None
        receipt, coverage = self.research.recheck_receipt(ctx["policy"]["id"], ctx["sha"], intent, stored)
        moved = self.intents.move(intent, COMPLETED, reason_code="research_receipt_accepted",
                           evidence_refs=list(receipt["evidence_refs"]), research_receipt=stored["receipt_sha256"],
                           research_coverage=coverage)
        return {"subject": moved["id"], "effect": "research_resolved", "route": RESEARCH}

    def _resume_await_backlog(self, ctx, intent, job):
        return None  # the approved backlog owns the next item; nothing to do here
