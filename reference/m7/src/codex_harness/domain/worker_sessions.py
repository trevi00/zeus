"""Durable Claude task sessions: the pure lifecycle, identity and archive policy (INV-WORKER-SESSION-001).

One logical worker task keeps one provider conversation through implementation -> frozen candidate
-> review wait -> qualified rejection correction, without an idle model process. This module
decides; it performs no I/O. The application owns the durable binding (`worker_sessions` rows) and
the adapter owns the bytes (a restricted content-addressed archive of the exact session's allowlisted
transcript files).

What is authoritative, and what is not:

- The binding is the task id, repository, workspace, provider, model, runtime image, runtime,
  policy and config identities. A task/repository/workspace mismatch is a foreign session and is
  never resumed. A model, image, runtime, policy or config mismatch refuses NATIVE resume and says
  that an explicit fresh evidence handoff is required; it never relabels a fresh context as resumed.
- A retained container, a UUID alone or a checkpoint row is not proof of transcript continuity. A
  resumed turn is continuous only when its exported transcript begins with the exact bytes of the
  archive it was restored from (`prefix_verified`); anything else is unproven and unresolved.
- Rejection authority is the existing succeeded independent review decision for the exact frozen
  candidate, read from its own row. Arbitrary text never moves a session. A decision makes a session
  eligible for correction; it creates no work, approves nothing and merges nothing.
- Resumed headless usage is cumulative. A delta is derived only against the same session's recorded
  baseline; otherwise the usage of that turn is unknown, never zero and never the cumulative total.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest

SCHEMA = "zeus.worker-session.v1"
ARCHIVE_SCHEMA = "zeus.worker-session-archive.v1"
PROMOTION_SCHEMA = "zeus.worker-session-promotion.v1"
AUTHORITY = ("read-only projection of worker_sessions rows: not a resume, a transcript continuity proof, "
             "an acceptance, a promotion or a release")

ACTIVE = "active"
CHECKPOINTED = "checkpointed"
AWAITING_REVIEW = "awaiting_review"
CORRECTION_READY = "correction_ready"
ACCEPTED = "accepted"
ARCHIVAL_PENDING = "archival_pending"
CLOSED = "closed"
# Explicit non-resumable states. Each names why native resume is refused; none is ever repaired
# silently into a fresh context.
ARCHIVE_MISSING = "archive_missing"
ARCHIVE_CORRUPT = "archive_corrupt"
INCOMPATIBLE = "incompatible"
UNRESOLVED = "unresolved"

STATES = (ACTIVE, CHECKPOINTED, AWAITING_REVIEW, CORRECTION_READY, ACCEPTED, ARCHIVAL_PENDING, CLOSED,
          ARCHIVE_MISSING, ARCHIVE_CORRUPT, INCOMPATIBLE, UNRESOLVED)
# The fixed state/action matrix. `None` is "no row yet".
TRANSITIONS = {
    None: frozenset({ACTIVE}),
    ACTIVE: frozenset({CHECKPOINTED, UNRESOLVED}),
    CHECKPOINTED: frozenset({ACTIVE, AWAITING_REVIEW, ARCHIVE_MISSING, ARCHIVE_CORRUPT, INCOMPATIBLE}),
    AWAITING_REVIEW: frozenset({CORRECTION_READY, ACCEPTED}),
    CORRECTION_READY: frozenset({ACTIVE, ARCHIVE_MISSING, ARCHIVE_CORRUPT, INCOMPATIBLE}),
    ACCEPTED: frozenset({ARCHIVAL_PENDING}),
    ARCHIVAL_PENDING: frozenset({CLOSED}),
    CLOSED: frozenset(),
    ARCHIVE_MISSING: frozenset(),
    ARCHIVE_CORRUPT: frozenset(),
    INCOMPATIBLE: frozenset(),
    # Only an explicit reconcile from verified retained bytes of this exact session leaves it.
    UNRESOLVED: frozenset({CHECKPOINTED}),
}
RESUMABLE = frozenset({CHECKPOINTED, CORRECTION_READY})

MODE_FRESH = "fresh"
MODE_RESUME = "native_resume"

# Task, repository and workspace say WHOSE session this is; the rest say whether the same provider
# configuration can read it. Both groups are compared exactly, never by prefix or alias.
OWNERSHIP_FIELDS = ("task_id", "repository", "workspace")
COMPATIBILITY_FIELDS = ("provider", "model", "runtime_image", "runtime_digest", "policy_digest", "config_digest")
IDENTITY_FIELDS = OWNERSHIP_FIELDS + COMPATIBILITY_FIELDS

SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REFERENCE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,199}$")
# One path component of an exported file: no dot-files (credentials, settings), no separators, no
# drive or stream syntax, bounded. Windows reserved device names are refused separately.
COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}

# Bounds for one exported session. Fixed here, not per task.
MAX_ARCHIVE_FILES = 64
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 6
MAX_HISTORY = 64

REVIEW_PHASES = ("review_lead", "review_conductor")


class WorkerSessionRefused(ContractError):
    """A refusal with a printable reason code; nothing was changed by the refused action."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__("worker session: " + reason + (": " + detail if detail else ""))
        self.reason = reason


