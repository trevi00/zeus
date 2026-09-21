"""Typed diagnosis, ONE bounded corrective lineage and truthful settlement for a rejected source
audit analysis (INV-AUDIT-REPAIR-001).

Pure policy over dictionaries: no store, clock, artifact store, scheduler, transport, provider or
model, and nothing here writes a record. It answers three questions and nothing else. What exactly
was refused (a typed diagnosis bound to the stored rejection marker, the immutable artifact and the
structured content of the draft, never to model prose or an arbitrary exception substring)? Which
ONE successor may exist for that rejection family (a deterministic identity, so a repeated tick, a
restart and a concurrent caller all name the same lineage)? What did that successor actually
achieve (a checkpoint is resumed partial work; only a corrected non-null subsystem record with a
justified test disposition is `repaired`, and a second refused draft is `research_required` with no
third attempt)?

The one automatically eligible family in this version is the demonstrated missing structured test
disposition: `SubsystemAnalysis.validate` refusing `Missing subsystem trace: tests` inside the pure
content decode. It is matched by the DIGEST of that validator message against the digest the
execution itself recorded, so a stored string never becomes a Zeus code and a rewording of any
other validator message cannot silently enter this family. Every other refusal - a relationship or
evidence-claim rejection from `ResearchAudits.checkpoint`, an execution, ownership, lease, store,
artifact or transport failure, an unclassified historical row - is not eligible and is reported as
the fixed reason it is.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest
from codex_harness.domain.observation import (
    ANALYSIS_CHECKPOINTED,
    ANALYSIS_CONTENT_REJECTED,
    ANALYSIS_REJECTED,
    analysis_facts,
)

SCHEMA = "urn:zeus:audit-repair:1"
VERSION = 1
ARTIFACT_REFERENCE = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
# The bounded recovery context: at most this many refused identities travel with the successor, and
# the honest total travels beside them. A draft is never copied into an assignment or a log.
MAX_IDENTITIES = 32
# One original and at most one successor. A second refused draft is the end of this family.
MAX_ATTEMPTS = 2

# ----- the diagnosis vocabulary -------------------------------------------------------------------
MISSING_TEST_DISPOSITION = "missing_test_disposition"
DIAGNOSES = (MISSING_TEST_DISPOSITION,)
# The exact validator messages each diagnosis is bound to. The text is never read from a record,
# logged or shown: only its digest is compared with the digest the execution recorded.
VALIDATOR_MESSAGES = {MISSING_TEST_DISPOSITION: "Missing subsystem trace: tests"}
DIAGNOSIS_FIELD = {MISSING_TEST_DISPOSITION: "tests"}
DIAGNOSIS_BY_DIGEST = {digest(text): code for code, text in VALIDATOR_MESSAGES.items()}
# The pure content decoder's own exception type. `AuditDraftRejected` (the checkpoint half of the
# rejection boundary) is deliberately NOT here: its claims are not this family.
DECODER_ERROR_TYPES = ("ContractError",)

# The owner-written pre-submission checklist for a correction. Versioned source text, never model
# output and never a validation loop: the existing validators stay the authority.
CHECKLISTS = {MISSING_TEST_DISPOSITION: (
    "Every returned subsystem record carries a non-empty tests or tests_not_run; both empty is "
    "refused as it was before.",
    "A test in tests is the exact JSON argv string of a successful runner receipt supplied to THIS "
    "execution; source-list and source-read are inspection and never test execution.",
    "An unexecuted test belongs in tests_not_run verbatim with reason and follow_up. A missing "
    "prerequisite is an explicit not-run fact, never a claimed or fabricated pass.",
    "Return null for an assigned identity you did not analyze; a null identity stays remaining work "
    "and is not a failure.",
)}

# ----- why nothing is admitted ---------------------------------------------------------------------
NOT_ENABLED = "not_enabled"
OUT_OF_SCOPE = "out_of_scope"
UNKNOWN_TASK = "unknown_task"
UNKNOWN_PARTITION = "unknown_partition"
FOREIGN_PARTITION = "foreign_partition"
TASK_NOT_SETTLED = "task_not_settled"
NOT_REJECTED = "not_rejected"
UNSUPPORTED_REASON = "unsupported_reason"
UNSUPPORTED_DIAGNOSIS = "unsupported_diagnosis"
GENERATION_CHANGED = "generation_changed"
SCOPE_CHANGED = "scope_changed"
EVIDENCE_MISSING = "evidence_missing"
EVIDENCE_UNREADABLE = "evidence_unreadable"
EVIDENCE_MISMATCH = "evidence_mismatch"
REPLAY_UNAVAILABLE = "replay_unavailable"
REPLAY_MISMATCH = "replay_mismatch"
NO_CORRECTABLE_IDENTITY = "no_correctable_identity"
LINEAGE_EXISTS = "lineage_exists"
FAMILY_CLOSED = "family_closed"
BINDING_CHANGED = "binding_changed"
PREDECESSOR_UNPUBLISHED = "predecessor_unpublished"
NO_CANDIDATE = "no_candidate"
# The commit-time control requirements: the same durable research activation the host service reads
# before every admission, and the unresolved termination markers of the execution being corrected.
# An unreadable control row is `control_unavailable`, which is unknown and therefore never permission.
RESEARCH_INACTIVE = "research_inactive"
UNRESOLVED_TERMINATION = "unresolved_termination"
CONTROL_UNAVAILABLE = "control_unavailable"
NOT_ADMITTED_REASONS = (NOT_ENABLED, OUT_OF_SCOPE, UNKNOWN_TASK, UNKNOWN_PARTITION, FOREIGN_PARTITION,
                        TASK_NOT_SETTLED, NOT_REJECTED, UNSUPPORTED_REASON, UNSUPPORTED_DIAGNOSIS,
                        GENERATION_CHANGED, SCOPE_CHANGED, EVIDENCE_MISSING, EVIDENCE_UNREADABLE,
                        EVIDENCE_MISMATCH, REPLAY_UNAVAILABLE, REPLAY_MISMATCH,
                        NO_CORRECTABLE_IDENTITY, LINEAGE_EXISTS, FAMILY_CLOSED, BINDING_CHANGED,
                        PREDECESSOR_UNPUBLISHED, NO_CANDIDATE, RESEARCH_INACTIVE,
                        UNRESOLVED_TERMINATION, CONTROL_UNAVAILABLE)

# ----- what a lineage is --------------------------------------------------------------------------
ADMITTED = "admitted"
REPAIRED = "repaired"
DEFERRED = "deferred"
RESEARCH_REQUIRED = "research_required"
RECONCILIATION_REQUIRED = "reconciliation_required"
STATES = (ADMITTED, REPAIRED, DEFERRED, RESEARCH_REQUIRED, RECONCILIATION_REQUIRED)
# A state nothing may be admitted after: the family is closed, by success or by its second strike.
TERMINAL_STATES = (REPAIRED, DEFERRED, RESEARCH_REQUIRED, RECONCILIATION_REQUIRED)
# Why a settlement reads the way it does. Fixed codes only.
SUCCESSOR_NOT_SUBMITTED = "successor_not_submitted"
SUCCESSOR_PENDING = "successor_pending"
SUCCESSOR_UNBOUND = "successor_unbound"
CORRECTED = "corrected"
PARTIALLY_CORRECTED = "partially_corrected"
NO_CORRECTED_SUBSYSTEM = "no_corrected_subsystem"
CONTENT_REJECTED_AGAIN = "content_rejected_again"
UNCLASSIFIED_RESULT = "unclassified_result"
EXECUTION_UNRESOLVED = "execution_unresolved"
SETTLEMENT_REASONS = (SUCCESSOR_NOT_SUBMITTED, SUCCESSOR_PENDING, SUCCESSOR_UNBOUND, CORRECTED,
                      PARTIALLY_CORRECTED, NO_CORRECTED_SUBSYSTEM, CONTENT_REJECTED_AGAIN,
                      UNCLASSIFIED_RESULT, EXECUTION_UNRESOLVED)
# The live task statuses a successor may legitimately still hold.
LIVE_STATUSES = ("queued", "running", "retry")


class RepairRefused(ContractError):
    """A refusal that names its fixed code; a caller prints the code and the type, never a value."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def identifier(value):
    """An opaque identifier, or None. A foreign or oversized value is dropped, never rewritten."""
    return value if type(value) is str and IDENTIFIER.fullmatch(value) else None


