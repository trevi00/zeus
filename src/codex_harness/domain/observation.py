"""Observation events: one contract for general, development and operations logs (INV-OBSERVATION-001).

An observation records that something happened and what evidence proves it. It is not a six-W
business message: it has no who/what/how sections, cannot be routed as an assignment, and grants
no workflow authority. Every record names the execution it belongs to (or says explicitly that it
is a system event with no task), keeps the event's own occurrence time apart from the moment it
was collected, orders itself by (process_run_id, sequence) rather than by wall clock, and carries
only the attributes its event type allows, redacted before any durable or public surface sees
them. A provider exit code or a transport acknowledgement never becomes a success outcome here.
"""
from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from codex_harness.domain.model import ContractError, canonical, digest, require

SCHEMA_VERSION = "1.0"
CATEGORIES = ("general", "development", "operations")
SEVERITIES = ("debug", "info", "warning", "error", "critical")
OUTCOMES = ("started", "succeeded", "failed", "aborted", "blocked", "unknown", "observed")
EXECUTION_KINDS = ("execution", "system")
BUCKETS = ("tasks", "decisions_pending")
MAX_STRING_CHARS = 1024
MAX_ATTRIBUTES_BYTES = 4096
MAX_EVIDENCE_REFS = 32
REASON_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
IDENTIFIER = re.compile(r"^[0-9a-f]{32}$")
# Correlation, causation and evidence identifiers are opaque handles (uuids, "kind:uuid", sha256
# references, task ids). They are refused, never rewritten, when they do not look like one: a
# redacted identifier would silently merge unrelated executions, and free text has no place here.
REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,199}$")

