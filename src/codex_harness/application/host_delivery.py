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
import threading
from datetime import datetime, timedelta

from codex_harness.application.release_queue import ReleaseQueue
from codex_harness.application.releases import Releases, expected_evaluator_pin
from codex_harness.application.tickets import ticket_binding
from codex_harness.domain.host_delivery import (
    ACTIVATION_GATE_CODES,
    ACTIVE,
    AUTHORITY,
    AWAITING_CI,
    AWAITING_CONSUMPTION,
    AWAITING_REVIEW,
    BLOCKED,
    CANARY_FLEET,
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
    EVIDENCE_REF,
    FAILED,
    MAX_STAGE_ATTEMPTS,
    MERGE_INTENDED,
    MERGED,
    MIGRATION_ACTIVE,
    MIGRATION_HELD,
    MIGRATION_KIND_ENVIRONMENT,
    MIGRATION_REGISTERED,
    MIGRATION_RESERVING,
    MIGRATION_STAGED,
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
    POST_MERGE_OPEN,
    PUBLISHING,
    RECOVERY_VERIFICATION_MISSING,
    REGISTERED,
    ROLLED_BACK,
    ROLLING_BACK,
    STATUS_SCHEMA,
    STOPPED_STAGES,
    SWITCHING,
    TERMINAL_STAGES,
    TICK_SCHEMA,
    VERIFYING,
    WITHDRAW_REASONS,
    WITHDRAWABLE_STAGES,
    WITHDRAWN,
    DeliveryRefused,
    LifecycleInterrupted,
    attempts_of,
    ci_verdict,
    consumption_verdict,
    delivery_status,
    descriptor_digest,
    migration_kind,
    migration_lineage_digest,
    migration_rejected_source,
    new_intent,
    plan_digest,
    recoveries_of,
    release_gate,
    resolve_descriptor,
    resumable,
    safe_error_type,
    stage_next_action,
    unresolved_attempts,
    validate_migration_ack,
    validate_migration_request,
    validate_pin,
    validate_plan,
    validate_targets,
)
from codex_harness.domain.managed_runtime import EnvironmentUnqualified
from codex_harness.domain.model import ContractError, digest, utcnow
from codex_harness.domain.policy import POLICY

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