def rejection_facts(task) -> dict | None:
    """The bound facts of ONE settled execution whose CONTENT was refused, or None.

    Everything here comes from the execution's own durable result and its own task row: the outcome
    and reason are the existing fixed codes, the reference must be an immutable artifact handle, and
    the error type and digest are what the execution recorded about the refusal. A task that did not
    succeed, a result with no marker and a marker of any other outcome return None: this reads
    history, it never reclassifies it.
    """
    if not isinstance(task, dict) or task.get("status") != "succeeded":
        return None
    facts = analysis_facts(task.get("result"))
    if facts["analysis_outcome"] != ANALYSIS_REJECTED:
        return None
    analysis = (task.get("result") or {}).get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    details = ((task.get("message") or {}).get("what") or {}).get("details") or {}
    error_digest = analysis.get("error_digest")
    return {"task_id": identifier(task.get("id")),
            "task_generation": task.get("generation") if type(task.get("generation")) is int else None,
            "attempt": task.get("attempt") if type(task.get("attempt")) is int else None,
            "audit_id": identifier(details.get("audit_id")),
            "partition_id": identifier(details.get("partition_id")),
            "partition_generation": facts["analysis_generation"],
            "execution_ref": facts["analysis_ref"],
            "reason_code": facts["analysis_reason"],
            "error_type": identifier(analysis.get("error_type")),
            "error_digest": error_digest if type(error_digest) is str
            and re.fullmatch(r"[0-9a-f]{64}", error_digest) else None}