# Attribute allow-lists per event type. A key that is not listed is refused; a value is a JSON
# scalar of the declared type. Prompts, environment variables, credentials, private keys and
# model reasoning have no place here by construction, and redaction runs on what remains.
_S, _I, _B, _F, _N, _NI = "string", "integer", "boolean", "number", "nullable_string", "nullable_integer"
REGISTRY = {
    "general.process_started": {"agent": _N, "autonomous": _B, "platform": _S, "python": _S, "mode": _S},
    "general.process_idle_exit": {"agent": _N, "idle_seconds": _I},
    "general.message_received": {"stream_entry_id": _S, "message_id": _S, "message_type": _S,
                                 "sender": _S, "recipient": _S},
    "general.message_accepted": {"message_id": _S, "message_type": _S, "result_kind": _S},
    "general.message_acknowledged": {"stream_entry_id": _S, "message_id": _S},
    "general.message_rejected": {"stream_entry_id": _S, "error_type": _S, "dead_letter": _B},
    "general.message_published": {"outbox_id": _S, "attempt_id": _S, "attempt_number": _I,
                                  "stream_entry_id": _S, "message_type": _S, "recipient": _S},
    "general.message_delivery_retry": {"outbox_id": _S, "attempt_id": _S, "attempt_number": _I, "error_type": _S},
    "general.message_delivery_error": {"outbox_id": _S, "attempt_id": _S, "attempt_number": _I, "error_type": _S},
    "general.message_quarantined": {"outbox_id": _S, "reason": _S, "quarantine_id": _S},
    "development.invocation_reserved": {"reservation_id": _S, "stage": _N, "transport": _S,
                                        "requested_model": _N, "budget_seconds": _F, "workload": _S},
    "development.provider_started": {"reservation_id": _N, "transport": _S, "requested_model": _N,
                                     "read_only": _B, "timeout_seconds": _F, "context_ref": _S},
    "development.provider_finished": {"reservation_id": _N, "invocation_outcome": _S, "elapsed_seconds": _F,
                                      "event_count": _I, "stream_hash": _S, "confirmed_model": _N,
                                      "usage_source": _S, "total_tokens": _NI, "thread_id": _N},
    "development.provider_failed": {"reservation_id": _N, "error_type": _S, "elapsed_seconds": _F,
                                    "provider_entered": _B},
    # operating-portfolio-001: what one attempt's output was judged to be, recorded once its durable
    # receipt exists. Fixed codes only (see the vocabularies below): a foreign provider string is
    # `unknown` and an absent one is `none`, never a missing field inferred from a subtype. The
    # prompt, the answer, schema property names, commands and exception text have no place here.
    "development.output_evaluated": {"reservation_id": _N, "invocation_outcome": _S, "output_reason": _S,
                                     "provider_cause": _S, "terminal_subtype": _S, "failure_owner": _S,
                                     "json_check": _S, "schema_check": _S, "execution_failure": _B},
    "development.invocation_settled": {"reservation_id": _S, "invocation_outcome": _S, "usage_source": _S,
                                       "total_tokens": _NI, "within_budget": _B},
    "development.invocation_abandoned": {"reservation_id": _S, "reason": _S},
    "development.progress_recorded": {"progress_sequence": _NI, "method": _S, "item_type": _N,
                                      "item_status": _N, "receipt_ref": _S, "malformed": _B, "defect": _N},
    "development.checkpoint_recorded": {"session_generation": _I, "session_id": _S, "handoff_reason": _S,
                                        "evidence_ref": _S, "context_ref": _S},
    # operating-portfolio-001: the evidence inspection boundary. `started` says how many claims went
    # in; `finished` says what came out, including no_claims, incomplete and a failed inspection,
    # with the denominator as typed counts. A failed inspection carries its exception's type and a
    # digest of its message, never the message (INV-EVIDENCE-001 keeps the verdict and gate as they are).
    "development.evidence_inspection_started": {"claims": _I},
    "development.evidence_inspection_finished": {"inspection_id": _N, "verdict": _S, "claims": _I,
                                                 "findings": _NI, "checked": _NI, "not_checked": _NI,
                                                 "missing": _NI, "unknown": _NI, "error": _NI,
                                                 "replay_failed": _NI, "flake_pattern": _NI,
                                                 "verified_mismatch": _NI, "elapsed_seconds": _F,
                                                 "error_type": _N, "message_sha256": _N},
    "development.task_completed": {"status": _S, "commands": _I},
    "development.task_failed": {"status": _S, "error_type": _S, "failure_receipt": _N},
    "development.termination_recorded": {"reservation_id": _N, "invocation_outcome": _S, "stream_hash": _S,
                                         "error_type": _S, "record_id": _S, "boundary": _S},
    "development.reconciliation_required": {"terminations": _I, "record_id": _S},
    "development.reconciliation_resolved": {"record_id": _S, "resolution": _S, "operator": _S},
    "operations.lease_renewed": {"lease_until": _S},
    "operations.supervisor_tick": {"services_running": _I, "backlog_total": _I, "desired_image": _S},
    "operations.backlog_observed": {"agent": _S, "stream_backlog": _I, "durable_ready": _B, "busy": _B,
                                    "running": _B},
    "operations.worker_wake_requested": {"agent": _S, "service": _S, "image": _S, "stream_backlog": _I,
                                         "durable_ready": _B},
    "operations.worker_replace_requested": {"agent": _S, "service": _S, "image_from": _N, "image_to": _S},
    "operations.supervisor_error": {"error_type": _S},
    "operations.maintenance_job": {"job": _S, "status": _S},
    "operations.spool_saturated": {"bytes": _I, "limit_bytes": _I, "dropped": _I},
    "operations.spool_append_failed": {"error_type": _S, "dropped": _I},
    "operations.sink_unavailable": {"sink": _S, "error_type": _S, "pending": _I},
    "operations.sink_recovered": {"sink": _S, "replayed": _I},
    "operations.observation_conflict": {"conflicting_event_id": _S, "expected_hash": _S, "observed_hash": _S,
                                        "quarantine_id": _S},
    "operations.observation_refused": {"refused_event_type": _S, "defect": _S},
    "operations.collection_completed": {"files": _I, "records": _I, "inserted": _I, "duplicates": _I,
                                        "conflicts": _I, "corrupt": _I, "truncated_tail": _I,
                                        "unconfirmed_audits": _I},
    # self-improvement-reference-001: the host audit service's own facts. Identifiers, fixed codes
    # and counts only; a partition's paths, the model's cursor, prompts and source text never
    # reach a log, and a remaining count is scope arithmetic, not a semantic review credit.
    "operations.audit_service_started": {"audit_id": _S, "release_id": _S, "revision": _S,
                                         "max_tasks": _NI, "partitions": _I},
    "operations.audit_service_scheduled": {"audit_id": _S, "created": _I, "pending": _I,
                                           "foreign_messages": _I},
    # `status` is what the EXECUTION did; `analysis_outcome` is what its content was judged to be
    # (a fixed code, or null when a settled execution has no analysis outcome at all). The two are
    # reported separately: a rejected draft is a completed execution, and an unclassified history
    # row is neither a checkpoint nor a rejection.
    "operations.audit_service_task": {"audit_id": _S, "task_id": _S, "partition_id": _S,
                                      "generation": _NI, "status": _S, "remaining_paths": _NI,
                                      "remaining_subsystems": _NI, "open_questions": _NI,
                                      "analysis_outcome": _N},
    "operations.audit_service_stopped": {"audit_id": _S, "completed_tasks": _I, "error_type": _N},
    # self-improvement-reference-001 goal progress: ONE observation of the audit's own records.
    # Identifiers, counts and fixed codes only - never a path, a cursor, source text or a metric
    # the model wrote. `status` says what the observation was (baseline, observed, window_closed or
    # degraded); a degraded observation says nothing about the execution that preceded it, a
    # `verdict` is an unverified symptom and a `candidate` id is a research topic, not a cause.
    "operations.audit_progress_observed": {"audit_id": _S, "epoch": _N, "status": _S, "verdict": _N,
                                           "window_index": _NI, "window_executions": _NI,
                                           "new_executions": _NI, "semantic_delta": _NI,
                                           "ranges_delta": _NI, "streak": _NI, "candidate": _N,
                                           "candidate_created": _B, "unknown": _N, "error_type": _N},
    # self-improvement-reference-001 bounded repair: the lineage of ONE rejected analysis. Fixed
    # codes, identifiers and counts only - never the refused draft, the validator's message, a
    # subsystem name, a prompt or an exception text. `admitted` false with a reason code says why
    # nothing was admitted; a settlement reports what the successor's own records showed.
    "operations.audit_repair_admitted": {"audit_id": _S, "correction_id": _N, "source_task_id": _N,
                                         "partition_id": _N, "partition_generation": _NI,
                                         "diagnosis": _N, "successor_task_id": _N, "admitted": _B,
                                         "published": _B, "error_type": _N},
    "operations.audit_repair_settled": {"audit_id": _S, "correction_id": _S, "source_task_id": _N,
                                        "successor_task_id": _N, "state": _S, "diagnosis": _N,
                                        "analysis_outcome": _N, "corrected_subsystems": _NI,
                                        "checkpoint_generation": _NI, "attempts": _I,
                                        "error_type": _N},
    "operations.alert_suppressed": {"kind": _S, "suppressed": _I},
    "operations.alert_pending": {"kind": _S, "channel": _N, "pending": _I},
    "operations.autonomous_stage": {"run_id": _S, "stage": _S, "state": _S},
    # INV-OPERATION-FINALIZATION-001: identifiers, counts and codes only; a parked message is a
    # durable disposition, never a task result, and the finalization summary is not the outcome.
    "operations.operation_finalized": {"operation_id": _S, "operation_status": _S, "retired_tasks": _I,
                                       "retired_decisions": _I, "unresolved": _I, "already_terminal": _I},
    "operations.operation_message_parked": {"operation_id": _S, "message_id": _S, "message_type": _S,
                                            "disposition_id": _S, "stream_entry_id": _N},
}

