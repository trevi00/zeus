from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import datetime, timezone
from uuid import uuid4

from codex_harness.application.tickets import TicketSuperseded, ticket_binding
from codex_harness.domain.model import digest, require, utcnow


class Releases:
    """Approval evidence is immutable and evaluated against the incumbent policy."""

    def __init__(self, store, organization):
        self.store, self.org = store, organization

    def reconcile_audits(self):
        """Recover derived activation after an incumbent controller promotes the new runtime."""
        from dataclasses import asdict
        with self.store.transaction() as tx:
            active = tx.get('deployment', 'active') or {}
            record = tx.get('releases', active.get('release_id', ''))
            if not record or record['status'] != 'active' or record['candidate'].get('audit_lifecycle_version') != 1:
                return None
            control = tx.get('research_control', 'activation')
            # INV-RESEARCH-004: rollback pauses survive restoration of another release,
            # including legacy records that identify only the removed release.
            if control and (control.get('status') == 'paused' or
                            control.get('release_id') == active['release_id'] or
                            control.get('rolled_back_release') == active['release_id']):
                return control  # Never undo a pause or rollback for the same release.
            require(record['candidate']['revision'] == active['revision']
                    and record['policy_hash'] == digest(record['policy']), 'Invalid active audit release')
            author = self.org.actor(record['candidate']['author'], 'worker')
            approved = {r['actor'] for r in record['reviews']
                        if r['accepted'] and r['revision'] == active['revision'] and r.get('evidence')}
            require(author.parent in approved and 'conductor' in approved, 'Audit reviews incomplete')
            require(all(record['checks'].get(k, {}).get('passed') is True
                        and record['checks'][k].get('evidence')
                        for k in {'tests', 'cli_start', 'cli_file_task'} | set(record['policy']['checks'])),
                    'Audit checks incomplete')
            tx.put('research_control', 'graph', {'revision': active['revision'],
                'tree': record['candidate']['tree'],
                'organization': digest({k: asdict(v) for k, v in self.org.agents.items()})})
            control = {'status': 'active', 'release_id': active['release_id'], 'revision': active['revision']}
            tx.put('research_control', 'activation', control)
            return control

    def propose(self, candidate: dict, policy: dict, *, transaction=None) -> dict:
        require(all(candidate.get(key) for key in ("revision", "base", "tree", "author")),
                "Candidate identity incomplete")
        self.org.actor(candidate["author"], "worker")
        require(bool(policy.get("checks")), "Incumbent checks required")
        identity = digest({"candidate": candidate, "policy": policy})
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            ticket_binding(tx, candidate)
            old = tx.get("releases", identity)
            if old:
                return old
            record = {"id": identity, "candidate": candidate, "policy": policy,
                      "policy_hash": digest(policy), "status": "candidate", "reviews": [],
                      "checks": {}, "created_at": utcnow()}
            tx.put("releases", identity, record)
            return record

    def review(self, release_id: str, actor: str, revision: str, accepted: bool,
               evidence: str, *, transaction=None) -> dict:
        require(type(accepted) is bool and bool(evidence), "Review verdict and evidence required")
        reviewer = self.org.actor(actor)
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None, "Release not found")
            ticket_binding(tx, record["candidate"])
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
            try:
                ticket_binding(tx, record["candidate"])
            except TicketSuperseded as exc:
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
        ticket_binding(tx, candidate)
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

    def request_reverification(self, release_id: str, actor: str, expected_revision: str,
                               expected_policy_hash: str, reason: str, evidence: str, *,
                               now: datetime | None = None) -> dict:
        """INV-RELEASE-REVERIFY-001: one reviewed successor of a check-rejected release.

        The explicit trusted conductor request re-arms nothing: the rejected source stays byte for
        byte unchanged, the successor inherits only the exact code reviews and starts with EMPTY
        checks, so the normal queue and runner must produce every check again for the new id.
        """
        require(isinstance(reason, str) and reason.strip() and isinstance(evidence, str)
                and evidence.strip(), "Reverification reason and evidence required")
        self.org.actor(actor, "conductor")
        now = now or datetime.now(timezone.utc)
        successor_id = digest({"reverify_of": release_id})
        request = {"actor": actor, "reason": reason, "evidence": evidence,
                   "expected_revision": expected_revision, "expected_policy_hash": expected_policy_hash}
        with self.store.transaction() as tx:
            source = tx.get("releases", release_id)
            require(source is not None, "Release not found")
            existing = tx.get("releases", successor_id)
            if existing:
                # A replay after a restart returns the same successor without any write.
                receipt = existing.get("reverification") or {}
                require(existing.get("reverify_of") == release_id
                        and {k: receipt.get(k) for k in request} == request,
                        "Conflicting reverification request")
                return existing
            candidate, reviews, checks = self._check_rejected_source(
                tx, source, expected_revision, expected_policy_hash, now)
            at = now.isoformat()
            receipt = {**request, "source_checks_digest": digest(checks),
                       "source_digest": digest(source), "at": at}
            record = {"id": successor_id, "candidate": candidate, "policy": source["policy"],
                      "policy_hash": source["policy_hash"], "status": "reviewed", "reviews": reviews,
                      "checks": {}, "created_at": at, "reverify_of": release_id,
                      "inherited_reviews": {"release_id": release_id, "digest": digest(reviews)},
                      "reverification": receipt}
            tx.put("releases", successor_id, record)
            tx.put("events", "release.reverification_requested:" + successor_id,
                   {"type": "release.reverification_requested", "at": at, "release_id": successor_id,
                    "reverify_of": release_id, "actor": actor})
            return record

    def request_evaluator_migration(self, release_id: str, actor: str, *, expected_revision: str,
                                    expected_policy_hash: str, approval: dict,
                                    now: datetime | None = None, transaction=None) -> dict:
        """INV-RELEASE-EVALUATOR-MIGRATION-001: one owner-approved evaluator successor per source.

        The SAME reviewed candidate of a check-rejected release is evaluated again with incumbent
        tests taken from an owner-approved, tests-only evaluator commit E instead of candidate.base.
        The source stays byte for byte unchanged; the successor (keyed by the source alone, so a
        second E is a conflict, never a second successor) inherits the exact reviews and the check
        set, starts with EMPTY checks and changes only `policy.revision`, hence the policy hash.
        The pin is recorded, never trusted: the runner re-derives tree, paths and patch from git.
        """
        _require_evaluator_approval(approval, release_id)
        self.org.actor(actor, "conductor")
        approver = self.org.actor(approval["approved_by"], "conductor")
        now = now or datetime.now(timezone.utc)
        successor_id = digest({"evaluator_migration_of": release_id})
        request = {**approval, "actor": actor, "source_policy_hash": expected_policy_hash}
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            source = tx.get("releases", release_id)
            require(source is not None, "Release not found")
            existing = tx.get("releases", successor_id)
            if existing:
                # A replay returns the one successor without any write; anything else conflicts.
                receipt = existing.get("evaluator_migration") or {}
                require(existing.get("reverify_of") == release_id
                        and existing["candidate"]["revision"] == expected_revision
                        and {k: receipt.get(k) for k in request} == request,
                        "Conflicting evaluator migration")
                return existing
            require(tx.get("releases", digest({"reverify_of": release_id})) is None,
                    "Release already has a reverification successor")
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
            tx.put("events", "release.evaluator_migration_requested:" + successor_id,
                   {"type": "release.evaluator_migration_requested", "at": at,
                    "release_id": successor_id, "reverify_of": release_id, "actor": actor,
                    "evaluator_revision": approval["evaluator_revision"]})
            return record

    def promote(self, release_id: str, expected_active: str | None, *, transaction=None) -> dict:
        with (nullcontext(transaction) if transaction is not None else self.store.transaction()) as tx:
            record = tx.get("releases", release_id)
            require(record is not None and record["status"] == "verified", "Release not verified")
            ticket_binding(tx, record["candidate"])
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
                       "previous": {"release_id": active["release_id"]} if active else None, "at": utcnow()}
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
            tx.put("events", str(uuid4()), {"type": "release.promoted", **pointer})
            return pointer

    def rollback(self, expected_active: str, reason: str) -> dict:
        require(bool(reason), "Rollback reason required")
        with self.store.transaction() as tx:
            active = tx.get("deployment", "active")
            require(active is not None and active["release_id"] == expected_active, "Stale rollback")
            require(active["previous"] is not None, "No known-good previous deployment")
            record = tx.get("releases", expected_active)
            require(record is not None, "Active release record missing")
            hook_id = record.get("candidate", {}).get("hook_id")
            hook = tx.get("hooks", hook_id) if hook_id else None
            if hook and hook["revision"] == record["candidate"]["revision"]:
                tx.put("hooks", hook_id, hook.get("previous_active") or {**hook, "status": "rolled_back"})
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
            tx.put("events", str(uuid4()), {"type": "release.rolled_back", "at": utcnow(),
                                           "release_id": expected_active, "reason": reason})
            return previous


