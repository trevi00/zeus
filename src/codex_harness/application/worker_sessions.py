"""Durable Claude task-session lifecycle over the existing store (INV-WORKER-SESSION-001).

One bucket, `worker_sessions`, keyed by the logical task id. The row is the binding and its state;
the transcript bytes live in the restricted `SessionArchives` store and the row keeps only their
reference and hashes. Every action is a few short store transactions with the file work strictly
between them, because the real `PostgresStore.transaction` takes a process-wide advisory lock and no
transaction may be open across file, process or another transaction:

1. read the row (one short transaction);
2. do the file work outside every transaction: put/verify the archive, check continuity, stage;
3. commit only if the row `version` is still the one read, and the caller still owns it.

A lost response is replayed to the same deterministic archive reference and an idempotent row
update; a changed version in step 3 is a refusal, never a blind overwrite. Waiting for review holds
no owner and calls nothing: there is no method here that starts a provider.

This primitive never creates work, approves a candidate, merges, or deletes an archive. The
conductor continuation is the sole admission owner of a correction turn.
"""
from __future__ import annotations

from uuid import uuid4

from codex_harness.domain.model import require, utcnow
from codex_harness.domain.worker_sessions import (
    ACCEPTED,
    ACTIVE,
    ARCHIVAL_PENDING,
    ARCHIVE_CORRUPT,
    ARCHIVE_MISSING,
    AWAITING_REVIEW,
    CHECKPOINTED,
    CLOSED,
    CORRECTION_READY,
    INCOMPATIBLE,
    MAX_HISTORY,
    MODE_FRESH,
    MODE_RESUME,
    REFERENCE,
    RESUMABLE,
    SCHEMA,
    UNRESOLVED,
    WorkerSessionRefused,
    compare_identity,
    refuse,
    review_outcome,
    status_view,
    transition,
    validate_candidate,
    validate_identity,
    validate_owner,
)

BUCKET = "worker_sessions"
DECISIONS = "decisions_pending"