# Runner classification (INV-INVOCATION-001) → observation outcome. Only `accepted` succeeds.
INVOCATION_OUTCOMES = {"accepted": "succeeded", "empty_answer": "failed", "invalid_output": "failed",
                       "tool_only": "failed", "provider_failure": "failed", "interrupted": "aborted",
                       "inspection_blocked": "blocked"}

# Closed code vocabularies for the boundary events above (operating-portfolio-001). Each lists the
# values this harness itself produces: the structural output reasons and owners of
# adapters.execution_output, the provider failure causes of the Codex and Claude adapters, the
# provider result subtypes those adapters read, and the structural check states. `safe_code` maps
# anything else, including a value a future provider version invents, to "unknown" rather than
# letting a foreign string become a Zeus code.
OUTPUT_REASONS = ("empty", "invalid_text", "invalid_json", "schema_mismatch", "schema_configuration")
FAILURE_OWNERS = ("agent_output", "configuration", "provider")
PROVIDER_CAUSES = ("codex-provider-usage-limit-exceeded", "claude-provider-budget-exhausted",
                   "claude-provider-cancelled", "claude-provider-conflicting-terminal",
                   "claude-provider-error-result", "claude-provider-exit-conflict",
                   "claude-provider-max-turns", "claude-provider-missing-terminal",
                   "claude-provider-model-mismatch", "claude-provider-session-conflicting",
                   "claude-provider-session-mismatch", "claude-provider-session-unreported",
                   "claude-provider-startup-failed", "claude-provider-stream-truncated",
                   "claude-provider-timeout")