EVALUATOR_APPROVAL_KEYS = ("source_release_id", "base", "evaluator_revision", "evaluator_tree",
                           "patch_sha256", "paths", "evidence", "approved_by")
_HEX40, _HEX64 = re.compile(r"[0-9a-f]{40}"), re.compile(r"[0-9a-f]{64}")


def _require_evaluator_approval(approval, release_id: str) -> None:
    """The exact owner-authored approval shape of INV-RELEASE-EVALUATOR-MIGRATION-001."""
    require(isinstance(approval, dict) and set(approval) == set(EVALUATOR_APPROVAL_KEYS)
            and all(type(approval[k]) is str for k in EVALUATOR_APPROVAL_KEYS if k != "paths"),
            "Evaluator migration approval incomplete")
    require(bool(_HEX40.fullmatch(approval["evaluator_revision"]))
            and bool(_HEX40.fullmatch(approval["evaluator_tree"]))
            and bool(_HEX64.fullmatch(approval["patch_sha256"]))
            and approval["evidence"].startswith("sha256:")
            and bool(_HEX64.fullmatch(approval["evidence"][7:])), "Evaluator migration pin malformed")
    paths = approval["paths"]
    require(type(paths) is list and bool(paths) and all(type(p) is str for p in paths)
            and paths == sorted(set(paths)), "Evaluator paths must be a sorted non-empty list")
    require(all(p.startswith("tests/") and ".." not in p.split("/") for p in paths),
            "Evaluator migration may change only tests/")
    require(approval["source_release_id"] == release_id, "Evaluator approval names another release")
    require(bool(approval["base"]) and bool(approval["approved_by"]), "Evaluator migration approval incomplete")
