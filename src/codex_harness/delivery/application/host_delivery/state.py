"""Delivery state shared by its objects: bucket names, the ambiguous-effect exception, the pure helpers and
the intent writer.

Layer: application
Context: delivery
Owns: bucket host_delivery_intents (sole writer), host_delivery_descriptors
Does not own: the stage decisions (the stage objects), review's releases and release_queue rows (the ReleaseAuthority/ReleaseClaims/ReleaseSettlement ports)
Entry points: DeliveryState, AmbiguousEffect
Contracts: INV-HOST-DELIVERY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

from codex_harness.delivery.domain.host_delivery import (
    ACTIVE,
    AUTHORITY,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    CANARY_FLEET,
    CI_HEAD_CHANGED,
    CI_PASSED,
    CI_PENDING,
    DRAIN_INTENDED,
    EVENT_BLOCKED,
    EVENT_CHECK,
    EVENT_STAGE,
    FAILED,
    MAX_STAGE_ATTEMPTS,
    OUTCOME_ACTIVE,
    OUTCOME_PENDING,
    OUTCOME_PROGRESSED,
    OUTCOME_UNAVAILABLE,
    POST_MERGE_OPEN,
    REGISTERED,
    ROLLING_BACK,
    SWITCHING,
    TICK_SCHEMA,
    VERIFYING,
    DeliveryRefused,
    LifecycleInterrupted,
    descriptor_digest,
    release_gate,
    safe_error_type,
    stage_next_action,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow
from codex_harness.kernel.policy import POLICY

BUCKET_TARGETS = "host_delivery_targets"


BUCKET_PLANS = "host_delivery_plans"


BUCKET_INTENTS = "host_delivery_intents"


BUCKET_DESCRIPTORS = "host_delivery_descriptors"


# INV-HOST-DELIVERY-MIGRATION-001: one evaluator migration per rejected source plan, keyed by it.
BUCKET_MIGRATIONS = "host_delivery_migrations"


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


def predecessor_in(tx, plan: dict) -> str:
    """`_predecessor` inside a caller's transaction. A `verifying` delivery that already merged
    (a resumed one, INV-HOST-DELIVERY-VERIFY-001) is in flight on its target, too."""
    intents = tx.scan(BUCKET_INTENTS)
    current_row = tx.get(BUCKET_DESCRIPTORS, plan["target_id"])
    for other in intents:
        if other.get("target_id") != plan["target_id"] or other.get("plan_id") == plan["plan_id"]:
            continue
        stage = other.get("stage")
        unsettled = stage in {BLOCKED, FAILED} and other.get("descriptor") is not None \
            and not (other.get("rollback") or {}).get("verified")
        merged_verifying = stage == VERIFYING and bool(other.get("merged_revision"))
        if stage in POST_MERGE_OPEN or unsettled or merged_verifying:
            return "in_flight"
    current = (current_row or {}).get("descriptor")
    current_sha = None if current is None else descriptor_digest(current)
    return "held" if current_sha == plan["expected_descriptor"] else "moved"


def record_effect(effect: str, write):
    """Commit what an external effect did; a lost fence here is ambiguity, not cancellation."""
    try:
        return write()
    except ContractError as exc:
        raise AmbiguousEffect(effect, exc) from exc


def lifecycle(action):
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


def replaces(intent: dict, *, forward: bool) -> dict:
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


def launch_record(host, target: dict):
    """This component's own record of the last launch of a target, or None when unavailable."""
    reader = getattr(host, "launch_record", None)
    if reader is None:
        return None
    try:
        return reader(target)
    except Exception:
        return None


def reconcile_descriptor(host, target: dict, intent: dict) -> str:
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


def require_port(port, reason_code: str):
    if port is None:
        raise DeliveryRefused(reason_code)
    return port