TERMINAL_SUBTYPES = ("success", "error_during_execution", "error_max_turns",
                     "error_max_structured_output_retries")
STRUCTURAL_CHECKS = ("checked", "unchecked", "failed", "configuration_error")

# self-improvement-reference-001: what one settled `audit_partition` execution's content was judged
# to be, written by the execution into its own durable result and read back from there. These are
# the one authority for the codes; `analysis_unclassified` is a result that carries no marker -
# historical rows included - and it is never promoted to a checkpoint or an acceptance. `safe_code`
# maps anything foreign to "unknown" rather than letting a stored string become a Zeus code. A
# checkpoint is partial progress, and a rejection is retained work, not a successful review.
ANALYSIS_CHECKPOINTED = "analysis_checkpointed"
ANALYSIS_REJECTED = "analysis_rejected"
ANALYSIS_UNCLASSIFIED = "analysis_unclassified"
ANALYSIS_CONTENT_REJECTED = "analysis_content_rejected"
ANALYSIS_OUTCOMES = (ANALYSIS_CHECKPOINTED, ANALYSIS_REJECTED, ANALYSIS_UNCLASSIFIED)
ANALYSIS_REASONS = (ANALYSIS_CONTENT_REJECTED,)
ANALYSIS_FACTS = ("analysis_outcome", "analysis_reason", "analysis_ref", "analysis_generation")
NO_ANALYSIS = dict.fromkeys(ANALYSIS_FACTS)
ARTIFACT_REFERENCE = re.compile(r"sha256:[0-9a-f]{64}")


def analysis_facts(result) -> dict:
    """The analysis outcome of ONE durable task result, in fixed codes and identifiers only.

    The result is data a reader reads, never an instruction: an outcome or reason outside the
    declared vocabularies is `unknown`, a reference that is not an immutable artifact handle is
    dropped, and a missing marker is `analysis_unclassified`. No stored string can become free text
    in a log, a step, a status read or a repair diagnosis this way. This is the one projection of
    that marker: `adapters.audit_service` and the repair owner both read it here.
    """
    analysis = result.get("analysis") if isinstance(result, dict) else None
    if not isinstance(analysis, dict):
        return {**NO_ANALYSIS, "analysis_outcome": ANALYSIS_UNCLASSIFIED}
    ref, generation = analysis.get("execution_ref"), analysis.get("partition_generation")
    return {"analysis_outcome": safe_code(analysis.get("outcome"), ANALYSIS_OUTCOMES,
                                          absent=ANALYSIS_UNCLASSIFIED),
            "analysis_reason": safe_code(analysis.get("reason_code"), ANALYSIS_REASONS, absent=None),
            "analysis_ref": ref if type(ref) is str and ARTIFACT_REFERENCE.fullmatch(ref) else None,
            "analysis_generation": generation if type(generation) is int else None}

# A terminal subtype that names its own actionable failure also names the projected reason, so an
# operator can tell it apart from every other provider failure without reading a raw stream. Only a
# subtype this harness declares can reach this map, because `safe_code` runs first and a foreign or
# future string is `unknown`; nothing about the output itself is inferred from the subtype, and a
# structural output reason, when there is one, stays the reason.
SUBTYPE_REASONS = {"error_max_structured_output_retries": "output_structured_retries_exhausted"}

