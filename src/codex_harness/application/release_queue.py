"""Fenced single-controller release dispatch with bounded durable retries."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from codex_harness.application.execution_fence import advance as advance_fence
from codex_harness.application.execution_fence import require_current as require_current_fence
from codex_harness.application.tickets import ticket_binding
from codex_harness.domain.model import ContractError, require
from codex_harness.domain.policy import POLICY


class ReleaseQueue:
    def __init__(self, store):
        self.store = store

    def retry(self, release_id, reason):
        require(isinstance(reason, str) and reason.strip(), "Retry reason required")
        now = datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            require(not lock.get("lease_until") or datetime.fromisoformat(lock["lease_until"]) <= now,
                    "Release controller still running")
            release = tx.get("releases", release_id)
            require(release and release["status"] in {"reviewed", "verified"}, "Release is not recoverable")
            ticket_binding(tx, release["candidate"])
            row = tx.get("release_queue", release_id) or {"id": release_id, "at": now.isoformat()}
            row.setdefault("manual_retries", []).append({"reason": reason, "at": now.isoformat(),
                                                        "previous_attempt": row.get("attempt", 0)})
            row.update(status="queued", attempt=0, retry_at=None, owner=None, lease_until=None)
            tx.put("release_queue", release_id, row)
            return row

    def enqueue(self, release_id, reason):
        """Queue an ALREADY reviewed release for the single release controller; idempotent.

        This is the same row the executor writes on conductor acceptance, created here for a
        release that was reviewed outside that path. It grants nothing: the row is refused unless
        the release record itself is `reviewed` or `verified` and its ticket binding still holds,
        an existing row of any status is returned untouched (a failed or cancelled release is never
        silently re-armed), and no lease, attempt, generation or fence is changed.
        """
        require(isinstance(reason, str) and reason.strip(), "Enqueue reason required")
        now = datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            existing = tx.get("release_queue", release_id)
            if existing:
                return existing
            release = tx.get("releases", release_id)
            require(release and release["status"] in {"reviewed", "verified"},
                    "Release is not queueable")
            ticket_binding(tx, release["candidate"])
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
        now = now or datetime.now(timezone.utc)
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
                owner = str(uuid4())
                try:
                    advance_fence(tx, "release_queue", row["id"], row.get("generation", 0) + 1, owner)
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
        return self._owned(tx, claim, now or datetime.now(timezone.utc))

    @staticmethod
    def _owned(tx, claim, now):
        row = tx.get("release_queue", claim["id"])
        lock = tx.get("deployment_locks", "controller") or {}
        require(row and row["status"] == "running" and row.get("owner") == claim["owner"]
                and row.get("generation") == claim["generation"]
                and lock.get("owner") == claim["owner"]
                and datetime.fromisoformat(row["lease_until"]) > now,
                "Stale release controller")
        require_current_fence(tx, "release_queue", row["id"], row.get("generation"), row.get("owner"))
        return row

    def heartbeat(self, claim, now=None):
        now = now or datetime.now(timezone.utc)
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
        now = now or datetime.now(timezone.utc)
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
        now = now or datetime.now(timezone.utc)
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