class _FenceObservations:
    """The fence `_verify` hands the evaluator: this claim's heartbeat, with its calls in flight counted.

    INV-HOST-DELIVERY-VERIFY-001: the evaluator observes each call within its bound in a helper
    thread and ABANDONS one that does not complete. Its join timed out or a stop interrupted it;
    nothing cancelled the call, and it may still complete later - a late successful heartbeat renews
    the abandoned lease once, which only delays its reclaim. The count is kept here, not read from
    that helper thread: once a stop interrupts the join, CPython 3.12 marks the still-running thread
    stopped. The store's completion is unobserved when an observation is still in flight as the
    evaluation returns, OR when one ended in an error instead of the store's answer. Under a stop
    the evaluator never sees that error (a blocked PostgreSQL call ends in `lock_timeout` during the
    cancelled attempt's cleanup), and the store it could not reach is the one every commit and
    settlement would wait on. A refusal (`ContractError`, a lost lease) IS the store's answer and
    stays `fence_lost`. `close` answers exactly that and refuses every later call, so an observation
    that had not yet begun can never reach the store after this controller stopped looking.
    """

    def __init__(self, heartbeat):
        self._heartbeat, self._lock = heartbeat, threading.Lock()
        self._flying, self._failed, self._closed = 0, False, False

    def __call__(self):
        with self._lock:
            if self._closed:
                raise DeliveryRefused("verification_fence_closed")
            self._flying += 1
        answered = False
        try:
            result = self._heartbeat()
            answered = True
            return result
        except ContractError:
            answered = True
            raise
        finally:
            # One step, so `close` sees this call either still in flight or with how it ended.
            with self._lock:
                self._flying -= 1
                self._failed = self._failed or not answered

    def close(self) -> bool:
        """End the evaluation's use of this fence; True when the store's completion is unobserved:
        an observation still in flight, or one that ended in an error instead of an answer."""
        with self._lock:
            self._closed = True
            return self._flying > 0 or self._failed


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
                 resume_seconds: int = RESUME_SECONDS, verifier=None, evaluator_pins=None):
        self.store, self.org, self.clock = store, org, clock
        self.github, self.hosts, self.canaries = github, hosts or {}, canaries or {}
        # INV-HOST-DELIVERY-VERIFY-001: the owned-attempt port over the existing incumbent
        # evaluator. Without it a reviewed release waits in `verifying` as `verifier_unavailable`.
        self.verifier = verifier
        # INV-RELEASE-EVALUATOR-MIGRATION-001: the repository resolver of an approved evaluator pin,
        # (evaluator_revision, base) -> resolve_evaluator_pin(...). Without it no migration stages.
        self.evaluator_pins = evaluator_pins
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
            cached = self._register_in(tx, plan, pin, sha, now)
        return {"registered": True, "cached": cached, "plan_id": plan["plan_id"], "plan_sha256": sha,
                "pin": pin, "target_id": plan["target_id"], "release_id": plan["release_id"],
                "authority": AUTHORITY}

    def _register_in(self, tx, plan: dict, pin: dict, sha: str, now: str, *, migration=None) -> bool:
        """`register` inside a caller's transaction; True for the identical cached registration.

        A target reserved by an unfinished evaluator migration (INV-HOST-DELIVERY-MIGRATION-001)
        admits no NEW plan except that migration's own one, so terminalizing the rejected source
        never frees its target for another delivery before the successor is registered."""
        if tx.get(BUCKET_TARGETS, plan["target_id"]) is None:
            raise DeliveryRefused("target_unregistered", "target_id")
        old = tx.get(BUCKET_PLANS, plan["plan_id"])
        intent = tx.get(BUCKET_INTENTS, plan["plan_id"])
        if old is not None:
            if old["plan_sha256"] == sha and old["pin"] == pin:
                return True
            if intent is not None and intent.get("stage") != REGISTERED:
                raise DeliveryRefused("delivery_in_flight", "plan_id")
        reserved = self._reservation_in(tx, plan["target_id"])
        if reserved is not None and (migration is None or reserved["id"] != migration["id"]):
            raise DeliveryRefused("target_reserved_by_migration", "target_id")
        row = {"id": plan["plan_id"], "plan_id": plan["plan_id"], "plan": plan,
               "plan_sha256": sha, "pin": pin, "target_id": plan["target_id"],
               "registered_at": (old or {}).get("registered_at") or now, "updated_at": now}
        tx.put(BUCKET_PLANS, plan["plan_id"], row)
        return False

    @staticmethod
    def _reservation_in(tx, target_id: str):
        """The unfinished migration (`staged`/`registered`) holding this target, or None."""
        for record in tx.scan(BUCKET_MIGRATIONS):
            if record.get("target_id") == target_id and record.get("state") in MIGRATION_RESERVING:
                return record
        return None

    def approval(self, document) -> dict:
        """What the EXISTING release record says about one plan document, before it is registered: the
        same read-only gate a tick applies (`release_gate`). A server owner publishing a plan uses it to
        publish only an approved exact candidate (INV-OWNER-ACTIONS-001); it approves nothing."""
        return self._gate(validate_plan(document))

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
            migrations = tx.scan(BUCKET_MIGRATIONS)
        # INV-HOST-DELIVERY-MIGRATION-001: each migration's phase and its successor's hold, read only.
        shown = sorted(({"old_plan_id": m.get("id"), "migration_id": m.get("migration_id"),
                         "kind": m.get("kind", "evaluator_migration"), "state": m.get("state"),
                         "held": (intents.get(m.get("plan_id")) or {}).get("held") if m.get("plan_id") else None,
                         "successor_release_id": m.get("successor_release_id"), "plan_id": m.get("plan_id"),
                         "target_id": m.get("target_id"), "at": m.get("at")}
                        for m in migrations if plan_id is None or plan_id in {m.get("id"), m.get("plan_id")}),
                       key=lambda m: (str(m["old_plan_id"]), str(m["migration_id"])))
        # The migration projection is additive: a store with no registered plan and no migration keeps
        # the exact unregistered envelope it always had (INV-HOST-DELIVERY-MIGRATION-001).
        projected = {"migrations": shown} if rows or migrations else {}
        if plan_id is not None and not rows:
            return {"schema": STATUS_SCHEMA, "plan_id": plan_id, "registered": False,
                    "enabled": self.enabled, "outcome": OUTCOME_UNREGISTERED, "deliveries": [],
                    "next_action": "register_plan", "targets": sorted(descriptors),
                    **projected, "authority": AUTHORITY}
        return {**delivery_status(rows, intents, descriptors, enabled=self.enabled), **projected}

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
        if (intent or {}).get("held"):
            # Defensive: `_select` never chooses a held intent; nothing is enqueued or claimed.
            return self._result(plan, intent, OUTCOME_BUSY, reason_code=str(intent["held"]))
        if not self.enabled:
            # Registration, reconciliation and projection stay available; nothing external happens.
            return self._result(plan, intent, OUTCOME_DISABLED, reason_code="delivery_disabled")
        gate = self._gate(plan)
        if gate["state"] == OUTCOME_REFUSED and intent["stage"] != VERIFYING:
            # A `verifying` delivery halts only from inside `_verify`, after its attempts are
            # reconciled, so a refused verdict never leaves attempt debt unreconciled here.
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
            return self._result(plan, intent, OUTCOME_BUSY, reason_code=self._unclaimed(plan))
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
        if result.get("claim") != "unsettled":
            # An unobserved verification fence (`_unobserved`) is not settled through the store it
            # could not observe: the claim stays running until its lease expires, and the next
            # owner reconciles the attempt first (INV-HOST-DELIVERY-VERIFY-001).
            self._settle(claim, result)
        return result

    def _unclaimed(self, plan: dict) -> str:
        """Why a claim of this plan's release got nothing - an operational fact of its own: another
        controller holds the single host lease, or this release's own queue row is not runnable."""
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"]) or {}
        status = queued.get("status")
        if status not in {"queued", "retry", "running"}:
            return "release_queue_" + str(status)
        if int(queued.get("attempt") or 0) >= POLICY.release_max_attempts:
            return "release_attempts_exhausted"
        if self._not_due(queued):
            # Its own bounded backoff, not another controller: a distinct operational fact.
            return "release_retry_not_due"
        return "controller_lease_held"

    # ----- owner withdrawal of a stale, untouched delivery ---------------------------------------
    def withdraw(self, plan_id: str, plan_sha256: str, reason: str, evidence_ref: str) -> dict:
        """Retire ONE registered delivery whose reviewed base or expected predecessor no longer holds.

        Allowed only while the host was never touched (no descriptor bound), and only on staleness
        observed NOW, never on a claim: `reviewed_base_moved` needs the remote main to be neither the
        reviewed base nor carrying this candidate, `descriptor_predecessor_moved` needs the target's
        descriptor to differ from the plan's expected one with no other delivery unsettled on it, and
        `merged_tree_mismatch` retires a delivery whose recorded merge is still exactly what main
        shows (its merge stays in the record as `main_effect: merged`). A merge observed for any other
        reason is `withdraw_merge_observed`; an unreadable GitHub or store is `withdraw_unobservable`
        and writes nothing. An open stage is fenced exactly as a tick is - the release's queue row is
        claimed, the intent written in the transaction that re-checks the claim, the row finished as
        `withdrawn` - so no controller can publish or merge in between.

        The plan row, its owner action, its canary request and any PR are never modified. The
        identical replay is `cached` (and finishes a queue row a crash left runnable, with no other
        effect); a different reason or evidence for a withdrawn plan is `withdrawal_conflict`.
        """
        if reason not in WITHDRAW_REASONS:
            raise DeliveryRefused("withdraw_reason_unsupported", "reason")
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("withdraw_evidence_invalid", "evidence")
        with self.store.transaction() as tx:
            row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
            intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("withdraw_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        if (intent or {}).get("stage") == WITHDRAWN:
            recorded = intent.get("withdrawal") or {}
            if (recorded.get("reason_code"), recorded.get("evidence_ref")) != (reason, evidence_ref):
                raise DeliveryRefused("withdrawal_conflict", "reason")
            return self._withdrawn(plan, intent, cached=True, queue=self._finish_withdrawn(plan))
        # Read-only first: an unobservable, fresh or merged delivery is refused with nothing written.
        self._withdrawable(intent, reason)
        self._stale_now(plan, intent, reason)
        claim = None
        if ((intent or {}).get("stage") or REGISTERED) not in STOPPED_STAGES:
            claim = self._withdraw_claim(plan)
        try:
            # Again under the fence, from the intent as it is now: what is written is what was proven.
            with self.store.transaction() as tx:
                intent = tx.get(BUCKET_INTENTS, plan_id)
            self._withdrawable(intent, reason)
            observed = self._stale_now(plan, intent, reason)
            settled = self._commit_withdrawal(row, intent, reason, evidence_ref, observed, claim)
        except Exception as exc:
            if claim is not None:
                try:
                    # Not an attempt of the release: the lease goes back with nothing else changed.
                    self.queue.defer(claim, {"status": "withdraw_refused",
                                             "reason": getattr(exc, "reason_code", None) or type(exc).__name__},
                                     resume_after_seconds=0, now=self._now())
                except ContractError:
                    pass
            raise
        queue = None
        if claim is not None:
            try:
                queue = self.queue.finish(claim, {"status": WITHDRAWN, "reason": reason}, self._now())["status"]
            except ContractError:
                queue = "controller_stale"   # the withdrawal is durable; a replay finishes the row
        self._emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": WITHDRAWN, "previous_stage": settled["previous_stage"]})
        LOGGER.warning("host delivery withdrawn plan=%s reason=%s previous_stage=%s", plan["plan_id"], reason,
                       settled["previous_stage"])
        return self._withdrawn(plan, settled, cached=False, queue=queue)

    @staticmethod
    def _withdrawable(intent, reason: str) -> None:
        """The host was never touched: no descriptor bound, at a stage before the host is reached."""
        stage = (intent or {}).get("stage") or REGISTERED
        if (intent or {}).get("held"):
            # INV-HOST-DELIVERY-MIGRATION-001: a held migration successor is never claimed or queued,
            # not even to be withdrawn; its handoff is resolved by its own owners.
            raise DeliveryRefused("withdraw_migration_held", "stage")
        if stage not in WITHDRAWABLE_STAGES or (intent or {}).get("descriptor") is not None:
            raise DeliveryRefused("withdraw_host_touched", "stage")
        if unresolved_attempts(intent):
            # INV-HOST-DELIVERY-VERIFY-001: a withdrawal never orphans verification ownership debt.
            raise DeliveryRefused("withdraw_verification_unresolved", "stage")
        recorded = stage in {BLOCKED, FAILED} and intent.get("reason_code") == "merged_tree_mismatch"
        if (reason == "merged_tree_mismatch") != recorded:
            # A recorded merge is retired only under its own reason, and that reason needs one.
            raise DeliveryRefused("withdraw_merge_observed" if recorded else "withdraw_not_stale", "reason")

    def _stale_now(self, plan: dict, intent, reason: str) -> dict:
        """Observe GitHub, the remote main and the target now; raise the named refusal, or return
        what was observed. Unavailable is not absent: any failure to observe refuses."""
        port = self.github
        try:
            if port is None:
                raise DeliveryRefused("github_port_unavailable")
            candidate = self._candidate(plan)
            observed = port.observe(candidate)
            state = port.merge_state(candidate, observed)
            predecessor = self._predecessor(plan)
            with self.store.transaction() as tx:
                current = (tx.get(BUCKET_DESCRIPTORS, plan["target_id"]) or {}).get("descriptor")
        except Exception as exc:
            raise DeliveryRefused("withdraw_unobservable", "github") from exc
        facts = {"main": state.get("main"), "merge_state": state["state"],
                 "pr_state": (observed or {}).get("state"), "pr_head": (observed or {}).get("head"),
                 "pr_number": (observed or {}).get("number"),
                 "descriptor_sha256": None if current is None else descriptor_digest(current)}
        if state["state"] == "merged":
            if reason != "merged_tree_mismatch" or state["merged_revision"] != (intent or {}).get("merged_revision"):
                raise DeliveryRefused("withdraw_merge_observed", "reason")
            return {"main_effect": "merged", "observed": facts}
        if reason == "merged_tree_mismatch":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        if reason == "reviewed_base_moved" and state["state"] != "base_moved":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        if reason == "descriptor_predecessor_moved" and predecessor != "moved":
            raise DeliveryRefused("withdraw_not_stale", "reason")
        return {"main_effect": "none", "observed": facts}

    def _withdraw_claim(self, plan: dict):
        """The same fence a tick takes for this release; refused with the tick's own reason codes."""
        try:
            self.queue.enqueue(plan["release_id"], "host delivery withdrawal " + plan["plan_id"])
            claim = self.queue.claim(now=self._now(), eligible=lambda queued: queued["id"] == plan["release_id"])
        except ContractError as exc:
            raise DeliveryRefused("withdraw_queue_refused", "release_id") from exc
        if claim is None:
            raise DeliveryRefused(self._unclaimed(plan), "release_id")
        return claim

    def _commit_withdrawal(self, row: dict, intent, reason: str, evidence_ref: str, observed: dict,
                           claim) -> dict:
        """One transaction: the fence (when claimed) and an unchanged intent, then the terminal row.
        An absent intent is created and withdrawn together, so nothing ever runs in between."""
        plan, now = row["plan"], self.clock()
        base = intent if intent is not None else new_intent(plan, row["plan_sha256"], now)
        withdrawal = {"reason_code": reason, "evidence_ref": evidence_ref, "previous_stage": base["stage"],
                      "main_effect": observed["main_effect"], "merged_revision": base.get("merged_revision"),
                      "observed": observed["observed"], "at": now}
        settled = {**base, "stage": WITHDRAWN, "previous_stage": base["stage"], "outcome": WITHDRAWN,
                   "reason_code": reason, "error_type": None, "stage_deadline": None, "withdrawal": withdrawal,
                   "updated_at": now}
        with self.store.transaction() as tx:
            if claim is not None:
                self.queue.owned(tx, claim, self._now())
            if tx.get(BUCKET_INTENTS, plan["plan_id"]) != intent:
                raise DeliveryRefused("withdraw_intent_changed", "plan_id")
            tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    def _finish_withdrawn(self, plan: dict) -> str | None:
        """A withdrawal whose queue row a crash left runnable: finish that row, and nothing else."""
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"])
        if not isinstance(queued, dict) or queued.get("status") not in {"queued", "retry", "running"}:
            return None if queued is None else queued.get("status")
        claim = self.queue.claim(now=self._now(), eligible=lambda row: row["id"] == plan["release_id"])
        if claim is None:
            return self._unclaimed(plan)
        return self.queue.finish(claim, {"status": WITHDRAWN, "reason": "withdrawal_replayed"}, self._now())["status"]

    def _withdrawn(self, plan: dict, intent: dict, *, cached: bool, queue) -> dict:
        return {"withdrawn": True, "cached": cached, "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": WITHDRAWN, "queue": queue,
                "withdrawal": dict(intent.get("withdrawal") or {}),
                "next_action": stage_next_action(WITHDRAWN), "authority": AUTHORITY}

    # ----- owner resume of a merged, never verified delivery (INV-HOST-DELIVERY-VERIFY-001) ------
    def resume(self, plan_id: str, plan_sha256: str, evidence_ref: str) -> dict:
        """Move exactly the legacy `release_not_verified`-at-`merged` shape back to `verifying`.

        Read-only first: the plan and its digest, the resumable shape, the release gate, GitHub's
        merge of exactly the recorded revision and the merge owner's own tree qualification. Then
        ONE store transaction - rolled back as a whole on any refusal - re-checks the intent (CAS),
        the controller lease, the queue row, the predecessor, the exact release identity and its
        ticket binding, re-arms a stopped queue row through `ReleaseQueue.retry` (one
        `manual_retries` entry) and writes `verifying` with the original halt copied into the
        recovery record. No claim, lease or generation is created, reset or finished here: the next
        ordinary tick claims the row and verifies.

        The same evidence is recognized as a replay from the durable recovery record at ANY later
        stage and answers `cached` with no write; a different evidence is refused.
        """
        if not (type(evidence_ref) is str and EVIDENCE_REF.fullmatch(evidence_ref)):
            raise DeliveryRefused("resume_evidence_invalid", "evidence")
        try:
            with self.store.transaction() as tx:
                row = tx.get(BUCKET_PLANS, plan_id) if type(plan_id) is str else None
                intent = tx.get(BUCKET_INTENTS, plan_id) if row is not None else None
                queued = tx.get("release_queue", row["plan"]["release_id"]) if row is not None else None
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if row is None:
            raise DeliveryRefused("plan_unregistered", "plan_id")
        if row["plan_sha256"] != plan_sha256:
            raise DeliveryRefused("resume_plan_mismatch", "plan_sha256")
        plan = row["plan"]
        replayed = self._resume_replay(plan, intent, evidence_ref)
        if replayed is not None:
            return replayed
        if not resumable(intent):
            raise DeliveryRefused("resume_not_applicable", "stage")
        try:
            gate = self._gate(plan)
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        self._resume_gate(gate)
        observed = self._resume_merge(plan, intent)
        now = self.clock()
        recovery = {"kind": RECOVERY_VERIFICATION_MISSING, "evidence_ref": evidence_ref,
                    "halted": {key: intent.get(key) for key in ("stage", "previous_stage", "reason_code",
                                                                "outcome", "attempts", "error_type",
                                                                "updated_at")},
                    "observed": {**observed, "tree_qualified": True, "predecessor": "held"}, "at": now}
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_INTENTS, plan["plan_id"])
                settled = (None if self._replay_of(current, evidence_ref)
                           else self._resume_in(tx, row, intent, queued, current, recovery, now))
        except DeliveryRefused:
            raise
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "store") from exc
        if settled is None:
            # A concurrent same-evidence resume committed first: its record answers, nothing written.
            return self._resumed(plan, current, cached=True, evidence_ref=evidence_ref)
        self._emit(EVENT_STAGE, "observed", plan, attributes={
            "plan_id": plan["plan_id"], "release_id": plan["release_id"], "target_id": plan["target_id"],
            "stage": VERIFYING, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery resumed plan=%s from=%s reason=%s", plan["plan_id"], intent["stage"],
                       intent.get("reason_code"))
        return self._resumed(plan, settled, cached=False)

    def _resume_in(self, tx, row: dict, intent: dict, queued, current, recovery: dict, now: str) -> dict:
        """Phase 2, inside the one transaction; any refusal raised here rolls every write back."""
        plan = row["plan"]
        if current != intent or tx.get(BUCKET_PLANS, plan["plan_id"]) != row:
            raise DeliveryRefused("resume_intent_changed", "plan_id")
        lock = tx.get("deployment_locks", "controller") or {}
        if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self._now():
            raise DeliveryRefused("resume_controller_running", "release_id")
        if tx.get("release_queue", plan["release_id"]) != queued:
            raise DeliveryRefused("resume_queue_changed", "release_id")
        predecessor = self._predecessor_in(tx, plan)
        if predecessor != "held":
            raise DeliveryRefused("resume_predecessor_" + predecessor, "target_id")
        # The exact immutable release identity and its ticket binding, whatever the queue shows.
        record = tx.get("releases", plan["release_id"])
        self._resume_gate(release_gate(record, plan, self._parent(record)))
        try:
            ticket_binding(tx, record["candidate"])
        except ContractError as exc:
            raise DeliveryRefused("resume_release_ticket_changed", "release_id") from exc
        status = (queued or {}).get("status")
        if status in {"blocked", "failed"}:
            try:
                self.queue.retry(plan["release_id"], "host delivery resume " + plan["plan_id"] + " "
                                 + recovery["evidence_ref"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("resume_queue_refused", "release_id") from exc
        elif not (queued is None or status in {"queued", "retry"}
                  or (status == "running" and not self._leased(queued))):
            raise DeliveryRefused("resume_queue_" + str(status), "release_id")
        settled = {**current, "stage": VERIFYING, "previous_stage": current["stage"],
                   "outcome": OUTCOME_PROGRESSED, "reason_code": None, "error_type": None, "attempts": 0,
                   "after_verification": MERGED,
                   "recoveries": [*(current.get("recoveries") or []), recovery],
                   "stage_entered_at": now, "updated_at": now}
        tx.put(BUCKET_INTENTS, plan["plan_id"], settled)
        return settled

    @staticmethod
    def _resume_gate(gate: dict) -> None:
        if gate["state"] == "approved" and gate["status"] in {"reviewed", "verified"}:
            return
        code = gate.get("reason_code") or "release_" + str(gate.get("status"))
        raise DeliveryRefused("resume_" + (code if code.startswith("release_") else "release_" + code),
                              "release_id")

    def _resume_merge(self, plan: dict, intent: dict) -> dict:
        """GitHub merged exactly the recorded revision, and it carries the reviewed tree. Read-only
        for the store; the qualification may refresh fetched refs, exactly as `_merge` does."""
        port = self.github
        qualify = getattr(port, "qualify", None)
        if port is None or qualify is None:
            raise DeliveryRefused("resume_unobservable", "github")
        try:
            candidate = self._candidate(plan)
            state = port.merge_state(candidate, port.observe(candidate))
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "github") from exc
        if state.get("state") != "merged" or state.get("merged_revision") != intent["merged_revision"]:
            raise DeliveryRefused("resume_merge_mismatch", "merged_revision")
        try:
            qualify(candidate, intent["merged_revision"])
        except ContractError as exc:
            raise DeliveryRefused("resume_tree_mismatch", "merged_revision") from exc
        except Exception as exc:
            raise DeliveryRefused("resume_unobservable", "github") from exc
        return {"main": state.get("main"), "merged_revision": intent["merged_revision"]}

    def _resume_replay(self, plan: dict, intent, evidence_ref: str):
        """The durable recovery record decides a repeated call, at whatever stage it now is."""
        if not self._replay_of(intent, evidence_ref):
            return None
        return self._resumed(plan, intent, cached=True, evidence_ref=evidence_ref)

    @staticmethod
    def _replay_of(intent, evidence_ref: str) -> bool:
        """True for this evidence's own recorded recovery; another evidence is refused. Pure."""
        recorded = recoveries_of(intent)
        if not recorded:
            return False
        if any(row.get("evidence_ref") == evidence_ref for row in recorded):
            return True
        # One recovery of this kind per delivery: halted again in the same shape is exhausted.
        if resumable({**intent, "recoveries": []}):
            raise DeliveryRefused("resume_exhausted", "evidence")
        raise DeliveryRefused("resume_conflict", "evidence")

    def _resumed(self, plan: dict, intent: dict, *, cached: bool, evidence_ref=None) -> dict:
        recorded = [row for row in recoveries_of(intent)
                    if evidence_ref is None or row.get("evidence_ref") == evidence_ref][-1]
        with self.store.transaction() as tx:
            queued = tx.get("release_queue", plan["release_id"]) or {}
        return {"resumed": True, "cached": cached, "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": intent["stage"],
                "after_verification": intent.get("after_verification"),
                "recovery": {"kind": recorded["kind"], "evidence_ref": recorded["evidence_ref"],
                             "halted_reason_code": (recorded.get("halted") or {}).get("reason_code"),
                             "at": recorded.get("at")},
                "queue": {"status": queued.get("status"),
                          "manual_retries": len(queued.get("manual_retries") or [])},
                "next_action": stage_next_action(intent["stage"], intent.get("outcome")),
                "authority": AUTHORITY}

    # ----- evaluator migration of a rejected, merged delivery (INV-HOST-DELIVERY-MIGRATION-001) ---
    # The lane half of an ordered control/lane handoff; each step is ONE lane transaction and a
    # crash between steps leaves a named `staged`/`registered` record that reserves the target and
    # holds its successor, never a free target or an unowned runnable delivery.
    def stage_migration(self, request: dict) -> dict:
        """Step 1: supersede the exact rejected, merged, host-untouched source and reserve its target.

        Read-only validation first; then ONE transaction re-checks the source intent and plan (CAS),
        the controller lease, the source queue row and the target, creates the reviewed successor
        release through `Releases.request_evaluator_migration` in that same transaction, terminalizes
        the old intent truthfully (`withdrawn`/`release_rejected_superseded`, its halt copied) and
        writes the `staged` record. Nothing is enqueued. The identical request replays `cached`
        with no write; any other request for the same source is `migration_conflict`.
        """
        request = validate_migration_request(request)
        sha, key = digest(request), request["old_plan_id"]
        try:
            with self.store.transaction() as tx:
                record = tx.get(BUCKET_MIGRATIONS, key)
                row = tx.get(BUCKET_PLANS, key)
                intent = tx.get(BUCKET_INTENTS, key)
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        if record is not None:
            return self._migration_replay(record, sha)
        if row is None:
            raise DeliveryRefused("plan_unregistered", "old_plan_id")
        if row["plan_sha256"] != request["old_plan_sha256"]:
            raise DeliveryRefused("migration_plan_mismatch", "old_plan_sha256")
        refusal = migration_rejected_source(intent, row["plan"], request)
        if refusal is not None:
            raise DeliveryRefused(refusal, "old_plan_id")
        if migration_kind(request) == MIGRATION_KIND_ENVIRONMENT:
            resolved = self._resolve_source_pin(request["source_release_id"])
        else:
            resolved = self._resolve_evaluator_pin(request["approval"])
        now = self.clock()
        try:
            with self.store.transaction() as tx:
                current = tx.get(BUCKET_MIGRATIONS, key)
                staged = None if current is not None else self._stage_in(tx, row, intent, request, sha, now,
                                                                         resolved)
        except DeliveryRefused:
            raise
        except ContractError as exc:
            raise DeliveryRefused("migration_release_refused", "source_release_id") from exc
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        if staged is None:
            # A concurrent request committed first: its record decides, nothing was written here.
            return self._migration_replay(current, sha)
        self._emit(EVENT_STAGE, "observed", row["plan"], attributes={
            "plan_id": key, "release_id": row["plan"]["release_id"], "target_id": row["plan"]["target_id"],
            "stage": WITHDRAWN, "previous_stage": intent["stage"]})
        LOGGER.warning("host delivery migration staged plan=%s successor=%s", key, staged["successor_release_id"])
        return self._migration_view(staged, cached=False)

    def _resolve_evaluator_pin(self, approval: dict) -> dict:
        """Derive the approved evaluator pin from the repository BEFORE any write and outside every
        store transaction (INV-RELEASE-EVALUATOR-MIGRATION-001). An absent or failing resolver is
        `migration_pin_unavailable`; any disagreement with the approval is `migration_pin_mismatch`.
        Either refusal leaves the source release, the migration identity and the old intent untouched."""
        if self.evaluator_pins is None:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision")
        try:
            resolved = self.evaluator_pins(approval["evaluator_revision"], approval["base"])
        except Exception as exc:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision") from exc
        if resolved != expected_evaluator_pin(approval):
            raise DeliveryRefused("migration_pin_mismatch", "approval")
        return resolved

    def _resolve_source_pin(self, release_id: str) -> dict:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001: re-derive the migrated source's OWN evaluator pin
        (its recorded E and base) from the repository, outside every store transaction. The release
        service compares it with the source's receipt again inside the staging transaction."""
        try:
            with self.store.transaction() as tx:
                source = tx.get("releases", release_id)
        except Exception as exc:
            raise DeliveryRefused("migration_unobservable", "store") from exc
        receipt = (source or {}).get("evaluator_migration")
        if not isinstance(receipt, dict):
            raise DeliveryRefused("migration_release_refused", "source_release_id")
        if self.evaluator_pins is None:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision")
        try:
            resolved = self.evaluator_pins(receipt["evaluator_revision"], receipt["base"])
        except Exception as exc:
            raise DeliveryRefused("migration_pin_unavailable", "evaluator_revision") from exc
        if resolved != expected_evaluator_pin(receipt):
            raise DeliveryRefused("migration_pin_mismatch", "approval")
        return resolved

    def _stage_in(self, tx, row: dict, intent: dict, request: dict, sha: str, now: str,
                  resolved_pin: dict) -> dict:
        """Phase 2 of `stage_migration`, inside its one transaction; any refusal rolls back all."""
        plan, key = row["plan"], row["plan_id"]
        if tx.get(BUCKET_PLANS, key) != row or tx.get(BUCKET_INTENTS, key) != intent:
            raise DeliveryRefused("migration_intent_changed", "old_plan_id")
        lock = tx.get("deployment_locks", "controller") or {}
        if (lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > self._now()) \
                or (tx.get("release_queue", plan["release_id"]) or {}).get("status") == "running":
            raise DeliveryRefused("migration_controller_running", "release_id")
        for other in tx.scan(BUCKET_MIGRATIONS):
            if other.get("source_release_id") == request["source_release_id"]:
                raise DeliveryRefused("migration_conflict", "source_release_id")
            if other.get("target_id") == plan["target_id"] and other.get("state") in MIGRATION_RESERVING:
                raise DeliveryRefused("migration_target_busy", "target_id")
        stages = {other["plan_id"]: other.get("stage") for other in tx.scan(BUCKET_INTENTS)}
        if any(other["target_id"] == plan["target_id"] and other["plan_id"] != key
               and stages.get(other["plan_id"]) not in TERMINAL_STAGES for other in tx.scan(BUCKET_PLANS)):
            # Every other plan of the target, including one no tick has given an intent yet.
            raise DeliveryRefused("migration_target_busy", "target_id")
        kind = migration_kind(request)
        successor_of = (self.releases.request_environment_reverification if kind == MIGRATION_KIND_ENVIRONMENT
                        else self.releases.request_evaluator_migration)
        successor = successor_of(
            request["source_release_id"], request["actor"], expected_revision=request["candidate_revision"],
            expected_policy_hash=request["source_policy_hash"], approval=request["approval"],
            resolved_pin=resolved_pin, now=self._now(), transaction=tx)
        if successor.get("status") != "reviewed" or successor.get("checks"):
            raise DeliveryRefused("migration_successor_advanced", "successor_release_id")
        if tx.get("release_queue", successor["id"]) is not None:
            raise DeliveryRefused("migration_successor_queued", "successor_release_id")
        original = {name: intent.get(name) for name in ("stage", "previous_stage", "reason_code", "outcome",
                                                        "attempts", "error_type", "updated_at")}
        tx.put(BUCKET_INTENTS, key, {
            **intent, "stage": WITHDRAWN, "previous_stage": intent["stage"], "outcome": WITHDRAWN,
            "reason_code": "release_rejected_superseded", "error_type": None, "stage_deadline": None,
            "main_effect": "merged",
            "supersession": {"migration_id": request["migration_id"], "successor_release_id": successor["id"],
                             "original_halt": original},
            "updated_at": now})
        record = {"id": key, "migration_id": request["migration_id"], "kind": kind, "request": request,
                  "request_sha256": sha, "state": MIGRATION_STAGED, "successor_release_id": successor["id"],
                  "source_release_id": request["source_release_id"], "target_id": plan["target_id"],
                  "plan_id": None, "plan_sha256": None, "ack": None, "at": now}
        tx.put(BUCKET_MIGRATIONS, key, record)
        return record

    def register_migration_plan(self, document, pin, migration_id: str) -> dict:
        """Step 2: register ONLY this migration's exact successor plan, HELD at `verifying`.

        The plan must name the staged successor release, the source's target and candidate
        revision, and a predecessor the target still holds. It is registered through the same
        `_register_in` as every plan; its intent keeps the source's observed merge (`verifying` then
        `merged`, never a second publication) and stays `held` until `finalize_migration`. Nothing
        is enqueued. The identical plan and pin replay `cached`; any other plan is a conflict.
        """
        plan, pin = validate_plan(document), validate_pin(pin)
        sha, now = plan_digest(plan), self.clock()
        with self.store.transaction() as tx:
            record = self._migration_in(tx, migration_id)
            if record["state"] != MIGRATION_STAGED:
                registered = tx.get(BUCKET_PLANS, plan["plan_id"]) or {}
                if (record["plan_id"], record["plan_sha256"], registered.get("pin")) == (plan["plan_id"], sha, pin):
                    return self._migration_view(record, cached=True)
                raise DeliveryRefused("migration_conflict", "plan_id")
            request = record["request"]
            if (plan["release_id"], plan["target_id"], plan["revision"]) != (
                    record["successor_release_id"], record["target_id"], request["candidate_revision"]):
                raise DeliveryRefused("migration_plan_mismatch", "plan_id")
            old = tx.get(BUCKET_INTENTS, record["id"]) or {}
            if old.get("stage") != WITHDRAWN or (old.get("supersession") or {}).get("migration_id") != migration_id:
                raise DeliveryRefused("migration_predecessor_changed", "old_plan_id")
            if tx.get(BUCKET_PLANS, plan["plan_id"]) is not None or tx.get(BUCKET_INTENTS, plan["plan_id"]):
                raise DeliveryRefused("migration_plan_exists", "plan_id")
            release = tx.get("releases", plan["release_id"])
            if release_gate(release, plan, self._parent(release))["state"] != "approved":
                raise DeliveryRefused("migration_release_not_approved", "release_id")
            if tx.get("release_queue", plan["release_id"]) is not None:
                raise DeliveryRefused("migration_successor_queued", "release_id")
            predecessor = self._predecessor_in(tx, plan)
            if predecessor != "held":
                raise DeliveryRefused("migration_predecessor_" + predecessor, "target_id")
            self._register_in(tx, plan, pin, sha, now, migration=record)
            tx.put(BUCKET_INTENTS, plan["plan_id"], {
                **new_intent(plan, sha, now), "stage": VERIFYING, "previous_stage": REGISTERED,
                "outcome": OUTCOME_PROGRESSED, "after_verification": MERGED,
                **{name: old.get(name) for name in ("merged_revision", "head", "pr_number", "pr_url",
                                                    "last_check_state")},
                "migration": {"migration_id": migration_id, "predecessor_plan_id": record["id"],
                              "source_release_id": record["source_release_id"]},
                "held": MIGRATION_HELD})
            record = {**record, "state": MIGRATION_REGISTERED, "plan_id": plan["plan_id"], "plan_sha256": sha}
            tx.put(BUCKET_MIGRATIONS, record["id"], record)
        return self._migration_view(record, cached=False)

    def finalize_migration(self, migration_id: str, ack: dict) -> dict:
        """Step 3: the explicit durable control acknowledgement releases the held successor.

        The acknowledgement must name exactly the registered plan id and digest and the staged
        request digest. In ONE transaction the hold is cleared, the ack recorded, the record made
        `active` and the successor release queued; only then may an ordinary tick claim and verify
        it. The identical ack replays `cached`; another ack for an active migration conflicts.
        """
        ack = validate_migration_ack(ack)
        with self.store.transaction() as tx:
            record = self._migration_in(tx, migration_id)
            if record["state"] == MIGRATION_ACTIVE:
                if record["ack"] == ack:
                    return self._migration_view(record, cached=True)
                raise DeliveryRefused("migration_conflict", "ack")
            if record["state"] != MIGRATION_REGISTERED:
                raise DeliveryRefused("migration_not_registered", "migration_id")
            if (ack["plan_id"], ack["plan_sha256"], ack["request_sha256"]) != (
                    record["plan_id"], record["plan_sha256"], record["request_sha256"]):
                raise DeliveryRefused("migration_ack_mismatch", "ack")
            if ack["lineage_sha256"] != migration_lineage_digest(
                    record["source_release_id"], record["successor_release_id"], record["id"],
                    record["plan_id"], record["migration_id"]):
                raise DeliveryRefused("migration_ack_mismatch", "lineage_sha256")
            intent = tx.get(BUCKET_INTENTS, record["plan_id"]) or {}
            if (intent.get("held") != MIGRATION_HELD or intent.get("stage") != VERIFYING
                    or (intent.get("migration") or {}).get("migration_id") != migration_id
                    or (tx.get(BUCKET_PLANS, record["plan_id"]) or {}).get("plan_sha256") != record["plan_sha256"]):
                raise DeliveryRefused("migration_intent_changed", "plan_id")
            try:
                queued = self.queue.enqueue(record["successor_release_id"],
                                            "host delivery migration " + record["plan_id"], transaction=tx)
            except ContractError as exc:
                raise DeliveryRefused("migration_queue_refused", "release_id") from exc
            if queued.get("status") != "queued" or queued.get("attempt"):
                # A row someone else created while held is never adopted as this successor's start.
                raise DeliveryRefused("migration_queue_refused", "release_id")
            tx.put(BUCKET_INTENTS, record["plan_id"], {**intent, "held": None, "updated_at": self.clock()})
            record = {**record, "state": MIGRATION_ACTIVE, "ack": ack}
            tx.put(BUCKET_MIGRATIONS, record["id"], record)
        return self._migration_view(record, cached=False)

    @staticmethod
    def _migration_in(tx, migration_id) -> dict:
        for record in tx.scan(BUCKET_MIGRATIONS):
            if type(migration_id) is str and record.get("migration_id") == migration_id:
                return record
        raise DeliveryRefused("migration_unknown", "migration_id")

    def _migration_replay(self, record: dict, sha: str) -> dict:
        if record.get("request_sha256") != sha:
            raise DeliveryRefused("migration_conflict", "request")
        return self._migration_view(record, cached=True)

    @staticmethod
    def _migration_view(record: dict, *, cached: bool) -> dict:
        return {"migration": True, "cached": cached, "kind": record.get("kind", "evaluator_migration"),
                **{name: record.get(name) for name in ("migration_id", "state", "request_sha256",
                                                       "source_release_id", "successor_release_id", "target_id",
                                                       "plan_id", "plan_sha256")},
                "old_plan_id": record.get("id"), "acknowledged": record.get("ack") is not None,
                "authority": AUTHORITY}

    def _predecessor(self, plan: dict) -> str:
        """The target as a NEW merge of this plan would find it: `in_flight` while another delivery of
        the target has merged and not settled the host - including a `blocked`/`failed` one that bound
        a descriptor without a verified rollback, which is never safe-to-switch evidence - else
        `moved` when the current descriptor is not the plan's expected predecessor, else `held`.
        One store read under the controller's serialization; the switch keeps its own CAS."""
        with self.store.transaction() as tx:
            return self._predecessor_in(tx, plan)

    @staticmethod
    def _predecessor_in(tx, plan: dict) -> str:
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
            reserved = {record["target_id"]: record for record in tx.scan(BUCKET_MIGRATIONS)
                        if record.get("state") in MIGRATION_RESERVING}
            blocked, chosen, chosen_intent, waiting = {}, None, None, None
            for index, row in enumerate(sorted(rows, key=lambda r: r["plan_id"])):
                intent = intents.get(row["plan_id"])
                stage = (intent or {}).get("stage") or REGISTERED
                if index >= MAX_SCAN:
                    blocked[row["plan_id"]] = "scan_bounded"
                    continue
                if (intent or {}).get("held"):
                    # INV-HOST-DELIVERY-MIGRATION-001: a held migration successor is never claimed,
                    # evaluated or even projected as the waiting selection until its durable
                    # control acknowledgement (`finalize_migration`) clears the hold.
                    blocked[row["plan_id"]] = str(intent["held"])
                    continue
                if stage == ACTIVE or stage in STOPPED_STAGES:
                    blocked[row["plan_id"]] = stage
                    continue
                migration = reserved.get(row["target_id"])
                if migration is not None and migration.get("plan_id") != row["plan_id"]:
                    blocked[row["plan_id"]] = "target_reserved_by_migration"
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
            # An already verified (or active) release keeps today's path; a reviewed one is verified
            # by the incumbent evaluator BEFORE anything is published (INV-HOST-DELIVERY-VERIFY-001).
            gate = self._gate(plan)
            return self._enter(plan, intent, PUBLISHING if gate["status"] in {"verified", "active"}
                               else VERIFYING, claim)
        if stage == VERIFYING:
            return self._verify(plan, intent, claim)
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

    # ----- verification before publication (INV-HOST-DELIVERY-VERIFY-001) ---------------------
    def _verify(self, plan: dict, intent: dict, claim) -> dict:
        """Drive the existing incumbent evaluator for a reviewed release, under this fence.

        In this order, and each step before any later one:
        0. every unresolved attempt on this host is reconciled exactly (never by prefix or age); an
           owner still alive or any resource not proven gone is a named wait - no evaluation, no
           attempt spent and NO transition, including the already-verified shortcut of step 1;
        1. a release already verified leaves for `after_verification` (or `publishing`); a refused
           one halts with the gate's own code;
        2. a hook candidate halts before any attempt exists;
        3. the attempt is durable in this store, then on disk, and only then evaluated;
        4. the verdict, the image and this intent are one owned transaction (`_verdict`).
        Nothing here publishes, merges or touches the host. After the attempt is recorded every
        write carries it, so no later halt or outage report can drop the attempt history.
        """
        port = self.verifier
        if port is None or not port.available():
            # No owned cancellation boundary here (no port, off the main thread, no /proc): a wait.
            return self._unavailable(plan, intent, "verifier_unavailable",
                                     DeliveryRefused("verifier_unavailable"), claim=claim)
        current = intent
        try:
            reconciled = port.reconcile(self._open_attempts())
            current = self._attach_cleanups(plan, current, claim, reconciled.get("resolved") or {})
            if reconciled["state"] != "clear":
                return self._pending(plan, current, claim, reconciled["reason_code"])
            if unresolved_attempts(current):
                return self._pending(plan, current, claim, "verification_cleanup_unconfirmed")
            gate = self._gate(plan)
            if gate["state"] == OUTCOME_REFUSED:
                return self._halt(plan, current, BLOCKED, OUTCOME_REFUSED, gate["reason_code"], claim=claim)
            if gate["status"] in {"verified", "active"}:
                return self._enter(plan, current, current.get("after_verification") or PUBLISHING, claim)
            if self._candidate(plan).get("hook_id"):
                # The legacy evaluator records hook canaries itself; this driver never does.
                return self._halt(plan, current, BLOCKED, OUTCOME_BLOCKED, "release_hook_unsupported",
                                  claim=claim)
            attempt = port.new_attempt(plan_id=plan["plan_id"], release_id=plan["release_id"],
                                       generation=claim["generation"])
            current = self._commit_verification(current, claim, lambda _tx, base: {
                **base, "verification": {"attempts": [*attempts_of(base), {
                    **attempt, "state": "prepared", "cleanup": None, "outcome": None}]},
                "updated_at": self.clock()})
            try:
                port.prepare(attempt)
            except Exception as exc:
                # The DB attempt without its disk record stays unresolved until reconcile proves
                # that nothing it could have named exists (`never_started`).
                return self._unavailable(plan, current, "verification_record_unavailable", exc, claim=claim)
            fence = _FenceObservations(lambda: self.queue.heartbeat(claim, now=self._now()))
            try:
                outcome = port.evaluate(plan["release_id"], attempt, fence=fence)
            except Exception as exc:
                if fence.close():
                    return self._unobserved(plan, current, exc)
                raise
            return self._verdict(plan, current, claim, attempt, outcome, unobserved=fence.close())
        except AmbiguousEffect:
            raise
        except ContractError as refusal:
            failure = refusal
            return self._halt(plan, current, BLOCKED, OUTCOME_REFUSED,
                              getattr(failure, "reason_code", None) or "verification_refused",
                              claim=claim, error_type=type(failure).__name__)
        except Exception as outage:
            return self._unavailable(plan, current, "verification_unavailable", outage, claim=claim)

    def _open_attempts(self) -> list:
        """Every attempt any delivery of this store recorded without a resolving cleanup."""
        with self.store.transaction() as tx:
            intents = tx.scan(BUCKET_INTENTS)
        return [{"plan_id": row.get("plan_id"), **{key: attempt.get(key) for key in
                                                   ("attempt_id", "generation", "owner", "started_at")}}
                for row in intents for attempt in unresolved_attempts(row)]

    def _attach_cleanups(self, plan: dict, intent: dict, claim, resolved: dict) -> dict:
        """Record reconciled cleanups on the attempts they close, in the owned transaction. An
        attempt already closed is never rewritten; this plan's intent is returned as stored."""
        if not resolved:
            return intent
        with self.store.transaction() as tx:
            self.queue.owned(tx, claim, self._now())
            for row in tx.scan(BUCKET_INTENTS):
                attempts = attempts_of(row)
                changed = [{**attempt, "state": "resolved", "cleanup": resolved[attempt["attempt_id"]]}
                           if attempt.get("attempt_id") in resolved and attempt in unresolved_attempts(row)
                           else attempt for attempt in attempts]
                if changed != attempts:
                    tx.put(BUCKET_INTENTS, row["id"], {**row, "verification": {
                        **(row.get("verification") or {}), "attempts": changed}})
            return tx.get(BUCKET_INTENTS, plan["plan_id"])

    def _commit_verification(self, intent: dict, claim, build) -> dict:
        """One transaction: this claim's fence, this intent unchanged (CAS), then `build`'s writes.

        A lost fence or a changed intent after an evaluation is an ambiguity about an external
        effect, never a refusal of it, so nothing is written; a refusal raised by `build` itself
        (the `Releases` verdict owner) rolls everything back and propagates as that refusal.
        """
        with self.store.transaction() as tx:
            try:
                self.queue.owned(tx, claim, self._now())
                if tx.get(BUCKET_INTENTS, intent["id"]) != intent:
                    raise DeliveryRefused("verification_intent_changed", "plan_id")
            except ContractError as exc:
                raise AmbiguousEffect("verification", exc) from exc
            settled = build(tx, intent)
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

    @staticmethod
    def _closed(intent: dict, attempt: dict, outcome: dict) -> dict:
        """This intent with its attempt closed by what the evaluation and its own cleanup observed."""
        cleanup = outcome.get("cleanup") if isinstance(outcome.get("cleanup"), dict) else None
        result = {"verdict": outcome.get("verdict"), "reason_code": outcome.get("reason_code"),
                  "evaluation": outcome.get("evaluation"), "error_type": outcome.get("error_type")}
        attempts = [{**row, "state": outcome.get("state") or row.get("state"), "cleanup": cleanup,
                     "outcome": result} if row.get("attempt_id") == attempt["attempt_id"] else row
                    for row in attempts_of(intent)]
        return {**intent, "verification": {**(intent.get("verification") or {}), "attempts": attempts}}

    def _verdict(self, plan: dict, intent: dict, claim, attempt: dict, outcome: dict, *,
                 unobserved: bool = False) -> dict:
        """What one owned evaluation ends in. Only `checked` and `superseded` write a verdict.

        `unobserved` is the fence's own answer (`_FenceObservations.close`): a heartbeat still in
        flight, or one that ended in an error, when the evaluation returned. A stop can end the
        evaluation while its heartbeat is blocked, and that heartbeat may fail only during the
        cancelled attempt's cleanup. Like `fence_unobservable`, the store's completion is
        unobserved, so whatever the verdict nothing is recorded or settled (L-3).
        """
        verdict = outcome.get("verdict")
        if unobserved or verdict == "fence_unobservable":
            return self._unobserved(plan, intent)
        if verdict == "fence_lost":
            # This controller no longer owns the release: it records nothing. Its disk record says
            # what its own cleanup proved, and the next reconcile attaches it (L-2).
            return {**self._result(plan, intent, OUTCOME_CONFLICT, reason_code="verification_fence_lost"),
                    "controller": "stale"}
        closed = self._closed(intent, attempt, outcome)
        if verdict == "interrupted":
            settled = self._commit_verification(intent, claim, lambda _tx, _base: self._pended(
                closed, "verification_interrupted"))
            return self._result(plan, settled, OUTCOME_PENDING, reason_code="verification_interrupted")
        if verdict == "retry":
            reason = outcome.get("reason_code") or "verification_observation_unavailable"
            settled = self._commit_verification(intent, claim, lambda _tx, _base: {
                **closed, "outcome": OUTCOME_UNAVAILABLE, "reason_code": reason,
                "error_type": safe_error_type(outcome.get("error_type")), "updated_at": self.clock()})
            return self._result(plan, settled, OUTCOME_UNAVAILABLE, reason_code=reason)
        if verdict == "refused":
            settled = self._commit_verification(intent, claim, lambda _tx, _base: self._halted(
                closed, BLOCKED, OUTCOME_REFUSED, "verification_refused",
                error_type=outcome.get("error_type")))
            return self._report_halted(plan, intent, settled)
        if verdict not in {"checked", "superseded"}:
            raise DeliveryRefused("verification_outcome_unknown", "verdict")
        confirmed = (outcome.get("cleanup") or {}).get("state") == "confirmed"

        def record(tx, _base):
            status = self._record_release(tx, plan, outcome)
            if not confirmed:
                # The verdict is real executed evidence and stays; leaving this stage waits for
                # the attempt's own cleanup to be proven (final review C1).
                return self._pended(closed, "verification_cleanup_unconfirmed")
            if status == "verified":
                return self._entered(closed, closed.get("after_verification") or PUBLISHING)
            return self._halted(closed, BLOCKED, OUTCOME_BLOCKED, "release_" + str(status))

        try:
            settled = self._commit_verification(intent, claim, record)
        except AmbiguousEffect:
            raise
        except ContractError as refusal:
            # `Releases` refused the verdict itself (a stale evaluator hash, a changed check set):
            # a definite stop, recorded WITH the closed attempt, never retried into a new evaluation.
            failure = refusal
            return self._halt(plan, closed, BLOCKED, OUTCOME_REFUSED,
                              getattr(failure, "reason_code", None) or "release_verdict_refused",
                              claim=claim, error_type=type(failure).__name__)
        if settled["stage"] == BLOCKED or settled["stage"] == FAILED:
            return self._report_halted(plan, intent, settled)
        if settled["outcome"] == OUTCOME_PENDING:
            return self._result(plan, settled, OUTCOME_PENDING, reason_code=settled["reason_code"])
        return self._report_entered(plan, intent, settled)

    def _record_release(self, tx, plan: dict, outcome: dict) -> str:
        """The release side of a verdict, through its owner and inside the caller's transaction."""
        if outcome["verdict"] == "superseded":
            record = tx.get("releases", plan["release_id"])
            if record is None or record.get("status") != "reviewed":
                raise DeliveryRefused("release_not_reviewed", "release_id")
            # The legacy runner's own record of a superseded ticket, written the same way.
            record.update(status="superseded_by_ticket_revision",
                          reason=str(outcome.get("reason") or "ticket superseded")[:500])
            tx.put("releases", plan["release_id"], record)
            return record["status"]
        if outcome.get("passed") and outcome.get("image"):
            tx.put("images", plan["release_id"], {"id": plan["release_id"], "image": outcome["image"],
                                                  "revision": plan["revision"]})
        # The plan's exact revision and evaluator hash: `Releases` refuses any other.
        record = self.releases.verify(plan["release_id"], plan["revision"], plan["policy_hash"],
                                      outcome["checks"], transaction=tx)
        return record["status"]

    def _publish(self, plan: dict, intent: dict, claim) -> dict:
        """Publish the reviewed candidate, or ADOPT the publication a lost response already made.

        A candidate whose reviewed base is no longer the remote main is refused here, before any PR
        or CI is spent on it: it can never be fast-forwarded (INV-HOST-DELIVERY-001)."""
        port = self._require_port(self.github, "github_port_unavailable")
        candidate = self._candidate(plan)
        observed = port.observe(candidate)
        if port.merge_state(candidate, observed)["state"] == "base_moved":
            return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "reviewed_base_moved", claim=claim)
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
        """Fast-forward main to the exact reviewed head, or RECOGNIZE the merge already made.

        Before a NEW effect the target must still hold the plan's expected predecessor with no other
        delivery unsettled on it, and the remote main must still be the reviewed base; the merge
        itself is the server-side compare-and-swap of exactly that (INV-HOST-DELIVERY-001).

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
        # An effect that already happened (our fast-forward whose response was lost, or anyone's
        # merge of this exact head) is reconciled FIRST, before any refusal or new effect.
        state = port.merge_state(candidate, observed)
        if state["state"] == "merged":
            merged = {"merged": True, "merged_revision": state["merged_revision"], "recovered": True}
        else:
            predecessor = self._predecessor(plan)
            if predecessor == "in_flight":
                # Another delivery of this target has merged and not settled the host: no effect, no
                # attempt spent, the stage stays; it is decided once that delivery is terminal.
                return self._pending(plan, intent, claim, "predecessor_in_flight")
            if predecessor == "moved":
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "descriptor_predecessor_moved",
                                  claim=claim)
            if state["state"] != "unmerged":
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "reviewed_base_moved", claim=claim)
            # A NEW mainline effect keeps the existing gates of that effect: the exact open PR of the
            # reviewed head and the plan's required checks passing on it right now. Recognizing an
            # effect above is recovery; it never stands in for this.
            if observed.get("state") != "OPEN":
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, "publication_not_open", claim=claim)
            verdict = ci_verdict(plan["required_checks"], observed.get("checks"), intent["head"],
                                 observed_head=observed.get("head"))
            if verdict["state"] != CI_PASSED:
                return self._halt(plan, intent, BLOCKED, OUTCOME_BLOCKED, verdict["reason_code"], claim=claim,
                                  last_check_state=verdict["state"])
            self._owned_now(claim)
            merged = port.merge(candidate, observed)
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
        if canary.get("pending") and not self._expired(intent):
            # The owner's requested actual canary has not answered yet: an external wait under the
            # stage's own deadline, never a pass. Expired, it is the failure below and rolls back.
            return self._pending(plan, intent, claim, canary.get("reason_code") or "canary_pending")
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
            except DeliveryRefused as exc:
                if exc.reason_code not in ACTIVATION_GATE_CODES:
                    record.update(started=False, verified=False,
                                  error_type=safe_error_type(type(exc).__name__), at=self.clock())
                    return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
                # The target's Fleet debt or pause is held or unknown: the predecessor is NOT started,
                # any committed admission pause stays, and the restoration waits for settlement - then
                # blocks for its recovery owner under that same code, never started past the debt.
                record.update(started=False, verified=False, error_type=None, gate=exc.reason_code,
                              at=self.clock())
                if not self._expired(intent):
                    return self._pending(plan, intent, claim, exc.reason_code, rollback=record)
                return self._blocked_rollback(plan, intent, claim, record, exc.reason_code)
            except Exception as exc:
                record.update(started=False, verified=False,
                              error_type=safe_error_type(type(exc).__name__), at=self.clock())
                return self._blocked_rollback(plan, intent, claim, record, "rollback_failed")
            record.pop("gate", None)
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

    # ----- durable bookkeeping ----------------------------------------------------------------
    def _enter(self, plan: dict, intent: dict, stage: str, claim, *, outcome=None, reason_code=None,
               error_type=None, active_pointer=None, **fields) -> dict:
        """Write the durable intent for the stage that is now owed, and report this tick."""
        settled = self._entered(intent, stage, outcome=outcome, reason_code=reason_code,
                                error_type=error_type, **fields)
        self._write(settled, claim)
        return self._report_entered(plan, intent, settled, active_pointer=active_pointer)

    def _entered(self, intent: dict, stage: str, *, outcome=None, reason_code=None, error_type=None,
                 **fields) -> dict:
        now = self.clock()
        return {**intent, **fields, "stage": stage, "previous_stage": intent["stage"],
                "outcome": outcome or (OUTCOME_ACTIVE if stage == ACTIVE else OUTCOME_PROGRESSED),
                "reason_code": reason_code, "error_type": error_type, "attempts": 0,
                "stage_entered_at": now if stage != intent["stage"] else intent["stage_entered_at"],
                "updated_at": now}

    def _report_entered(self, plan: dict, intent: dict, settled: dict, *, active_pointer=None) -> dict:
        if settled["stage"] != intent["stage"]:
            self._emit(EVENT_STAGE, "observed", plan, attributes={
                "plan_id": plan["plan_id"], "release_id": plan["release_id"],
                "target_id": plan["target_id"], "stage": settled["stage"], "previous_stage": intent["stage"]})
        return self._result(plan, settled, settled["outcome"], reason_code=settled["reason_code"],
                            active=active_pointer)

    def _pending(self, plan: dict, intent: dict, claim, reason_code: str, **fields) -> dict:
        """A bounded external wait: the lease goes back, the stage and its deadline do not move."""
        settled = self._pended(intent, reason_code, **fields)
        self._write(settled, claim)
        return self._result(plan, settled, OUTCOME_PENDING, reason_code=reason_code)

    def _pended(self, intent: dict, reason_code: str, **fields) -> dict:
        return {**intent, **fields, "outcome": OUTCOME_PENDING, "reason_code": reason_code,
                "error_type": None, "updated_at": self.clock()}

    def _halt(self, plan: dict, intent: dict, stage: str, outcome: str, reason_code: str, *,
              claim=None, error_type=None, **fields) -> dict:
        """A definite stop that PRESERVES the stage it happened at, its evidence and its reason."""
        settled = self._halted(intent, stage, outcome, reason_code, error_type=error_type, **fields)
        self._write(settled, claim)
        return self._report_halted(plan, intent, settled)

    def _halted(self, intent: dict, stage: str, outcome: str, reason_code: str, *, error_type=None,
                **fields) -> dict:
        attempts = int(intent.get("attempts") or 0) + 1
        final = FAILED if attempts >= MAX_STAGE_ATTEMPTS and stage == BLOCKED else stage
        return {**intent, **fields, "stage": final, "previous_stage": intent["stage"],
                "outcome": outcome, "reason_code": reason_code,
                "error_type": safe_error_type(error_type), "attempts": attempts,
                "updated_at": self.clock()}

    def _report_halted(self, plan: dict, intent: dict, settled: dict) -> dict:
        reason_code, attempts = settled["reason_code"], settled["attempts"]
        self._emit(EVENT_BLOCKED, "blocked", plan, severity="error", reason_code=reason_code,
                   attributes={"plan_id": plan["plan_id"], "target_id": plan["target_id"],
                               "stage": intent["stage"], "outcome": settled["outcome"],
                               "error_type": settled["error_type"], "attempts": attempts})
        LOGGER.warning("host delivery halted plan=%s stage=%s reason=%s attempts=%d",
                       plan["plan_id"], intent["stage"], reason_code, attempts)
        return self._result(plan, settled, settled["outcome"], reason_code=reason_code)

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

    def _unobserved(self, plan: dict, intent: dict, exc=None) -> dict:
        """The verification fence's completion was not observed (INV-HOST-DELIVERY-VERIFY-001, L-3).

        The store that did not answer the heartbeat is the one every write and settlement would go
        through, and a blocked call there does not end by itself: nothing is committed, and the
        claim is NOT settled - no `finish`, no `defer`, no release. The receipt says so
        (`"claim": "unsettled"`). The row stays `running` with this generation and the attempt
        stays unresolved in the intent; nothing else acts until the lease expires, and the next
        owner reconciles the attempt from its disk record before any new evaluation. The abandoned
        heartbeat is not claimed to be cancelled: it may still complete and renew this lease once.
        """
        result = self._unavailable(plan, intent, "verification_fence_unobservable",
                                   exc or DeliveryRefused("verification_fence_unobservable"), commit=False)
        return {**result, "claim": "unsettled"}

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


__all__ = ["BUCKET_DESCRIPTORS", "BUCKET_INTENTS", "BUCKET_MIGRATIONS", "BUCKET_PLANS", "BUCKET_TARGETS", "LOGGER",
           "MAX_SCAN", "RESUME_SECONDS", "TARGET_BUSY_STAGES", "AmbiguousEffect", "HostDelivery"]
