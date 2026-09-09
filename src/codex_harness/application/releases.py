from __future__ import annotations

from contextlib import nullcontext
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

    def verify(self, release_id: str, revision: str, policy_hash: str, checks: dict) -> dict:
        with self.store.transaction() as tx:
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
