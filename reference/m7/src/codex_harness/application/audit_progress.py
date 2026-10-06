"""Observe the goal progress of ONE selected source audit and, after two comparable low-yield
windows, record ONE research candidate (INV-AUDIT-PROGRESS-001).

This is an observer, not a second scheduler, analysis engine, source reader, executor or promotion
authority. It calls no provider and no model, it starts, retries, cancels and rewrites nothing, and
it never touches a `tasks`, `schedule`, `research_*` or `fleet_jobs` row: the durable audit records
stay the authority and are read only. Its own durable state is two narrow buckets - the per-audit
epoch state and the closed window receipts - plus at most one `portfolio_investigations` row of the
explicit `audit_progress` kind, in the owner's undecided state.

One observation reads the authoritative rows in a short transaction, verifies the source-read
evidence bodies through the existing artifact store OUTSIDE any transaction, and then re-reads the
same rows and commits only when that binding is unchanged. An observation that cannot be taken is
explicitly `degraded`: it writes nothing, it never increments a streak, and it says nothing about
the execution that preceded it. A low window is an unverified symptom, never a cause.
"""
from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files

from codex_harness.application.portfolio import BUCKET_INVESTIGATIONS, RESEARCH_REQUIRED
from codex_harness.domain.audit_progress import (
    BASELINE,
    CLOSED,
    DEGRADED,
    KIND,
    LOW_VERDICTS,
    OBSERVATION_SCHEMA,
    OBSERVED,
    ProgressRefused,
    candidate_identity,
    candidate_row,
    epoch_identity,
    execution_key,
    measurement,
    observation_entry,
    policy_digest,
    range_identity,
    reason_for,
    record_observation,
    scope_digest,
    streak_after,
    validate_policy,
    window_cohort,
    window_delta,
    window_row,
    window_verdict,
)
from codex_harness.domain.model import digest, utcnow
from codex_harness.domain.research import PATH_DISPOSITIONS

BUCKET_STATE, BUCKET_WINDOWS = "audit_progress_state", "audit_progress_windows"
POLICY_RESOURCE = "audit-progress-policy-v1.json"
# The inert reader command `adapters.audit_runner` records in its receipts; it is not defined here.
SOURCE_READ = "source-read"
# The ONE literally semantic path disposition of the existing audit vocabulary
# (`domain.research.PATH_DISPOSITIONS`). Every other disposition is non-semantic HERE and is counted
# apart: `unreviewed` and `unavailable` are not coverage at all, while `generated`, `duplicate` and
# `binary` remain entirely VALID completions for `ResearchAudits._coverage` and the remaining-path
# and completion contract below. They are progress of the audit, not semantic review of a path, so
# they are never semantic gain and can never clear a low-yield streak on their own.
SEMANTIC = "semantic"
NON_SEMANTIC = tuple(name for name in PATH_DISPOSITIONS if name != SEMANTIC)


def packaged_policy(name: str = POLICY_RESOURCE) -> dict:
    """The owner-written threshold resource, unvalidated: `AuditProgress` validates it. Versioned
    Git data; no runtime self-editing and never model input."""
    return json.loads(files("codex_harness.resources").joinpath(name).read_text("utf-8"))


