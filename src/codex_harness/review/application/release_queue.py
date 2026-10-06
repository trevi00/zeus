"""Fenced single-controller release dispatch with bounded durable retries (M7 `application/release_queue.py`).

Layer: application
Context: review
Owns: the `release_queue` rows and review's `deployment_locks:controller` lease
Does not own: the execution fence rows (coordination's `execution_fences`, through the injected ExecutionFences
    port), ticket binding (intake, injected), what a claimant does with its claim (delivery)
Entry points: ReleaseQueue.retry, .enqueue, .claim, .owned, .heartbeat, .defer, .finish, .cancel, .hold_maintenance, .owned_maintenance, .heartbeat_maintenance, .release_maintenance, MAINTENANCE_SCOPE
Contracts: INV-RELEASE-001, INV-HOST-DELIVERY-VERIFY-001, INV-HOST-DELIVERY-MIGRATION-001, INV-HOST-DELIVERY-MAINTENANCE-001

S7 named transcription (DESIGN-s7 V3/V5, A/evidence/rebuild/s7/review-move/transcribe.py): M7's bodies with the
R1/R3/R4/R7 seams; `cancel` is the V5 owner operation of M7 ReleaseRunner.abandon's queue write.
The four `*_maintenance` methods are ported from main b9d8f15 (S2R): its fence calls go through the injected `fences`
(`current`, `advance`, `require_current`), its clock and owner token through `clock` and `ids`.

M7 docstring follows.

Fenced single-controller release dispatch with bounded durable retries."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.kernel.policy import POLICY

# INV-HOST-DELIVERY-MAINTENANCE-001: the execution-fence scope of an active-generation maintenance hold.
# The hold takes the SAME `deployment_locks:controller` exclusion every controller on this host takes; only
# its fence row (scope, maintenance id) is its own, so no release row, attempt or generation is borrowed.
MAINTENANCE_SCOPE = "host_delivery_maintenance"


class ReleaseQueue:
    def __init__(self, store, *, ticket_binding=None, fences=None, clock=None, ids=None):
        # S7 (DESIGN-s7 V3): intake's ticket_binding and coordination's execution fences are injected;
        # the lease/retry times take an injected clock and the controller owner token an id source.
        self.store = store
        self.ticket_binding, self.fences, self.clock, self.ids = ticket_binding, fences, clock, ids

    def retry(self, release_id, reason, *, transaction=None):
        """Re-arm a stopped row. `transaction` runs this unchanged body inside the caller's
        transaction, so a caller's own refusal rolls the re-arm back with it (INV-HOST-DELIVERY-VERIFY-001)."""
        require(isinstance(reason, str) and reason.strip(), "Retry reason required")
        now = _now(self.clock)
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            require(not lock.get("lease_until") or datetime.fromisoformat(lock["lease_until"]) <= now,
                    "Release controller still running")
            release = tx.get("releases", release_id)
            require(release and release["status"] in {"reviewed", "verified"}, "Release is not recoverable")
            self.ticket_binding(tx, release["candidate"])
            row = tx.get("release_queue", release_id) or {"id": release_id, "at": now.isoformat()}
            row.setdefault("manual_retries", []).append({"reason": reason, "at": now.isoformat(),
                                                        "previous_attempt": row.get("attempt", 0)})
            row.update(status="queued", attempt=0, retry_at=None, owner=None, lease_until=None)
            tx.put("release_queue", release_id, row)
            return row

    def enqueue(self, release_id, reason, *, transaction=None):
        """Queue an ALREADY reviewed release for the single release controller; idempotent.

        This is the same row the executor writes on conductor acceptance, created here for a
        release that was reviewed outside that path. It grants nothing: the row is refused unless
        the release record itself is `reviewed` or `verified` and its ticket binding still holds,
        an existing row of any status is returned untouched (a failed or cancelled release is never
        silently re-armed), and no lease, attempt, generation or fence is changed. `transaction`
        runs this unchanged body inside the caller's transaction (INV-HOST-DELIVERY-MIGRATION-001).
        """
        require(isinstance(reason, str) and reason.strip(), "Enqueue reason required")
        now = _now(self.clock)
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            existing = tx.get("release_queue", release_id)
            if existing:
                return existing
            release = tx.get("releases", release_id)
            require(release and release["status"] in {"reviewed", "verified"},
                    "Release is not queueable")
            self.ticket_binding(tx, release["candidate"])
            row = {"id": release_id, "status": "queued", "at": now.isoformat(), "attempt": 0,
                   "reason": reason}
            tx.put("release_queue", release_id, row)
            return row

    def claim(self, now=None, eligible=None):
        """Claim the next runnable row under the single controller lease.

        `eligible` is an optional predicate over the row: a second controller on this host (the
        host delivery controller) claims only the rows a registered plan names, so it can never
        consume another controller's row or spend its attempt budget. The lease itself is
        deliberately NOT narrowed - `deployment_locks:controller` still serializes every controller
        on this host, exactly as before.
        """
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > now:
                return None
            for row in sorted(tx.scan("release_queue"), key=lambda r: (r.get("at", ""), r["id"])):
                if row["status"] not in {"queued", "retry", "running"}:
                    continue
                if eligible is not None and not eligible(row):
                    continue
                if row.get("retry_at") and datetime.fromisoformat(row["retry_at"]) > now:
                    continue
                if row.get("attempt", 0) >= POLICY.release_max_attempts:
                    row.update(status="failed", reason="release attempt budget exhausted")
                    tx.put("release_queue", row["id"], row)
                    continue
                owner = str((self.ids or SYSTEM_IDS).uuid4())
                try:
                    self.fences.advance(tx, "release_queue", row["id"], row.get("generation", 0) + 1, owner,
                                        clock=self.clock)
                except ContractError as exc:
                    row.update(status="failed", reason=str(exc))
                    tx.put("release_queue", row["id"], row)
                    continue
                row.update(status="running", attempt=row.get("attempt", 0) + 1,
                           owner=owner, generation=row.get("generation", 0) + 1,
                           lease_until=(now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat())
                tx.put("release_queue", row["id"], row)
                tx.put("deployment_locks", "controller", {"release_id": row["id"],
                    "owner": row["owner"], "lease_until": row["lease_until"]})
                return row
        return None

    def owned(self, tx, claim, now=None):
        """Re-check this claim's ownership INSIDE a caller's transaction.

        A controller that writes its own durable observation elsewhere commits it in the same
        transaction as this check, so a stale or superseded controller cannot record what it
        observed. It is the check `heartbeat` and `finish` already make, exposed rather than
        duplicated; it changes no row and grants nothing.
        """
        return self._owned(tx, claim, now or _now(self.clock))

    def _owned(self, tx, claim, now):
        row = tx.get("release_queue", claim["id"])
        lock = tx.get("deployment_locks", "controller") or {}
        require(row and row["status"] == "running" and row.get("owner") == claim["owner"]
                and row.get("generation") == claim["generation"]
                and lock.get("owner") == claim["owner"]
                and datetime.fromisoformat(row["lease_until"]) > now,
                "Stale release controller")
        self.fences.require_current(tx, "release_queue", row["id"], row.get("generation"), row.get("owner"))
        return row

    def heartbeat(self, claim, now=None):
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            row = self._owned(tx, claim, now)
            row["lease_until"] = (now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat()
            tx.put("release_queue", row["id"], row)
            tx.put("deployment_locks", "controller", {"release_id": row["id"],
                "owner": row["owner"], "lease_until": row["lease_until"]})

    def defer(self, claim, result, *, resume_after_seconds=0, now=None):
        """Release the lease for an EXTERNAL WAIT under the same durable logical intent.

        A 20-minute CI run must not be waited out while holding the controller lease, and it is
        not a failed attempt either. `defer` therefore completes this tick, records what was
        observed in the same `attempts` history `finish` writes, returns the row to `queued` with a
        bounded resume time and clears the controller lock. The attempt counter goes back to zero
        because the wait is bounded elsewhere: the CALLER's durable intent carries the stage
        deadline that ends this wait (`ci_timeout`, `consumption_timeout`), and a definite failure
        still goes through `finish` with its unchanged retry budget and backoff. Ownership is
        checked exactly as in `finish`: a stale controller cannot commit here either.
        """
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            row = self._owned(tx, claim, now)
            row.setdefault("attempts", []).append({"attempt": row["attempt"], "at": now.isoformat(),
                                                   "result": result, "deferred": True})
            row.update(status="queued", attempt=0, result=result, owner=None, lease_until=None,
                       retry_at=(now + timedelta(seconds=max(0, int(resume_after_seconds)))).isoformat())
            tx.put("release_queue", row["id"], row)
            tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
            return row

    def finish(self, claim, result, now=None):
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            row = self._owned(tx, claim, now)
            status = result["status"]
            if status == "retry" and row["attempt"] >= POLICY.release_max_attempts:
                status = "failed"
            row.setdefault("attempts", []).append({"attempt": row["attempt"],
                "at": now.isoformat(), "result": result})
            row.update(status=status, result=result, owner=None, lease_until=None,
                       retry_at=(now + timedelta(seconds=POLICY.release_retry_seconds
                                 * 2 ** (row["attempt"] - 1))).isoformat() if status == "retry" else None)
            if status == "failed" and result["status"] == "retry":
                row["reason"] = "release attempt budget exhausted"
            tx.put("release_queue", row["id"], row)
            tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
            return row

    def cancel(self, release_id, reason, *, transaction=None):
        """S7 V5: an abandoned release's queue row (M7 ReleaseRunner.abandon wrote it directly; the body is its)."""
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            queue = tx.get("release_queue", release_id)
            if queue:
                tx.put("release_queue", release_id, {**queue, "status": "cancelled", "reason": reason})
            return queue

    # ----- the active-generation maintenance hold (INV-HOST-DELIVERY-MAINTENANCE-001) -------------------
    def hold_maintenance(self, maintenance_id: str, *, now=None, within=None) -> dict | None:
        """Take the single controller lease for ONE maintenance phase, in ONE transaction.

        The `deployment_locks:controller` lease must be free (absent or expired), otherwise nothing is
        written, `within` does not run and the answer is None. The maintenance fence (scope
        `MAINTENANCE_SCOPE`, row `maintenance_id`) advances to its next generation under a new owner,
        the lock names this maintenance and that owner, and `within(tx, claim)` runs BEFORE the commit:
        its exception rolls the lease, the fence and its own writes back together and propagates. No
        release queue row, attempt, generation or release status is ever touched here, and `claim`/
        `retry` keep refusing for as long as the lease is held."""
        require(isinstance(maintenance_id, str) and maintenance_id, "Maintenance id required")
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > now:
                return None
            fence = self.fences.current(tx, MAINTENANCE_SCOPE, maintenance_id)
            previous = 0 if fence is None else fence.get("generation")
            require(type(previous) is int and previous >= 0, "Maintenance fence is corrupted")
            owner, generation = str((self.ids or SYSTEM_IDS).uuid4()), previous + 1
            self.fences.advance(tx, MAINTENANCE_SCOPE, maintenance_id, generation, owner, clock=self.clock)
            lease_until = (now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat()
            tx.put("deployment_locks", "controller", {"maintenance_id": maintenance_id, "owner": owner,
                                                      "lease_until": lease_until})
            claim = {"id": maintenance_id, "scope": MAINTENANCE_SCOPE, "owner": owner, "generation": generation,
                     "lease_until": lease_until}
            if within is not None:
                within(tx, dict(claim))
            return claim

    def owned_maintenance(self, tx, claim, now=None) -> dict:
        """Re-check a maintenance hold INSIDE the caller's transaction: the lock still names this
        maintenance and owner with an unexpired lease, and the durable fence is exactly this claim's
        generation and owner. Anything else is `Stale maintenance controller`; nothing is changed."""
        now = now or _now(self.clock)
        lock = tx.get("deployment_locks", "controller") or {}
        try:
            fresh = datetime.fromisoformat(lock["lease_until"]) > now
        except (KeyError, TypeError, ValueError):
            fresh = False
        require(isinstance(claim, dict) and lock.get("owner") == claim.get("owner") is not None
                and lock.get("maintenance_id") == claim.get("id") and fresh, "Stale maintenance controller")
        require(self.fences.current(tx, MAINTENANCE_SCOPE, claim["id"]) is not None, "Stale maintenance controller")
        try:
            self.fences.require_current(tx, MAINTENANCE_SCOPE, claim["id"], claim.get("generation"), claim["owner"])
        except ContractError:
            raise ContractError("Stale maintenance controller") from None
        return lock

    def heartbeat_maintenance(self, claim, now=None) -> dict:
        """Extend an owned maintenance lease in its own transaction; a stale hold raises and extends nothing."""
        now = now or _now(self.clock)
        with self.store.transaction() as tx:
            self.owned_maintenance(tx, claim, now)
            lease_until = (now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat()
            tx.put("deployment_locks", "controller", {"maintenance_id": claim["id"], "owner": claim["owner"],
                                                      "lease_until": lease_until})
        return {**claim, "lease_until": lease_until}

    def release_maintenance(self, claim, now=None) -> bool:
        """Clear the lease ONLY while it is still exactly this hold's (owner and maintenance id); True when
        cleared. A successor's lease is never cleared and a mismatch never raises."""
        with self.store.transaction() as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            if not (isinstance(claim, dict) and claim.get("owner") is not None
                    and lock.get("owner") == claim.get("owner") and lock.get("maintenance_id") == claim.get("id")):
                return False
            tx.put("deployment_locks", "controller", {"owner": None, "lease_until": None})
            return True


def _now(clock) -> datetime:
    """The clock seam of M7's `datetime.now(timezone.utc)` (an aware UTC datetime)."""
    return (clock or SYSTEM_CLOCK).now().astimezone(timezone.utc)