def diagnosis_for(facts) -> str | None:
    """The typed diagnosis of one rejection, or None when this version does not own it.

    Structured content plus the validator's own digest: the reason family must be the declared
    content rejection, the error type must be the pure decoder's own type, and the recorded digest
    must equal the digest of a validator message this diagnosis is bound to.
    """
    if not isinstance(facts, dict) or facts.get("reason_code") != ANALYSIS_CONTENT_REJECTED:
        return None
    if facts.get("error_type") not in DECODER_ERROR_TYPES:
        return None
    return DIAGNOSIS_BY_DIGEST.get(facts.get("error_digest") or "")


def target_identities(answer, assigned) -> list:
    """EVERY assigned subsystem identity whose returned record carries NO test disposition.

    Structured inspection of the retained draft, bound to the trusted assigned scope: a body that is
    not an object, an identity that was not assigned and every other field are ignored, and a null
    identity is simply unanalyzed work, not a defect. This complete list is the diagnosed TARGET set
    and therefore the internal denominator of settlement; only the prompt-facing projection below is
    bounded, so a truncated recovery context can never shrink what a repair must correct.
    """
    results = answer.get("subsystems") if isinstance(answer, dict) else None
    names = []
    for name in assigned if isinstance(assigned, list) else []:
        body = results.get(name) if isinstance(results, dict) else None
        if isinstance(body, dict) and not body.get("tests") and not body.get("tests_not_run"):
            names.append(name)
    return sorted(set(names))


def unjustified_subsystems(answer, assigned) -> dict:
    """The BOUNDED prompt-facing projection of the diagnosed targets, with the honest total beside
    it. No value from the draft other than an assigned identity is copied."""
    names = target_identities(answer, assigned)
    return {"identities": names[:MAX_IDENTITIES], "total": len(names),
            "truncated": len(names) > MAX_IDENTITIES}


def scope_digest(partition) -> str:
    """The immutable assigned scope of one partition: a change makes an admission invalid."""
    return digest({key: (partition or {}).get(key) for key in
                   ("audit_id", "partition_id", "generation", "paths", "subsystems")})


def binding(facts, partition, diagnosis: str) -> str:
    """The exact state one admission was diagnosed against; re-read and compared before it commits."""
    return digest({"schema": SCHEMA, "version": VERSION, "diagnosis": diagnosis,
                   "task": facts.get("task_id"), "task_generation": facts.get("task_generation"),
                   "attempt": facts.get("attempt"), "execution_ref": facts.get("execution_ref"),
                   "error_digest": facts.get("error_digest"), "scope": scope_digest(partition)})