def _seconds(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


class AuditProgress:
    """One audit's progress observer over the existing store and artifact store."""

    def __init__(self, store, artifacts, *, policy: dict | None = None, clock=utcnow):
        self.store, self.artifacts, self.clock = store, artifacts, clock
        self.policy = validate_policy(packaged_policy() if policy is None else policy)
        self.policy_sha256 = policy_digest(self.policy)

    # ----- the authoritative reads ------------------------------------------------------------
    def _facts(self, tx, audit_id: str) -> dict:
        """Everything this observer reads from the store, in one transaction and read only.

        COMPLETION comes from the EXISTING audit authority (`ResearchAudits._coverage`/`_observed`),
        unchanged: it counts every valid disposition, including `generated`, `duplicate` and
        `binary`, and it alone decides the remaining paths and subsystems. SEMANTIC YIELD is the
        narrower fact this observer measures, so it counts the literal `semantic` dispositions and
        reports all the others apart - the completion denominator is not a semantic denominator.
        Neither definition lives here twice: a malformed stored record raises in that authority and
        this observation becomes degraded rather than a known zero.
        """
        from codex_harness.application.research import ResearchAudits

        audit = tx.get("research_audits", audit_id)
        if not isinstance(audit, dict):
            raise ProgressRefused("unknown_audit")
        partitions = sorted([p for p in tx.scan("research_partitions") if p["audit_id"] == audit_id],
                            key=lambda p: p["partition_id"])
        if not partitions:
            raise ProgressRefused("audit_not_partitioned")
        covered, subsystems = ResearchAudits._coverage(tx, audit)
        observed = ResearchAudits._observed(tx, audit)
        # Every disposition here was already validated against the vocabulary by `_coverage` above.
        semantic, non_semantic = set(), {}
        for row in tx.scan("research_paths"):
            if row["audit_id"] != audit_id:
                continue
            record = row.get("record") or {}
            disposition = record.get("disposition")
            if disposition == SEMANTIC:
                semantic.add(record.get("path"))
            elif disposition in NON_SEMANTIC:
                non_semantic[disposition] = non_semantic.get(disposition, 0) + 1
        inventory = {entry["path"] for entry in audit.get("inventory") or []}
        remaining_paths = sorted(inventory - covered)
        remaining_subsystems = sorted(set(audit.get("subsystems") or []) - subsystems)
        open_questions = [q for p in partitions for q in p.get("open_questions") or []]
        executions, statuses = [], {}
        for task in tx.scan("tasks"):
            details = ((task.get("message") or {}).get("what") or {}).get("details") or {}
            if details.get("audit_id") != audit_id:
                continue
            key = execution_key(task)
            if key is None:
                continue        # queued, running or retrying work is live, never settled
            executions.append((task.get("completed_at") or task.get("created_at") or "", key))
            statuses[task["status"]] = statuses.get(task["status"], 0) + 1
        reads = [row["receipt"]["output_ref"] for row in tx.scan("research_receipts")
                 if row["audit_id"] == audit_id
                 and (row["receipt"].get("command") or [None])[0] == SOURCE_READ
                 and type(row["receipt"].get("output_ref")) is str]
        # Content-addressed: two receipts of the same read name one immutable body, and the
        # distinct ranges below are computed over the bodies, never over the command count.
        read_refs = sorted(set(reads))
        facts = {"audit": audit, "scope_sha256": scope_digest(audit, partitions),
                 "semantic_paths": len(semantic), "semantic_subsystems": len(subsystems),
                 "non_semantic": non_semantic, "remaining_paths": len(remaining_paths),
                 "remaining_subsystems": len(remaining_subsystems), "open_questions": len(open_questions),
                 "executions": [key for _, key in sorted(executions)], "statuses": statuses,
                 "read_refs": read_refs, "read_receipts": len(reads),
                 "complete": not remaining_paths and not remaining_subsystems and not open_questions
                 and observed["pending"] == 0}
        # The exact binding this observation was measured against; a change between the read and
        # the commit refuses the whole observation instead of mixing two states.
        facts["binding"] = digest({key: facts[key] for key in
                                   ("scope_sha256", "semantic_paths", "semantic_subsystems", "non_semantic",
                                    "remaining_paths", "remaining_subsystems", "open_questions",
                                    "executions", "read_refs", "read_receipts", "complete")})
        return facts

    def _evidence(self, refs: list) -> dict:
        """Distinct verified source-read RANGES, read through the existing artifact store outside
        any transaction. A body that cannot be read or cannot be understood is unknown - never zero
        progress and never a second strike - and a repeated range adds no new evidence."""
        ranges, unreadable, malformed = set(), 0, 0
        for ref in refs:
            try:
                body = self.artifacts.document(ref)
            except Exception:
                unreadable += 1     # absent, modified or unreadable evidence: unknown, not zero
                continue
            identity = range_identity(body)
            if identity is None:
                malformed += 1
                continue
            ranges.add(identity)
        unknown = ("unreadable_evidence" if unreadable else "malformed_evidence" if malformed else None)
        return {"distinct_ranges": len(ranges), "unreadable": unreadable, "malformed": malformed,
                "unknown": unknown, "verified_bodies": len(refs)}

    # ----- one observation ---------------------------------------------------------------------
    def observe(self, audit_id: str, *, release_id=None, revision=None) -> dict:
        """One restart-safe observation. Never raises: an observation that cannot be taken is
        `degraded` with a fixed reason, writes nothing and leaves the audit's own success alone."""
        try:
            return self._observe(audit_id, release_id=release_id, revision=revision)
        except ProgressRefused as exc:
            return self._degraded(audit_id, exc.reason_code)
        except Exception as exc:
            return self._degraded(audit_id, "observation_failed", error_type=type(exc).__name__)

    def _observe(self, audit_id: str, *, release_id, revision) -> dict:
        with self.store.transaction() as tx:
            facts = self._facts(tx, audit_id)
        evidence = self._evidence(facts["read_refs"])
        now = self.clock()
        with self.store.transaction() as tx:
            current = self._facts(tx, audit_id)
            if current["binding"] != facts["binding"]:
                # The records moved while the evidence was being verified: this reading is not a
                # fact about either state, so nothing is written and no window can close on it.
                return self._degraded(audit_id, "state_changed")
            return self._apply(tx, current, evidence, release_id=release_id, revision=revision, now=now)

    def _apply(self, tx, facts: dict, evidence: dict, *, release_id, revision, now: str) -> dict:
        evidence = {**evidence, "read_receipts": facts["read_receipts"]}
        epoch = epoch_identity(audit_id=facts["audit"]["id"], scope_sha256=facts["scope_sha256"],
                               policy_sha256=self.policy_sha256, release_id=release_id, revision=revision)
        metrics = measurement(semantic_paths=facts["semantic_paths"],
                              semantic_subsystems=facts["semantic_subsystems"],
                              non_semantic=facts["non_semantic"], remaining_paths=facts["remaining_paths"],
                              remaining_subsystems=facts["remaining_subsystems"],
                              open_questions=facts["open_questions"], executions=len(facts["executions"]),
                              ranges=evidence["distinct_ranges"], unknown=evidence["unknown"],
                              complete=facts["complete"], observed_at=now)
        state = tx.get(BUCKET_STATE, epoch["audit_id"])
        if not isinstance(state, dict) or (state.get("epoch") or {}).get("id") != epoch["id"]:
            return self._start_epoch(tx, state, epoch, facts, metrics, evidence, now)
        counted = set(state.get("counted") or [])
        new = [key for key in facts["executions"] if key not in counted]
        cohort = window_cohort(new, self.policy["window_executions"])
        if not cohort["closes"]:
            return self._record(tx, state, metrics, evidence, now,
                                status=OBSERVED, new_executions=len(new), window=None, candidate=None)
        return self._close_window(tx, state, epoch, metrics, evidence, cohort, now)

    def _start_epoch(self, tx, previous, epoch: dict, facts: dict, metrics: dict, evidence: dict,
                     now: str) -> dict:
        """A first observation, or a changed scope, policy, release or revision: a NEW epoch with
        its own baseline. Every execution that already settled is counted into the baseline, so no
        historical work can ever earn a strike, and the previous epoch's windows and any recorded
        candidate stay exactly as they are - history is never rewritten or compared across epochs."""
        state = {"id": epoch["audit_id"], "audit_id": epoch["audit_id"], "epoch": epoch,
                 "policy_sha256": self.policy_sha256,
                 "baseline": {"executions": len(facts["executions"]), "metrics": metrics, "at": now},
                 "counted": list(facts["executions"]),
                 "window": {"index": 1, "opening": metrics, "opened_at": now},
                 "windows_completed": 0, "streak": 0, "last_verdict": None, "candidate": None,
                 "epochs": int((previous or {}).get("epochs") or 0) + 1,
                 "created_at": now, "updated_at": now}
        return self._record(tx, state, metrics, evidence, now, status=BASELINE, new_executions=0,
                            window=None, candidate=None)

    def _close_window(self, tx, state: dict, epoch: dict, metrics: dict, evidence: dict, cohort: dict,
                      now: str) -> dict:
        """Close EXACTLY one window per reading with the cohort `window_cohort` allows.

        Exactly `window_executions` new settled executions are one comparable window. A larger
        cohort is consumed ENTIRELY by one `not_comparable` overflow receipt that reports its real
        size, and the next window opens at this same complete reading: no execution is left over to
        be re-measured later against an opening it never had, so an overflow can neither hide work
        nor manufacture a zero-gain strike out of it, and a repeated reading finds nothing new to
        close. Either way the streak follows the verdict alone.
        """
        members = cohort["members"]
        opening, opened_at = state["window"]["opening"], state["window"]["opened_at"]
        delta = window_delta(opening, metrics, _seconds(opened_at, now))
        verdict = window_verdict(opening=opening, closing=metrics, delta=delta, policy=self.policy,
                                 incomparable=cohort["incomparable"])
        window = window_row(epoch=epoch, index=state["window"]["index"], members=members,
                            opening=opening, closing=metrics, delta=delta, verdict=verdict,
                            policy_sha256=self.policy_sha256, opened_at=opened_at, closed_at=now)
        tx.put(BUCKET_WINDOWS, window["id"], window)
        streak = streak_after(int(state.get("streak") or 0), window["verdict"])
        state.update(counted=sorted(set(state.get("counted") or []) | set(members)),
                     window={"index": window["index"] + 1, "opening": metrics, "opened_at": now},
                     windows_completed=int(state.get("windows_completed") or 0) + 1,
                     streak=streak, last_verdict=window["verdict"])
        candidate = None
        if streak >= self.policy["low_yield_windows"]:
            candidate = self._candidate(tx, epoch, window, streak, now)
            if candidate["id"] is not None:
                state["candidate"] = candidate["id"]
        return self._record(tx, state, metrics, evidence, now, status=CLOSED,
                            new_executions=len(members), window=window, candidate=candidate)

    def _candidate(self, tx, epoch: dict, window: dict, streak: int, now: str) -> dict:
        """ONE candidate per epoch. A first streak records the row in the owner's undecided state;
        every later streak of the same epoch only appends a bounded observation, so an owner
        disposition, the original windows and the recorded reason all survive."""
        required = self.policy["low_yield_windows"]
        low = sorted([row for row in tx.scan(BUCKET_WINDOWS)
                      if row.get("epoch") == epoch["id"] and row.get("comparable")
                      and row.get("verdict") in LOW_VERDICTS], key=lambda row: row["index"])
        streaked = low[-required:]
        contiguous = [row["index"] for row in streaked] == list(
            range(window["index"] - len(streaked) + 1, window["index"] + 1))
        identifier = candidate_identity(epoch["id"])
        existing = tx.get(BUCKET_INVESTIGATIONS, identifier)
        if isinstance(existing, dict):
            row = record_observation(existing, observation_entry(window=window, streak=streak, now=now))
            tx.put(BUCKET_INVESTIGATIONS, identifier, row)
            return {"id": identifier, "created": False, "reason_code": row.get("reason_code"),
                    "windows": list(row.get("windows") or [])}
        if len(streaked) < required or not contiguous:
            # The streak counter and the durable window receipts disagree: report the streak and
            # record no candidate rather than inventing a membership.
            return {"id": None, "created": False, "reason_code": None, "windows": []}
        row = candidate_row(epoch=epoch, policy_sha256=self.policy_sha256,
                            reason_code=reason_for(streaked), windows=streaked,
                            metrics=window["closing"], required_state=RESEARCH_REQUIRED, now=now)
        tx.put(BUCKET_INVESTIGATIONS, identifier, row)
        return {"id": identifier, "created": True, "reason_code": row["reason_code"],
                "windows": list(row["windows"])}

    def _record(self, tx, state: dict, metrics: dict, evidence: dict, now: str, *, status: str,
                new_executions: int, window, candidate) -> dict:
        observation = {"schema": OBSERVATION_SCHEMA, "audit_id": state["audit_id"], "status": status,
                       "epoch": state["epoch"]["id"], "policy_sha256": self.policy_sha256,
                       "window_index": state["window"]["index"], "new_executions": new_executions,
                       "window": None if window is None else {
                           key: window[key] for key in ("id", "index", "verdict", "comparable",
                                                        "verdict_reason", "executions", "delta")},
                       "verdict": None if window is None else window["verdict"],
                       "streak": int(state.get("streak") or 0),
                       "candidate": (candidate or {}).get("id") or state.get("candidate"),
                       "candidate_created": bool((candidate or {}).get("created")),
                       "unknown": metrics["unknown"], "evidence": evidence, "metrics": metrics,
                       "at": now}
        state.update(last_observation=observation, updated_at=now)
        tx.put(BUCKET_STATE, state["id"], state)
        return observation

    def _degraded(self, audit_id: str, reason_code: str, **facts) -> dict:
        """An observation failure: explicit, bounded and separate from the audit's own success. It
        writes nothing, counts no window and increments no streak."""
        return {"schema": OBSERVATION_SCHEMA, "audit_id": audit_id, "status": DEGRADED,
                "reason_code": reason_code, "epoch": None, "window": None, "verdict": None,
                "streak": None, "candidate": None, "candidate_created": False, "unknown": reason_code,
                "at": self.clock(), **facts}

    # ----- read-only ---------------------------------------------------------------------------
    def state(self, audit_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET_STATE, audit_id)

    def windows(self, audit_id: str) -> list:
        with self.store.transaction() as tx:
            rows = [row for row in tx.scan(BUCKET_WINDOWS) if row.get("audit_id") == audit_id]
        return sorted(rows, key=lambda row: (row["epoch"], row["index"]))

    def candidates(self, audit_id: str | None = None) -> list:
        with self.store.transaction() as tx:
            rows = [row for row in tx.scan(BUCKET_INVESTIGATIONS) if row.get("kind") == KIND]
        return [row for row in rows if audit_id is None or row.get("audit_id") == audit_id]


def status_view(state) -> dict:
    """The bounded read-only projection of one audit's progress state: identifiers, fixed codes and
    counts only. `observed` false means no observation exists, never that progress is zero."""
    if not isinstance(state, dict):
        return {"observed": False, "epoch": None, "policy_sha256": None, "windows_completed": 0,
                "streak": 0, "candidate": None, "last_verdict": None, "last_observation": None,
                "last_delta": None}
    last = state.get("last_observation") or {}
    return {"observed": True, "epoch": (state.get("epoch") or {}).get("id"),
            "policy_sha256": state.get("policy_sha256"),
            "baseline_executions": (state.get("baseline") or {}).get("executions"),
            "counted_executions": len(state.get("counted") or []),
            "windows_completed": int(state.get("windows_completed") or 0),
            "window_index": (state.get("window") or {}).get("index"),
            "streak": int(state.get("streak") or 0), "candidate": state.get("candidate"),
            "last_verdict": state.get("last_verdict"), "updated_at": state.get("updated_at"),
            "last_observation": {key: last.get(key) for key in
                                 ("status", "verdict", "new_executions", "unknown", "at")},
            # The last closed window's own arithmetic: semantic and evidence deltas beside the
            # absolute counts below. `null` while no window has closed in this epoch.
            "last_delta": (last.get("window") or {}).get("delta"),
            "metrics": {key: (last.get("metrics") or {}).get(key) for key in
                        ("semantic_paths", "semantic_subsystems", "remaining_paths",
                         "remaining_subsystems", "open_questions", "distinct_ranges", "executions")}}


__all__ = ["BUCKET_STATE", "BUCKET_WINDOWS", "AuditProgress", "packaged_policy", "status_view"]
