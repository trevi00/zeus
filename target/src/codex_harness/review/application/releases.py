"""Release candidates and their reviews: approval evidence is immutable and evaluated against incumbent policy.

Layer: application
Context: review
Owns: the `releases` bucket's candidate proposal and review (M7 `application/releases.Releases.propose/review`,
    moved ahead in S4 unchanged: lead decision Option A, the owner operations the §2.9 decision unit writes)
Does not own: verification, re-verification, evaluator/environment migration, promote and rollback (the rest
    of M7 `application/releases.py`: S8), ticket binding (intake, injected)
Entry points: Releases, Releases.propose, Releases.review
Contracts: INV-RELEASE-001, INV-TICKET-001

`transaction=` joins the caller's atomic unit (§2.9 rule 2): with it the operation never opens a transaction.
"""

from __future__ import annotations

from contextlib import nullcontext

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest, utcnow


class Releases:
    """Approval evidence is immutable and evaluated against the incumbent policy."""

    def __init__(self, store, organization, *, ticket_binding, clock=None):
        # Target (§2.4): intake's ticket_binding is injected (review imports no other application); the
        # receipt time takes an injected clock. S8 adds the remaining M7 methods to this class.
        self.store, self.org = store, organization
        self.ticket_binding, self.clock = ticket_binding, clock

    def propose(self, candidate: dict, policy: dict, *, transaction=None) -> dict:
        require(all(candidate.get(key) for key in ("revision", "base", "tree", "author")),
                "Candidate identity incomplete")
        self.org.actor(candidate["author"], "worker")
        require(bool(policy.get("checks")), "Incumbent checks required")
        identity = digest({"candidate": candidate, "policy": policy})
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            self.ticket_binding(tx, candidate)
            old = tx.get("releases", identity)
            if old:
                return old
            record = {"id": identity, "candidate": candidate, "policy": policy,
                      "policy_hash": digest(policy), "status": "candidate", "reviews": [],
                      "checks": {}, "created_at": utcnow(self.clock)}
            tx.put("releases", identity, record)
            return record

    def review(self, release_id: str, actor: str, revision: str, accepted: bool,
               evidence: str, *, transaction=None) -> dict:
        require(type(accepted) is bool and bool(evidence), "Review verdict and evidence required")
        reviewer = self.org.actor(actor)
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None, "Release not found")
            self.ticket_binding(tx, record["candidate"])
            require(record["candidate"]["revision"] == revision, "Stale release review")
            previous = next((r for r in record["reviews"] if r["actor"] == actor), None)
            if previous:
                require(previous["accepted"] == accepted, "Conflicting duplicate review")
                return record
            require(record["status"] in {"candidate", "reviewed"}, "Release is not reviewable")
            author = self.org.actor(record["candidate"]["author"])
            require(actor == author.parent or reviewer.role == "conductor", "Unauthorized review")
            if reviewer.role == "conductor":
                require(any(r["actor"] == author.parent and r["accepted"] for r in record["reviews"]),
                        "Lead review required first")
            require(not any(r["actor"] == actor for r in record["reviews"]), "Duplicate release review")
            record["reviews"].append({"actor": actor, "revision": revision,
                                      "accepted": accepted, "evidence": evidence})
            record["status"] = ("rejected" if not accepted else "reviewed"
                                if reviewer.role == "conductor" else "candidate")
            tx.put("releases", release_id, record)
            return record