# Evidence inspection verdict → (outcome, reason_code, severity). Only a completed all_checked
# inspection succeeds: no claims, an incomplete check, a failed inspection and any verdict this
# table does not know are recorded as what they are (INV-EVIDENCE-001 owns the verdict itself).
INSPECTION_VERDICTS = {"all_checked": ("succeeded", "evidence_all_checked", "info"),
                       "no_claims": ("blocked", "evidence_no_claims", "warning"),
                       "incomplete": ("blocked", "evidence_incomplete", "warning"),
                       "inspection_error": ("unknown", "evidence_inspection_error", "error")}
UNKNOWN_VERDICT = ("unknown", "evidence_verdict_unknown", "error")


def safe_code(value, allowed, *, absent: str = "none") -> str:
    """One declared code, or a word that says why there is none. Never the foreign value itself."""
    if value is None:
        return absent
    return value if type(value) is str and value in allowed else "unknown"


def inspection_verdict(verdict) -> tuple:
    """(outcome, reason_code, severity) for an inspection verdict; an unknown verdict never succeeds."""
    return INSPECTION_VERDICTS.get(verdict, UNKNOWN_VERDICT) if type(verdict) is str else UNKNOWN_VERDICT

_URL_CREDENTIALS = re.compile(r"([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.I)
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|private[_-]?key|비밀번호|암호)"
    r"(\s*[:=]\s*|\s+)(\"[^\"]*\"|'[^']*'|\S+)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")
_TOKEN_SHAPES = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                           r"|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}"
                           r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")


def redact_text(text: str) -> tuple[str, int]:
    """Replace credential-shaped spans; returns the text and how many spans were replaced."""
    require(type(text) is str, "Only text is redacted")
    count = 0

    def sub(pattern, replacement, value):
        nonlocal count
        value, n = pattern.subn(replacement, value)
        count += n
        return value

    text = sub(_PRIVATE_KEY, "[REDACTED private_key]", text)
    text = sub(_URL_CREDENTIALS, r"\1[REDACTED credential]@", text)
    text = sub(_BEARER, "Bearer [REDACTED token]", text)
    text = sub(_ASSIGNED_SECRET, r"\1\2[REDACTED credential]", text)
    text = sub(_TOKEN_SHAPES, "[REDACTED token]", text)
    return text, count


def redact_value(value, *, max_chars: int = MAX_STRING_CHARS):
    """Redact every string inside nested JSON data and bound each string's length.

    Returns (value, findings, truncated). Dictionary keys are redacted too: an error message
    used as a key would otherwise escape the pass.
    """
    if isinstance(value, str):
        text, findings = redact_text(value)
        truncated = 0
        if len(text) > max_chars:
            text, truncated = text[:max_chars] + "…[truncated " + str(len(text) - max_chars) + "]", 1
        return text, findings, truncated
    if isinstance(value, dict):
        out, findings, truncated = {}, 0, 0
        for key, item in value.items():
            key_text, f1, t1 = redact_value(str(key), max_chars=max_chars)
            item, f2, t2 = redact_value(item, max_chars=max_chars)
            out[key_text] = item
            findings, truncated = findings + f1 + f2, truncated + t1 + t2
        return out, findings, truncated
    if isinstance(value, (list, tuple)):
        out, findings, truncated = [], 0, 0
        for item in value:
            item, f, t = redact_value(item, max_chars=max_chars)
            out.append(item)
            findings, truncated = findings + f, truncated + t
        return out, findings, truncated
    if value is None or type(value) in (bool, int):
        return value, 0, 0
    if type(value) is float:
        require(value == value and value not in (float("inf"), float("-inf")), "Attribute numbers must be finite")
        return value, 0, 0
    return {"invalid_type": type(value).__name__}, 0, 0


def opaque_identifier(value, name: str, limit: int = 200) -> str:
    """An identifier is refused when it does not look like an opaque handle or when it looks like
    a credential (a character-set rule is not a secret check; the redactor's shapes are)."""
    require(type(value) is str and REFERENCE.fullmatch(value) is not None and len(value) <= limit,
            f"{name} must be an opaque identifier (letters, digits, . _ : @ + -), at most {limit} characters")
    _, findings = redact_text(value)
    require(findings == 0, f"{name} looks like a credential and is refused")
    return value