def refuse(condition, reason: str, detail: str = "") -> None:
    if not condition:
        raise WorkerSessionRefused(reason, detail)


def transition(current, target: str) -> str:
    refuse(target in TRANSITIONS.get(current, frozenset()), "invalid_transition", f"{current} -> {target}")
    return target


# ---- identity -----------------------------------------------------------------------------------
def validate_identity(identity) -> dict:
    refuse(isinstance(identity, dict) and set(identity) == set(IDENTITY_FIELDS), "identity_malformed",
           "exactly " + ", ".join(IDENTITY_FIELDS))
    for name in IDENTITY_FIELDS:
        refuse(type(identity[name]) is str and TOKEN.fullmatch(identity[name]) is not None, "identity_malformed", name)
    return {name: identity[name] for name in IDENTITY_FIELDS}


def compare_identity(bound: dict, current: dict) -> dict:
    """Which exact fields differ, split by what the difference means."""
    foreign = sorted(name for name in OWNERSHIP_FIELDS if bound.get(name) != current.get(name))
    incompatible = sorted(name for name in COMPATIBILITY_FIELDS if bound.get(name) != current.get(name))
    return {"foreign": foreign, "incompatible": incompatible,
            "decision": "foreign" if foreign else "incompatible" if incompatible else "match",
            "next_action": ("refuse: another task's session" if foreign
                            else "explicit fresh evidence handoff required; native resume refused" if incompatible
                            else "native resume permitted")}


def validate_owner(owner) -> dict:
    """The execution that exclusively holds the session while a provider runs."""
    refuse(isinstance(owner, dict) and set(owner) == {"execution", "generation", "attempt"}, "owner_malformed")
    refuse(type(owner["execution"]) is str and bool(owner["execution"]), "owner_malformed", "execution")
    refuse(type(owner["generation"]) is int and type(owner["attempt"]) is int, "owner_malformed", "generation/attempt")
    return dict(owner)


def validate_candidate(candidate) -> dict:
    refuse(isinstance(candidate, dict), "candidate_malformed")
    body = {key: candidate.get(key) for key in ("revision", "tree", "base")}
    for key, value in body.items():
        refuse(type(value) is str and REVISION.fullmatch(value) is not None, "candidate_malformed", key)
    return body


# ---- archive paths ------------------------------------------------------------------------------
def project_key(cwd: str) -> str:
    """The CLI's per-project transcript directory name: every non-alphanumeric character of the
    absolute working directory becomes '-'. POSIX `/workspace` -> `-workspace`; Windows
    `C:\\work\\x` -> `C--work-x`. Owner qualification confirms this against the pinned CLI."""
    refuse(type(cwd) is str and bool(cwd) and len(cwd) <= 400, "workspace_malformed")
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def transcript_path(project: str, session_id: str) -> str:
    refuse(SESSION_ID.fullmatch(session_id or "") is not None, "session_id_malformed")
    return f"projects/{project}/{session_id}.jsonl"


