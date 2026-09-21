"""Admit at most ONE evidence-bound corrective successor for a rejected source audit analysis, and
settle it truthfully (INV-AUDIT-REPAIR-001).

This is an owner of two narrow buckets over the records that already exist; it is not a second
scheduler, analysis engine, source reader, executor, provider, promotion authority or retry engine.
It calls no model. It never writes a `research_partitions`, `research_paths`, `research_subsystems`,
`research_checkpoints` or `audit_progress_*` row, never rewrites the original task, its result, its
artifact or its rejection, never moves an execution fence or a lease, and never acknowledges,
cancels or republishes anyone else's message. What it writes, in ONE transaction, is its own
correction record plus the ordinary `audit_partition` assignment of the SAME trusted partition
generation: the existing outbox, the existing `schedule` deduplication, the existing Redis delivery,
the existing Workflow claim and fence and the existing validators then do exactly what they already
do.

Opt-in and scope. Nothing is admitted unless an operator durably enabled THIS audit and named the
rejected task. Disabling prevents new admission only: a recorded lineage, its evidence and its
settlement survive.

One successor. The lineage identity is derived from the durable records (audit, partition, partition
generation, original task, its execution generation and the diagnosis), so a repeated tick, a
restarted service and a concurrent admission caller all find the SAME record instead of creating a
second call. If the corrective attempt is itself rejected, the family records `research_required`
and stops: the original and the successor are two distinct attempts and there is no third one.
Infrastructure or unknown execution is `reconciliation_required`, which is not a strike either.

Evidence first. The immutable artifact is inspected and read OUTSIDE any transaction, the pure
content decode is replayed against it (the replay is injected; this layer imports no adapter), and
the admission commits only when the exact state it was diagnosed against is unchanged.
"""
from __future__ import annotations

from codex_harness.application.execution_notices import RESEARCH_REQUIRED as NOTICE_REASON
from codex_harness.application.execution_notices import record as execution_notice
from codex_harness.domain.audit_repair import (
    BINDING_CHANGED,
    CONTROL_UNAVAILABLE,
    EVIDENCE_MISMATCH,
    EVIDENCE_MISSING,
    EVIDENCE_UNREADABLE,
    FAMILY_CLOSED,
    FOREIGN_PARTITION,
    GENERATION_CHANGED,
    LINEAGE_EXISTS,
    NO_CANDIDATE,
    NO_CORRECTABLE_IDENTITY,
    NOT_ENABLED,
    OUT_OF_SCOPE,
    PREDECESSOR_UNPUBLISHED,
    REPLAY_MISMATCH,
    REPLAY_UNAVAILABLE,
    RESEARCH_INACTIVE,
    RESEARCH_REQUIRED,
    TERMINAL_STATES,
    UNKNOWN_PARTITION,
    UNKNOWN_TASK,
    UNRESOLVED_TERMINATION,
    UNSUPPORTED_DIAGNOSIS,
    RepairRefused,
    binding,
    correction_identity,
    correction_row,
    diagnosis_for,
    diagnosis_view,
    family_identity,
    notice_evidence,
    notice_proof,
    rejection_facts,
    repair_context,
    repair_details,
    schedule_key,
    settlement,
    status_view,
    target_identities,
    unjustified_subsystems,
)
from codex_harness.domain.model import digest, envelope, utcnow

BUCKET_ACTIVATION = "audit_repair_activation"
BUCKET_CORRECTIONS = "audit_repair_corrections"
# The durable control rows a commit re-reads. `research_control/activation` is the SAME run gate the
# host service reads before every admission, and `observation_terminations` holds the unconfirmed /
# pending_reconciliation markers whose owner is the operator alone. Neither is written here.
BUCKET_CONTROL = "research_control"
CONTROL_KEY = "activation"
BUCKET_TERMINATIONS = "observation_terminations"
UNRESOLVED_MARKERS = ("unconfirmed", "pending_reconciliation")
# The ONE action, sender and recipient a correction may ever use: the ordinary partition assignment
# of the existing research lane. Nothing here can address another agent or invent another action.
SENDER, AGENT, ACTION = "lead:research", "worker:github", "audit_partition"
ENABLED, DISABLED = "enabled", "disabled"