def family_identity(facts, diagnosis: str) -> str:
    """ONE lineage per (original task, partition generation, rejection family).

    A repeated tick, a restarted service and a concurrent admission caller all compute this same
    identity from the durable records, so they find the existing lineage instead of creating a
    second one. The original task's own execution generation is part of it: an operator recovery
    that advances the fence is a different execution, not a second successor of this one.
    """
    return digest({"schema": SCHEMA, "version": VERSION, "audit": facts.get("audit_id"),
                   "partition": facts.get("partition_id"),
                   "partition_generation": facts.get("partition_generation"),
                   "task": facts.get("task_id"), "task_generation": facts.get("task_generation"),
                   "diagnosis": diagnosis})


def correction_identity(family: str) -> str:
    """The bounded durable id of one lineage; the full family digest stays on the row."""
    return "repair-" + family[:24]


def schedule_key(correction_id: str) -> str:
    """The successor's own deterministic schedule key: never the original partition's key, which
    keeps holding the rejected draft's generation exactly as it is."""
    return "repair:" + correction_id


def repair_context(*, correction_id: str, facts: dict, diagnosis: str, identities: dict) -> dict:
    """The bounded recovery context that travels with the successor assignment.

    Identifiers, fixed codes, counts and owner-written checklist text only: the refused draft, the
    validator's message, the provider's stream and every exception text stay in the immutable
    artifact this context merely names.
    """
    return {"schema": SCHEMA, "version": VERSION, "correction_id": correction_id,
            "source_task_id": facts["task_id"], "source_execution_ref": facts["execution_ref"],
            "source_partition_generation": facts["partition_generation"],
            "diagnosis": diagnosis, "field": DIAGNOSIS_FIELD[diagnosis], "attempt": MAX_ATTEMPTS,
            "subsystems": list(identities["identities"]), "subsystems_total": identities["total"],
            "subsystems_truncated": identities["truncated"],
            "checklist": list(CHECKLISTS[diagnosis]),
            "authority": "one bounded correction of a refused draft; the existing validators remain "
                         "the authority and a justified not-run fact is an accepted incomplete result"}


def repair_details(facts: dict, context: dict) -> dict:
    """The successor's six-W details: the ORDINARY `audit_partition` assignment of the SAME trusted
    partition generation, plus the bounded repair context. Nothing about the assignment's scope,
    action, agent or generation differs from an ordinary continuation."""
    return {"audit_id": facts["audit_id"], "partition_id": facts["partition_id"],
            "generation": facts["partition_generation"], "repair": context}


def repair_evidence(details) -> dict | None:
    """The bounded repair context of an assignment, allow-listed, or None.

    An executing worker reads its assignment's details as DATA: only the declared keys with their
    declared types survive, identities are bounded, the checklist is the owner's own versioned text
    (never a value carried in the message), and anything else a producer put there is dropped. A
    context that does not name this schema, a known diagnosis and an immutable artifact is no
    context at all, so no assignment can smuggle instructions into an analysis prompt this way.
    """
    row = (details or {}).get("repair") if isinstance(details, dict) else None
    if not isinstance(row, dict) or row.get("schema") != SCHEMA or row.get("version") != VERSION:
        return None
    diagnosis = row.get("diagnosis")
    ref = row.get("source_execution_ref")
    if diagnosis not in DIAGNOSES or type(ref) is not str or not ARTIFACT_REFERENCE.fullmatch(ref):
        return None
    names = [name for name in (row.get("subsystems") or []) if identifier(name)][:MAX_IDENTITIES]
    total = row.get("subsystems_total")
    return {"schema": SCHEMA, "version": VERSION,
            "correction_id": identifier(row.get("correction_id")),
            "source_task_id": identifier(row.get("source_task_id")),
            "source_execution_ref": ref, "diagnosis": diagnosis, "field": DIAGNOSIS_FIELD[diagnosis],
            "attempt": row.get("attempt") if type(row.get("attempt")) is int else MAX_ATTEMPTS,
            "subsystems": names, "subsystems_total": total if type(total) is int else len(names),
            "subsystems_truncated": bool(row.get("subsystems_truncated")),
            "checklist": list(CHECKLISTS[diagnosis])}