def check_component(name: str) -> bool:
    return (COMPONENT.fullmatch(name) is not None and name.split(".")[0].upper() not in WINDOWS_RESERVED
            and not name.endswith("."))


def allowed_path(relative: str, project: str, session_id: str) -> bool:
    """Only the exact session's transcript and the files under that session's own directory."""
    if type(relative) is not str or "\\" in relative or relative.startswith("/") or ":" in relative:
        return False
    if relative == transcript_path(project, session_id):
        return True
    prefix = f"projects/{project}/{session_id}/"
    if not relative.startswith(prefix):
        return False
    parts = relative[len(prefix):].split("/")
    return 0 < len(parts) <= MAX_ARCHIVE_DEPTH and all(check_component(part) for part in parts)


def validate_manifest(manifest, *, session_id: str | None = None) -> dict:
    """An exported session's file list: exact session, allowlisted paths, bounds, hashes."""
    refuse(isinstance(manifest, dict) and manifest.get("schema") == ARCHIVE_SCHEMA, "archive_malformed", "schema")
    sid, project, files = manifest.get("session_id"), manifest.get("project"), manifest.get("files")
    refuse(type(sid) is str and SESSION_ID.fullmatch(sid) is not None, "archive_malformed", "session_id")
    refuse(session_id is None or sid == session_id, "archive_foreign_session")
    refuse(type(project) is str and bool(project) and "/" not in project and "\\" not in project
           and project not in (".", ".."), "archive_malformed", "project")
    refuse(isinstance(files, list) and 0 < len(files) <= MAX_ARCHIVE_FILES, "archive_bounds", "file count")
    seen, total = set(), 0
    for entry in files:
        refuse(isinstance(entry, dict) and set(entry) == {"path", "bytes", "sha256"}, "archive_malformed", "entry")
        refuse(allowed_path(entry["path"], project, sid), "archive_path_refused", str(entry.get("path"))[:120])
        folded = entry["path"].casefold()
        refuse(folded not in seen, "archive_path_refused", "duplicate or case collision")
        seen.add(folded)
        refuse(type(entry["bytes"]) is int and 0 <= entry["bytes"] <= MAX_ARCHIVE_FILE_BYTES, "archive_bounds", "file bytes")
        refuse(type(entry["sha256"]) is str and SHA256.fullmatch(entry["sha256"]) is not None, "archive_malformed", "sha256")
        total += entry["bytes"]
    refuse(total <= MAX_ARCHIVE_BYTES, "archive_bounds", "total bytes")
    refuse(transcript_path(project, sid) in {entry["path"] for entry in files}, "archive_transcript_missing")
    return {"schema": ARCHIVE_SCHEMA, "session_id": sid, "project": project,
            "files": sorted(({"path": e["path"], "bytes": e["bytes"], "sha256": e["sha256"]} for e in files),
                            key=lambda e: e["path"])}


def transcript_entry(manifest: dict) -> dict:
    wanted = transcript_path(manifest["project"], manifest["session_id"])
    return next(entry for entry in manifest["files"] if entry["path"] == wanted)


# ---- usage --------------------------------------------------------------------------------------
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def usage_delta(*, mode: str, session_id: str, baseline: dict | None, raw) -> dict:
    """This turn's usage from the provider's raw totals.

    A fresh turn's totals are its own. A resumed turn's totals are cumulative, so its delta exists
    only against a baseline recorded for the SAME session; a missing, foreign or decreasing baseline
    leaves the turn unknown rather than counting the cumulative total twice."""
    record = {"raw": raw if isinstance(raw, dict) else None, "session_id": session_id, "mode": mode,
              "baseline": baseline, "delta": None, "basis": "unknown"}
    if not isinstance(raw, dict):
        return record
    numbers = {key: raw.get(key) for key in USAGE_KEYS if type(raw.get(key)) is int and raw.get(key) >= 0}
    if mode == MODE_FRESH:
        return {**record, "delta": numbers, "basis": "fresh_session_totals"}
    if not isinstance(baseline, dict) or baseline.get("session_id") != session_id \
            or not isinstance(baseline.get("raw"), dict):
        return {**record, "basis": "unknown_no_matching_baseline"}
    delta = {}
    for key, value in numbers.items():
        previous = baseline["raw"].get(key)
        if type(previous) is not int or value < previous:
            return {**record, "basis": "unknown_baseline_not_monotonic"}
        delta[key] = value - previous
    return {**record, "delta": delta, "basis": "cumulative_minus_session_baseline"}