class WorkerSessions:
    """The lifecycle owner. `archives` is a `SessionArchives`; `evidence` (optional) is the general
    artifact store used only to verify that a promoted evidence reference really exists."""

    def __init__(self, store, archives, *, evidence=None, clock=utcnow):
        self.store, self.archives, self.evidence, self.clock = store, archives, evidence, clock

    # ---- reads ----------------------------------------------------------------------------------
    def _read(self, task_id: str) -> dict | None:
        with self.store.transaction() as tx:
            return tx.get(BUCKET, task_id)

    def status(self, task_id: str | None = None) -> dict:
        """Read-only projection; never transcript bytes."""
        with self.store.transaction() as tx:
            rows = [tx.get(BUCKET, task_id)] if task_id is not None else tx.scan(BUCKET)
        rows = [row for row in rows if row is not None]
        return {"schema": SCHEMA, "sessions": [status_view(row) for row in rows][:200],
                "truncated": len(rows) > 200}

    # ---- the one conditional write --------------------------------------------------------------
    def _commit(self, task_id: str, version, change) -> dict:
        """Apply `change(row)` only if the row is still at `version`; otherwise refuse unchanged."""
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, task_id)
            refuse((row or {}).get("version") == version, "session_changed",
                   f"expected version {version}, found {(row or {}).get('version')}")
            updated = change(row)
            updated["version"] = (version or 0) + 1
            updated["updated_at"] = self.clock()
            tx.put(BUCKET, task_id, updated)
            return updated

    @staticmethod
    def _event(row: dict, kind: str, **detail) -> None:
        row["history"] = (row.get("history") or [])[-(MAX_HISTORY - 1):] + [{"event": kind, **detail}]

    def _set_state(self, row: dict, target: str, reason: str | None = None, **detail) -> dict:
        previous = row.get("state")
        row["state"] = transition(previous, target)
        row["reason"] = reason
        self._event(row, "state", previous=previous, state=target, reason=reason, at=self.clock(), **detail)
        return row

    # ---- begin a turn ---------------------------------------------------------------------------
    def begin(self, task_id: str, identity: dict, owner: dict) -> dict:
        """Claim the session exclusively for one execution and say how to open the provider.

        No row: a new session and a fresh turn. A resumable row: the archive is verified OUTSIDE the
        transaction, then the claim commits only if nothing moved meanwhile. A duplicate begin by the
        same owner returns the same plan. Any other owner is refused, however old the claim looks."""
        identity, owner = validate_identity(identity), validate_owner(owner)
        refuse(identity["task_id"] == task_id, "identity_malformed", "task_id")
        row = self._read(task_id)
        if row is None:
            session_id = str(uuid4())
            try:
                created = self._commit(task_id, None, lambda _row: self._set_state(
                    {"schema": SCHEMA, "task_id": task_id, "session_id": session_id, "identity": identity,
                     "owner": owner, "claimed_from": None, "checkpoints": [], "candidates": [], "reviews": [],
                     "created_at": self.clock()}, ACTIVE, "opened", owner=owner))
            except WorkerSessionRefused as exc:
                if exc.reason != "session_changed":
                    raise
                return self.begin(task_id, identity, owner)  # a concurrent opener won; decide against its row
            return self._plan(created, MODE_FRESH)
        comparison = compare_identity(row["identity"], identity)
        refuse(comparison["decision"] != "foreign", "session_foreign", ",".join(comparison["foreign"]))
        if row.get("owner") is not None:
            refuse(row["owner"] == owner, "session_owned", "another execution holds this session")
            return self._plan(row, row.get("mode") or MODE_FRESH)
        if row["state"] == ACTIVE and not row.get("checkpoints"):
            # Opened but no turn was ever adopted: a fresh turn under a NEW session id, never a
            # resume of a transcript nobody verified. The binding itself is still not rewritten.
            refuse(comparison["decision"] == "match", "session_incompatible", ",".join(comparison["incompatible"]))
            session_id = str(uuid4())

            def reopened(current):
                self._event(current, "reopened", previous_session=current["session_id"], owner=owner, at=self.clock())
                return {**current, "session_id": session_id, "owner": owner, "mode": MODE_FRESH, "claimed_from": None}
            return self._plan(self._claim(task_id, row, reopened, identity, owner), MODE_FRESH)
        refuse(row["state"] in RESUMABLE, "session_not_resumable", str(row["state"]))
        if comparison["decision"] == "incompatible":
            self._commit(task_id, row["version"], lambda current: self._set_state(
                current, INCOMPATIBLE, "fresh_evidence_handoff_required",
                fields=comparison["incompatible"], observed={k: identity[k] for k in comparison["incompatible"]}))
            raise WorkerSessionRefused("session_incompatible",
                                       "native resume refused (" + ",".join(comparison["incompatible"])
                                       + "); an explicit fresh evidence handoff is required")
        archive = row["checkpoints"][-1]["archive"]
        try:
            self.archives.load(archive["ref"], session_id=row["session_id"])
        except WorkerSessionRefused as exc:
            reason = exc.reason
            target = ARCHIVE_MISSING if reason == "archive_missing" else ARCHIVE_CORRUPT
            self._commit(task_id, row["version"], lambda current: self._set_state(current, target, reason))
            raise
        def claimed(current):
            previous = current["state"]
            return {**self._set_state(current, ACTIVE, "claimed_for_resume", owner=owner),
                    "owner": owner, "claimed_from": previous, "mode": MODE_RESUME}
        return self._plan(self._claim(task_id, row, claimed, identity, owner), MODE_RESUME)

    def _claim(self, task_id, row, change, identity, owner) -> dict:
        """Commit a claim at the version read; a concurrent winner is re-read and decided again."""
        try:
            return self._commit(task_id, row["version"], change)
        except WorkerSessionRefused as exc:
            if exc.reason != "session_changed":
                raise
            self.begin(task_id, identity, owner)  # the winner's row: normally `session_owned`
            raise

    def _plan(self, row: dict, mode: str) -> dict:
        last = (row.get("checkpoints") or [None])[-1]
        return {"task_id": row["task_id"], "session_id": row["session_id"], "mode": mode,
                "version": row["version"], "archive": (last or {}).get("archive") if mode == MODE_RESUME else None,
                "usage_baseline": (last or {}).get("usage_baseline") if mode == MODE_RESUME else None,
                "owner": row["owner"]}

    def stage(self, plan: dict, destination) -> dict | None:
        """Write the plan's verified archive into a transport's empty restore directory."""
        if plan["mode"] != MODE_RESUME:
            return None
        return self.archives.stage(plan["archive"]["ref"], destination, session_id=plan["session_id"])

    def release(self, task_id: str, owner: dict, reason: str) -> dict:
        """The claiming execution ended without a turn to adopt (refused before entry, or a failed
        turn whose transcript is not the continuation). The prior resume point stays authoritative."""
        owner = validate_owner(owner)
        row = self._read(task_id)
        refuse(row is not None and row.get("owner") == owner, "session_not_owned")
        if row.get("claimed_from") is None:
            # A first turn that was not adopted: the session stays opened and unclaimed, and the
            # next begin opens a fresh turn under a new session id.
            def unclaimed(current):
                self._event(current, "released", state=current["state"], reason=reason, at=self.clock())
                return {**current, "owner": None, "mode": None, "reason": reason}
            return self._commit(task_id, row["version"], unclaimed)

        def returned(current):
            previous = current["claimed_from"]
            current.update(state=previous, reason=reason, owner=None, claimed_from=None, mode=None)
            self._event(current, "released", state=previous, reason=reason, at=self.clock())
            return current
        return self._commit(task_id, row["version"], returned)

    def mark_unresolved(self, task_id: str, owner: dict, reason: str) -> dict:
        """The execution's effect is unknown: the claim is kept as evidence, nothing resumes it."""
        owner = validate_owner(owner)
        row = self._read(task_id)
        refuse(row is not None and row.get("owner") == owner, "session_not_owned")
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, UNRESOLVED, reason, owner=owner), "owner": None, "unresolved_owner": owner})

    # ---- checkpoint a turn ----------------------------------------------------------------------
    def checkpoint(self, task_id: str, owner: dict, export_directory, *, usage: dict | None,
                   cli_version: str | None = None) -> dict:
        """Adopt one finished turn: archive (deterministic, verified) THEN an idempotent row update.

        A crash after the archive write and before the commit is replayed to the same reference.
        A duplicate checkpoint of the same archive by the same owner returns the recorded one."""
        owner = validate_owner(owner)
        row = self._read(task_id)
        refuse(row is not None, "session_missing")
        export = self.archives.read_export(export_directory, session_id=row["session_id"])
        receipt = self.archives.put(export)
        last = (row.get("checkpoints") or [None])[-1]
        if last is not None and last["archive"]["ref"] == receipt["ref"] and last["owner"] == owner:
            return row  # duplicate event: already adopted
        refuse(row.get("owner") == owner and row["state"] == ACTIVE, "session_not_owned")
        mode = row.get("mode") or MODE_FRESH
        continuity = "fresh_session"
        if mode == MODE_RESUME:
            continuity = self.archives.continuity(last["archive"]["ref"], export, session_id=row["session_id"])
        if continuity == "unproven":
            # Never relabel an unproven context as resumed; the bytes stay retained for the owner.
            self._commit(task_id, row["version"], lambda current: {
                **self._set_state(current, UNRESOLVED, "resume_continuity_unproven", archive=receipt["ref"]),
                "owner": None, "unresolved_owner": owner, "unadopted_archive": receipt})
            raise WorkerSessionRefused("resume_continuity_unproven", receipt["ref"])
        entry = {"archive": receipt, "owner": owner, "mode": mode, "continuity": continuity,
                 "usage_baseline": {"session_id": row["session_id"], "raw": (usage or {}).get("raw")},
                 "usage": usage, "cli_version": cli_version, "at": self.clock()}
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, CHECKPOINTED, "turn_adopted", archive=receipt["ref"]),
            "checkpoints": (current.get("checkpoints") or []) + [entry],
            "owner": None, "claimed_from": None, "mode": None})

    def reconcile(self, task_id: str, export_directory, *, usage: dict | None = None) -> dict:
        """UNRESOLVED -> CHECKPOINTED from retained verified bytes of this exact session, only when
        they continue the last adopted archive (or are the first archive of this session)."""
        row = self._read(task_id)
        refuse(row is not None and row["state"] == UNRESOLVED, "session_not_unresolved")
        export = self.archives.read_export(export_directory, session_id=row["session_id"])
        receipt = self.archives.put(export)
        last = (row.get("checkpoints") or [None])[-1]
        continuity = ("fresh_session" if last is None
                      else self.archives.continuity(last["archive"]["ref"], export, session_id=row["session_id"]))
        refuse(continuity != "unproven", "resume_continuity_unproven", receipt["ref"])
        entry = {"archive": receipt, "owner": row.get("unresolved_owner"), "mode": "reconciled",
                 "continuity": continuity, "usage_baseline": {"session_id": row["session_id"],
                                                              "raw": (usage or {}).get("raw")},
                 "usage": usage, "cli_version": None, "at": self.clock()}
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, CHECKPOINTED, "reconciled", archive=receipt["ref"]),
            "checkpoints": (current.get("checkpoints") or []) + [entry], "unadopted_archive": None})

    # ---- review ---------------------------------------------------------------------------------
    def submit(self, task_id: str, candidate: dict) -> dict:
        """Freeze the candidate the last checkpoint produced. Resubmitting the identical candidate is
        a duplicate; a rejected candidate is immutable and never becomes reviewable again."""
        candidate = validate_candidate(candidate)
        row = self._read(task_id)
        refuse(row is not None, "session_missing")
        prior = [entry for entry in row.get("candidates") or [] if entry["revision"] == candidate["revision"]]
        refuse(all(entry["tree"] == candidate["tree"] and entry["base"] == candidate["base"] for entry in prior),
               "candidate_conflict", "same revision, different content")
        if row["state"] == AWAITING_REVIEW and row["candidates"][-1]["revision"] == candidate["revision"]:
            return row
        refuse(not any(entry.get("outcome") == "rejected" for entry in prior), "candidate_rejected_immutable")
        refuse(row["state"] == CHECKPOINTED and row.get("owner") is None, "session_not_submittable", str(row["state"]))
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, AWAITING_REVIEW, "candidate_frozen", revision=candidate["revision"]),
            "candidates": (current.get("candidates") or []) + [{**candidate, "outcome": None,
                                                               "archive": current["checkpoints"][-1]["archive"]["ref"],
                                                               "submitted_at": self.clock()}]})

    def record_review(self, task_id: str, decision_id: str) -> dict:
        """Read the existing decision row for the frozen candidate and move the session on it."""
        require(type(decision_id) is str and bool(decision_id), "Decision id required")
        with self.store.transaction() as tx:
            row = tx.get(BUCKET, task_id)
            refuse(row is not None, "session_missing")
            if any(review["decision_id"] == decision_id for review in row.get("reviews") or []):
                return row  # duplicate event
            refuse(row["state"] == AWAITING_REVIEW, "session_not_awaiting_review", str(row["state"]))
            candidate = {key: row["candidates"][-1][key] for key in ("revision", "tree", "base")}
            outcome = review_outcome(tx.get(DECISIONS, decision_id), candidate)
            refuse(outcome["decision_id"] == decision_id, "review_malformed", "id")
            target = {"rejected": CORRECTION_READY, "accepted": ACCEPTED}.get(outcome["outcome"])
            row["reviews"] = (row.get("reviews") or []) + [{**outcome, "at": self.clock()}]
            if outcome["outcome"] in ("rejected", "accepted"):
                row["candidates"][-1]["outcome"] = outcome["outcome"]
            if target is not None:
                self._set_state(row, target, "review_" + outcome["outcome"], decision_id=decision_id)
            else:
                self._event(row, "review", decision_id=decision_id, outcome=outcome["outcome"], at=self.clock())
            row["version"] = row["version"] + 1
            row["updated_at"] = self.clock()
            tx.put(BUCKET, task_id, row)
            return row

    # ---- closure --------------------------------------------------------------------------------
    def promote(self, task_id: str, evidence_ref: str) -> dict:
        """ACCEPTED -> ARCHIVAL_PENDING once the accepted evidence is durably promoted and verified."""
        refuse(type(evidence_ref) is str and REFERENCE.fullmatch(evidence_ref) is not None, "evidence_malformed")
        row = self._read(task_id)
        refuse(row is not None, "session_missing")
        if row["state"] == ARCHIVAL_PENDING and (row.get("promotion") or {}).get("evidence_ref") == evidence_ref:
            return row
        refuse(row["state"] == ACCEPTED, "session_not_accepted", str(row["state"]))
        if self.evidence is not None:
            self.evidence.inspect(evidence_ref)  # outside any transaction; raises when absent or modified
        self.archives.load(row["checkpoints"][-1]["archive"]["ref"], session_id=row["session_id"])
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, ARCHIVAL_PENDING, "evidence_promoted", evidence_ref=evidence_ref),
            "promotion": {"evidence_ref": evidence_ref, "verified": self.evidence is not None, "at": self.clock()}})

    def close(self, task_id: str, cleanup=None) -> dict:
        """ARCHIVAL_PENDING -> CLOSED after the owner's scratch cleanup succeeded. A cleanup failure is
        recorded and the session stays pending with its archive; the archive itself is never removed."""
        row = self._read(task_id)
        refuse(row is not None, "session_missing")
        if row["state"] == CLOSED:
            return row
        refuse(row["state"] == ARCHIVAL_PENDING and row.get("promotion"), "session_not_promoted", str(row["state"]))
        self.archives.load(row["checkpoints"][-1]["archive"]["ref"], session_id=row["session_id"])
        failure = None
        if cleanup is not None:
            try:
                cleanup(row)
            except Exception as exc:  # recorded by type; never permission to discard the last copy
                failure = type(exc).__name__
        if failure is not None:
            return self._commit(task_id, row["version"], lambda current: {
                **current, "cleanup": {"state": "failed", "error_type": failure, "at": self.clock(),
                                       "archive_retained": current["checkpoints"][-1]["archive"]["ref"]}})
        return self._commit(task_id, row["version"], lambda current: {
            **self._set_state(current, CLOSED, "closed"),
            "cleanup": {"state": "done" if cleanup is not None else "not_requested", "at": self.clock(),
                        "archive_retained": current["checkpoints"][-1]["archive"]["ref"]}})