def deadline_from(anchor: str, seconds: int) -> str:
    """A deadline derived from an ALREADY-READ instant (no second clock read)."""
    return (datetime.fromisoformat(anchor) + timedelta(seconds=int(seconds))).isoformat()


class DeliveryState:
    """The intent writer and the helpers every delivery object shares: stage entry, waits and halts with their
    observations, the descriptor record, the fence re-check inside a caller's unit, the port and target
    lookups, the release gate and the controller clock (M7 `HostDelivery` shared helpers)."""

    def __init__(self, store, *, org=None, clock=utcnow, hosts=None, canaries=None, observer=None,
                 claims=None):
        self.store = store
        self.org = org
        self.clock = clock
        self.hosts = hosts or {}
        self.canaries = canaries or {}
        self.observer = observer
        self.claims = claims

    # ----- durable bookkeeping ----------------------------------------------------------------
    def enter(self, plan: dict, intent: dict, stage: str, claim, *, outcome=None, reason_code=None,
               error_type=None, active_pointer=None, **fields) -> dict:
        """Write the durable intent for the stage that is now owed, and report this tick."""
        settled = self.entered(intent, stage, outcome=outcome, reason_code=reason_code,
                                error_type=error_type, **fields)
        self._write(settled, claim)
        return self.report_entered(plan, intent, settled, active_pointer=active_pointer)

    def entered(self, intent: dict, stage: str, *, outcome=None, reason_code=None, error_type=None,
                 **fields) -> dict:
        now = self.clock()
        return {**intent, **fields, "stage": stage, "previous_stage": intent["stage"],
                "outcome": outcome or (OUTCOME_ACTIVE if stage == ACTIVE else OUTCOME_PROGRESSED),
                "reason_code": reason_code, "error_type": error_type, "attempts": 0,
                "stage_entered_at": now if stage != intent["stage"] else intent["stage_entered_at"],
                "updated_at": now}

    def report_entered(self, plan: dict, intent: dict, settled: dict, *, active_pointer=None) -> dict:
        if settled["stage"] != intent["stage"]:
            self.emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": settled["stage"], "previous_stage": intent["stage"]})
        return self.result(plan, settled, settled["outcome"], reason_code=settled["reason_code"],
                            active=active_pointer)

    def pending(self, plan: dict, intent: dict, claim, reason_code: str, **fields) -> dict:
        """A bounded external wait: the lease goes back, the stage and its deadline do not move."""
        settled = self.pended(intent, reason_code, **fields)
        self._write(settled, claim)
        return self.result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    def pended(self, intent: dict, reason_code: str, **fields) -> dict:
        return {**intent, **fields, "outcome": OUTCOME_PENDING, "reason_code": reason_code,
                "error_type": None, "updated_at": self.clock()}

    def halt(self, plan: dict, intent: dict, stage: str, outcome: str, reason_code: str, *,
              claim=None, error_type=None, **fields) -> dict:
        """A definite stop that PRESERVES the stage it happened at, its evidence and its reason."""
        settled = self.halted(intent, stage, outcome, reason_code, error_type=error_type, **fields)
        self._write(settled, claim)
        return self.report_halted(plan, intent, settled)

    def halted(self, intent: dict, stage: str, outcome: str, reason_code: str, *, error_type=None,
                **fields) -> dict:
        attempts = int(intent.get("attempts") or 0) + 1
        final = FAILED if attempts >= MAX_STAGE_ATTEMPTS and stage == BLOCKED else stage
        return {**intent, **fields, "stage": final, "previous_stage": intent["stage"],
                "outcome": outcome, "reason_code": reason_code,
                "error_type": safe_error_type(error_type), "attempts": attempts,
                "updated_at": self.clock()}

    def report_halted(self, plan: dict, intent: dict, settled: dict) -> dict:
        reason_code, attempts = settled["reason_code"], settled["attempts"]
        self.emit(EVENT_BLOCKED, "blocked", plan, severity="error", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "stage": intent["stage"], "outcome": settled["outcome"],
                               "error_type": settled["error_type"], "attempts": attempts})
        LOGGER.warning("host delivery halted plan=%s stage=%s reason=%s attempts=%d",
                       plan["plan_id"], intent["stage"], reason_code, attempts)
        return self.result(plan, settled, settled["outcome"], reason_code=reason_code)

    def unavailable(self, plan: dict, intent: dict, reason_code: str, exc, *, claim=None,
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
        return self.result(plan, settled, OUTCOME_UNAVAILABLE, reason_code=reason_code,
                            error_type=error_type)

    def unobserved(self, plan: dict, intent: dict, exc=None) -> dict:
        """The verification fence's completion was not observed (INV-HOST-DELIVERY-VERIFY-001, L-3).

        The store that did not answer the heartbeat is the one every write and settlement would go
        through, and a blocked call there does not end by itself: nothing is committed, and the
        claim is NOT settled - no `finish`, no `defer`, no release. The receipt says so
        (`"claim": "unsettled"`). The row stays `running` with this generation and the attempt
        stays unresolved in the intent; nothing else acts until the lease expires, and the next
        owner reconciles the attempt from its disk record before any new evaluation. The abandoned
        heartbeat is not claimed to be cancelled: it may still complete and renew this lease once.
        """
        result = self.unavailable(plan, intent, "verification_fence_unobservable",
                                   exc or DeliveryRefused("verification_fence_unobservable"), commit=False)
        return {**result, "claim": "unsettled"}

    def _write(self, intent: dict, claim) -> None:
        """Commit one durable observation in the SAME transaction that re-checks the fence."""
        with self.store.transaction() as tx:
            if claim is not None:
                self.claims.owned(tx, claim, self.now())
            tx.put(BUCKET_INTENTS, intent["id"], intent)

    def record_descriptor(self, plan: dict, intent: dict, descriptor: dict, *, consumed: bool,
                           instance_id, claim, rolled_back: bool = False, startup=None) -> None:
        """The host's active descriptor per target, recorded after the host itself moved.

        `startup` is what the launched instance reported about ITSELF and is recorded separately
        from `consumed`: a runtime can be observed without being activated, and the read-only
        projection says which of the two happened rather than blurring them into one flag.
        """
        now = self.clock()
        with self.store.transaction() as tx:
            if claim is not None:
                self.claims.owned(tx, claim, self.now())
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

    def await_review(self, plan: dict, intent: dict, reason_code: str) -> dict:
        now = self.clock()
        settled = {**intent, "stage": AWAITING_REVIEW, "previous_stage": intent["stage"],
                   "outcome": OUTCOME_PENDING, "reason_code": reason_code, "updated_at": now,
                   "stage_entered_at": now if intent["stage"] != AWAITING_REVIEW
                   else intent["stage_entered_at"]}
        # No claim here on purpose: a plan awaiting its independent review never takes the release
        # controller lease and never spends an attempt of it.
        self._write(settled, None)
        if intent["stage"] != AWAITING_REVIEW:
            self.emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": AWAITING_REVIEW,
                "previous_stage": intent["stage"]})
        return self.result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    # ----- the mutation boundary ---------------------------------------------------------------
    def owned_now(self, claim) -> None:
        """Re-check this claim's generation, owner and lease IMMEDIATELY before a mutation.

        One short store transaction of its own: no external call is ever made from inside it, and
        a stale actor raises here, before it can publish, merge, drain, switch, start or restore.
        """
        if claim is None:
            return
        with self.store.transaction() as tx:
            self.claims.owned(tx, claim, self.now())

    def authorizer(self, claim):
        """The same check, handed to the host adapter so it runs INSIDE the target lock."""
        if claim is None:
            return None
        return lambda: self.owned_now(claim)

    def host(self, plan: dict):
        with self.store.transaction() as tx:
            target = tx.get(BUCKET_TARGETS, plan["target_id"])
        if target is None:
            raise DeliveryRefused("target_unregistered", "target_id")
        host = self.hosts.get(target["kind"])
        if host is None:
            raise DeliveryRefused("host_port_unavailable", "kind")
        return host, target

    def candidate(self, plan: dict) -> dict:
        """The reviewed candidate record itself; the plan never supplies a branch, a title or a body."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        if not record or not record.get("candidate"):
            raise DeliveryRefused("release_missing", "release_id")
        return record["candidate"]

    def canary(self, plan: dict, target: dict, descriptor: dict, startup: dict) -> dict:
        """The incumbent fixed check named by id; a plan can never supply the check itself.

        It is given the OBSERVED startup of the instance that reported this descriptor, so it can
        bind its answer to that instance and that runtime rather than to an activation.
        """
        check = self.canaries.get(plan["canary_check_id"])
        if check is None:
            return {"passed": False, "reason_code": "canary_unavailable", "evidence": None,
                    "check_id": plan["canary_check_id"]}
        # The owner's canary answers for exactly the plan being consumed (aibox SPEC s14 G2), never for
        # whichever plan of this target filed its request last.
        bound = {"plan": plan} if plan["canary_check_id"] == CANARY_FLEET else {}
        try:
            result = check(target, descriptor, startup, **bound)
        except Exception as exc:
            return {"passed": False, "reason_code": "canary_error", "evidence": None,
                    "error_type": safe_error_type(type(exc).__name__),
                    "check_id": plan["canary_check_id"]}
        passed = bool(result.get("passed"))
        return {"passed": passed, "evidence": result.get("evidence"), "reason_code": result.get("reason_code"),
                "check_id": plan["canary_check_id"], **({"pending": True} if result.get("pending") and not passed
                                                        else {})}

    def gate(self, plan: dict) -> dict:
        """What the EXISTING release record says about this plan. This never writes anything."""
        with self.store.transaction() as tx:
            record = tx.get("releases", plan["release_id"])
        return release_gate(record, plan, self.parent(record))

    def parent(self, record) -> str | None:
        """The candidate author's own lead, from the existing organization; unknown stays None."""
        author = (record or {}).get("candidate", {}).get("author")
        if self.org is None or not isinstance(author, str):
            return None
        try:
            return self.org.actor(author).parent
        except Exception:
            return None

    def predecessor(self, plan: dict) -> str:
        """The target as a NEW merge of this plan would find it: `in_flight` while another delivery of
        the target has merged and not settled the host - including a `blocked`/`failed` one that bound
        a descriptor without a verified rollback, which is never safe-to-switch evidence - else
        `moved` when the current descriptor is not the plan's expected predecessor, else `held`.
        One store read under the controller's serialization; the switch keeps its own CAS."""
        with self.store.transaction() as tx:
            return predecessor_in(tx, plan)

    def leased(self, row: dict) -> bool:
        try:
            return datetime.fromisoformat(row["lease_until"]) > self.now()
        except (KeyError, TypeError, ValueError):
            return False

    def not_due(self, row: dict) -> bool:
        try:
            return datetime.fromisoformat(row["retry_at"]) > self.now()
        except (KeyError, TypeError, ValueError):
            return False

    # ----- time --------------------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.fromisoformat(self.clock())

    def deadline(self, seconds: int) -> str:
        return (self.now() + timedelta(seconds=int(seconds))).isoformat()

    def expired(self, intent: dict) -> bool:
        deadline = intent.get("stage_deadline")
        if not deadline:
            return False
        try:
            return self.now() >= datetime.fromisoformat(deadline)
        except (TypeError, ValueError):
            return False

    # ----- receipts and structured observation --------------------------------------------------
    def result(self, plan, intent, outcome: str, *, reason_code=None, error_type=None,
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

    def emit(self, event_type: str, outcome: str, plan, *, attributes: dict, severity="info",
              reason_code=None) -> None:
        if self.observer is None:
            return
        self.observer.emit(event_type, outcome, severity=severity, reason_code=reason_code,
                           attributes=attributes)

    def emit_check(self, plan: dict, intent: dict, stage: str, verdict: dict,
                    canary_passed=None, claim=None, durations=None) -> None:
        """One evidence-stage transition. A repeated poll with the SAME verdict emits nothing."""
        if self.observer is None or verdict["state"] == intent.get("last_check_state"):
            return
        self.emit(EVENT_CHECK, "observed" if verdict["state"] in {CI_PENDING} else
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
        self._emit_ci_checks(plan, stage, verdict, claim, durations)

    def _emit_ci_checks(self, plan: dict, stage: str, verdict: dict, claim, durations=None) -> None:
        """One `operations.ci_observed` per REQUIRED check at a CI-stage transition (DESIGN-s10 §17c, R-a54 (1)).

        `conclusion` is the adapter's normalized state through the verdict's lists (`failed` -> failure, `pending`
        -> pending, `missing` -> other, else success): the adapter collapses every completion, so no finer value is
        invented. `duration_seconds` is the adapter's per-check duration (`durations`, name -> whole seconds, from
        `delivery.adapters.host_delivery.check_durations` via the observed PR; S10 F2) for a check that finished, and null when
        it is unknown: no timestamps, a pending or missing check, or a port that reports none. `attempt` is the claimed release_queue
        row's `attempt` (the delivery attempt; the intent's `attempts` counts halts only). A canary transition
        (`awaiting_consumption`) and a moved head (no per-check lists) are not CI observations.
        """
        if stage != AWAITING_CI or verdict["state"] == CI_HEAD_CHANGED:
            return
        failed, pending = set(verdict.get("failed") or ()), set(verdict.get("pending") or ())
        missing = set(verdict.get("missing") or ())
        attempt = int((claim or {}).get("attempt") or 0)
        for name in plan["required_checks"]:
            conclusion = ("failure" if name in failed else "pending" if name in pending
                          else "other" if name in missing else "success")
            self.observer.emit("operations.ci_observed", "observed", attributes={
                "check": "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest(),
                "conclusion": conclusion, "attempt": attempt,
                "duration_seconds": (durations or {}).get(name) if conclusion in {"success", "failure"} else None})

    def emit_queue_wait(self, claim) -> None:
        """One `operations.queue_item_waited` per claim of a release_queue row (DESIGN-s10 §17c, R-a54 (2)).

        `wait_seconds` is this controller's claim time minus the row's own enqueue time (`at`, set by
        `ReleaseQueue.enqueue`). A row without a timezone-aware parseable `at` (or one enqueued after the claim)
        emits nothing: no guessed wait.
        """
        if self.observer is None:
            return
        try:
            queued = datetime.fromisoformat(claim["at"])
        except (KeyError, TypeError, ValueError):
            return
        if queued.tzinfo is None:
            return
        wait = (self.now() - queued).total_seconds()
        if wait < 0:
            return
        self.observer.emit("operations.queue_item_waited", "observed", attributes={
            "queue": "release_queue", "item_ref": "sha256:" + hashlib.sha256(str(claim["id"]).encode("utf-8")).hexdigest(),
            "wait_seconds": wait, "outcome": "started"})

    def unclaimed(self, plan: dict) -> str:
        """Why a claim of this plan's release got nothing - an operational fact of its own: another
        controller holds the single host lease, or this release's own queue row is not runnable."""
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"]) or {}
        status = queued.get("status")
        if status not in {"queued", "retry", "running"}:
            return "release_queue_" + str(status)
        if int(queued.get("attempt") or 0) >= POLICY.release_max_attempts:
            return "release_attempts_exhausted"
        if self.not_due(queued):
            # Its own bounded backoff, not another controller: a distinct operational fact.
            return "release_retry_not_due"
        return "controller_lease_held"