def _typed(kind, value):
    if kind == _N:
        return value is None or (type(value) is str)
    if kind == _NI:
        return value is None or (type(value) is int)
    if kind == _S:
        return type(value) is str
    if kind == _I:
        return type(value) is int
    if kind == _B:
        return type(value) is bool
    if kind == _F:
        return type(value) in (int, float) and value == value and value not in (float("inf"), float("-inf"))
    return False


def check_attributes(event_type: str, attributes: dict) -> dict:
    """Keep only declared keys with declared scalar types; refuse anything else by name."""
    require(event_type in REGISTRY, "Unknown observation event type: " + str(event_type))
    require(isinstance(attributes, dict), "Observation attributes must be an object")
    allowed = REGISTRY[event_type]
    unknown = sorted(str(key) for key in attributes if key not in allowed)
    require(not unknown, f"Attributes not allowed for {event_type}: " + ", ".join(unknown))
    mistyped = sorted(key for key, value in attributes.items() if not _typed(allowed[key], value))
    require(not mistyped, f"Attribute types refused for {event_type}: " + ", ".join(mistyped))
    return dict(attributes)


def new_process_run_id() -> str:
    return uuid4().hex


def execution_identity(kind: str, *, process_run_id: str, role=None, provider=None, session_id=None,
                       bucket=None, task_id=None, generation=None, attempt=None, invocation_id=None,
                       revision=None) -> dict:
    """The execution an event belongs to. System events say their task and session are absent."""
    require(kind in EXECUTION_KINDS, "Unknown execution kind")
    require(type(process_run_id) is str and IDENTIFIER.fullmatch(process_run_id) is not None,
            "process_run_id must be a 32-hex process identifier")
    identity = {"kind": kind, "role": role, "provider": provider, "process_run_id": process_run_id,
                "session_id": session_id, "bucket": bucket, "task_id": task_id, "generation": generation,
                "attempt": attempt, "invocation_id": invocation_id, "revision": revision}
    for key in ("role", "provider", "session_id", "task_id", "invocation_id", "revision"):
        if identity[key] is not None:
            opaque_identifier(identity[key], f"execution.{key}", 255)
    for key in ("generation", "attempt"):
        require(identity[key] is None or (type(identity[key]) is int and identity[key] >= 0),
                f"execution.{key} must be a non-negative integer or null")
    require(bucket is None or bucket in BUCKETS, "execution.bucket must name a known aggregate or be null")
    if kind == "execution":
        require(type(role) is str and type(task_id) is str and bucket in BUCKETS
                and type(generation) is int and type(attempt) is int,
                "Execution events need role, task_id, bucket, generation and attempt")
    else:
        require(all(identity[key] is None for key in ("task_id", "session_id", "bucket", "generation",
                                                      "attempt", "invocation_id")),
                "System events carry explicit null task and session identity")
    return identity


def lease_identity(lease: dict, *, process_run_id: str, role: str, provider=None, session_id=None,
                   invocation_id=None, revision=None) -> dict:
    """Identity of the execution a lease row names (tasks or decisions_pending)."""
    require(isinstance(lease, dict) and type(lease.get("id")) is str, "Lease must identify a task")
    return execution_identity("execution", process_run_id=process_run_id, role=role, provider=provider,
                              session_id=session_id, bucket=lease.get("_bucket", "tasks"), task_id=lease["id"],
                              generation=lease.get("generation"), attempt=lease.get("attempt"),
                              invocation_id=invocation_id, revision=revision)