def correction_row(*, correction_id: str, family: str, facts: dict, diagnosis: str, identities: dict,
                   targets, bound: str, successor: dict, now: str) -> dict:
    """The immutable lineage record: original execution, diagnosis, successor and state.

    `targets` is the COMPLETE diagnosed identity set this correction must repair; `subsystems` is
    only the bounded list the assignment carries. Settlement counts against `targets`, so a bounded
    recovery context never shrinks the denominator. The original task, its result, its artifact and
    the partition generation it holds are never written by this owner; they are referenced here.
    """
    return {"schema": SCHEMA, "version": VERSION, "id": correction_id, "family": family,
            "audit_id": facts["audit_id"], "partition_id": facts["partition_id"],
            "partition_generation": facts["partition_generation"],
            "source_task_id": facts["task_id"], "source_task_generation": facts["task_generation"],
            "source_attempt": facts["attempt"], "source_execution_ref": facts["execution_ref"],
            "source_error_type": facts["error_type"], "source_error_digest": facts["error_digest"],
            "diagnosis": diagnosis, "field": DIAGNOSIS_FIELD[diagnosis],
            "subsystems": list(identities["identities"]), "subsystems_total": identities["total"],
            "targets": list(targets), "binding": bound, "successor": dict(successor),
            "attempts": MAX_ATTEMPTS, "state": ADMITTED, "reason_code": SUCCESSOR_NOT_SUBMITTED,
            "settlement": None, "notice": None, "created_at": now, "updated_at": now}


def diagnosed_targets(correction) -> list:
    """The complete diagnosed target set of one lineage. A row written before targets were retained
    falls back to its bounded list rather than silently counting zero."""
    row = correction if isinstance(correction, dict) else {}
    targets = row.get("targets")
    if not isinstance(targets, list):
        targets = row.get("subsystems")
    return sorted({name for name in (targets or []) if identifier(name)})


def corrected_targets(history_rows, successor_task_id, targets) -> list:
    """Which of the DIAGNOSED targets THIS successor persisted with a justified test disposition.

    The rows are the existing `research_evidence_history` records, which only
    `ResearchAudits.checkpoint` writes and which `SubsystemAnalysis.validate` already refused unless
    tests or tests_not_run was non-empty. History is used rather than the latest
    `research_subsystems` coverage rows because an ordinary later checkpoint overwrites those by
    (audit, item), which would let unrelated work stand in for, or erase, this successor's own
    record. Every row must name this successor's execution AND a diagnosed target identity: a
    subsystem the successor happened to analyse outside the diagnosed set is valid work and is not
    counted here, and a path disposition (no `name`) is not a subsystem record at all.
    """
    wanted, corrected = set(targets or []), set()
    for row in history_rows if isinstance(history_rows, list) else []:
        if not isinstance(row, dict) or row.get("task_id") != successor_task_id:
            continue
        record = row.get("record") if isinstance(row.get("record"), dict) else {}
        name = record.get("name")
        if name in wanted and (record.get("tests") or record.get("tests_not_run")):
            corrected.add(name)
    return sorted(corrected)


