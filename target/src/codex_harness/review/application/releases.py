"""Release candidates and their reviews: approval evidence is immutable and evaluated against incumbent policy.

Layer: application
Context: review
Owns: the `releases` bucket (proposal and review, moved ahead in S4; verify, the migration successors,
    promote, rollback and the V5 owner operations, moved ahead in S7 for delivery), and review's
    `deployment`, `deployment_history` and `research_control` rows those write
Does not own: reconcile_audits and request_reverification (S8), ticket binding (intake, injected), events
    (coordination's EventAppend) and hooks (research's HookRollback), each injected
Entry points: Releases, Releases.propose, Releases.review
Contracts: INV-RELEASE-001, INV-TICKET-001

`transaction=` joins the caller's atomic unit (§2.9 rule 2): with it the operation never opens a transaction.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, digest, utcnow
from codex_harness.review.domain.releases import (
    EnvironmentReverificationRefused,
    UnsupportedEvaluatorReverification,
    _evaluator_migrated,
    _require_environment_approval,
    _require_evaluator_approval,
    environment_successor_id,
    evaluator_successor_id,
    expected_evaluator_pin,
    require_controller_code,
    reverification_successor_id,
)


class Releases:
    """Approval evidence is immutable and evaluated against the incumbent policy."""

    def __init__(self, store, organization, *, ticket_binding, clock=None, ticket_superseded=None, events=None,
                 hooks=None, ids=None):
        # Target (§2.4): intake's ticket_binding/TicketSuperseded are injected (review imports no other
        # application); the receipt time takes an injected clock and the event keys an injected id source.
        # S7 (DESIGN-s7 V3) adds the methods delivery calls; `events` is coordination's EventAppend and `hooks`
        # research's HookRollback, each joining the caller's transaction. S8 adds the rest of M7.
        self.store, self.org = store, organization
        self.ticket_binding, self.clock = ticket_binding, clock
        self.ticket_superseded, self.events, self.hooks, self.ids = ticket_superseded, events, hooks, ids

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

    def verify(self, release_id: str, revision: str, policy_hash: str, checks: dict, *,
               transaction=None) -> dict:
        # INV-HOST-DELIVERY-VERIFY-001: a caller holding the release fence records the verdict in
        # the same transaction that re-checks that fence; the body is unchanged.
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None and record["status"] == "reviewed", "Reviews incomplete")
            require(record["candidate"]["revision"] == revision
                    and record["policy_hash"] == policy_hash, "Stale candidate or evaluator")
            require(set(checks) == set(record["policy"]["checks"]), "Missing or extra canary checks")
            require(all(isinstance(c, dict) and type(c.get("passed")) is bool and c.get("evidence")
                        for c in checks.values()), "Checks require real execution evidence")
            record.update(checks=checks, status="verified" if all(c["passed"] for c in checks.values())
                          else "rejected")
            require(self.ticket_superseded is not None, "Ticket supersession is not wired")
            try:
                self.ticket_binding(tx, record["candidate"])
            except self.ticket_superseded as exc:
                record.update(status="superseded_by_ticket_revision", reason=str(exc))
            tx.put("releases", release_id, record)
            return record

    def _check_rejected_source(self, tx, source: dict, expected_revision: str,
                               expected_policy_hash: str, now: datetime) -> tuple:
        """The guards every successor of a check-rejected release shares (INV-RELEASE-REVERIFY-001).

        Returns the source's (candidate, reviews, checks); refuses unless the source is a complete,
        honestly check-rejected, fully reviewed release with no running controller or promotion effect.
        """
        release_id = source["id"]
        require(source["status"] == "rejected", "Release is not check-rejected")
        candidate, reviews, checks = source["candidate"], source["reviews"], source["checks"]
        require(candidate["revision"] == expected_revision
                and source["policy_hash"] == expected_policy_hash, "Stale candidate or evaluator")
        require(source["policy_hash"] == digest(source["policy"]), "Evaluator changed")
        self.ticket_binding(tx, candidate)
        author = self.org.actor(candidate["author"], "worker")
        require(all(r["accepted"] is True for r in reviews), "Release review rejected")
        accepted = {r["actor"] for r in reviews
                    if r["revision"] == candidate["revision"] and r.get("evidence")}
        require(len(reviews) == len(accepted) and {author.parent, "conductor"} <= accepted,
                "Release reviews incomplete")
        require(set(checks) == set(source["policy"]["checks"])
                and all(isinstance(c, dict) and type(c.get("passed")) is bool and c.get("evidence")
                        for c in checks.values()), "Rejection check evidence incomplete")
        require(any(c["passed"] is False and not c.get("skipped") for c in checks.values()),
                "No executed failed check")
        lock = tx.get("deployment_locks", "controller") or {}
        require(not lock.get("lease_until") or datetime.fromisoformat(lock["lease_until"]) <= now,
                "Release controller still running")
        require((tx.get("release_queue", release_id) or {}).get("status") != "running",
                "Release controller still running")
        require(tx.get("promotion_intents", release_id) is None
                and (tx.get("deployment", "active") or {}).get("release_id") != release_id,
                "Promotion effects exist for the release")
        return candidate, reviews, checks

    def request_evaluator_migration(self, release_id: str, actor: str, *, expected_revision: str,
                                    expected_policy_hash: str, approval: dict, resolved_pin: dict,
                                    now: datetime | None = None, transaction=None) -> dict:
        """INV-RELEASE-EVALUATOR-MIGRATION-001: one owner-approved evaluator successor per source.

        The SAME reviewed candidate of a check-rejected release is evaluated again with incumbent
        tests taken from an owner-approved, tests-only evaluator commit E instead of candidate.base.
        The source stays byte for byte unchanged; the successor (keyed by the source alone, so a
        second E is a conflict, never a second successor) inherits the exact reviews and the check
        set, starts with EMPTY checks and changes only `policy.revision`, hence the policy hash.
        The pin is recorded, never trusted: `resolved_pin` is the trusted resolver's derivation
        (`adapters.deployment.resolve_evaluator_pin`) made BEFORE this call and outside any lock; it
        must equal the approved pin exactly, with E a direct child of the approved base, or nothing
        is written. The runner still re-derives tree, paths and patch from git at execution time.
        """
        _require_evaluator_approval(approval, release_id)
        self.org.actor(actor, "conductor")
        approver = self.org.actor(approval["approved_by"], "conductor")
        now = now or _now(self.clock)
        successor_id = evaluator_successor_id(release_id)
        request = {**approval, "actor": actor, "source_policy_hash": expected_policy_hash}
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            source = tx.get("releases", release_id)
            require(source is not None, "Release not found")
            if _evaluator_migrated(source):
                raise UnsupportedEvaluatorReverification()  # no recursive migration
            require(resolved_pin == expected_evaluator_pin(approval), "Evaluator pin does not match the repository")
            existing = tx.get("releases", successor_id)
            if existing:
                # A replay returns the one successor without any write; anything else conflicts.
                receipt = existing.get("evaluator_migration") or {}
                require(existing.get("reverify_of") == release_id
                        and existing["candidate"]["revision"] == expected_revision
                        and {k: receipt.get(k) for k in request} == request,
                        "Conflicting evaluator migration")
                return existing
            require(tx.get("releases", reverification_successor_id(release_id)) is None,
                    "Release already has a reverification successor")
            # INV-RELEASE-ENVIRONMENT-REVERIFY-001: the three successor kinds block each other.
            require(tx.get("releases", environment_successor_id(release_id)) is None,
                    "Release already has an environment reverification successor")
            candidate, reviews, checks = self._check_rejected_source(
                tx, source, expected_revision, expected_policy_hash, now)
            require(approver.id != candidate["author"], "Evaluator approver is the candidate author")
            require(approval["base"] == candidate["base"], "Evaluator approval base differs from candidate")
            require(approval["evaluator_revision"] not in {candidate["revision"], candidate["base"]},
                    "Evaluator revision must differ from candidate and base")
            at = now.isoformat()
            policy = {**source["policy"], "revision": approval["evaluator_revision"]}
            receipt = {**request, "source_checks_digest": digest(checks),
                       "source_digest": digest(source), "at": at}
            record = {"id": successor_id, "candidate": candidate, "policy": policy,
                      "policy_hash": digest(policy), "status": "reviewed", "reviews": reviews,
                      "checks": {}, "created_at": at, "reverify_of": release_id,
                      "inherited_reviews": {"release_id": release_id, "digest": digest(reviews)},
                      "evaluator_migration": receipt}
            tx.put("releases", successor_id, record)
            self._event(tx, "release.evaluator_migration_requested:" + successor_id,
                   {"type": "release.evaluator_migration_requested", "at": at,
                    "release_id": successor_id, "reverify_of": release_id, "actor": actor,
                    "evaluator_revision": approval["evaluator_revision"]})
            return record

    def request_environment_reverification(self, release_id: str, actor: str, *, expected_revision: str,
                                           expected_policy_hash: str, approval: dict, resolved_pin: dict,
                                           resolved_controller, now: datetime | None = None,
                                           transaction=None) -> dict:
        """INV-RELEASE-ENVIRONMENT-REVERIFY-001: one conductor-approved re-evaluation of a migrated source.

        The source is an evaluator-migrated successor (INV-RELEASE-EVALUATOR-MIGRATION-001) whose
        incumbent tests PASSED and whose rejection came only from an executed, failed non-test
        (environment) check. The successor is the SAME candidate under the SAME policy (so the same
        evaluator E) with the SAME reviews; it copies the source's `evaluator_migration` receipt
        verbatim so the runner re-derives E exactly as before, records the approval (including the
        approved `controller_revision` and `fix_evidence`) and starts with EMPTY checks. Depth is
        bounded to one: a source that is itself an environment successor is refused. `resolved_pin`
        is the trusted resolver's derivation of the source's (E, base), made outside any lock; it
        must equal the source's recorded pin exactly. `resolved_controller` is the trusted
        integration boundary's resolution of the ACTUAL running controller code (never the approval's
        own string); it must equal the approved `controller_revision` and is recorded with the
        receipt. Every refusal happens before any write.
        """
        _require_environment_approval(approval, release_id)
        require_controller_code(resolved_controller, approval["controller_revision"])
        if approval["source_policy_hash"] != expected_policy_hash:
            # The receipt records ONE source policy hash; a replay must not mask a differing approval.
            raise EnvironmentReverificationRefused("environment_reverification_approval_invalid",
                                                   "environment approval names another evaluator")
        self.org.actor(actor, "conductor")
        approver = self.org.actor(approval["approved_by"], "conductor")
        now = now or _now(self.clock)
        successor_id = environment_successor_id(release_id)
        request = {**approval, "actor": actor, "source_policy_hash": expected_policy_hash}
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            source = tx.get("releases", release_id)
            require(source is not None, "Release not found")
            migration = source.get("evaluator_migration")
            if not isinstance(migration, dict):
                raise EnvironmentReverificationRefused(
                    "environment_reverification_requires_migrated_source",
                    "release is not an evaluator-migrated successor")
            if "environment_reverification" in source:
                raise EnvironmentReverificationRefused(
                    "environment_reverification_depth", "release is already an environment successor")
            if resolved_pin != expected_evaluator_pin(migration) \
                    or source["policy"].get("revision") != migration["evaluator_revision"] \
                    or migration["base"] != source["candidate"].get("base"):
                raise EnvironmentReverificationRefused(
                    "environment_reverification_pin_mismatch", "evaluator pin does not match the source")
            existing = tx.get("releases", successor_id)
            if existing:
                # A replay returns the one successor without any write; anything else conflicts.
                receipt = existing.get("environment_reverification") or {}
                require(existing.get("reverify_of") == release_id
                        and existing["candidate"]["revision"] == expected_revision
                        and {k: receipt.get(k) for k in request} == request,
                        "Conflicting environment reverification")
                return existing
            require(tx.get("releases", reverification_successor_id(release_id)) is None,
                    "Release already has a reverification successor")
            require(tx.get("releases", evaluator_successor_id(release_id)) is None,
                    "Release already has an evaluator migration successor")
            candidate, reviews, checks = self._check_rejected_source(
                tx, source, expected_revision, expected_policy_hash, now)
            require(approval["source_policy_hash"] == source["policy_hash"],
                    "Environment approval names another evaluator")
            require(approver.id != candidate["author"], "Environment approver is the candidate author")
            tests = checks.get("tests") or {}
            if tests.get("passed") is not True or tests.get("skipped"):
                raise EnvironmentReverificationRefused("tests_not_passed", "incumbent tests did not pass")
            if not any(name != "tests" and c["passed"] is False and not c.get("skipped")
                       for name, c in checks.items()):
                raise EnvironmentReverificationRefused(
                    "environment_reverification_no_failed_environment_check",
                    "no executed failed non-test check")
            at = now.isoformat()
            receipt = {**request, "source_checks_digest": digest(checks),
                       "source_digest": digest(source), "controller_resolved": resolved_controller, "at": at}
            record = {"id": successor_id, "candidate": candidate, "policy": source["policy"],
                      "policy_hash": source["policy_hash"], "status": "reviewed", "reviews": reviews,
                      "checks": {}, "created_at": at, "reverify_of": release_id,
                      "inherited_reviews": {"release_id": release_id, "digest": digest(reviews)},
                      "evaluator_migration": migration, "environment_reverification": receipt}
            tx.put("releases", successor_id, record)
            self._event(tx, "release.environment_reverification_requested:" + successor_id,
                   {"type": "release.environment_reverification_requested", "at": at,
                    "release_id": successor_id, "reverify_of": release_id, "actor": actor,
                    "controller_revision": approval["controller_revision"]})
            return record

    def promote(self, release_id: str, expected_active: str | None, *, transaction=None) -> dict:
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None and record["status"] == "verified", "Release not verified")
            self.ticket_binding(tx, record["candidate"])
            active = tx.get("deployment", "active")
            require((active or {}).get("release_id") == expected_active, "Active deployment changed")
            require(record["policy_hash"] == digest(record["policy"]), "Evaluator changed")
            if active:
                tx.put("deployment_history", active["release_id"], active)
                previous_release = tx.get("releases", active["release_id"])
                if previous_release:
                    previous_release["status"] = "superseded"
                    tx.put("releases", previous_release["id"], previous_release)
            pointer = {"release_id": release_id, "revision": record["candidate"]["revision"],
                       "previous": {"release_id": active["release_id"]} if active else None, "at": utcnow(self.clock)}
            tx.put("deployment", "active", pointer)
            # INV-RESEARCH-004: activation follows the exact candidate's incumbent checks.
            if record['candidate'].get('audit_lifecycle_version') == 1:
                require(all(record['checks'].get(k, {}).get('passed')
                            for k in ('tests', 'cli_start', 'cli_file_task')),
                        'Audit activation requires actual CLI canary')
                from dataclasses import asdict
                tx.put('research_control', 'graph', {'revision': pointer['revision'],
                    'tree': record['candidate']['tree'],
                    'organization': digest({k: asdict(v) for k, v in self.org.agents.items()})})
                tx.put('research_control', 'activation', {'status': 'active',
                    'release_id': release_id, 'revision': pointer['revision']})
            elif tx.get('research_control', 'activation'):
                tx.put('research_control', 'activation', {'status': 'paused',
                    'reason': 'active candidate does not declare audit lifecycle'})
            record["status"] = "active"
            tx.put("releases", release_id, record)
            self._event(tx, str((self.ids or SYSTEM_IDS).uuid4()), {"type": "release.promoted", **pointer})
            return pointer

    def rollback(self, expected_active: str, reason: str) -> dict:
        require(bool(reason), "Rollback reason required")
        with self.store.transaction() as tx:
            active = tx.get("deployment", "active")
            require(active is not None and active["release_id"] == expected_active, "Stale rollback")
            require(active["previous"] is not None, "No known-good previous deployment")
            record = tx.get("releases", expected_active)
            require(record is not None, "Active release record missing")
            self._roll_back_hook(tx, record)  # R6: research's HookRollback (the hooks bucket is research's)
            # INV-RESEARCH-004: retain evidence and bind the pause to the restored deployment.
            if tx.get('research_control', 'activation'):
                tx.put('research_control', 'activation', {'status': 'paused',
                    'release_id': active['previous']['release_id'],
                    'reason': reason, 'rolled_back_release': expected_active})
            record.update(status="rolled_back", rollback_reason=reason)
            tx.put("releases", expected_active, record)
            previous = tx.get("deployment_history", active["previous"]["release_id"]) or active["previous"]
            tx.put("deployment", "active", previous)
            previous_release = tx.get("releases", previous["release_id"])
            if previous_release:
                previous_release["status"] = "active"
                tx.put("releases", previous_release["id"], previous_release)
            self._event(tx, str((self.ids or SYSTEM_IDS).uuid4()), {"type": "release.rolled_back", "at": utcnow(self.clock),
                                           "release_id": expected_active, "reason": reason})
            return previous

    # ----- S7 V5: the review writes M7 delivery code made inline, as owner operations in the caller's unit --------
    def record_superseded(self, release_id: str, reason: str, *, transaction=None) -> dict:
        """A reviewed release whose ticket was superseded (M7 host_delivery `_record_release` and ReleaseRunner.run
        wrote this row directly; the body is theirs)."""
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None, "Release not found")
            record.update(status="superseded_by_ticket_revision", reason=reason)
            tx.put("releases", release_id, record)
            return record

    def cancel(self, release_id: str, reason: str, *, transaction=None) -> dict:
        """An abandoned release (M7 ReleaseRunner.abandon wrote this row directly; the body is its)."""
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            release = tx.get("releases", release_id)
            require(release is not None, "Release not found")
            tx.put("releases", release_id, {**release, "status": "cancelled", "reason": reason})
            return release

    def _event(self, tx, identity: str, body: dict) -> None:
        require(self.events is not None, "Event journal is not wired")
        self.events.append(tx, identity, body)

    def _roll_back_hook(self, tx, record: dict) -> None:
        require(self.hooks is not None, "Hook rollback is not wired")
        self.hooks.roll_back(tx, record)


def _now(clock) -> datetime:
    """The clock seam of M7's `datetime.now(timezone.utc)` (an aware UTC datetime)."""
    return (clock or SYSTEM_CLOCK).now().astimezone(timezone.utc)
