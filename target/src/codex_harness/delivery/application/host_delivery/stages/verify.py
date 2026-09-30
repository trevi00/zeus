"""The verification stage.

Layer: application
Context: delivery
Owns: bucket images (the verified image of a release)
Does not own: the release verdict (review's Releases.verify/record_superseded), the evaluator (its port)
Entry points: Verification
Contracts: INV-HOST-DELIVERY-VERIFY-001

Split from M7 `application/host_delivery.py` (SOURCE e38aa722) by the named S7 split (DESIGN-s7 V8,
A/evidence/rebuild/s7/host-delivery-split/split_host_delivery.py); the bodies are M7's.
"""

from __future__ import annotations

import threading

from codex_harness.delivery.application.host_delivery.state import BUCKET_INTENTS, AmbiguousEffect
from codex_harness.delivery.domain.host_delivery import (
    BLOCKED,
    FAILED,
    OUTCOME_BLOCKED,
    OUTCOME_CONFLICT,
    OUTCOME_PENDING,
    OUTCOME_REFUSED,
    OUTCOME_UNAVAILABLE,
    PUBLISHING,
    DeliveryRefused,
    attempts_of,
    safe_error_type,
    unresolved_attempts,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import utcnow


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


def closed_attempt(intent: dict, attempt: dict, outcome: dict) -> dict:
    """This intent with its attempt closed by what the evaluation and its own cleanup observed."""
    cleanup = outcome.get("cleanup") if isinstance(outcome.get("cleanup"), dict) else None
    result = {"verdict": outcome.get("verdict"), "reason_code": outcome.get("reason_code"),
              "evaluation": outcome.get("evaluation"), "error_type": outcome.get("error_type")}
    attempts = [{**row, "state": outcome.get("state") or row.get("state"), "cleanup": cleanup,
                 "outcome": result} if row.get("attempt_id") == attempt["attempt_id"] else row
                for row in attempts_of(intent)]
    return {**intent, "verification": {**(intent.get("verification") or {}), "attempts": attempts}}


class Verification:
    """The `verifying` stage: the incumbent evaluator's owned attempt under this claim's fence, and the
    verdict recorded through review's release owner (INV-HOST-DELIVERY-VERIFY-001)."""

    def __init__(self, store, *, clock=utcnow, releases=None, claims=None, verifier=None, state=None):
        self.store = store
        self.clock = clock
        self.releases = releases
        self.claims = claims
        self.verifier = verifier
        self.state = state

    # ----- verification before publication (INV-HOST-DELIVERY-VERIFY-001) ---------------------
    def verify(self, plan: dict, intent: dict, claim) -> dict:
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
            return self.state.unavailable(plan, intent, "verifier_unavailable",
                                     DeliveryRefused("verifier_unavailable"), claim=claim)
        current = intent
        try:
            reconciled = port.reconcile(self._open_attempts())
            current = self._attach_cleanups(plan, current, claim, reconciled.get("resolved") or {})
            if reconciled["state"] != "clear":
                return self.state.pending(plan, current, claim, reconciled["reason_code"])
            if unresolved_attempts(current):
                return self.state.pending(plan, current, claim, "verification_cleanup_unconfirmed")
            gate = self.state.gate(plan)
            if gate["state"] == OUTCOME_REFUSED:
                return self.state.halt(plan, current, BLOCKED, OUTCOME_REFUSED, gate["reason_code"], claim=claim)
            if gate["status"] in {"verified", "active"}:
                return self.state.enter(plan, current, current.get("after_verification") or PUBLISHING, claim)
            if self.state.candidate(plan).get("hook_id"):
                # The legacy evaluator records hook canaries itself; this driver never does.
                return self.state.halt(plan, current, BLOCKED, OUTCOME_BLOCKED, "release_hook_unsupported",
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
                return self.state.unavailable(plan, current, "verification_record_unavailable", exc, claim=claim)
            fence = _FenceObservations(lambda: self.claims.heartbeat(claim, now=self.state.now()))
            try:
                outcome = port.evaluate(plan["release_id"], attempt, fence=fence)
            except Exception as exc:
                if fence.close():
                    return self.state.unobserved(plan, current, exc)
                raise
            return self._verdict(plan, current, claim, attempt, outcome, unobserved=fence.close())
        except AmbiguousEffect:
            raise
        except ContractError as refusal:
            failure = refusal
            return self.state.halt(plan, current, BLOCKED, OUTCOME_REFUSED,
                              getattr(failure, "reason_code", None) or "verification_refused",
                              claim=claim, error_type=type(failure).__name__)
        except Exception as outage:
            return self.state.unavailable(plan, current, "verification_unavailable", outage, claim=claim)

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
            self.claims.owned(tx, claim, self.state.now())
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
                self.claims.owned(tx, claim, self.state.now())
                if tx.get(BUCKET_INTENTS, intent["id"]) != intent:
                    raise DeliveryRefused("verification_intent_changed", "plan_id")
            except ContractError as exc:
                raise AmbiguousEffect("verification", exc) from exc
            settled = build(tx, intent)
            tx.put(BUCKET_INTENTS, settled["id"], settled)
        return settled

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
            return self.state.unobserved(plan, intent)
        if verdict == "fence_lost":
            # This controller no longer owns the release: it records nothing. Its disk record says
            # what its own cleanup proved, and the next reconcile attaches it (L-2).
            return {**self.state.result(plan, intent, OUTCOME_CONFLICT, reason_code="verification_fence_lost"),
                    "controller": "stale"}
        closed = closed_attempt(intent, attempt, outcome)
        if verdict == "interrupted":
            settled = self._commit_verification(intent, claim, lambda _tx, _base: self.state.pended(
                closed, "verification_interrupted"))
            return self.state.result(plan, settled, OUTCOME_PENDING, reason_code="verification_interrupted")
        if verdict == "retry":
            reason = outcome.get("reason_code") or "verification_observation_unavailable"
            settled = self._commit_verification(intent, claim, lambda _tx, _base: {
                **closed, "outcome": OUTCOME_UNAVAILABLE, "reason_code": reason,
                "error_type": safe_error_type(outcome.get("error_type")), "updated_at": self.clock()})
            return self.state.result(plan, settled, OUTCOME_UNAVAILABLE, reason_code=reason)
        if verdict == "refused":
            settled = self._commit_verification(intent, claim, lambda _tx, _base: self.state.halted(
                closed, BLOCKED, OUTCOME_REFUSED, "verification_refused",
                error_type=outcome.get("error_type")))
            return self.state.report_halted(plan, intent, settled)
        if verdict not in {"checked", "superseded"}:
            raise DeliveryRefused("verification_outcome_unknown", "verdict")
        confirmed = (outcome.get("cleanup") or {}).get("state") == "confirmed"

        def record(tx, _base):
            status = self._record_release(tx, plan, outcome)
            if not confirmed:
                # The verdict is real executed evidence and stays; leaving this stage waits for
                # the attempt's own cleanup to be proven (final review C1).
                return self.state.pended(closed, "verification_cleanup_unconfirmed")
            if status == "verified":
                return self.state.entered(closed, closed.get("after_verification") or PUBLISHING)
            return self.state.halted(closed, BLOCKED, OUTCOME_BLOCKED, "release_" + str(status))

        try:
            settled = self._commit_verification(intent, claim, record)
        except AmbiguousEffect:
            raise
        except ContractError as refusal:
            # `Releases` refused the verdict itself (a stale evaluator hash, a changed check set):
            # a definite stop, recorded WITH the closed attempt, never retried into a new evaluation.
            failure = refusal
            return self.state.halt(plan, closed, BLOCKED, OUTCOME_REFUSED,
                              getattr(failure, "reason_code", None) or "release_verdict_refused",
                              claim=claim, error_type=type(failure).__name__)
        if settled["stage"] == BLOCKED or settled["stage"] == FAILED:
            return self.state.report_halted(plan, intent, settled)
        if settled["outcome"] == OUTCOME_PENDING:
            return self.state.result(plan, settled, OUTCOME_PENDING, reason_code=settled["reason_code"])
        return self.state.report_entered(plan, intent, settled)

    def _record_release(self, tx, plan: dict, outcome: dict) -> str:
        """The release side of a verdict, through its owner and inside the caller's transaction."""
        if outcome["verdict"] == "superseded":
            record = tx.get("releases", plan["release_id"])
            if record is None or record.get("status") != "reviewed":
                raise DeliveryRefused("release_not_reviewed", "release_id")
            # R7 (DESIGN-s7 V5): the legacy runner's own record of a superseded ticket, written by review's owner
            # operation inside this unit.
            record = self.releases.record_superseded(
                plan["release_id"], str(outcome.get("reason") or "ticket superseded")[:500], transaction=tx)
            return record["status"]
        if outcome.get("passed") and outcome.get("image"):
            tx.put("images", plan["release_id"], {"id": plan["release_id"], "image": outcome["image"],
                                                  "revision": plan["revision"]})
        # The plan's exact revision and evaluator hash: `Releases` refuses any other.
        record = self.releases.verify(plan["release_id"], plan["revision"], plan["policy_hash"],
                                      outcome["checks"], transaction=tx)
        return record["status"]
