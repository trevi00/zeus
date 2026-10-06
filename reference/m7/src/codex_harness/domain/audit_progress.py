"""Goal progress of ONE source audit: the policy, the epoch identity, the window arithmetic, the
candidate row and the immutable council snapshot (INV-AUDIT-PROGRESS-001).

Everything here is policy over dictionaries: no store, clock, artifact, Git, network or provider
access, and nothing here writes a row. A window says what was observed between two observations of
the authoritative audit records - how many terminal executions settled, how many semantically
dispositioned paths and subsystems exist, how many distinct verified source-read ranges were seen
and what remains - and a below-target window is an UNVERIFIED symptom, never a cause, a stall, a
crash, a failed execution or an approved repair. Source-read evidence is never semantic completion,
repeated ranges are never new evidence, and unknown evidence is unknown: it is never a known zero
and never a second strike. Values never enter refusal messages; field names do.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest

POLICY_SCHEMA = "urn:zeus:audit-progress-policy:1"
OBSERVATION_SCHEMA = "urn:zeus:audit-progress-observation:1"
WINDOW_SCHEMA = "urn:zeus:audit-progress-window:1"
SNAPSHOT_SCHEMA = "urn:zeus:audit-progress-snapshot:1"
# The explicit candidate kind. A `portfolio_investigations` row without one is the legacy
# failure-family candidate (`domain.research_investigations.KIND`), and the two rules never mix.
KIND = "audit_progress"

POLICY_FIELDS = {"schema", "version", "window_executions", "minimum_semantic_paths",
                 "low_yield_windows", "authority"}
SOURCE_FIELDS = {"topic", "audit_ids"}
MAX_AUDITS = 10
MAX_WINDOW_EXECUTIONS = 100
MAX_OBSERVATIONS = 20          # later observations kept on one deduplicated candidate row
MAX_MEMBER_SAMPLE = 20         # bounded execution identities per window in a snapshot
AUDIT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# A task row is settled only in one of these statuses; `queued`, `running` and `retry` are live work
# and are never counted, never called stalled and never treated as cancelled because another task
# finished. `failed`, `cancelled`, `expired`, `blocked` and `superseded` are recorded distinctly and
# grant no semantic credit at all.
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "expired", "blocked", "superseded")
SUCCEEDED = "succeeded"

# Window verdicts. Only the two low-yield verdicts can add a strike; everything else clears the
# streak, because a comparison that did not hold is not evidence of low progress.
ADEQUATE = "adequate_progress"
LOW_YIELD = "low_semantic_yield"
NO_EVIDENCE = "no_new_evidence"
UNKNOWN_EVIDENCE = "unknown_evidence"
AUDIT_COMPLETE = "audit_complete"
NOT_COMPARABLE = "not_comparable"
LOW_VERDICTS = (LOW_YIELD, NO_EVIDENCE)
VERDICTS = (ADEQUATE, LOW_YIELD, NO_EVIDENCE, UNKNOWN_EVIDENCE, AUDIT_COMPLETE, NOT_COMPARABLE)

# Observation statuses this module's callers report; `degraded` is an observation failure and says
# nothing about the audit execution that preceded it.
BASELINE, OBSERVED, CLOSED, DEGRADED = "baseline", "observed", "window_closed", "degraded"

# The fixed exclusion vocabulary of the eligibility rule: bounded counts only, never a row or value.
EXCLUSIONS = ("malformed", "state", "scope", "epoch", "window", "policy", "claimed")

TRUST = ("unverified low-yield progress symptom measured from the authoritative audit records; it "
         "is a research topic, never a cause, a stalled or failed execution, an incident, an owner "
         "disposition or an approved repair")
AUTHORITY = ("audit progress observation and research dispatch only; it promotes no knowledge, "
             "completes no audit, retries nothing and decides no adoption")


class ProgressRefused(ContractError):
    """Refused with a fixed reason code and at most a field name, never a value."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("audit progress refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _bounded_int(value, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


# ----- policy and opt-in configuration -----------------------------------------------------------
def validate_policy(document) -> dict:
    """The packaged `urn:zeus:audit-progress-policy:1` thresholds, strictly validated.

    Versioned Git data, never model input and never self-edited at runtime: a policy the caller
    cannot validate is refused instead of defaulted, because a silently repaired threshold would
    decide when a research topic is opened.
    """
    if not isinstance(document, dict) or document.get("schema") != POLICY_SCHEMA:
        raise ProgressRefused("policy_schema")
    if set(document) != POLICY_FIELDS:
        raise ProgressRefused("policy_fields", "root")
    if document["version"] != 1:
        raise ProgressRefused("policy_invalid", "version")
    if not _bounded_int(document["window_executions"], 1, MAX_WINDOW_EXECUTIONS):
        raise ProgressRefused("policy_invalid", "window_executions")
    if not _bounded_int(document["minimum_semantic_paths"], 1, 1000):
        raise ProgressRefused("policy_invalid", "minimum_semantic_paths")
    if not _bounded_int(document["low_yield_windows"], 2, 10):
        raise ProgressRefused("policy_invalid", "low_yield_windows")
    if type(document["authority"]) is not str or not document["authority"].strip():
        raise ProgressRefused("policy_invalid", "authority")
    return {key: document[key] for key in sorted(POLICY_FIELDS)}


def policy_digest(policy: dict) -> str:
    return digest(policy)


def validate_source(document, topic_ids) -> dict:
    """The optional `audit_progress_source` block of `urn:zeus:research-program:1`.

    Present means the owner authorized THIS program's unchanged template plan for exactly those
    audits; absent means disabled and leaves the legacy canonical config (and its digest) untouched.
    `null`, `[]`, a wildcard and any other field are refused with a field name only.
    """
    name = "audit_progress_source"
    if not isinstance(document, dict):
        raise ProgressRefused("config_invalid", name)
    if set(document) != SOURCE_FIELDS:
        raise ProgressRefused("config_fields", name)
    if type(document["topic"]) is not str or document["topic"] not in set(topic_ids):
        raise ProgressRefused("config_invalid", name + ".topic")
    audits = document["audit_ids"]
    if not (isinstance(audits, list) and 1 <= len(audits) <= MAX_AUDITS):
        raise ProgressRefused("config_invalid", name + ".audit_ids")
    for value in audits:
        if type(value) is not str or AUDIT_ID.fullmatch(value) is None:
            raise ProgressRefused("config_invalid", name + ".audit_ids[]")
    if len(set(audits)) != len(audits):
        raise ProgressRefused("config_duplicate", name + ".audit_ids")
    return {"topic": document["topic"], "audit_ids": list(audits)}


# ----- identity ----------------------------------------------------------------------------------
def scope_digest(audit: dict, partitions: list) -> str:
    """The audit's source identity plus its inventory and partition scope. A changed source,
    inventory or partitioning is a different measuring scope, so it starts a new epoch instead of
    silently comparing two different denominators."""
    return digest({"source": audit.get("source"), "subsystems": sorted(audit.get("subsystems") or []),
                   "inventory": sorted(entry["path"] for entry in audit.get("inventory") or []),
                   "partitions": sorted([p["partition_id"], sorted(p.get("paths") or []),
                                         sorted(p.get("subsystems") or [])] for p in partitions)})


def epoch_identity(*, audit_id: str, scope_sha256: str, policy_sha256: str, release_id, revision) -> dict:
    """One comparable measuring era: this audit, this scope, this policy, this runtime identity.
    Windows of different epochs are never compared and never share a streak."""
    body = {"audit_id": audit_id, "scope_sha256": scope_sha256, "policy_sha256": policy_sha256,
            "release_id": release_id, "revision": revision}
    return {"id": digest({"kind": KIND, **body}), **body}


def execution_key(task) -> str | None:
    """The identity of ONE settled execution: task, execution generation and attempt.

    A replay, a duplicate tick or a restart re-reads the same key and can never close a second
    window with it; a live or retrying row has no key at all.
    """
    if not isinstance(task, dict) or type(task.get("id")) is not str or not task["id"]:
        return None
    if task.get("status") not in TERMINAL_STATUSES:
        return None
    return ":".join([task["id"], str(task.get("generation")), str(task.get("attempt")),
                     str(task.get("status"))])


def range_identity(body) -> tuple | None:
    """ONE verified source-read chunk: the source object (or its inventory path) and the start and
    end offsets the reader itself recorded. This is a DISTINCT RANGE, not unique bytes and not
    reviewed coverage - two ranges may overlap the same bytes - and a repeated range adds nothing.
    `None` marks a body this rule cannot read, which is unknown, never zero."""
    if not isinstance(body, dict):
        return None
    identity = body.get("object_id") or body.get("path")
    offsets = [body.get("start_line"), body.get("start_char"), body.get("next_line"), body.get("next_char")]
    if type(identity) is not str or not identity or any(type(value) is not int for value in offsets):
        return None
    return (identity, *offsets)


# ----- measurement and window arithmetic ----------------------------------------------------------
def measurement(*, semantic_paths: int, semantic_subsystems: int, non_semantic: dict, remaining_paths: int,
                remaining_subsystems: int, open_questions: int, executions: int, ranges: int,
                unknown: str | None, complete: bool, observed_at: str) -> dict:
    """One dated reading of the authoritative records.

    `semantic_paths` counts the LITERALLY semantic path dispositions only. Every other disposition -
    `unreviewed` and `unavailable`, and equally the valid completions `generated`, `duplicate` and
    `binary` - is counted apart in `non_semantic`, so no disposition change alone can be presented
    as semantic progress, while the existing completion and remaining-path contract keeps counting
    those valid dispositions as covered. A source-read range is evidence, never completion.
    """
    return {"semantic_paths": semantic_paths, "semantic_subsystems": semantic_subsystems,
            "semantic_total": semantic_paths + semantic_subsystems,
            "non_semantic": dict(sorted(non_semantic.items())), "remaining_paths": remaining_paths,
            "remaining_subsystems": remaining_subsystems, "open_questions": open_questions,
            "executions": executions, "distinct_ranges": ranges, "unknown": unknown,
            "complete": bool(complete), "observed_at": observed_at}


def window_delta(opening: dict, closing: dict, elapsed_seconds) -> dict:
    """Net progress is gains minus regressions, never positive-only: a semantic set that shrank is
    visible as a negative delta with `regressed` true. The path delta and the subsystem delta are
    separate facts, and a subsystem gain never hides a path regression behind the total."""
    total = closing["semantic_total"] - opening["semantic_total"]
    paths = closing["semantic_paths"] - opening["semantic_paths"]
    return {"semantic_paths": paths,
            "semantic_subsystems": closing["semantic_subsystems"] - opening["semantic_subsystems"],
            "semantic_total": total, "regressed": paths < 0 or total < 0,
            "distinct_ranges": closing["distinct_ranges"] - opening["distinct_ranges"],
            "remaining_paths": closing["remaining_paths"] - opening["remaining_paths"],
            "elapsed_seconds": elapsed_seconds}


def window_verdict(*, opening: dict, closing: dict, delta: dict, policy: dict,
                   incomparable: str | None = None) -> dict:
    """The verdict of ONE closed window, and whether it may count towards a streak.

    Unknown evidence, an incomparable window (an overflowed or restarted observation) and a
    completed audit are all explicitly NOT low yield: they clear the streak instead of adding one,
    because a comparison that did not hold is not evidence that the work produced nothing.
    """
    if opening.get("unknown") or closing.get("unknown"):
        return {"verdict": UNKNOWN_EVIDENCE, "comparable": False,
                "reason": closing.get("unknown") or opening.get("unknown")}
    if incomparable is not None:
        return {"verdict": NOT_COMPARABLE, "comparable": False, "reason": incomparable}
    if closing.get("complete"):
        # Completion is the existing audit contract, not a semantic count: binary, generated and
        # unavailable paths keep their own valid dispositions.
        return {"verdict": AUDIT_COMPLETE, "comparable": True, "reason": None}
    if delta["semantic_paths"] >= policy["minimum_semantic_paths"]:
        # `minimum_semantic_paths` is a PATH threshold: it is met by net literal semantic path gain
        # alone. Subsystem progress and the non-semantic dispositions are reported beside it and
        # never add to it, so a single generated, duplicate or binary disposition - valid completion
        # as it is - can never clear a streak by itself.
        return {"verdict": ADEQUATE, "comparable": True, "reason": None}
    if delta["distinct_ranges"] > 0:
        # New verified source evidence with no semantic gain: low yield, explicitly not "no work".
        return {"verdict": LOW_YIELD, "comparable": True, "reason": None}
    return {"verdict": NO_EVIDENCE, "comparable": True, "reason": None}


def window_cohort(new: list, size: int) -> dict:
    """The exact membership of the window ONE reading may close, from the uncounted settled
    executions it saw, oldest first.

    Fewer than `size`: no window closes yet. Exactly `size`: one comparable window, the only shape
    that can ever count as a strike. MORE than `size` is an overflow - a backlog, a restart or a
    reading taken late - and the whole cohort is consumed ONCE as a single `not_comparable` receipt
    whose execution count is honestly larger than the configured size. Those executions settled
    before this reading and have no historical per-execution measurement, and none may be inferred:
    keeping a remainder for the next window would hand old executions a NEW opening measurement they
    never earned and invent a zero-gain strike out of work that was never comparably observed.
    """
    if len(new) < size:
        return {"members": [], "closes": False, "incomparable": None}
    return {"members": list(new), "closes": True,
            "incomparable": "window_overflow" if len(new) > size else None}


def streak_after(previous: int, verdict: str) -> int:
    return previous + 1 if verdict in LOW_VERDICTS else 0


def window_row(*, epoch: dict, index: int, members: list, opening: dict, closing: dict, delta: dict,
               verdict: dict, policy_sha256: str, opened_at: str, closed_at: str) -> dict:
    """The durable receipt of one closed window: its exact membership, both readings and the
    verdict. It is never rewritten, and a later window never re-closes it."""
    ordered = sorted(members)
    return {"schema": WINDOW_SCHEMA, "id": window_id(epoch["id"], index), "epoch": epoch["id"],
            "audit_id": epoch["audit_id"], "index": index, "members": ordered,
            "members_sha256": digest(ordered), "executions": len(ordered),
            "policy_sha256": policy_sha256, "opening": opening, "closing": closing, "delta": delta,
            "verdict": verdict["verdict"], "comparable": verdict["comparable"],
            "verdict_reason": verdict["reason"], "opened_at": opened_at, "closed_at": closed_at}


def window_id(epoch_id: str, index: int) -> str:
    return epoch_id[:32] + ":" + "%04d" % index


# ----- the candidate ------------------------------------------------------------------------------
def candidate_identity(epoch_id: str) -> str:
    """One candidate per epoch: a later tick of the same epoch deduplicates onto this row."""
    return digest({"kind": KIND, "epoch": epoch_id})


def candidate_label(identifier: str) -> str:
    """Deterministic, bounded research-candidate id for one progress candidate; the full candidate
    id stays on the row and in the snapshot."""
    return "ap-" + identifier[:24]


def candidate_row(*, epoch: dict, policy_sha256: str, reason_code: str, windows: list, metrics: dict,
                  required_state: str, now: str) -> dict:
    """The `portfolio_investigations` row of an audit-progress candidate.

    It carries NO job ids and no Fleet status: an empty membership is never presented as a
    failed-job family, and no job, task, partition or audit row is written, retried or rewritten by
    recording it. `state` is the owner's undecided state; the row asserts a symptom, not a cause.
    """
    return {"id": candidate_identity(epoch["id"]), "kind": KIND, "state": required_state,
            "audit_id": epoch["audit_id"], "epoch": epoch["id"], "epoch_scope": dict(epoch),
            "policy_sha256": policy_sha256, "reason_code": reason_code,
            "windows": [w["id"] for w in windows], "window_sha256": [w["members_sha256"] for w in windows],
            "count": len(windows), "metrics": metrics, "observations": [], "evidence_refs": [],
            "decided_at": None, "trust": TRUST, "authority": AUTHORITY,
            "created_at": now, "updated_at": now}


def observation_entry(*, window: dict, streak: int, now: str) -> dict:
    """A later observation of an already recorded candidate: bounded facts only. It never changes
    the owner's disposition, the original windows or the recorded reason."""
    return {"window": window["id"], "verdict": window["verdict"], "executions": window["executions"],
            "semantic_total": window["delta"]["semantic_total"],
            "distinct_ranges": window["delta"]["distinct_ranges"], "streak": streak, "at": now}


def record_observation(row: dict, entry: dict) -> dict:
    """Append one bounded later observation to an existing candidate, preserving everything the
    owner or an earlier tick recorded - state, evidence, decision, windows and reason code."""
    observations = [o for o in (row.get("observations") or []) if o.get("window") != entry["window"]]
    return {**row, "observations": (observations + [entry])[-MAX_OBSERVATIONS:],
            "updated_at": entry["at"]}


def reason_for(windows: list) -> str:
    """The streak's fixed reason code: `no_new_evidence` only when NO window in it saw new verified
    ranges; both codes are symptoms, and neither is a root cause."""
    return NO_EVIDENCE if all(w["verdict"] == NO_EVIDENCE for w in windows) else LOW_YIELD


# ----- research eligibility and the council snapshot ----------------------------------------------
def eligible_candidates(*, candidates, windows, states, source: dict, claimed, required_state: str,
                        policy_sha256: str) -> dict:
    """The deterministic eligibility rule over authoritative rows only, with bounded counts.

    Eligible: the row is a well formed audit-progress candidate, its audit is authorized by
    `source`, its state is the owner's undecided `required_state`, its epoch is still the audit's
    CURRENT epoch, its policy digest is the one in force, no dispatch claim exists for it (across
    ALL programs), and every window it names still exists in that epoch, is comparable, carries a
    low-yield verdict and still matches the membership digest recorded with it. Nothing is derived,
    nothing is written, and a discovery item can never forge one of these: they are synthesized from
    these reads alone.
    """
    audits = set(source["audit_ids"])
    window_rows = {w["id"]: w for w in windows if isinstance(w, dict) and type(w.get("id")) is str}
    current = {s["audit_id"]: s for s in states
               if isinstance(s, dict) and type(s.get("audit_id")) is str}
    claimed_ids = set(claimed)
    counts = {"scanned": 0, "eligible": 0, **{name: 0 for name in EXCLUSIONS}}
    found = []
    for row in candidates:
        if not isinstance(row, dict) or row.get("kind") != KIND:
            continue            # another candidate kind: the failure-family rule owns those rows
        counts["scanned"] += 1
        identifier, audit_id = row.get("id"), row.get("audit_id")
        if (type(identifier) is not str or IDENTITY.fullmatch(identifier) is None
                or type(audit_id) is not str or type(row.get("epoch")) is not str
                or row.get("reason_code") not in LOW_VERDICTS
                or not isinstance(row.get("windows"), list) or not row["windows"]):
            counts["malformed"] += 1
            continue
        if audit_id not in audits:
            counts["scope"] += 1
            continue
        if row.get("state") != required_state:
            counts["state"] += 1
            continue
        if row.get("policy_sha256") != policy_sha256:
            counts["policy"] += 1
            continue
        state = current.get(audit_id)
        if not isinstance(state, dict) or (state.get("epoch") or {}).get("id") != row["epoch"]:
            # The scope, policy or runtime identity moved on: an old epoch is never re-dispatched.
            counts["epoch"] += 1
            continue
        selected, broken = [], False
        for index, window_ref in enumerate(row["windows"]):
            window = window_rows.get(window_ref)
            recorded = (row.get("window_sha256") or [None] * len(row["windows"]))
            if (window is None or window.get("epoch") != row["epoch"] or not window.get("comparable")
                    or window.get("verdict") not in LOW_VERDICTS
                    or window.get("members_sha256") != (recorded[index] if index < len(recorded) else None)):
                broken = True
                break
            selected.append(window)
        if broken or len(selected) < row.get("count", len(row["windows"])):
            counts["window"] += 1
            continue
        if identifier in claimed_ids:
            counts["claimed"] += 1
            continue
        counts["eligible"] += 1
        found.append({"candidate": row, "windows": selected})
    return {"candidates": sorted(found, key=lambda entry: entry["candidate"]["id"]), "counts": counts}


def snapshot(*, candidate: dict, windows: list, program_id: str, cycle_number: int, topic: str,
             observed_at: str) -> dict:
    """The immutable bounded snapshot the council receives: identities, fixed codes, both window
    receipts with their complete membership digests and a bounded member sample, and the explicit
    unverified trust. No source text, path, cursor, prompt, output, credential or provider stream is
    ever copied here, and `investigation` is the candidate row this snapshot belongs to, so the
    existing cross-program claim keys on it exactly as it does for a failure family."""
    return {"schema": SNAPSHOT_SCHEMA, "kind": KIND, "investigation": candidate["id"],
            "program": program_id, "cycle": cycle_number, "topic": topic,
            "audit_id": candidate["audit_id"], "epoch": candidate["epoch"],
            "policy_sha256": candidate["policy_sha256"], "reason_code": candidate["reason_code"],
            "windows": [{"id": w["id"], "index": w["index"], "verdict": w["verdict"],
                         "executions": w["executions"], "members_sha256": w["members_sha256"],
                         "members": sorted(w["members"])[:MAX_MEMBER_SAMPLE],
                         "members_truncated": len(w["members"]) > MAX_MEMBER_SAMPLE,
                         "delta": dict(w["delta"]), "closing": dict(w["closing"]),
                         "closed_at": w["closed_at"]} for w in windows],
            "metrics": dict(candidate["metrics"]), "observed_at": observed_at,
            "trust": TRUST, "authority": AUTHORITY}


__all__ = ["ADEQUATE", "AUDIT_COMPLETE", "AUTHORITY", "BASELINE", "CLOSED", "DEGRADED", "EXCLUSIONS",
           "KIND", "LOW_VERDICTS", "LOW_YIELD", "MAX_OBSERVATIONS", "NOT_COMPARABLE", "NO_EVIDENCE",
           "OBSERVATION_SCHEMA", "OBSERVED", "POLICY_SCHEMA", "SNAPSHOT_SCHEMA", "SUCCEEDED",
           "TERMINAL_STATUSES", "TRUST", "UNKNOWN_EVIDENCE", "VERDICTS", "WINDOW_SCHEMA",
           "ProgressRefused", "candidate_identity", "candidate_label", "candidate_row", "eligible_candidates",
           "epoch_identity", "execution_key", "measurement", "observation_entry", "policy_digest",
           "range_identity", "reason_for", "record_observation", "scope_digest", "snapshot",
           "streak_after", "validate_policy", "validate_source", "window_cohort", "window_delta",
           "window_id", "window_row", "window_verdict"]