class AuditRepair:
    """One audit's bounded repair owner over the existing store and artifact store."""

    def __init__(self, store, org, artifacts, *, replay=None, clock=utcnow):
        self.store, self.org, self.artifacts = store, org, artifacts
        # The pure content decode of ONE retained draft, injected by the adapter that owns it. When
        # it is absent nothing becomes eligible: an unavailable validator is unknown, not permission.
        self.replay, self.clock = replay, clock

    # ----- the durable opt-in -------------------------------------------------------------------
    def enable(self, audit_id: str, task_id: str, *, operator: str) -> dict:
        """Scope this owner to ONE audit and ONE rejected task. Evidence-bound: the task must exist,
        belong to that audit and carry its own recorded rejection. Writes no assignment."""
        self._label(operator)
        with self.store.transaction() as tx:
            self._known_audit(tx, audit_id)
            facts = rejection_facts(tx.get("tasks", self._identity(task_id, "task_id")))
            if facts is None or facts["audit_id"] != audit_id:
                raise RepairRefused(UNKNOWN_TASK)
            now = self.clock()
            row = tx.get(BUCKET_ACTIVATION, audit_id) or self._default_activation(audit_id, now)
            row.update(status=ENABLED, operator=operator, updated_at=now,
                       task_ids=sorted(set(row.get("task_ids") or []) | {task_id}))
            tx.put(BUCKET_ACTIVATION, audit_id, row)
            return {"audit_id": audit_id, "enabled": True, "scope": list(row["task_ids"])}

    def disable(self, audit_id: str, *, operator: str) -> dict:
        """Close admission. Recorded lineages, their evidence and their settlement are untouched,
        and a successor that is already queued keeps its own durable assignment and claim order."""
        self._label(operator)
        with self.store.transaction() as tx:
            self._known_audit(tx, audit_id)
            now = self.clock()
            row = tx.get(BUCKET_ACTIVATION, audit_id) or self._default_activation(audit_id, now)
            row.update(status=DISABLED, operator=operator, updated_at=now)
            tx.put(BUCKET_ACTIVATION, audit_id, row)
            return {"audit_id": audit_id, "enabled": False, "scope": list(row.get("task_ids") or [])}

    @staticmethod
    def _default_activation(audit_id: str, now: str) -> dict:
        return {"id": audit_id, "audit_id": audit_id, "status": DISABLED, "task_ids": [],
                "operator": None, "created_at": now, "updated_at": now}

    @staticmethod
    def _label(operator) -> str:
        """An audit label, never an authenticated identity."""
        if type(operator) is not str or not operator.strip():
            raise RepairRefused("operator_invalid")
        return operator

    @staticmethod
    def _identity(value, field: str) -> str:
        if type(value) is not str or not value.strip():
            raise RepairRefused(field + "_invalid")
        return value

    @staticmethod
    def _known_audit(tx, audit_id: str) -> dict:
        audit = tx.get("research_audits", AuditRepair._identity(audit_id, "audit_id"))
        if audit is None:
            raise RepairRefused("unknown_audit")
        return audit

    # ----- read-only inspection -----------------------------------------------------------------
    def inspect(self, audit_id: str, task_id: str | None = None) -> dict:
        """Every rejected analysis of this audit with its typed diagnosis. Creates NO task, no
        record and no activation: a historical row is classified by the same read-only validator."""
        candidates = []
        for facts in self._candidates(audit_id, task_id):
            candidates.append(self._diagnose(facts))
        with self.store.transaction() as tx:
            activation = tx.get(BUCKET_ACTIVATION, audit_id)
        return {"audit_id": audit_id, "enabled": (activation or {}).get("status") == ENABLED,
                "scope": sorted((activation or {}).get("task_ids") or []),
                "candidates": [self._candidate_view(row) for row in candidates]}

    @staticmethod
    def _candidate_view(row: dict) -> dict:
        return {"source_task_id": row["facts"]["task_id"],
                "partition_id": row["facts"]["partition_id"],
                "partition_generation": row["facts"]["partition_generation"],
                "source_execution_ref": row["facts"]["execution_ref"],
                "diagnosis": row.get("diagnosis"), "eligible": row["eligible"],
                "reason_code": row.get("reason_code"), "error_type": row.get("error_type"),
                "subsystems_total": (row.get("identities") or {}).get("total")}

    def _candidates(self, audit_id: str, task_id: str | None = None) -> list:
        """This audit's settled executions whose CONTENT was refused, oldest first. Read only."""
        with self.store.transaction() as tx:
            rows = []
            for task in tx.scan("tasks"):
                facts = rejection_facts(task)
                if facts is None or facts["audit_id"] != audit_id:
                    continue
                if task_id is not None and facts["task_id"] != task_id:
                    continue
                rows.append((str(task.get("completed_at") or task.get("created_at") or ""),
                             str(facts["task_id"]), facts,
                             ((task.get("message") or {}).get("correlation_id")))
                            )
        return [{**facts, "correlation_id": correlation}
                for _, _, facts, correlation in sorted(rows, key=lambda row: (row[0], row[1]))]

    # ----- the typed diagnosis ------------------------------------------------------------------
    def _diagnose(self, facts: dict) -> dict:
        """One evidence-bound diagnosis, with the artifact read OUTSIDE any transaction.

        Every refusal is a fixed reason code. An unreadable artifact, an unavailable replay and a
        replay that does not reproduce the recorded refusal are all ineligible: unknown is never
        permission, and no defect is repaired, decoded or normalized here.
        """
        refused = dict(facts)
        with self.store.transaction() as tx:
            partition = tx.get("research_partitions", facts["partition_id"] or "")
            unpublished = any(not row.get("sent") and ((row.get("message") or {}).get("correlation_id")
                                                       == facts.get("correlation_id"))
                              for row in tx.scan("outbox"))
        if not isinstance(partition, dict):
            return self._ineligible(refused, UNKNOWN_PARTITION)
        if partition.get("audit_id") != facts["audit_id"]:
            return self._ineligible(refused, FOREIGN_PARTITION)
        if partition.get("generation") != facts["partition_generation"]:
            # The scope moved on: this rejection no longer holds the generation it was assigned.
            return self._ineligible(refused, GENERATION_CHANGED)
        diagnosis = diagnosis_for(facts)
        if diagnosis is None:
            return self._ineligible(refused, UNSUPPORTED_DIAGNOSIS, partition=partition)
        if unpublished:
            return self._ineligible(refused, PREDECESSOR_UNPUBLISHED, partition=partition,
                                    diagnosis=diagnosis)
        ref = facts["execution_ref"]
        if ref is None:
            return self._ineligible(refused, EVIDENCE_MISSING, partition=partition, diagnosis=diagnosis)
        try:
            inspected = self.artifacts.inspect(ref)
            document = self.artifacts.document(ref)
        except FileNotFoundError as exc:
            return self._ineligible(refused, EVIDENCE_MISSING, partition=partition,
                                    diagnosis=diagnosis, error_type=type(exc).__name__)
        except Exception as exc:
            return self._ineligible(refused, EVIDENCE_UNREADABLE, partition=partition,
                                    diagnosis=diagnosis, error_type=type(exc).__name__)
        answer = document.get("answer") if isinstance(document, dict) else None
        if inspected.get("ref") != ref or not isinstance(answer, dict):
            return self._ineligible(refused, EVIDENCE_MISMATCH, partition=partition, diagnosis=diagnosis)
        if self.replay is None:
            return self._ineligible(refused, REPLAY_UNAVAILABLE, partition=partition, diagnosis=diagnosis)
        try:
            replayed = self.replay(partition, answer)
        except Exception as exc:
            return self._ineligible(refused, REPLAY_UNAVAILABLE, partition=partition,
                                    diagnosis=diagnosis, error_type=type(exc).__name__)
        if not (replayed.get("refused") and replayed.get("error_digest") == facts["error_digest"]
                and replayed.get("error_type") == facts["error_type"]):
            # The retained draft does not reproduce the refusal this task recorded: the evidence and
            # the record disagree, so nothing is admitted on it.
            return self._ineligible(refused, REPLAY_MISMATCH, partition=partition, diagnosis=diagnosis)
        # The COMPLETE diagnosed target set travels with the diagnosis; the bounded projection is
        # only what the assignment may carry, so settlement's denominator is never truncated.
        targets = target_identities(answer, partition.get("subsystems"))
        identities = unjustified_subsystems(answer, partition.get("subsystems"))
        if not identities["total"]:
            return self._ineligible(refused, NO_CORRECTABLE_IDENTITY, partition=partition,
                                    diagnosis=diagnosis, identities=identities)
        return {"facts": facts, "eligible": True, "diagnosis": diagnosis, "reason_code": None,
                "error_type": None, "identities": identities, "targets": targets,
                "partition": partition, "binding": binding(facts, partition, diagnosis)}

    @staticmethod
    def _ineligible(facts: dict, reason_code: str, *, partition=None, diagnosis=None,
                    error_type=None, identities=None) -> dict:
        return {"facts": facts, "eligible": False, "diagnosis": diagnosis,
                "reason_code": reason_code, "error_type": error_type, "identities": identities,
                "targets": [], "partition": partition, "binding": None}

    # ----- admission ----------------------------------------------------------------------------
    def admit(self, audit_id: str) -> dict:
        """Admit at most ONE corrective successor for this audit, or say why none was.

        The diagnosis and its evidence are read first, outside any transaction; the commit re-reads
        the activation, the task, the partition and the lineage and refuses unless the exact state
        it was diagnosed against is unchanged. Nothing is published here: the existing
        correlation-scoped outbox relay publishes this assignment's own record, exactly as it does
        for an ordinary one.
        """
        with self.store.transaction() as tx:
            activation = tx.get(BUCKET_ACTIVATION, audit_id) or {}
        if activation.get("status") != ENABLED:
            return self._not_admitted(NOT_ENABLED)
        scope = set(activation.get("task_ids") or [])
        candidates = [facts for facts in self._candidates(audit_id) if facts["task_id"] in scope]
        if not candidates:
            return self._not_admitted(OUT_OF_SCOPE if scope else NO_CANDIDATE)
        last = self._not_admitted(NO_CANDIDATE)
        for facts in candidates:
            diagnosed = self._diagnose(facts)
            if not diagnosed["eligible"]:
                last = self._not_admitted(diagnosed["reason_code"], facts=facts,
                                          diagnosis=diagnosed.get("diagnosis"),
                                          error_type=diagnosed.get("error_type"))
                continue
            admitted = self._commit(audit_id, diagnosed)
            if admitted["admitted"]:
                return admitted
            last = admitted
        return last

    def _commit(self, audit_id: str, diagnosed: dict) -> dict:
        facts, diagnosis = diagnosed["facts"], diagnosed["diagnosis"]
        family = family_identity(facts, diagnosis)
        correction_id = correction_identity(family)
        key = schedule_key(correction_id)
        now = self.clock()
        with self.store.transaction() as tx:
            activation = tx.get(BUCKET_ACTIVATION, audit_id) or {}
            if activation.get("status") != ENABLED or facts["task_id"] not in set(
                    activation.get("task_ids") or []):
                # Disabled or rescoped between the diagnosis and this commit: nothing is admitted.
                return self._not_admitted(NOT_ENABLED, facts=facts, diagnosis=diagnosis)
            control = self._control(tx, facts["task_id"])
            if control is not None:
                # The run gate or the execution's own unresolved markers, re-read HERE rather than
                # trusted from the diagnosis: a paused control and an unreconciled termination both
                # stop this admission before a successor is queued at all. The service's own
                # pre-execution gate stays exactly where it is; this does not replace it.
                return self._not_admitted(control, facts=facts, diagnosis=diagnosis)
            existing = tx.get(BUCKET_CORRECTIONS, correction_id)
            if isinstance(existing, dict):
                # The same lineage, from a repeated tick, a restart or a concurrent caller: this is
                # that one successor, never another call.
                reason = FAMILY_CLOSED if existing.get("state") in TERMINAL_STATES else LINEAGE_EXISTS
                return self._not_admitted(reason, facts=facts, diagnosis=diagnosis,
                                          correction=diagnosis_view(existing))
            current = rejection_facts(tx.get("tasks", facts["task_id"] or ""))
            partition = tx.get("research_partitions", facts["partition_id"] or "")
            if current is None or binding(current, partition, diagnosis) != diagnosed["binding"]:
                return self._not_admitted(BINDING_CHANGED, facts=facts, diagnosis=diagnosis)
            if tx.get("schedule", key) is not None:
                return self._not_admitted(LINEAGE_EXISTS, facts=facts, diagnosis=diagnosis)
            context = repair_context(correction_id=correction_id, facts=facts, diagnosis=diagnosis,
                                     identities=diagnosed["identities"])
            message = envelope("task.assign", SENDER, AGENT, ACTION, repair_details(facts, context), key)
            self.org.authorize(message)
            successor = {"task_id": message["message_id"], "correlation_id": key,
                         "schedule_key": key, "published": None, "assigned_at": now}
            row = correction_row(correction_id=correction_id, family=family, facts=facts,
                                 diagnosis=diagnosis, identities=diagnosed["identities"],
                                 targets=diagnosed["targets"], bound=diagnosed["binding"],
                                 successor=successor, now=now)
            tx.put("outbox", message["message_id"], {"message": message, "sent": False})
            tx.put("schedule", key, {"id": key, "task_id": message["message_id"],
                                     "partition_id": facts["partition_id"], "at": now,
                                     "repair": correction_id})
            tx.put(BUCKET_CORRECTIONS, correction_id, row)
            # The required durable audit record of this admission, in the same transaction.
            tx.put("events", correction_id, {
                "id": correction_id, "type": "audit.repair_admitted", "audit_id": audit_id,
                "correction_id": correction_id, "source_task_id": facts["task_id"],
                "successor_task_id": message["message_id"], "diagnosis": diagnosis, "at": now})
        return {"admitted": True, "reason_code": None, "diagnosis": diagnosis,
                "correction_id": correction_id, "source_task_id": facts["task_id"],
                "successor_task_id": successor["task_id"], "partition_id": facts["partition_id"],
                "partition_generation": facts["partition_generation"], "error_type": None,
                "correction": diagnosis_view(row)}

    @staticmethod
    def _control(tx, source_task_id) -> str | None:
        """Why the durable controls refuse this admission right now, or None.

        Two existing requirements, read inside the admitting transaction and never written here: the
        research activation must still be `active`, and the execution being corrected must carry no
        unconfirmed or pending-reconciliation termination marker, whose only owner is the operator.
        A read that cannot be completed is `control_unavailable`: unknown is not permission.
        """
        try:
            control = tx.get(BUCKET_CONTROL, CONTROL_KEY)
            markers = [row for row in tx.scan(BUCKET_TERMINATIONS) if isinstance(row, dict)]
        except Exception:
            return CONTROL_UNAVAILABLE
        if not isinstance(control, dict) or control.get("status") != "active":
            return RESEARCH_INACTIVE
        for row in markers:
            if (row.get("status") in UNRESOLVED_MARKERS
                    and row.get("bucket", "tasks") == "tasks"
                    and row.get("task_id") == source_task_id):
                return UNRESOLVED_TERMINATION
        return None

    @staticmethod
    def _not_admitted(reason_code: str, *, facts=None, diagnosis=None, error_type=None,
                      correction=None) -> dict:
        facts = facts or {}
        return {"admitted": False, "reason_code": reason_code, "diagnosis": diagnosis,
                "correction_id": (correction or {}).get("id"),
                "source_task_id": facts.get("task_id"),
                "successor_task_id": (correction or {}).get("successor_task_id"),
                "partition_id": facts.get("partition_id"),
                "partition_generation": facts.get("partition_generation"),
                "error_type": error_type, "correction": correction}

    # ----- settlement ---------------------------------------------------------------------------
    def settle(self, audit_id: str) -> dict:
        """Reconcile every open lineage of this audit from terminal task evidence. Idempotent.

        A restart, a lost commit response and a repeated tick all recompute the same state from the
        durable records; a terminal lineage is never reopened, rewritten or retried, and a live
        successor simply stays `admitted`. A lineage that reaches `research_required` records its
        terminal settlement, ONE deterministic informational lead notice and that notice's own outbox
        record in the SAME transaction, so the second strike can never be stored without the message
        that reports it. `notices` carries each research_required notice of this audit with the
        publication state read from its OWN outbox record, so a caller can publish the pending ones;
        publication is never assumed, and a repeated settlement returns the same notice identity.
        """
        settled, changed, notices = [], [], []
        with self.store.transaction() as tx:
            rows = [row for row in tx.scan(BUCKET_CORRECTIONS)
                    if isinstance(row, dict) and row.get("audit_id") == audit_id]
            # Immutable evidence history, not the latest coverage rows: an ordinary later checkpoint
            # overwrites `research_subsystems` by (audit, item), which would let unrelated work stand
            # in for - or erase - what THIS successor actually persisted.
            history = [row for row in tx.scan("research_evidence_history")
                       if isinstance(row, dict) and row.get("audit_id") == audit_id]
            now = self.clock()
            for row in sorted(rows, key=lambda r: str(r.get("id"))):
                if row.get("state") in TERMINAL_STATES:
                    settled.append(row.get("settlement") or {"correction_id": row.get("id"),
                                                             "state": row.get("state")})
                    self._pending_notice(tx, row, notices)
                    continue
                task = tx.get("tasks", (row.get("successor") or {}).get("task_id") or "")
                partition = tx.get("research_partitions", row.get("partition_id") or "")
                result = settlement(row, task, history, partition)
                settled.append(result)
                if result["state"] == row.get("state") and result["reason_code"] == row.get("reason_code"):
                    continue
                row.update(state=result["state"], reason_code=result["reason_code"],
                           settlement=result, updated_at=now)
                if result["state"] == RESEARCH_REQUIRED:
                    row["notice"] = self._notify(tx, row, result, task, now)
                # Publication is read from the assignment's OWN outbox record, never inferred from
                # the existence of a task row: `null` stays null until that record says `sent`.
                record = tx.get("outbox", (row.get("successor") or {}).get("task_id") or "")
                if isinstance(record, dict):
                    row["successor"] = {**row["successor"], "published": bool(record.get("sent"))}
                tx.put(BUCKET_CORRECTIONS, row["id"], row)
                changed.append(result)
                self._pending_notice(tx, row, notices)
        return {"audit_id": audit_id, "settled": settled, "changed": changed, "notices": notices}

    def _notify(self, tx, row: dict, result: dict, task, now: str) -> dict:
        """ONE proof-bound informational lead notice for this second refused draft.

        The existing `execution_notices` builder and the existing direct reporting edge do the work:
        the notice is bound to the lineage proof (its digest is the transition reference), retains
        both immutable execution references, and is idempotent by identity, so a repeated settlement,
        a restart and a lost commit response all return the same notice and the same outbox record.
        Receiving it performs no research and authorizes no third call. A source the builder cannot
        turn into a notice is quarantined by that owner, and this lineage says so instead of claiming
        a delivery it does not have.
        """
        proof = notice_proof(row, result)
        notice = execution_notice(tx, self.org, task, "tasks", NOTICE_REASON, now,
                                  digest(proof), proof=proof,
                                  evidence_refs=notice_evidence(result))
        if not isinstance(notice, dict) or not isinstance(notice.get("transition"), dict):
            return {"id": None, "correlation_id": None, "published": None,
                    "error_id": (notice or {}).get("id")}
        return {"id": notice["id"], "correlation_id": notice["message"]["correlation_id"],
                "published": False, "error_id": None, "at": now}

    @staticmethod
    def _pending_notice(tx, row: dict, notices: list) -> None:
        """Report this lineage's notice and whether its own outbox record is still unsent.

        The durable flag is refreshed from that record, so a pending publication survives a restart
        and a later tick can retry it without building a second notice.
        """
        notice = row.get("notice")
        if not isinstance(notice, dict) or not notice.get("id"):
            return
        record = tx.get("outbox", notice["id"])
        published = bool(record.get("sent")) if isinstance(record, dict) else None
        if published != notice.get("published"):
            row["notice"] = {**notice, "published": published}
            tx.put(BUCKET_CORRECTIONS, row["id"], row)
        notices.append({"correction_id": row.get("id"), "notice_id": notice["id"],
                        "correlation_id": notice.get("correlation_id"), "published": published})

    # ----- one service tick ---------------------------------------------------------------------
    def tick(self, audit_id: str) -> dict:
        """Settle first, then admit: a tick never admits on a lineage it has not reconciled."""
        settled = self.settle(audit_id)
        admitted = self.admit(audit_id)
        return {"audit_id": audit_id, "settled": settled["changed"],
                "notices": settled["notices"], "admission": admitted}

    # ----- read-only ----------------------------------------------------------------------------
    def status(self, audit_id: str) -> dict:
        with self.store.transaction() as tx:
            activation = tx.get(BUCKET_ACTIVATION, audit_id)
            corrections = [row for row in tx.scan(BUCKET_CORRECTIONS)
                           if isinstance(row, dict) and row.get("audit_id") == audit_id]
        return {"audit_id": audit_id, **status_view(activation, corrections)}


def repair_view(activation, corrections) -> dict:
    """The bounded projection a reader that already holds the rows can use (the audit service's own
    `status` reads both buckets in its existing transaction)."""
    return status_view(activation, corrections)


__all__ = ["ACTION", "AGENT", "BUCKET_ACTIVATION", "BUCKET_CORRECTIONS", "DISABLED", "ENABLED",
           "SENDER", "AuditRepair", "repair_view"]