def settlement(correction: dict, task, history_rows, partition) -> dict:
    """What the successor ACHIEVED against its DIAGNOSED targets. Idempotent and truthful.

    A checkpoint is resumed partial work, never subsystem acceptance, and work outside the diagnosed
    set is never the repair that was asked for: `repaired` requires every diagnosed target to carry a
    corrected record with a justified test disposition, a corrected subset is `deferred`
    (`partially_corrected`) with its target, corrected and remaining counts exposed, and no corrected
    target at all is `deferred` (`no_corrected_subsystem`). A second refused draft is
    `research_required` - the original and the successor are two distinct attempts and there is no
    third one. An execution that failed, was cancelled or cannot be read is
    `reconciliation_required`, which is not a strike and not another attempt. A live successor is
    still `admitted`, so a repeated call before the successor settles changes nothing.
    """
    successor = correction.get("successor") or {}
    task_id = successor.get("task_id")
    targets = diagnosed_targets(correction)
    if not isinstance(task, dict):
        return _settled(correction, ADMITTED, SUCCESSOR_NOT_SUBMITTED, task_id=task_id,
                        targets=targets)
    bound = ((task.get("message") or {}).get("correlation_id") == successor.get("correlation_id")
             and task.get("id") == task_id)
    if not bound:
        return _settled(correction, RECONCILIATION_REQUIRED, SUCCESSOR_UNBOUND, task_id=task_id,
                        targets=targets)
    status = task.get("status")
    if status in LIVE_STATUSES:
        return _settled(correction, ADMITTED, SUCCESSOR_PENDING, task_id=task_id, targets=targets)
    if status != "succeeded":
        return _settled(correction, RECONCILIATION_REQUIRED, EXECUTION_UNRESOLVED, task_id=task_id,
                        targets=targets)
    facts = analysis_facts(task.get("result"))
    outcome = facts["analysis_outcome"]
    if outcome == ANALYSIS_REJECTED:
        # The second actual rejected execution of this family: recorded once, and this family stops.
        return _settled(correction, RESEARCH_REQUIRED, CONTENT_REJECTED_AGAIN, task_id=task_id,
                        analysis_outcome=outcome, targets=targets,
                        successor_execution_ref=facts["analysis_ref"])
    corrected = corrected_targets(history_rows, task_id, targets)
    generation = (partition or {}).get("generation") if isinstance(partition, dict) else None
    generation = generation if type(generation) is int else None
    if outcome != ANALYSIS_CHECKPOINTED:
        return _settled(correction, DEFERRED, UNCLASSIFIED_RESULT, task_id=task_id,
                        analysis_outcome=outcome, corrected=corrected, targets=targets,
                        checkpoint_generation=generation,
                        successor_execution_ref=facts["analysis_ref"])
    whole = bool(targets) and len(corrected) == len(targets)
    state = REPAIRED if whole else DEFERRED
    reason = (CORRECTED if whole else PARTIALLY_CORRECTED if corrected else NO_CORRECTED_SUBSYSTEM)
    return _settled(correction, state, reason, task_id=task_id, analysis_outcome=outcome,
                    corrected=corrected, targets=targets, checkpoint_generation=generation,
                    successor_execution_ref=facts["analysis_ref"])


def _settled(correction: dict, state: str, reason_code: str, *, task_id=None, analysis_outcome=None,
             corrected=(), targets=(), checkpoint_generation=None,
             successor_execution_ref=None) -> dict:
    corrected, targets = list(corrected), list(targets)
    return {"correction_id": correction.get("id"), "audit_id": correction.get("audit_id"),
            "source_task_id": correction.get("source_task_id"), "successor_task_id": task_id,
            "source_execution_ref": correction.get("source_execution_ref"),
            "successor_execution_ref": successor_execution_ref,
            "diagnosis": correction.get("diagnosis"), "state": state, "reason_code": reason_code,
            "analysis_outcome": analysis_outcome, "target_subsystems": len(targets),
            "corrected_subsystems": len(corrected),
            "remaining_targets": len(targets) - len(corrected),
            "checkpoint_generation": checkpoint_generation,
            "attempts": int(correction.get("attempts") or MAX_ATTEMPTS)}


def notice_proof(correction: dict, settled: dict) -> dict:
    """The lineage proof ONE informational lead notice is bound to.

    Its digest becomes the notice's `transition_ref`, so the notice identity is the (successor
    execution, repair transition) pair: a repeated settlement, a restart and a lost commit response
    all rebuild the same identity, and no other transition can borrow it. Identifiers, fixed codes
    and counts only - both immutable artifact references travel as references, never as content.
    """
    return {"schema": SCHEMA, "version": VERSION, "correction_id": correction.get("id"),
            "family": correction.get("family"), "audit_id": correction.get("audit_id"),
            "partition_id": correction.get("partition_id"),
            "partition_generation": correction.get("partition_generation"),
            "diagnosis": correction.get("diagnosis"),
            "source_task_id": settled.get("source_task_id"),
            "source_execution_ref": settled.get("source_execution_ref"),
            "successor_task_id": settled.get("successor_task_id"),
            "successor_execution_ref": settled.get("successor_execution_ref"),
            "state": settled.get("state"), "reason_code": settled.get("reason_code"),
            "attempts": settled.get("attempts"),
            "authority": "informational lead notice; the two attempts of this family are closed and "
                         "no research has run"}


