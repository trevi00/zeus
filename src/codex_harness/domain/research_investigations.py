"""Investigation-to-research bridge: the opt-in source configuration, the eligibility rule, the
immutable bounded snapshot and the dispatch row shape (INV-RESEARCH-PROGRAM-001, research-dispatch-001).

Everything here is policy over dictionaries: no store, clock, Git, network or provider access, and no
portfolio row is ever written from this module. A candidate is one coarse triage family - the same
terminal status and the same fixed reason code observed on two or more distinct bound jobs - so an
eligible investigation is an UNTRUSTED hypothesis, never a cause, an incident or an approved repair.
The owner's `portfolio_investigations.state` is read only; the caller supplies the required state and
the family minimum so `application/portfolio.py` stays the single authority for those definitions.
Values never enter refusal messages; field names do.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest

SOURCE = "investigation"
# The candidate kind THIS rule owns. A `portfolio_investigations` row without a kind is a legacy
# failure family; a row of another kind (audit-progress, see `domain.audit_progress`) has its own
# rule, its own counts and its own snapshot, and is never scanned, counted or dispatched here.
KIND = "failure_family"
SOURCE_FIELDS = {"topic", "project_ids", "reason_codes"}
SNAPSHOT_SCHEMA = "urn:zeus:research-investigation-snapshot:1"
DISPATCH_SCHEMA = "urn:zeus:research-investigation-dispatch:1"
MAX_PROJECTS, MAX_REASON_CODES, MAX_JOB_SAMPLE = 20, 50, 50
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REASON_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
INVESTIGATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# The fixed exclusion vocabulary: bounded counts only, never a row, a value or a derived cause.
EXCLUSIONS = ("malformed", "state", "reason_code", "insufficient_jobs", "claimed")
CLAIMED, DISPATCHED, RESOLVED = "claimed", "dispatched", "resolved"
TRUST = ("unverified failure-family symptom recorded by the operating portfolio; identical symptoms "
         "are a hypothesis, never a cause, an incident resolution or an approved repair")
AUTHORITY = ("research dispatch claim and council outcome only; it is not an owner disposition, not an "
             "incident resolution and not a promotion")


class InvestigationRefused(ContractError):
    """Refused with a fixed reason code and at most a field name, never a value. The research program
    converts this into its own `ProgramRefused` so one refusal vocabulary reaches the operator."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("investigation source refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _list(values, limit: int, pattern, field: str) -> list:
    """Nonempty, bounded, distinct, pattern-matched. `null`, `[]`, a wildcard `*` and any non-string
    fail the pattern or the bound, so no rule here can widen to "every project" or "every reason"."""
    if not (isinstance(values, list) and 1 <= len(values) <= limit):
        raise InvestigationRefused("config_invalid", field)
    for value in values:
        if type(value) is not str or pattern.fullmatch(value) is None:
            raise InvestigationRefused("config_invalid", field + "[]")
    if len(set(values)) != len(values):
        raise InvestigationRefused("config_duplicate", field)
    return list(values)


def validate_source(document, topic_ids) -> dict:
    """The optional `investigation_source` block of `urn:zeus:research-program:1`. Present means the
    owner authorized THIS program's unchanged template plan for those projects and reason codes;
    absent means disabled and leaves the legacy canonical config (and its digest) untouched."""
    name = "investigation_source"
    if not isinstance(document, dict):
        raise InvestigationRefused("config_invalid", name)
    if set(document) != SOURCE_FIELDS:
        raise InvestigationRefused("config_fields", name)
    if type(document["topic"]) is not str or document["topic"] not in set(topic_ids):
        raise InvestigationRefused("config_invalid", name + ".topic")
    return {"topic": document["topic"],
            "project_ids": _list(document["project_ids"], MAX_PROJECTS, PROJECT_ID, name + ".project_ids"),
            "reason_codes": _list(document["reason_codes"], MAX_REASON_CODES, REASON_CODE, name + ".reason_codes")}


def candidate_identity(investigation_id: str) -> str:
    """Deterministic, bounded candidate id for one investigation; the full id stays on the row."""
    return "inv-" + investigation_id[:24]