# ---- review authority ---------------------------------------------------------------------------
def review_outcome(row, candidate: dict) -> dict:
    """The existing succeeded independent review of the exact frozen candidate, or a refusal.

    Review phases run read-only, which only the default (Codex) provider is permitted to do; the
    row is the durable decision record the executor committed, not text supplied by anyone."""
    refuse(isinstance(row, dict), "review_missing")
    refuse(row.get("phase") in REVIEW_PHASES, "review_not_independent", str(row.get("phase")))
    refuse(row.get("status") == "succeeded", "review_not_succeeded", str(row.get("status")))
    reviewed = (row.get("input") or {}).get("candidate") or {}
    refuse(reviewed.get("revision") == candidate["revision"] and reviewed.get("tree") == candidate["tree"],
           "review_candidate_mismatch")
    result = row.get("result") or {}
    refuse(type(result.get("accepted")) is bool, "review_malformed", "accepted")
    refuse(type(result.get("execution_ref")) is str and REFERENCE.fullmatch(result["execution_ref"]) is not None,
           "review_malformed", "execution_ref")
    accepted = result["accepted"]
    outcome = ("rejected" if not accepted else "accepted" if row["phase"] == "review_conductor" else "lead_accepted")
    return {"decision_id": row.get("id"), "phase": row["phase"], "accepted": accepted, "outcome": outcome,
            "execution_ref": result["execution_ref"], "candidate": dict(candidate)}


# ---- evidence promotion -------------------------------------------------------------------------
def accepted_binding(row: dict) -> dict:
    """What a promotion receipt must name for THIS session: the accepted frozen candidate, the
    archive it was frozen from (with its hashes), and the succeeded independent review that accepted
    it. Refuses when the row holds no such accepted candidate/review/archive triple."""
    refuse(row.get("state") in (ACCEPTED, ARCHIVAL_PENDING, CLOSED), "session_not_accepted", str(row.get("state")))
    candidates = row.get("candidates") or []
    refuse(bool(candidates) and candidates[-1].get("outcome") == "accepted", "promotion_binding_missing", "candidate")
    frozen = candidates[-1]
    reviews = [review for review in row.get("reviews") or [] if review.get("outcome") == "accepted"
               and (review.get("candidate") or {}).get("revision") == frozen["revision"]
               and (review.get("candidate") or {}).get("tree") == frozen["tree"]]
    refuse(len(reviews) == 1, "promotion_binding_missing", "review")
    archives = [entry["archive"] for entry in row.get("checkpoints") or [] if entry["archive"]["ref"] == frozen.get("archive")]
    refuse(bool(archives), "promotion_binding_missing", "archive")
    return {"schema": PROMOTION_SCHEMA, "task_id": row["task_id"], "session_id": row["session_id"],
            "candidate": {key: frozen[key] for key in ("revision", "tree", "base")},
            "archive": {key: archives[-1][key] for key in ("ref", "manifest_sha256", "transcript_sha256")},
            "review": {"decision_id": reviews[0]["decision_id"], "execution_ref": reviews[0]["execution_ref"]}}


def promotion_receipt(row: dict, evidence: list) -> dict:
    """The receipt document the evidence-promotion owner writes into the verified evidence store
    once `evidence` (content-addressed references) is durably promoted for the accepted candidate."""
    return {**accepted_binding(row), "evidence": sorted(set(evidence))}