def notice_evidence(settled: dict) -> list:
    """The original and successor execution references the notice retains, in that order."""
    return [ref for ref in (settled.get("source_execution_ref"),
                            settled.get("successor_execution_ref"))
            if type(ref) is str and ARTIFACT_REFERENCE.fullmatch(ref)]


def diagnosis_view(row: dict) -> dict:
    """The bounded read-only projection of ONE diagnosis or lineage: identifiers, fixed codes and
    counts. No draft, validator message, exception text or source text can travel through it."""
    keys = ("id", "audit_id", "partition_id", "partition_generation", "source_task_id",
            "source_task_generation", "source_execution_ref", "diagnosis", "field", "state",
            "reason_code", "attempts", "subsystems_total", "created_at", "updated_at")
    successor = row.get("successor") or {}
    settled = row.get("settlement") or {}
    notice = row.get("notice") or {}
    return {**{key: row.get(key) for key in keys},
            "successor_task_id": successor.get("task_id"),
            "successor_schedule_key": successor.get("schedule_key"),
            "successor_published": successor.get("published"),
            "successor_execution_ref": settled.get("successor_execution_ref"),
            # Execution success, analysis rejection, repair settlement and notice delivery stay four
            # separate facts: a recorded notice is a delivered question, never a repaired subsystem.
            "target_subsystems": settled.get("target_subsystems"),
            "corrected_subsystems": settled.get("corrected_subsystems"),
            "remaining_targets": settled.get("remaining_targets"),
            "checkpoint_generation": settled.get("checkpoint_generation"),
            "analysis_outcome": settled.get("analysis_outcome"),
            "notice_id": notice.get("id"), "notice_published": notice.get("published")}


def status_view(activation, corrections) -> dict:
    """The audit's whole bounded repair projection: the opt-in, the lineages and the fixed counts.

    Attempted, repaired, deferred, research_required and unknown are reported SEPARATELY: a
    checkpoint is not an acceptance, a deferred outcome is not a repair, and `enabled: false` means
    no new admission, never that a recorded lineage disappeared.
    """
    rows = [row for row in (corrections or []) if isinstance(row, dict)]
    counts = {"attempted": len(rows), **{state: 0 for state in STATES}}
    for row in rows:
        state = row.get("state")
        counts[state if state in STATES else RECONCILIATION_REQUIRED] += 1
    control = activation if isinstance(activation, dict) else {}
    return {"schema": SCHEMA, "enabled": control.get("status") == "enabled",
            "scope": sorted(control.get("task_ids") or []), "operator": control.get("operator"),
            "updated_at": control.get("updated_at"), "counts": counts,
            "corrections": [diagnosis_view(row) for row in
                            sorted(rows, key=lambda r: (str(r.get("created_at") or ""), str(r.get("id"))))]}


__all__ = ["ADMITTED", "CHECKLISTS", "CONTROL_UNAVAILABLE", "DEFERRED", "DIAGNOSES",
           "DIAGNOSIS_BY_DIGEST", "DIAGNOSIS_FIELD", "LIVE_STATUSES", "MAX_ATTEMPTS",
           "MAX_IDENTITIES", "MISSING_TEST_DISPOSITION", "NOT_ADMITTED_REASONS",
           "RECONCILIATION_REQUIRED", "REPAIRED", "RESEARCH_INACTIVE", "RESEARCH_REQUIRED",
           "SCHEMA", "SETTLEMENT_REASONS", "STATES", "TERMINAL_STATES", "UNRESOLVED_TERMINATION",
           "VALIDATOR_MESSAGES", "VERSION", "RepairRefused", "binding", "correction_identity",
           "correction_row", "corrected_targets", "diagnosed_targets", "diagnosis_for",
           "diagnosis_view", "family_identity", "identifier", "notice_evidence", "notice_proof",
           "rejection_facts", "repair_context", "repair_details", "repair_evidence", "schedule_key",
           "scope_digest", "settlement", "status_view", "target_identities",
           "unjustified_subsystems"]