def _timestamp(value, name):
    if value is None:
        return None
    require(type(value) is str, name + " must be an ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(name + " must be an ISO timestamp or null") from exc
    require(parsed.utcoffset() is not None, name + " must be timezone-aware")
    return value


def build_event(*, event_type: str, outcome: str, execution: dict, sequence: dict, observed_at: str,
                source: dict, occurred_at=None, correlation_id=None, causation_id=None, reason_code=None,
                evidence_refs=(), attributes=None, severity: str = "info", identity=None) -> dict:
    """Validate and assemble one observation. Redaction is applied before the identity hash.

    `identity`, when given, is the list of values that make this event the same logical event
    on redelivery (for example an outbox attempt or a reservation transition); otherwise the
    (process_run_id, sequence number) pair identifies it. Same id with the same bytes is a
    redelivery; same id with different bytes is a conflict for the sink to isolate.
    """
    require(type(event_type) is str and "." in event_type, "event_type is '<category>.<name>'")
    category = event_type.split(".", 1)[0]
    require(category in CATEGORIES, "Unknown observation category")
    require(outcome in OUTCOMES, "Unknown observation outcome")
    require(severity in SEVERITIES, "Unknown observation severity")
    require(isinstance(execution, dict) and execution.get("kind") in EXECUTION_KINDS, "Execution identity required")
    require(isinstance(sequence, dict) and sequence.get("process_run_id") == execution["process_run_id"]
            and (sequence.get("number") is None or (type(sequence["number"]) is int and sequence["number"] >= 1))
            and sequence.get("basis") in ("spool_append", "unassigned")
            and (sequence["number"] is None) == (sequence["basis"] == "unassigned"),
            "Sequence must name the process run and say whether a number was assigned")
    require(isinstance(source, dict) and type(source.get("component")) is str and bool(source["component"]),
            "Source component required")
    if correlation_id is not None:
        opaque_identifier(correlation_id, "correlation_id")
    if causation_id is not None:
        opaque_identifier(causation_id, "causation_id")
    if reason_code is not None:
        require(type(reason_code) is str and REASON_CODE.fullmatch(reason_code) is not None,
                "reason_code must be an identifier or null")
        opaque_identifier(reason_code, "reason_code", 80)
    require(isinstance(evidence_refs, (list, tuple)) and len(evidence_refs) <= MAX_EVIDENCE_REFS,
            "Evidence references must be a short list")
    for ref in evidence_refs:
        opaque_identifier(ref, "evidence_ref")
    _timestamp(observed_at, "observed_at")
    require(observed_at is not None, "observed_at is the collection moment and is required")
    _timestamp(occurred_at, "occurred_at")
    attributes = check_attributes(event_type, attributes or {})
    redacted, findings, truncated = redact_value(attributes)
    require(len(canonical(redacted).encode("utf-8")) <= MAX_ATTRIBUTES_BYTES,
            f"Attributes exceed {MAX_ATTRIBUTES_BYTES} bytes for {event_type}")
    refs = list(evidence_refs)  # identifiers passed the reference rule; nothing to redact
    redacted_source, source_findings, _ = redact_value({"component": source["component"],
                                                        "host": source.get("host"), "pid": source.get("pid")})
    findings += source_findings
    if identity is None:
        require(sequence["number"] is not None, "An event without an explicit identity needs a sequence number")
        identity = ["sequence", sequence["process_run_id"], sequence["number"]]
    else:
        require(isinstance(identity, (list, tuple)) and bool(identity), "Identity must be a non-empty list")
        identity = ["identity", *identity]
    event_id = digest(["observation", SCHEMA_VERSION, event_type, *identity])
    return {"schema_version": SCHEMA_VERSION, "event_id": event_id, "category": category, "event_type": event_type,
            "severity": severity, "source": redacted_source, "observed_at": observed_at, "occurred_at": occurred_at,
            "correlation_id": correlation_id, "causation_id": causation_id, "execution": dict(execution),
            "sequence": dict(sequence), "outcome": outcome, "reason_code": reason_code,
            "evidence_refs": refs, "attributes": redacted,
            "redaction": {"applied": True, "findings": findings, "truncated": truncated}}


CONTENT_FIELDS = ("schema_version", "category", "event_type", "severity", "occurred_at", "correlation_id",
                  "causation_id", "execution", "outcome", "reason_code", "evidence_refs", "attributes")


def content_hash(event: dict) -> str:
    """Hash of the redacted event content, excluding collection metadata (observed_at, sequence, source).

    A redelivery or re-collection of the same logical event carries the same id and the same
    content hash; the same id with a different content hash is a conflict for the sink to isolate.
    """
    return digest({key: event.get(key) for key in CONTENT_FIELDS})


def invocation_outcome(classification: str) -> str:
    require(classification in INVOCATION_OUTCOMES, "Unknown invocation classification")
    return INVOCATION_OUTCOMES[classification]


def is_business_message(value) -> bool:
    """A six-W message shape is refused by every observation sink; log records cannot assign work."""
    return isinstance(value, dict) and any(key in value for key in ("who", "what", "how", "message_id", "type"))