def candidate_key(investigation_id: str) -> str:
    return SOURCE + ":" + investigation_id


def scoped_job_ids(investigation: dict, jobs: dict, bindings: dict, project_ids: set) -> list | None:
    """ONLY the referenced jobs that still exist, still carry this family's exact status and reason
    code, and are immutably bound to an allowed project. `None` marks a malformed row. Unrelated
    members of the same family are never added: the investigation's own membership is the scope."""
    referenced = investigation.get("job_ids")
    if not isinstance(referenced, list):
        return None
    status, reason = investigation.get("family_status"), investigation.get("reason_code")
    if type(status) is not str or type(reason) is not str or REASON_CODE.fullmatch(reason) is None:
        return None
    scoped = set()
    for job_id in referenced:
        if type(job_id) is not str or not job_id:
            return None
        job, binding = jobs.get(job_id), bindings.get(job_id)
        if job is None or binding is None:
            continue
        if job.get("status") != status or job.get("reason_code") != reason:
            continue
        if binding.get("project_id") not in project_ids:
            continue
        scoped.add(job_id)
    return sorted(scoped)


def eligible_investigations(*, investigations, jobs, bindings, source: dict, claimed, required_state: str,
                            minimum: int) -> dict:
    """The deterministic eligibility rule over authoritative rows only, with bounded exclusion counts.

    Eligible: the row is well formed, its state is the owner's undecided `required_state`, its reason
    code is authorized by `source`, no dispatch claim exists for it (`claimed`, across ALL programs),
    and at least `minimum` distinct scoped jobs remain. No root cause is derived, no row is modified
    and a changed owner disposition simply stops being eligible. A row of another candidate kind is
    skipped before it is scanned: this rule's counts describe failure families only.
    """
    project_ids, reason_codes = set(source["project_ids"]), set(source["reason_codes"])
    job_rows = {j["id"]: j for j in jobs if isinstance(j, dict) and type(j.get("id")) is str}
    binding_rows = {b["job_id"]: b for b in bindings if isinstance(b, dict) and type(b.get("job_id")) is str}
    claimed_ids = set(claimed)
    counts = {"scanned": 0, "eligible": 0, **{name: 0 for name in EXCLUSIONS}}
    candidates = []
    for row in investigations:
        if isinstance(row, dict) and row.get("kind", KIND) != KIND:
            continue    # another candidate kind: not this family rule's population at all
        counts["scanned"] += 1
        if not isinstance(row, dict) or type(row.get("id")) is not str or INVESTIGATION_ID.fullmatch(row.get("id") or "") is None:
            counts["malformed"] += 1
            continue
        if row.get("state") != required_state:
            counts["state"] += 1
            continue
        if row.get("reason_code") not in reason_codes:
            counts["reason_code"] += 1
            continue
        if row["id"] in claimed_ids:
            counts["claimed"] += 1
            continue
        scoped = scoped_job_ids(row, job_rows, binding_rows, project_ids)
        if scoped is None:
            counts["malformed"] += 1
            continue
        if len(scoped) < minimum:
            counts["insufficient_jobs"] += 1
            continue
        counts["eligible"] += 1
        candidates.append({"investigation": row["id"], "family_status": row["family_status"],
                           "reason_code": row["reason_code"], "job_ids": scoped,
                           "projects": sorted({binding_rows[j]["project_id"] for j in scoped})})
    return {"candidates": sorted(candidates, key=lambda c: c["investigation"]), "counts": counts}


def snapshot(*, candidate: dict, program_id: str, cycle_number: int, topic: str, observed_at: str) -> dict:
    """The immutable bounded source snapshot the council receives: versioned schema, identities, the
    fixed codes, at most MAX_JOB_SAMPLE job ids with the complete count and the digest of the FULL
    scoped id set (so truncation is explicit), the observation time and the explicit unverified trust.
    No prompt, output, exception, error text, credential or provider stream is ever copied here."""
    ids = sorted(candidate["job_ids"])
    return {"schema": SNAPSHOT_SCHEMA, "investigation": candidate["investigation"], "program": program_id,
            "cycle": cycle_number, "topic": topic, "family_status": candidate["family_status"],
            "reason_code": candidate["reason_code"], "projects": list(candidate["projects"]),
            "job_ids": ids[:MAX_JOB_SAMPLE], "job_ids_total": len(ids), "job_ids_sha256": digest(ids),
            "job_ids_truncated": len(ids) > MAX_JOB_SAMPLE, "observed_at": observed_at, "trust": TRUST}