def validate_promotion(document, row: dict) -> dict:
    """A promotion receipt is bound to this session's exact accepted candidate, archive and review.
    A syntactically valid hash of anything else, or an extra/missing field, is refused."""
    refuse(isinstance(document, dict) and set(document) == {"schema", "task_id", "session_id", "candidate",
                                                            "archive", "review", "evidence"},
           "promotion_receipt_malformed", "fields")
    refuse(document.get("schema") == PROMOTION_SCHEMA, "promotion_receipt_malformed", "schema")
    evidence = document.get("evidence")
    refuse(isinstance(evidence, list) and 0 < len(evidence) <= 64 and len(set(evidence)) == len(evidence)
           and all(type(ref) is str and REFERENCE.fullmatch(ref) is not None for ref in evidence),
           "promotion_receipt_malformed", "evidence")
    expected = accepted_binding(row)
    refuse({key: document[key] for key in expected} == expected, "promotion_receipt_unrelated")
    return {**expected, "evidence": list(evidence)}


# ---- read-only projection -----------------------------------------------------------------------
BLOCKED_STATES = frozenset({ARCHIVE_MISSING, ARCHIVE_CORRUPT, INCOMPATIBLE, UNRESOLVED})


def status_view(row: dict) -> dict:
    """Bounded read-only projection: ids, hashes, states, reasons, the next owner and action; never
    transcript bytes and never the raw binding values (the identity travels as one digest)."""
    last =(row.get("checkpoints") or [None])[-1]
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else None
    return {"task_id": row.get("task_id"), "state": row.get("state"), "session_id": row.get("session_id"),
            "version": row.get("version"), "owner": row.get("owner"),
            "identity_sha256": digest(identity) if identity is not None else None,
            "archive": (last or {}).get("archive"),
            "checkpoints": len(row.get("checkpoints") or []), "candidates": len(row.get("candidates") or []),
            "reviews": [{key: review.get(key) for key in ("decision_id", "phase", "outcome")}
                        for review in row.get("reviews") or []][-8:],
            "reason": row.get("reason"), "blocked": row.get("state") in BLOCKED_STATES or bool(
                (row.get("cleanup") or {}).get("state") == "failed"),
            "next_owner": next_owner(row), "next_action": next_action(row),
            "cleanup": row.get("cleanup"), "promotion": row.get("promotion")}


def next_owner(row: dict) -> str:
    """Who acts next, as a fixed code. A blocked state or a failed cleanup is the operator's."""
    state = row.get("state")
    if row.get("owner"):
        return "execution"
    if state in BLOCKED_STATES or (row.get("cleanup") or {}).get("state") == "failed":
        return "operator"
    return {ACTIVE: "conductor", CHECKPOINTED: "conductor", AWAITING_REVIEW: "independent_review",
            CORRECTION_READY: "conductor", ACCEPTED: "evidence_promotion", ARCHIVAL_PENDING: "session_owner",
            CLOSED: "none"}.get(state, "operator")


def next_action(row: dict) -> str:
    state = row.get("state")
    if row.get("owner"):
        return "owned by a running execution"
    if state == ARCHIVAL_PENDING and (row.get("cleanup") or {}).get("state") == "failed":
        return "operator: repair scratch cleanup, then close again; the archive is retained"
    return {ACTIVE: "no turn adopted yet; the next begin opens a fresh turn",
            CHECKPOINTED: "submit candidate or continue by native resume",
            AWAITING_REVIEW: "wait for the independent review decision (no model calls)",
            CORRECTION_READY: "conductor may admit a correction turn by native resume",
            ACCEPTED: "promote evidence with a bound promotion receipt", ARCHIVAL_PENDING: "confirm closure and cleanup",
            CLOSED: "none", ARCHIVE_MISSING: "owner: restore the archive or hand off fresh evidence",
            ARCHIVE_CORRUPT: "owner: investigate corrupt archive; fresh evidence handoff",
            INCOMPATIBLE: "explicit fresh evidence handoff required",
            UNRESOLVED: "owner: reconcile from retained verified session bytes"}.get(
                state, "operator: unknown state; inspect the row")
