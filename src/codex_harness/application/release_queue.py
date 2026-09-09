"""Fenced single-controller release dispatch with bounded durable retries."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from codex_harness.application.tickets import ticket_binding
from codex_harness.domain.model import require
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

    def claim(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            lock = tx.get("deployment_locks", "controller") or {}
            if lock.get("lease_until") and datetime.fromisoformat(lock["lease_until"]) > now:
                return None
            for row in sorted(tx.scan("release_queue"), key=lambda r: (r.get("at", ""), r["id"])):
                if row["status"] not in {"queued", "retry", "running"}:
                    continue
                if row.get("retry_at") and datetime.fromisoformat(row["retry_at"]) > now:
                    continue
                if row.get("attempt", 0) >= POLICY.release_max_attempts:
                    row.update(status="failed", reason="release attempt budget exhausted")
                    tx.put("release_queue", row["id"], row)
                    continue
                row.update(status="running", attempt=row.get("attempt", 0) + 1,
                           owner=str(uuid4()), generation=row.get("generation", 0) + 1,
                           lease_until=(now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat())
                tx.put("release_queue", row["id"], row)
                tx.put("deployment_locks", "controller", {"release_id": row["id"],
                    "owner": row["owner"], "lease_until": row["lease_until"]})
                return row
        return None

    @staticmethod
    def _owned(tx, claim, now):
        row = tx.get("release_queue", claim["id"])
        lock = tx.get("deployment_locks", "controller") or {}
        require(row and row["status"] == "running" and row.get("owner") == claim["owner"]
                and row.get("generation") == claim["generation"]
                and lock.get("owner") == claim["owner"]
                and datetime.fromisoformat(row["lease_until"]) > now,
                "Stale release controller")
        return row

    def heartbeat(self, claim, now=None):
        now = now or datetime.now(timezone.utc)
        with self.store.transaction() as tx:
            row = self._owned(tx, claim, now)
            row["lease_until"] = (now + timedelta(seconds=POLICY.release_lease_seconds)).isoformat()
            tx.put("release_queue", row["id"], row)
            tx.put("deployment_locks", "controller", {"release_id": row["id"],
                "owner": row["owner"], "lease_until": row["lease_until"]})

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
