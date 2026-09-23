"""Durable delivery of a reviewed release to an actual host target (INV-HOST-DELIVERY-001).

A bounded coordinator, not a second approval authority and not a second executor. It owns four
buckets over the existing store - `host_delivery_targets` (the owner's authorized host registry),
`host_delivery_plans` (one registered Git-pinned plan per plan id), `host_delivery_intents` (one
durable intent per plan) and `host_delivery_descriptors` (the active descriptor of each target) -
and it reaches everything else through its existing owners:

* `application.releases.Releases` remains the only approval and the only active-release CAS. The
  lead+conductor reviews, the exact revision/tree/evaluator hash and the ticket binding are read
  from ITS record; nothing here writes a review, and `promote` is called only after the prescribed
  checks AND an actual consumption receipt.
* `application.release_queue.ReleaseQueue` remains the fence: one controller on this host at a
  time, with its generation, lease, attempt budget and backoff unchanged. This controller claims
  only the rows a registered plan names.
* The GitHub port publishes and merges through the existing `GitWorkspace` contracts and observes
  the real checks of the exact PR head; the host port owns the descriptor, the drain and the
  process; the canary port is an incumbent fixed check id, never text from a plan.

One tick is a few short store transactions with every external action strictly between them,
because `PostgresStore.transaction` takes `pg_advisory_xact_lock` per transaction and a nested call
would block until `lock_timeout`. No transaction is open across GitHub, the filesystem, a
subprocess or another independently locking transaction, and every durable observation is committed
in the same transaction that re-checks this controller's ownership.

Idempotence follows the durable-intent rule: the intent names the stage BEFORE the external action
of that stage, so a lost response can only reconcile what already happened - an existing PR at the
intended head is adopted, an already merged PR is recognized, and an already consumed descriptor is
recognized - never repeated. A long external wait (CI, startup) does not sleep holding the lease:
the tick answers `pending`, releases the lease through `ReleaseQueue.defer`, and the next bounded
tick resumes the same logical intent under its own durable stage deadline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases
from codex_harness.domain.host_delivery import (
    ACTIVE,
    AUTHORITY,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    CI_FAILED,
    CI_HEAD_CHANGED,
    CI_PASSED,
    CI_PENDING,
    DRAIN_INTENDED,
    EVENT_BLOCKED,
    EVENT_CHECK,
    EVENT_ROLLBACK,
    EVENT_STAGE,
    EVENT_SWITCHED,
    FAILED,
    MAX_STAGE_ATTEMPTS,
    MERGE_INTENDED,
    MERGED,
    OUTCOME_ACTIVE,
    OUTCOME_BLOCKED,
    OUTCOME_BUSY,
    OUTCOME_CONFLICT,
    OUTCOME_DISABLED,
    OUTCOME_IDLE,
    OUTCOME_PENDING,
    OUTCOME_PROGRESSED,
    OUTCOME_REFUSED,
    OUTCOME_ROLLED_BACK,
    OUTCOME_UNAVAILABLE,
    OUTCOME_UNREGISTERED,
    PUBLISHING,
    REGISTERED,
    ROLLED_BACK,
    ROLLING_BACK,
    STATUS_SCHEMA,
    STOPPED_STAGES,
    SWITCHING,
    TICK_SCHEMA,
    DeliveryRefused,
    LifecycleInterrupted,
    ci_verdict,
    consumption_verdict,
    delivery_status,
    descriptor_digest,
    new_intent,
    plan_digest,
    release_gate,
    resolve_descriptor,
    safe_error_type,
    stage_next_action,
    validate_pin,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.domain.model import ContractError, utcnow
from codex_harness.domain.policy import POLICY

BUCKET_TARGETS = "host_delivery_targets"
BUCKET_PLANS = "host_delivery_plans"
BUCKET_INTENTS = "host_delivery_intents"
BUCKET_DESCRIPTORS = "host_delivery_descriptors"
LOGGER = logging.getLogger("zeus.host.delivery")

# The stages at which another plan on the SAME target is already touching the host. A second plan
# for that target waits rather than racing it; unrelated targets keep moving.
TARGET_BUSY_STAGES = frozenset({DRAIN_INTENDED, SWITCHING, AWAITING_CONSUMPTION, ROLLING_BACK})
# How long a pending external wait asks to be resumed after; the stage deadline in the intent is
# what actually ends the wait.
RESUME_SECONDS = 15
# One tick reads at most this many registered plans looking for an actionable one; the rest are
# recorded as `scan_bounded` rather than scanned, so selection stays bounded however many exist.
MAX_SCAN = 64


class AmbiguousEffect(Exception):
    """An external effect happened and the fence was gone when this controller tried to record it.

    It is deliberately not a `ContractError`: a refused contract is a definite verdict about the
    work, while this is an UNKNOWN about an effect that is already out in the world. The durable
    evidence is the intent that named the stage before the effect - which is why the next owner of
    this plan reconciles the host instead of repeating the action - and the tick reports the
    conflict rather than claiming the effect was cancelled.
    """

    def __init__(self, effect: str, cause: Exception):
        super().__init__(effect)
        self.effect, self.cause = effect, cause


class HostDelivery:
    """One store, the existing release authority and fence, and three injected host-side ports.

    `github`, `hosts` and `canaries` are ports the adapter wires to the real GitHub CLI, the real
    host targets and the incumbent fixed canary checks. Without them a tick cannot act: the missing
    port is reported as `unavailable` with its own reason code, never as an empty success.

    `enabled` is the opt-in: production delivery is off by default, and while it is off a tick
    registers, projects and refuses to touch anything external.
    """

    def __init__(self, store, org=None, *, github=None, hosts=None, canaries=None, clock=utcnow,
                 observer=None, enabled=False, releases=None, queue=None,
                 resume_seconds: int = RESUME_SECONDS):
        self.store, self.org, self.clock = store, org, clock
        self.github, self.hosts, self.canaries = github, hosts or {}, canaries or {}
        self.observer, self.enabled = observer, bool(enabled)
        self.resume_seconds = int(resume_seconds)
        self.releases = releases if releases is not None else Releases(store, org)
        self.queue = queue if queue is not None else ReleaseQueue(store)

    # ----- registry -----------------------------------------------------------------------
    def register_targets(self, document) -> dict:
        """Register the owner's authorized host target registry; the identical document is cached."""
        registry = validate_targets(document)
        now = self.clock()
        with self.store.transaction() as tx:
            for target in registry["targets"]:
                old = tx.get(BUCKET_TARGETS, target["target_id"]) or {}
                tx.put(BUCKET_TARGETS, target["target_id"],
                       {"id": target["target_id"], **target,
                        "registered_at": old.get("registered_at") or now, "updated_at": now})
        return {"registered": True, "targets": [t["target_id"] for t in registry["targets"]],
                "authority": AUTHORITY}

    def register(self, document, pin) -> dict:
        """Register one validated delivery plan read at an explicit commit.

        The target must already exist in the owner's registry, so a plan can never introduce one.
        The identical plan at the identical pin is cached. A plan whose delivery has already left
        `registered` may not be edited at all: a changed release, revision, tree, evaluator hash,
        target or descriptor refuses the whole registration and writes nothing, so no in-flight
        delivery is ever re-pointed at another candidate.
        """
        plan = validate_plan(document)
        pin = validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            if tx.get(BUCKET_TARGETS, plan["target_id"]) is None:
                raise DeliveryRefused("target_unregistered", "target_id")
            old = tx.get(BUCKET_PLANS, plan["plan_id"])
            intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
            if old is not None:
                if old["plan_sha256"] == sha and old["pin"] == pin:
                    return {"registered": True, "cached": True, "plan_id": plan["plan_id"],
                            "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
                            "release_id": plan["release_id"], "authority": AUTHORITY}
                if intent is not None and intent.get("stage") != REGISTERED:
                    raise DeliveryRefused("delivery_in_flight", "plan_id")
            row = {"id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan,
                   "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
                   "registered_at": (old or {}).get("registered_at") or now, "updated_at": now}
            tx.put(BUCKET_PLANS, plan["plan_id"], row)
        return {"registered": True, "cached": False, "plan_id": plan["plan_id"], "plan_sha256": sha,
                "pin": pin, "target_id": plan["target_id"], "release_id": plan["release_id"],
                "authority": AUTHORITY}

    def plan(self, plan_id: str):
        with self.store.transaction() as tx:
            return tx.get(BUCKET_PLANS, plan_id)

    def status(self, plan_id: str | None = None) -> dict:
        """The durable bounded projection of one plan or of every registered plan. Store reads only:
        no git, GitHub, process, descriptor file, provider or host observation happens here."""
        with self.store.transaction() as tx:
            rows = (tx.scan(BUCKET_PLANS) if plan_id is None
                    else [row for row in [tx.get(BUCKET_PLANS, plan_id)] if row])
            intents = {row["plan_id"]: row for row in tx.scan(BUCKET_INTENTS)}
            descriptors = {row["target_id"]: row for row in tx.scan(BUCKET_DESCRIPTORS)}
        if plan_id is not None and not rows:
            return {"schema": STATUS_SCHEMA, "plan_id": plan_id, "registered": False,
                    "enabled": self.enabled, "outcome": OUTCOME_UNREGISTERED, "deliveries": [],
                    "next_action": "register_plan", "targets": sorted(descriptors),
                    "authority": AUTHORITY}
        return delivery_status(rows, intents, descriptors, enabled=self.enabled)

    # ----- one bounded tick ------------------------------------------------------------------
    def tick(self, plan_id: str | None = None) -> dict:
        """Advance at most ONE delivery by at most one stage, under the existing release fence.

        Whatever this tick did, its receipt carries why every OTHER registered plan waited, so a
        plan that was passed over is an explicit recorded reason rather than a silent omission.
        """
        try:
            selection = self._select(plan_id, create=self.enabled)
        except Exception as exc:
            # The durable state itself cannot be read. That is an explicit outage with its
            # exception TYPE, never an idle poll and never an invented cause.
            return self._result(None, None, OUTCOME_UNAVAILABLE, reason_code="store_unavailable",
                                error_type=safe_error_type(type(exc).__name__))
        if selection["plan"] is None:
            return self._result(None, None, selection["outcome"], blocked=selection["blocked"],
                                reason_code=selection.get("reason_code"))
        result = self._act(selection)
        result["blocked"] = {**selection["blocked"], **(result.get("blocked") or {})}
        return result

    def _act(self, selection: dict) -> dict:
        """Everything one tick does once its single plan has been selected."""
        row, intent = selection["plan"], selection["intent"]
        plan = row["plan"]
        if not self.enabled:
            # Registration, reconciliation and projection stay available; nothing external happens.
            return self._result(plan, intent, OUTCOME_DISABLED, reason_code="delivery_disabled")
        gate = self._gate(plan)
        if gate["state"] == OUTCOME_REFUSED:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, gate["reason_code"])
        if gate["state"] == AWAITING_REVIEW:
            # A registered plan whose review is not complete PROJECTS the wait; it never runs, and
            # no queue row, PR, merge or host change is created for it.
            return self._await_review(plan, intent, gate["reason_code"])
        try:
            self.queue.enqueue(plan["release_id"], "host delivery plan " + plan["plan_id"])
            # This controller's own clock drives its fence too, so a lease, a backoff and a stage
            # deadline are never read from two different times.
            claim = self.queue.claim(now=self._now(),
                                     eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "queue_refused",
                              error_type=type(exc).__name__)
        except Exception as exc:  # the store itself is unreachable: an outage, not a verdict
            return self._unavailable(plan, intent, "queue_unavailable", exc, commit=False)
        if claim is None:
            # Why this tick got nothing is an operational fact of its own: another controller holds
            # the single host lease, or this release's own queue row is no longer runnable.
            with self.store.transaction() as tx:
                queued = tx.get("release_queue", plan["release_id"]) or {}
            status = queued.get("status")
            if status not in {"queued", "retry", "running"}:
                reason = "release_queue_" + str(status)
            elif int(queued.get("attempt") or 0) >= POLICY.release_max_attempts:
                reason = "release_attempts_exhausted"
            elif self._not_due(queued):
                # Its own bounded backoff, not another controller: a distinct operational fact.
                reason = "release_retry_not_due"
            else:
                reason = "controller_lease_held"
            return self._result(plan, intent, OUTCOME_BUSY, reason_code=reason)
        try:
            result = self._advance(row, intent, claim)
        except AmbiguousEffect as ambiguous:
            # The effect happened; this controller no longer owns the fence that would record it.
            # It is neither progress nor a cancellation: the successor reconciles what is there.
            LOGGER.warning("host delivery ambiguous effect plan=%s stage=%s effect=%s error=%s",
                           plan["plan_id"], intent["stage"], ambiguous.effect,
                           type(ambiguous.cause).__name__)
            result = {**self._result(plan, intent, OUTCOME_CONFLICT,
                                     reason_code="controller_stale_after_effect",
                                     error_type=type(ambiguous.cause).__name__),
                      "controller": "stale", "ambiguous_effect": ambiguous.effect}
        except ContractError as refusal:
            # A definite contract refusal of this stage; a fence that moved underneath it cannot be
            # recorded either, and says so instead of raising over what was already observed. The
            # exception is bound to a local because `except ... as` unbinds its own name on exit.
            failure = refusal
            result = self._guard(plan, intent, OUTCOME_REFUSED, lambda: self._halt(
                plan, intent, BLOCKED, OUTCOME_REFUSED,
                getattr(failure, "reason_code", None) or "contract_refused",
                error_type=type(failure).__name__, claim=claim))
        except Exception as outage:
            failure = outage
            # The one NAMED outage: a managed runtime whose dependencies are not the qualified
            # environment waits for the owner to build and qualify it; nothing is installed here.
            reason = ("environment_unqualified" if isinstance(outage, EnvironmentUnqualified)
                      else "stage_unavailable")
            result = self._guard(plan, intent, OUTCOME_UNAVAILABLE, lambda: self._unavailable(
                plan, intent, reason, failure, claim=claim))
        self._settle(claim, result)
        return result

    # ----- the mutation boundary ---------------------------------------------------------------
    def _owned_now(self, claim) -> None:
        """Re-check this claim's generation, owner and lease IMMEDIATELY before a mutation.

        One short store transaction of its own: no external call is ever made from inside it, and
        a stale actor raises here, before it can publish, merge, drain, switch, start or restore.
        """
        if claim is None:
            return
        with self.store.transaction() as tx:
            self.queue.owned(tx, claim, self._now())

    def _authorizer(self, claim):
        """The same check, handed to the host adapter so it runs INSIDE the target lock."""
        if claim is None:
            return None
        return lambda: self._owned_now(claim)

    @staticmethod
    def _record(effect: str, write):
        """Commit what an external effect did; a lost fence here is ambiguity, not cancellation."""
        try:
            return write()
        except ContractError as exc:
            raise AmbiguousEffect(effect, exc) from exc

    @staticmethod
    def _lifecycle(action):
        """Run one guarded host lifecycle operation and name what an interruption of it means.

        The host adapter raises `LifecycleInterrupted` only when this controller lost the fence
        AFTER it had already stopped that target's service, inside the guard that prevents anyone
        else from acting in the middle of it. That effect is out in the world, so it becomes the
        same ambiguity every other lost-across-the-effect case is - reconciled by the next owner -
        rather than a refusal that would claim nothing happened.
        """
        try:
            return action()
        except LifecycleInterrupted as interrupted:
            raise AmbiguousEffect(interrupted.effect, interrupted.cause) from interrupted

    def _guard(self, plan: dict, intent: dict, outcome: str, record) -> dict:
        """Record a stop, or report that this controller no longer owns what it observed."""
        try:
            return record()
        except ContractError as exc:
            return {**self._result(plan, intent, outcome, reason_code="controller_stale",
                                   error_type=type(exc).__name__), "controller": "stale"}

    def _settle(self, claim, result: dict) -> None:
        """Release the fence: a bounded external wait defers, everything else finishes.

        A stale controller cannot commit this either; its own ownership error is recorded on the
        receipt rather than raised over the result that was already observed.
        """
        outcome, now = result["outcome"], self._now()
        try:
            if outcome == OUTCOME_PENDING:
                self.queue.defer(claim, {"status": "pending", "stage": result["stage"],
                                         "reason": result["reason_code"]},
                                 resume_after_seconds=self.resume_seconds, now=now)
            elif outcome == OUTCOME_UNAVAILABLE:
                self.queue.finish(claim, {"status": "retry", "reason": result["reason_code"]}, now)
            elif outcome in {OUTCOME_BLOCKED, OUTCOME_REFUSED}:
                self.queue.finish(claim, {"status": "blocked", "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ROLLED_BACK:
                self.queue.finish(claim, {"status": "rolled_back",
                                          "reason": result["reason_code"]}, now)
            elif outcome == OUTCOME_ACTIVE:
                self.queue.finish(claim, {"status": "active", "release_id": result["release_id"]}, now)
            else:
                self.queue.defer(claim, {"status": "progressed", "stage": result["stage"]},
                                 resume_after_seconds=0, now=now)
        except ContractError as exc:
            result["controller"] = "stale"
            result["error_type"] = type(exc).__name__

    def _select(self, plan_id: str | None, *, create: bool = True) -> dict:
        """Transaction 1: the one plan this tick may work on, and why every other one waits.

        A plan that cannot be acted on right now - its independent review is not complete, its
        queue row is in backoff, exhausted, blocked or held by another controller - does not
        consume the single selection: the scan keeps looking for a plan that IS actionable, so one
        waiting target can no longer starve a qualified one. Every skipped plan is recorded with
        its own explicit wait reason rather than silently passed over, the same-target exclusion is
        unchanged, and the scan itself is bounded.

        Only when nothing is actionable does the first WAITING plan become the selection, so a
        single registered plan still projects its own wait (`awaiting_review`) exactly as before.

        `create` is the opt-in: while delivery is disabled the selection is a pure read and not
        even a durable intent is written, so an unaccepted host stays exactly as it was.
        """
        now = self.clock()
        with self.store.transaction() as tx:
            rows = (tx.scan(BUCKET_PLANS) if plan_id is None
                    else [row for row in [tx.get(BUCKET_PLANS, plan_id)] if row])
            if not rows:
                return {"plan": None, "intent": None, "blocked": {},
                        "outcome": OUTCOME_UNREGISTERED if plan_id else OUTCOME_IDLE}
            intents = {row["plan_id"]: row for row in tx.scan(BUCKET_INTENTS)}
            busy = {intent["target_id"] for intent in intents.values()
                    if intent.get("stage") in TARGET_BUSY_STAGES}
            blocked, chosen, chosen_intent, waiting = {}, None, None, None
            for index, row in enumerate(sorted(rows, key=lambda r: r["plan_id"])):
                intent = intents.get(row["plan_id"])
                stage = (intent or {}).get("stage") or REGISTERED
                if index >= MAX_SCAN:
                    blocked[row["plan_id"]] = "scan_bounded"
                    continue
                if stage == ACTIVE or stage in STOPPED_STAGES:
                    blocked[row["plan_id"]] = stage
                    continue
                if row["target_id"] in busy and stage not in TARGET_BUSY_STAGES:
                    blocked[row["plan_id"]] = "target_busy"
                    continue
                if chosen is not None:
                    blocked[row["plan_id"]] = "controller_serialized"
                    continue
                reason = self._waiting_reason(tx, row["plan"], stage)
                if reason is not None:
                    blocked[row["plan_id"]] = reason
                    waiting = waiting or (row, intent)
                    continue
                chosen, chosen_intent = row, intent
            if chosen is None and waiting is not None:
                # Nothing is actionable; the first waiting plan is selected so its own wait is
                # projected and recorded, which advances no stage and touches nothing external.
                chosen, chosen_intent = waiting
                blocked.pop(chosen["plan_id"], None)
            if chosen is None:
                return {"plan": None, "intent": None, "blocked": blocked, "outcome": OUTCOME_IDLE}
            if chosen_intent is None:
                # The durable intent exists before anything else does, including the queue row.
                chosen_intent = new_intent(chosen["plan"], chosen["plan_sha256"], now)
                if create:
                    tx.put(BUCKET_INTENTS, chosen_intent["id"], chosen_intent)
        return {"plan": chosen, "intent": chosen_intent, "blocked": blocked, "outcome": OUTCOME_PROGRESSED}

    def _waiting_reason(self, tx, plan: dict, stage: str) -> str | None:
        """Why this plan cannot be advanced right now, or None when it can be.

        Read-only, inside the caller's transaction, and deliberately in the same order as the tick
        itself: the existing release record first, then the existing queue row. A refused release
        is NOT a wait - halting it is the tick's owed work - and a rolling back delivery is owed
        work too, because a restoration that stopped being selected would leave the host on a
        descriptor that failed its own canary.
        """
        if stage == ROLLING_BACK:
            return None
        record = tx.get("releases", plan["release_id"])
        gate = release_gate(record, plan, self._parent(record))
        if gate["state"] == AWAITING_REVIEW:
            return gate["reason_code"]
        if gate["state"] == OUTCOME_REFUSED:
            return None
        row = tx.get("release_queue", plan["release_id"])
        if row is None:
            return None
        if row.get("status") not in {"queued", "retry", "running"}:
            return "release_queue_" + str(row.get("status"))
        if int(row.get("attempt") or 0) >= POLICY.release_max_attempts:
            return "release_attempts_exhausted"
        if row.get("status") == "running" and self._leased(row):
            return "controller_lease_held"
        if self._not_due(row):
            return "release_retry_not_due"
        return None

    def _leased(self, row: dict) -> bool:
        try:
            return datetime.fromisoformat(row["lease_until"]) > self._now()
        except (KeyError, TypeError, ValueError):
            return False

    def _not_due(self, row: dict) -> bool:
        try:
            return datetime.fromisoformat(row["retry_at"]) > self._now()
        except (KeyError, TypeError, ValueError):
            return False

    def _gate(self, plan: dict) -> dict:
        """What the EXISTING release record says about this plan. This never writes anything."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        return release_gate(record, plan, self._parent(record))

    def _parent(self, record) -> str | None:
        """The candidate author's own lead, from the existing organization; unknown stays None."""
        author = (record or {}).get("candidate", {}).get("author")
        if self.org is None or not isinstance(author, str):
            return None
        try:
            return self.org.actor(author).parent
        except Exception:
            return None

    # ----- the stages -------------------------------------------------------------------------
    def _advance(self, row: dict, intent: dict, claim) -> dict:
        plan, stage = row["plan"], intent["stage"]
        if stage in {REGISTERED, AWAITING_REVIEW}:
            return self._enter(plan, intent, PUBLISHING, claim)
        if stage == PUBLISHING:
            return self._publish(plan, intent, claim)
        if stage == AWAITING_CI:
            return self._observe_ci(plan, intent, claim)
        if stage == MERGE_INTENDED:
            return self._merge(plan, intent, claim)
        if stage == MERGED:
            return self._prepare_switch(plan, intent, claim)
        if stage == DRAIN_INTENDED:
            return self._drain(plan, intent, claim)
        if stage == SWITCHING:
            return self._switch(plan, intent, claim)
        if stage == AWAITING_CONSUMPTION:
            return self._consume(plan, intent, claim)
        if stage == ROLLING_BACK:
            return self._rollback(plan, intent, claim)
        return self._result(plan, intent, OUTCOME_IDLE, reason_code="stage_terminal")

    def _publish(self, plan: dict, intent: dict, claim) -> dict:
        """Publish the reviewed candidate, or ADOPT the publication a lost response already made."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            self._owned_now(claim)
            observed = port.publish(candidate)
        head = (observed or {}).get("head")
        if head != plan["revision"]:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publish_head_mismatch",
                              claim=claim)
        deadline = self._deadline(plan["ci_timeout_seconds"])
        return self._record("published", lambda: self._enter(
            plan, intent, AWAITING_CI, claim, head=head, pr_number=observed.get("number"),
            pr_url=observed.get("url"), stage_deadline=deadline))

    def _observe_ci(self, plan: dict, intent: dict, claim) -> dict:
        """The REAL checks of the exact intended head; nothing else is evidence that CI passed."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            # The publication this intent recorded is gone: that is a definite refusal to merge, not
            # a reason to publish a second time under the same intent.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        verdict = ci_verdict(plan["required_checks"], observed.get("checks"), intent["head"],
                             observed_head=observed.get("head"))
        self._emit_check(plan, intent, AWAITING_CI, verdict)
        if verdict["state"] == CI_PASSED:
            return self._enter(plan, intent, MERGE_INTENDED, claim, stage_deadline=None,
                               last_check_state=CI_PASSED)
        if verdict["state"] == CI_FAILED:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, verdict["reason_code"],
                              claim=claim, last_check_state=CI_FAILED)
        if verdict["state"] == CI_HEAD_CHANGED:
            # A moved head goes to requalification; it is never rebased into the old acceptance.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim,
                              last_check_state=CI_HEAD_CHANGED)
        if self._expired(intent):
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_timeout", claim=claim,
                              last_check_state=CI_PENDING)
        return self._pending(plan, intent, claim, verdict["reason_code"], last_check_state=CI_PENDING)

    def _merge(self, plan: dict, intent: dict, claim) -> dict:
        """Merge the exact reviewed head, or RECOGNIZE the merge a lost response already made.

        Both paths end at the SAME qualification: the merged revision must carry the reviewed tree,
        checked by the merge owner itself. A merge that happened is not a qualified deployment, so
        a merged tree that is not the reviewed one blocks here - on the tick that performed it and
        on every later tick that observes it - instead of inheriting the old acceptance.
        """
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if observed is None:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_missing", claim=claim)
        if observed.get("head") != intent["head"]:
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "ci_head_changed", claim=claim)
        if observed.get("state") == "MERGED":
            merged = {"merged": True, "merged_revision": observed.get("merged_revision")
                      or intent["head"], "recovered": True}
        else:
            self._owned_now(claim)
            merged = port.merge(candidate)
        revision = merged.get("merged_revision") or intent["head"]
        qualify = getattr(port, "qualify", None)
        if qualify is None:
            return self._record("merged", lambda: self._halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "merge_unqualified", claim=claim,
                merged_revision=revision))
        try:
            qualify(candidate, revision)
        except ContractError as refusal:
            # Bound to a local: `except ... as` unbinds its own name before the lambda runs.
            failure = type(refusal).__name__
            return self._record("merged", lambda: self._halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "merged_tree_mismatch", claim=claim,
                error_type=failure, merged_revision=revision))
        return self._record("merged", lambda: self._enter(plan, intent, MERGED, claim,
                                                          merged_revision=revision))

    def _prepare_switch(self, plan: dict, intent: dict, claim) -> dict:
        """Bind the exact target tuple this delivery will switch to, before touching the host.

        The verified release, the registered target, the current descriptor and the plan's expected
        predecessor must all agree here; the resolved descriptor and the active-release CAS value
        are written durably, so the switch, a replay of it and a rollback all act on one identity.

        The IDENTITY of the instance that is running there is captured here too, while the
        predecessor's own receipt still names it, and durably: the authority to replace an instance
        cannot be re-derived from the target after its descriptor has been replaced. A target whose
        running instance is not the one this delivery's own records name is a disagreement to
        reconcile (`target_instance_mismatch`), not something to switch on top of.
        """
        gate = self._gate(plan)
        if gate["status"] not in {"verified", "active"}:
            # The incumbent checks of this candidate are the evaluator's, not this controller's.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "release_not_verified", claim=claim)
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
            current_row = tx.get(BUCKET_DESCRIPTORS, plan["target_id"])
            active = tx.get("deployment", "active") or {}
        if target is None:
            return self._halt(plan, intent, BLOCKED, OUTCOME_REFUSED, "target_unregistered", claim=claim)
        current = (current_row or {}).get("descriptor")
        current_sha = None if current is None else descriptor_digest(current)
        if plan["expected_descriptor"] != current_sha:
            # The host is not where the owner approved this switch from.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_predecessor_mismatch",
                              claim=claim)
        # The identity of the instance this delivery may replace is captured HERE, before the
        # descriptor is replaced and therefore while the predecessor's own receipt still names it.
        # It is durable, so a later tick, a restart or a lost response acts on the same authority.
        # A port that is not wired yet is not a reason to refuse here - the stage that actually
        # touches the host reports that - and it leaves this delivery with NO authority to replace
        # anything, which the start then refuses rather than acting on an assumption.
        host = self.hosts.get(target["kind"])
        identity = host.identity(target) if hasattr(host, "identity") else {}
        recorded = (current_row or {}).get("instance_id") or (current_row or {}).get(
            "observed_instance_id")
        observed_instance = identity.get("instance_id")
        if recorded and observed_instance and recorded != observed_instance:
            # This delivery's own records and the target disagree about who is running there.
            # Nothing is switched, stopped or started on contradictory evidence.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "target_instance_mismatch",
                              claim=claim)
        descriptor = resolve_descriptor(target, plan, current)
        # A managed target runs an immutable sealed runtime: it is materialized (or, after a lost
        # response, revalidated as the same immutable result) BEFORE the drain, so nothing on the
        # running instance is paused for a runtime that cannot exist. Other kinds have no such port.
        runtime = None
        materialize = getattr(host, "materialize", None)
        if materialize is not None:
            self._owned_now(claim)
            runtime = materialize(target, descriptor, authorize=self._authorizer(claim))
        return self._enter(plan, intent, DRAIN_INTENDED, claim, descriptor=descriptor,
                           **({"runtime": runtime} if runtime is not None else {}),
                           descriptor_sha256=descriptor_digest(descriptor),
                           previous_descriptor=current, previous_descriptor_sha256=current_sha,
                           previous_instance_id=observed_instance or recorded,
                           previous_launch=identity.get("launch"),
                           expected_active=active.get("release_id"), expected_active_set=True,
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _drain(self, plan: dict, intent: dict, claim) -> dict:
        """Pause new admission and prove the target drained; an unconfirmed effect blocks the switch."""
        host, target = self._host(plan)
        # Pausing admission writes to the target's state directory: a stale actor pauses nothing.
        # The check is made again inside the target guard, where the pause actually happens.
        self._owned_now(claim)
        observed = host.drain(target, authorize=self._authorizer(claim))
        # A target that reports what its instance is doing (the managed heartbeat verdict) has that
        # observation recorded with the stage, so the projection shows why a drain waits.
        work = {"work": observed["work"]} if isinstance(observed.get("work"), dict) else {}
        if observed.get("unconfirmed"):
            # Unknown work is not finished work: this never kills active model work to deploy.
            if self._expired(intent):
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_unconfirmed_effects",
                                  claim=claim, **work)
            return self._pending(plan, intent, claim, "drain_unconfirmed_effects", **work)
        if not observed.get("drained"):
            if self._expired(intent):
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "drain_timeout", claim=claim,
                                  **work)
            return self._pending(plan, intent, claim, "drain_pending", **work)
        return self._enter(plan, intent, SWITCHING, claim,
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]), **work)

    def _switch(self, plan: dict, intent: dict, claim) -> dict:
        """Replace the immutable descriptor atomically and start the service exactly once.

        Both halves are reconciled before they are repeated, because a tick that lost its response
        after writing the descriptor or after starting the process must not write a second one or
        start a second instance: the descriptor that is already there is compared to the intended
        one, and a process that is already running and already reports this exact descriptor is
        recognized instead of restarted.

        The start carries the authority captured before the descriptor was replaced, so the only
        running instance it may end is the predecessor this transition named - and what it launched
        or recognized is recorded durably, because that is what a rollback is later authorized to
        replace.
        """
        host, target = self._host(plan)
        descriptor = intent["descriptor"]
        state = self._reconcile_descriptor(host, target, intent)
        if state == "foreign":
            # Neither the descriptor this delivery bound nor the one it expected to replace is
            # there. Something outside this delivery owns the target; it is not overwritten.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_foreign",
                              claim=claim)
        authorize = self._authorizer(claim)
        if state == "intended":
            switched = {"written": False, "recovered": True}
        else:
            self._owned_now(claim)
            switched = host.switch(target, descriptor, expected=intent["previous_descriptor_sha256"],
                                   authorize=authorize)
        running = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if running["consumed"] and host.running(target):
            started = {"started": False, "recovered": True, "instance_id": running["instance_id"]}
        else:
            # This outer check is not the mutation boundary: the guard inside the adapter proves
            # ownership again before the first effect, reconciles what is actually on the target,
            # recognizes an already matching live instance instead of restarting it, and replaces
            # only the instance this delivery's durable transition authorized it to replace.
            self._owned_now(claim)
            started = self._lifecycle(
                lambda: host.start(target, descriptor, authorize=authorize,
                                   replaces=self._replaces(intent, forward=True)))
        self._record("descriptor_switched", lambda: self._record_descriptor(
            plan, intent, descriptor, consumed=False, instance_id=None, claim=claim))
        self._emit(EVENT_SWITCHED, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"], "instance_id": None,
            "consumed": False})
        # What this delivery itself put on the target: the instance it launched or recognized, and
        # the launch record that identifies it even if that instance never confirms a startup. A
        # rollback replaces exactly this, never the predecessor it is restoring.
        return self._record("descriptor_switched", lambda: self._enter(
            plan, intent, AWAITING_CONSUMPTION, claim,
            candidate_instance_id=started.get("instance_id") or intent.get("candidate_instance_id"),
            candidate_launch=started.get("launch") or self._launch_record(host, target),
            switch={"at": self.clock(), "written": bool(switched.get("written")),
                    "started": bool(started.get("started")),
                    "recovered": bool(switched.get("recovered") or started.get("recovered"))},
            stage_deadline=self._deadline(plan["consumption_timeout_seconds"])))

    @staticmethod
    def _replaces(intent: dict, *, forward: bool) -> dict:
        """The ONE instance this delivery is authorized to replace, from its own durable intent.

        Forward, that is the predecessor whose identity was captured BEFORE the descriptor was
        replaced. In a rollback it is the failed candidate THIS intent started - not the
        predecessor it is restoring - because that is the instance this delivery put there. Both
        carry the exact descriptor digest and, when the startup identity was never confirmed, the
        launch record this component wrote under the target's own guard. The adapter is handed this
        authority; it never infers permission from whatever receipt is currently on the target.
        """
        if forward:
            return {"descriptor_sha256": intent.get("previous_descriptor_sha256"),
                    "instance_id": intent.get("previous_instance_id"),
                    "launch": intent.get("previous_launch")}
        return {"descriptor_sha256": intent.get("descriptor_sha256"),
                "instance_id": intent.get("candidate_instance_id"),
                "launch": intent.get("candidate_launch")}

    @staticmethod
    def _launch_record(host, target: dict):
        """This component's own record of the last launch of a target, or None when unavailable."""
        reader = getattr(host, "launch_record", None)
        if reader is None:
            return None
        try:
            return reader(target)
        except Exception:
            return None

    @staticmethod
    def _reconcile_descriptor(host, target: dict, intent: dict) -> str:
        """What is on the host RIGHT NOW, named against this delivery's own two descriptors.

        `intended` is the switch this delivery already made (a lost response, or a restart);
        `previous` is the state it expected to replace, including "no descriptor yet" when that is
        what the plan approved; anything else is `foreign` - another delivery, another controller
        or a hand edit - and is reconciled by an owner rather than overwritten.
        """
        current = host.current(target)
        observed = None if current is None else descriptor_digest(current)
        if observed == intent["descriptor_sha256"]:
            return "intended"
        if observed == intent["previous_descriptor_sha256"]:
            return "previous"
        return "foreign"

    def _consume(self, plan: dict, intent: dict, claim) -> dict:
        """The launched process's OWN startup evidence decides activation; a switch alone does not.

        Observing the startup and activating it are two separate facts in two separate records.
        The accepted receipt is recorded as an OBSERVED startup first - instance, runtime root and
        the revision that runtime is actually at - and only then is the canary asked whether that
        observed runtime may become the active one. The canary therefore never has to read the
        activation this stage has deliberately not written yet, and a runtime that is observed but
        refused is durably an unconsumed descriptor rather than a half-claimed activation.
        """
        host, target = self._host(plan)
        descriptor = intent["descriptor"]
        verdict = consumption_verdict(descriptor, host.receipt(target),
                                      expected_instance=intent.get("previous_instance_id"))
        if not verdict["consumed"]:
            if verdict["reason_code"] in {"receipt_missing", "receipt_stale_instance"} \
                    and not self._expired(intent):
                return self._pending(plan, intent, claim, verdict["reason_code"])
            # A wrong receipt never grants activation, and an expired wait is not an unknown that
            # can be waited out: the exact predecessor is restored.
            return self._begin_rollback(plan, intent, claim, verdict["reason_code"])
        startup = {key: verdict.get(key) for key in
                   ("instance_id", "pid", "runtime_root", "module_root", "revision")}
        self._record("startup_observed", lambda: self._record_descriptor(
            plan, intent, descriptor, consumed=False, instance_id=None, claim=claim,
            startup=startup))
        canary = self._canary(plan, target, descriptor, startup)
        # A canary state of its own, so a passed canary is never mistaken for the CI verdict that
        # preceded it and neither one suppresses the other's transition.
        self._emit_check(plan, intent, AWAITING_CONSUMPTION,
                         {"state": "canary_passed" if canary["passed"] else "canary_failed",
                          "reason_code": canary.get("reason_code"), "missing": [], "failed": [],
                          "pending": []}, canary_passed=bool(canary["passed"]))
        if not canary["passed"]:
            # The instance this delivery started is now known by its own receipt: the rollback that
            # follows replaces exactly it, and nothing else that may be on the target.
            return self._begin_rollback(plan, intent, claim, canary.get("reason_code") or "canary_failed",
                                        canary=canary, instance_id=verdict["instance_id"])
        self._record("consumed", lambda: self._record_descriptor(
            plan, intent, descriptor, consumed=True, instance_id=verdict["instance_id"],
            claim=claim, startup=startup))
        self._emit(EVENT_SWITCHED, "succeeded", plan, attributes={
            "plan_id": plan["plan_id"], "target_id": plan["target_id"],
            "descriptor_sha256": intent["descriptor_sha256"],
            "previous_sha256": intent["previous_descriptor_sha256"],
            "instance_id": verdict["instance_id"], "consumed": True})
        try:
            pointer = self._promote(plan, intent, claim)
        except ContractError as refusal:
            # `Releases` refused its own compare-and-swap: the host is consumed, the pointer is
            # not this release's, and that is a blocked operational fact, never an activation.
            failure = type(refusal).__name__
            return self._record("consumed", lambda: self._halt(
                plan, intent, BLOCKED, OUTCOME_BLOCKED, "release_promotion_refused", claim=claim,
                error_type=failure))
        LOGGER.info("host delivery active plan=%s release=%s target=%s descriptor=%s instance=%s",
                    plan["plan_id"], plan["release_id"], plan["target_id"],
                    intent["descriptor_sha256"], verdict["instance_id"])
        return self._record("release_promoted", lambda: self._enter(
            plan, intent, ACTIVE, claim, outcome=OUTCOME_ACTIVE,
            instance_id=verdict["instance_id"], canary=canary, stage_deadline=None,
            active_pointer=pointer))

    def _promote(self, plan: dict, intent: dict, claim) -> dict | None:
        """Move the existing release pointer through `Releases`, with ITS compare-and-swap.

        The fence check and the promotion share ONE transaction - the promotion is handed the very
        transaction the ownership was checked in - so there is no window between "this controller
        still owns the release" and "this controller moved the active pointer". The expected active
        release is the one recorded when this delivery bound its target tuple, so a pointer that
        moved in between refuses here instead of overwriting another activation, and a release this
        promotion already made active is recognized rather than promoted twice.
        """
        with self.store.transaction() as tx:
            if claim is not None:
                try:
                    self.queue.owned(tx, claim, self._now())
                except ContractError as exc:
                    raise AmbiguousEffect("release_promotion", exc) from exc
            record = tx.get("releases", plan["release_id"]) or {}
            active = tx.get("deployment", "active") or {}
            if record.get("status") == "active" and active.get("release_id") == plan["release_id"]:
                return active
            return self.releases.promote(plan["release_id"], intent.get("expected_active"),
                                         transaction=tx)

    def _begin_rollback(self, plan: dict, intent: dict, claim, reason_code: str, canary=None,
                        instance_id=None) -> dict:
        if instance_id is not None:
            intent = {**intent, "candidate_instance_id": instance_id}
        if intent.get("previous_descriptor") is None:
            # There is no known-good predecessor for this target: nothing may be restored, and the
            # delivery stops where it is rather than inventing a state to return to.
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "no_known_good_predecessor",
                              claim=claim, rollback={"requested": True, "restored": False,
                                                     "verified": False, "reason_code": reason_code},
                              **({"canary": canary} if canary is not None else {}))
        # Progress toward the restoration, not a stop: the fence is deferred rather than finished,
        # so the very next bounded tick performs the rollback instead of waiting for an owner.
        return self._enter(plan, intent, ROLLING_BACK, claim, outcome=OUTCOME_PROGRESSED,
                           reason_code=reason_code, canary=canary,
                           rollback={"requested": True, "restored": False, "verified": False,
                                     "reason_code": reason_code},
                           stage_deadline=self._deadline(plan["consumption_timeout_seconds"]))

    def _rollback(self, plan: dict, intent: dict, claim) -> dict:
        """Restore the EXACT predecessor tuple, then PROVE the restored runtime is the one running.

        Every entry into this stage reconciles first: what descriptor is on the host right now, and
        which instance is actually running. A restoration whose durable acknowledgement was lost is
        RESUMED from what the host already shows rather than attempted a second time against an
        expectation that no longer holds, a descriptor that is neither the failed one nor the
        predecessor is a foreign state that blocks instead of being overwritten, and the start is
        performed at most once per restoration. The instance it is authorized to replace is the
        failed CANDIDATE this intent started - by its own receipt, or by this delivery's launch
        record when that candidate never confirmed a startup - and never an unknown one. Nothing sleeps under the lease: the predecessor's
        own fresh receipt and a live process are what verify it, and a restoration that cannot be
        proven becomes a blocked operational alert rather than a `rolled_back` claim.
        """
        host, target = self._host(plan)
        previous = intent["previous_descriptor"]
        record = dict(intent.get("rollback") or {})
        reason = record.get("reason_code") or "rollback"
        state = self._reconcile_descriptor(host, target, intent)
        if state == "foreign":
            record.update(restored=False, verified=False, error_type=None, at=self.clock())
            return self._blocked_rollback(plan, intent, claim, record, "rollback_foreign_descriptor")
        if state == "intended":
            # The failed descriptor is still the one on the host: restore the predecessor now.
            try:
                self._owned_now(claim)
                host.switch(target, previous, expected=intent["descriptor_sha256"],
                            authorize=self._authorizer(claim))
            except AmbiguousEffect:
                raise
            except Exception as exc:
                error_type = safe_error_type(type(exc).__name__)
                record.update(restored=False, verified=False, error_type=error_type,
                              at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.update(restored=True, started=False, verified=False, error_type=None,
                          at=self.clock())
            return self._record("descriptor_restored", lambda: self._pending(
                plan, intent, claim, "rollback_awaiting_consumption", rollback=record,
                stage_deadline=self._deadline(plan["consumption_timeout_seconds"])))
        # The predecessor descriptor IS on the host, whether this tick wrote it or a lost response
        # did. The restoration is a fact of the host, not of the record that failed to name it.
        record.update(restored=True)
        try:
            verdict = consumption_verdict(previous, host.receipt(target))
            alive = bool(host.running(target))
            error_type = None
        except Exception as exc:
            verdict, alive = {"consumed": False, "instance_id": None}, False
            error_type = safe_error_type(type(exc).__name__)
        if not (verdict["consumed"] and alive) and not record.get("started"):
            # The restored descriptor is there but its runtime is not: start it exactly once, under
            # the same guard, the same authorization and the same reconciliation as a forward start.
            try:
                self._owned_now(claim)
                self._lifecycle(lambda: host.start(target, previous,
                                                   authorize=self._authorizer(claim),
                                                   replaces=self._replaces(intent, forward=False)))
            except AmbiguousEffect:
                raise
            except Exception as exc:
                record.update(started=False, verified=False,
                              error_type=safe_error_type(type(exc).__name__), at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.update(started=True, verified=False, error_type=None, at=self.clock())
            return self._record("predecessor_started", lambda: self._pending(
                plan, intent, claim, "rollback_awaiting_consumption", rollback=record,
                stage_deadline=self._deadline(plan["consumption_timeout_seconds"])))
        if not (verdict["consumed"] and alive):
            record.update(verified=False, error_type=error_type)
            if not self._expired(intent):
                return self._pending(plan, intent, claim, "rollback_awaiting_consumption",
                                     rollback=record)
            return self._blocked_rollback(plan, intent, claim, record, "rollback_unverified")
        record.update(verified=True, error_type=None, at=self.clock())
        self._emit(EVENT_ROLLBACK, "succeeded", plan, severity="warning", reason_code=reason,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": True, "verified": True, "error_type": None})
        self._record("predecessor_consumed", lambda: self._record_descriptor(
            plan, intent, previous, consumed=True, instance_id=verdict.get("instance_id"),
            claim=claim, rolled_back=True,
            startup={key: verdict.get(key) for key in
                     ("instance_id", "pid", "runtime_root", "module_root", "revision")}))
        LOGGER.warning("host delivery rolled back plan=%s target=%s descriptor=%s reason=%s",
                       plan["plan_id"], plan["target_id"], intent["previous_descriptor_sha256"], reason)
        return self._record("predecessor_consumed", lambda: self._enter(
            plan, intent, ROLLED_BACK, claim, outcome=OUTCOME_ROLLED_BACK, reason_code=reason,
            rollback=record, stage_deadline=None))

    def _blocked_rollback(self, plan: dict, intent: dict, claim, record: dict,
                          reason_code: str) -> dict:
        """A failed or unproven restoration: a critical operations alert, never a rolled-back claim."""
        self._emit(EVENT_ROLLBACK, "blocked", plan, severity="critical", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "descriptor_sha256": intent["previous_descriptor_sha256"],
                               "restored": bool(record.get("restored")), "verified": False,
                               "error_type": record.get("error_type")})
        return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, reason_code, claim=claim,
                          error_type=record.get("error_type"), rollback=record)

    # ----- ports ------------------------------------------------------------------------------
    @staticmethod
    def _require_port(port, reason_code: str):
        if port is None:
            raise DeliveryRefused(reason_code)
        return port

    def _host(self, plan: dict):
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
        if target is None:
            raise DeliveryRefused("target_unregistered", "target_id")
        host = self.hosts.get(target["kind"])
        if host is None:
            raise DeliveryRefused("host_port_unavailable", "kind")
        return host, target

    def _candidate(self, plan: dict) -> dict:
        """The reviewed candidate record itself; the plan never supplies a branch, a title or a body."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        if not record or not record.get("candidate"):
            raise DeliveryRefused("release_missing", "release_id")
        return record["candidate"]

    def _canary(self, plan: dict, target: dict, descriptor: dict, startup: dict) -> dict:
        """The incumbent fixed check named by id; a plan can never supply the check itself.

        It is given the OBSERVED startup of the instance that reported this descriptor, so it can
        bind its answer to that instance and that runtime rather than to an activation.
        """
        check = self.canaries.get(plan["canary_check_id"])
        if check is None:
            return {"passed": False, "reason_code": "canary_unavailable", "evidence": None,
                    "check_id": plan["canary_check_id"]}
        try:
            result = check(target, descriptor, startup)
        except Exception as exc:
            return {"passed": False, "reason_code": "canary_error", "evidence": None,
                    "error_type": safe_error_type(type(exc).__name__),
                    "check_id": plan["canary_check_id"]}
        return {"passed": bool(result.get("passed")), "evidence": result.get("evidence"),
                "reason_code": result.get("reason_code"), "check_id": plan["canary_check_id"]}

    # ----- durable bookkeeping ----------------------------------------------------------------
    def _enter(self, plan: dict, intent: dict, stage: str, claim, *, outcome=None, reason_code=None,
               error_type=None, active_pointer=None, **fields) -> dict:
        """Write the durable intent for the stage that is now owed, and report this tick."""
        now = self.clock()
        settled = {**intent, **fields, "stage": stage, "previous_stage": intent["stage"],
                   "outcome": outcome or (OUTCOME_ACTIVE if stage == ACTIVE else OUTCOME_PROGRESSED),
                   "reason_code": reason_code, "error_type": error_type, "attempts": 0,
                   "stage_entered_at": now if stage != intent["stage"] else intent["stage_entered_at"],
                   "updated_at": now}
        self._write(settled, claim)
        if stage != intent["stage"]:
            self._emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": stage, "previous_stage": intent["stage"]})
        return self._result(plan, settled, settled["outcome"], reason_code=reason_code,
                            active=active_pointer)

    def _pending(self, plan: dict, intent: dict, claim, reason_code: str, **fields) -> dict:
        """A bounded external wait: the lease goes back, the stage and its deadline do not move."""
        now = self.clock()
        settled = {**intent, **fields, "outcome": OUTCOME_PENDING, "reason_code": reason_code,
                   "error_type": None, "updated_at": now}
        self._write(settled, claim)
        return self._result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    def _halt(self, plan: dict, intent: dict, stage: str, outcome: str, reason_code: str, *,
              claim=None, error_type=None, **fields) -> dict:
        """A definite stop that PRESERVES the stage it happened at, its evidence and its reason."""
        now = self.clock()
        attempts = int(intent.get("attempts") or 0) + 1
        final = FAILED if attempts >= MAX_STAGE_ATTEMPTS and stage == BLOCKED else stage
        settled = {**intent, **fields, "stage": final, "previous_stage": intent["stage"],
                   "outcome": outcome, "reason_code": reason_code,
                   "error_type": safe_error_type(error_type), "attempts": attempts,
                   "updated_at": now}
        self._write(settled, claim)
        self._emit(EVENT_BLOCKED, "blocked", plan, severity="error", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "stage": intent["stage"], "outcome": outcome,
                               "error_type": settled["error_type"], "attempts": attempts})
        LOGGER.warning("host delivery halted plan=%s stage=%s reason=%s attempts=%d",
                       plan["plan_id"], intent["stage"], reason_code, attempts)
        return self._result(plan, settled, outcome, reason_code=reason_code)

    def _unavailable(self, plan: dict, intent: dict, reason_code: str, exc, *, claim=None,
                     commit: bool = True) -> dict:
        """An outage of the store, of GitHub or of the host: the exception TYPE only, never text."""
        error_type = safe_error_type(type(exc).__name__)
        settled = {**intent, "outcome": OUTCOME_UNAVAILABLE, "reason_code": reason_code,
                   "error_type": error_type, "updated_at": self.clock()}
        if commit:
            try:
                self._write(settled, claim)
            except Exception:
                # The store is what is unavailable; the outage is still reported honestly.
                pass
        LOGGER.warning("host delivery unavailable plan=%s stage=%s reason=%s error=%s",
                       plan["plan_id"], intent["stage"], reason_code, error_type)
        return self._result(plan, settled, OUTCOME_UNAVAILABLE, reason_code=reason_code,
                            error_type=error_type)

    def _write(self, intent: dict, claim) -> None:
        """Commit one durable observation in the SAME transaction that re-checks the fence."""
        with self.store.transaction() as tx:
            if claim is not None:
                self.queue.owned(tx, claim, self._now())
            tx.put(BUCKET_INTENTS, intent["id"], intent)

    def _record_descriptor(self, plan: dict, intent: dict, descriptor: dict, *, consumed: bool,
                           instance_id, claim, rolled_back: bool = False, startup=None) -> None:
        """The host's active descriptor per target, recorded after the host itself moved.

        `startup` is what the launched instance reported about ITSELF and is recorded separately
        from `consumed`: a runtime can be observed without being activated, and the read-only
        projection says which of the two happened rather than blurring them into one flag.
        """
        now = self.clock()
        with self.store.transaction() as tx:
            if claim is not None:
                self.queue.owned(tx, claim, self._now())
            old = tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) or {}
            history = list(old.get("history") or [])[-9:]
            if old.get("descriptor_sha256") and old.get("descriptor_sha256") != descriptor_digest(descriptor):
                history.append({"descriptor_sha256": old["descriptor_sha256"], "at": old.get("updated_at"),
                                "consumed": bool(old.get("consumed"))})
            tx.put(BUCKET_DESCRIPTORS, plan["target_id"], {
                "id": plan["target_id"], "target_id": plan["target_id"], "descriptor": descriptor,
                "descriptor_sha256": descriptor_digest(descriptor), "consumed": bool(consumed),
                "startup_observed": bool(startup),
                "observed_instance_id": (startup or {}).get("instance_id"),
                "observed_revision": (startup or {}).get("revision"),
                "observed_runtime_root": (startup or {}).get("runtime_root"),
                "instance_id": instance_id, "plan_id": plan["plan_id"],
                "release_id": plan["release_id"], "rolled_back": bool(rolled_back),
                "history": history, "updated_at": now})

    def _await_review(self, plan: dict, intent: dict, reason_code: str) -> dict:
        now = self.clock()
        settled = {**intent, "stage": AWAITING_REVIEW, "previous_stage": intent["stage"],
                   "outcome": OUTCOME_PENDING, "reason_code": reason_code, "updated_at": now,
                   "stage_entered_at": now if intent["stage"] != AWAITING_REVIEW
                   else intent["stage_entered_at"]}
        # No claim here on purpose: a plan awaiting its independent review never takes the release
        # controller lease and never spends an attempt of it.
        self._write(settled, None)
        if intent["stage"] != AWAITING_REVIEW:
            self._emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": AWAITING_REVIEW,
                "previous_stage": intent["stage"]})
        return self._result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    # ----- time --------------------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.fromisoformat(self.clock())

    def _deadline(self, seconds: int) -> str:
        return (self._now() + timedelta(seconds=int(seconds))).isoformat()

    def _expired(self, intent: dict) -> bool:
        deadline = intent.get("stage_deadline")
        if not deadline:
            return False
        try:
            return self._now() >= datetime.fromisoformat(deadline)
        except (TypeError, ValueError):
            return False

    # ----- receipts and structured observation --------------------------------------------------
    def _result(self, plan, intent, outcome: str, *, reason_code=None, error_type=None,
                blocked=None, active=None) -> dict:
        """The bounded tick receipt: identities, digests, one outcome and a fixed reason code."""
        stage = (intent or {}).get("stage") or REGISTERED
        return {"schema": TICK_SCHEMA, "plan_id": (plan or {}).get("plan_id"),
                "release_id": (plan or {}).get("release_id"), "target_id": (plan or {}).get("target_id"),
                "outcome": outcome, "stage": stage if plan is not None else None,
                "reason_code": reason_code if reason_code is not None else (intent or {}).get("reason_code"),
                "error_type": error_type if error_type is not None else (intent or {}).get("error_type"),
                "head": (intent or {}).get("head"), "pr_number": (intent or {}).get("pr_number"),
                "merged_revision": (intent or {}).get("merged_revision"),
                "descriptor_sha256": (intent or {}).get("descriptor_sha256"),
                "previous_descriptor_sha256": (intent or {}).get("previous_descriptor_sha256"),
                "instance_id": (intent or {}).get("instance_id"),
                "canary": (intent or {}).get("canary"), "rollback": (intent or {}).get("rollback"),
                "active": active, "ambiguous_effect": None,
                "attempts": int((intent or {}).get("attempts") or 0),
                "blocked": dict(blocked or {}), "at": self.clock(),
                "next_action": stage_next_action(stage, outcome), "authority": AUTHORITY}

    def _emit(self, event_type: str, outcome: str, plan, *, attributes: dict, severity="info",
              reason_code=None) -> None:
        if self.observer is None:
            return
        self.observer.emit(event_type, outcome, severity=severity, reason_code=reason_code,
                           attributes=attributes)

    def _emit_check(self, plan: dict, intent: dict, stage: str, verdict: dict,
                    canary_passed=None) -> None:
        """One evidence-stage transition. A repeated poll with the SAME verdict emits nothing."""
        if self.observer is None or verdict["state"] == intent.get("last_check_state"):
            return
        self._emit(EVENT_CHECK, "observed" if verdict["state"] in {CI_PENDING} else
                   "succeeded" if verdict["state"] == CI_PASSED else "failed", plan,
                   severity="info" if verdict["state"] in {CI_PASSED, CI_PENDING} else "warning",
                   reason_code=verdict.get("reason_code"),
                   attributes={"plan_id": plan["plan_id"], "release_id": plan["release_id"],
                               "stage": stage, "check_state": verdict["state"],
                               "required": len(plan["required_checks"]),
                               "missing": len(verdict.get("missing") or []),
                               "pending": len(verdict.get("pending") or []),
                               "failed": len(verdict.get("failed") or []),
                               "canary_passed": canary_passed})


__all__ = ["BUCKET_DESCRIPTORS", "BUCKET_INTENTS", "BUCKET_PLANS", "BUCKET_TARGETS", "LOGGER",
           "MAX_SCAN", "RESUME_SECONDS", "TARGET_BUSY_STAGES", "AmbiguousEffect", "HostDelivery"]