def dispatch_row(*, document: dict, candidate_id: str, cycle_ref: str, now: str) -> dict:
    """The `research_investigation_dispatches` claim, keyed SOLELY by investigation id: one claim
    across programs and across candidate kinds. It binds program, cycle, the snapshot digest, the
    kind and the fixed codes; run and manifest are bound when the council starts, never before.

    A failure family binds its scoped job ids. Another kind (audit progress) has no job membership
    at all, so the job fields are explicitly `null` and its own bounded scope travels in `scope`: an
    empty list would read as a failed-job family with no members, which it is not.
    """
    kind = document.get("kind", KIND)
    family = kind == KIND
    return {"schema": DISPATCH_SCHEMA, "id": document["investigation"], "investigation": document["investigation"],
            "kind": kind, "scope": None if family else scope_reference(document),
            "program": document["program"], "cycle": cycle_ref, "cycle_number": document["cycle"],
            "candidate": candidate_id, "state": CLAIMED, "snapshot_sha256": digest(document),
            "family_status": document.get("family_status"), "reason_code": document["reason_code"],
            "job_ids": list(document["job_ids"]) if family else None,
            "job_ids_total": document["job_ids_total"] if family else None,
            "job_ids_sha256": document["job_ids_sha256"] if family else None,
            "run_id": None, "manifest_sha256": None,
            "manifest_ref": None, "result": None, "result_reason": None, "row_status": None,
            "reported_result": None, "failure": None, "claimed_at": now, "started_at": None,
            "finished_at": None, "updated_at": now, "authority": AUTHORITY}


def scope_reference(document: dict) -> dict:
    """The bounded scope of a non-family claim: identifiers and digests only, never a measurement,
    a path, a cursor or any source text."""
    return {key: document.get(key) for key in ("audit_id", "epoch", "policy_sha256")}


def dispatch_view(row: dict) -> dict:
    """The bounded read-only projection: identifiers, fixed codes and counts only. `kind` and
    `scope` are additive: a legacy row reads as the failure family it is."""
    keys = ("investigation", "program", "cycle", "cycle_number", "state", "result", "result_reason", "row_status",
            "reported_result", "run_id", "manifest_sha256", "snapshot_sha256", "family_status", "reason_code",
            "job_ids_total", "job_ids_sha256", "failure", "claimed_at", "started_at", "finished_at", "updated_at")
    return {**{k: row.get(k) for k in keys}, "kind": row.get("kind", KIND), "scope": row.get("scope")}


def dispatch_counts(rows: list) -> dict:
    """Dispatch is counted separately from acceptance: claimed and dispatched are work in flight."""
    counts = {"total": len(rows), "claimed": 0, "dispatched": 0, "accepted": 0, "rejected": 0, "failed": 0, "unknown": 0}
    for row in rows:
        result = row.get("result")
        if result in counts:
            counts[result] += 1
        elif row.get("state") == DISPATCHED:
            counts["dispatched"] += 1
        else:
            counts["claimed"] += 1
    return counts


__all__ = ["AUTHORITY", "CLAIMED", "DISPATCHED", "DISPATCH_SCHEMA", "EXCLUSIONS", "KIND", "MAX_JOB_SAMPLE",
           "MAX_PROJECTS", "MAX_REASON_CODES", "RESOLVED", "SNAPSHOT_SCHEMA", "SOURCE", "TRUST",
           "InvestigationRefused", "candidate_identity", "candidate_key", "dispatch_counts", "dispatch_row",
           "dispatch_view", "eligible_investigations", "scope_reference", "scoped_job_ids", "snapshot",
           "validate_source"]
