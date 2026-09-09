"""Exact-revision acceptance contracts; signatures and IO belong to adapters."""
import re
from datetime import datetime, timedelta, timezone

from codex_harness.domain.model import ContractError, digest, require

HASH = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
REF = re.compile(r"sha256:[0-9a-f]{64}")


def timestamp(value):
    require(isinstance(value, str), "Timestamp required")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContractError("Invalid lifecycle timestamp") from exc
    require(result.tzinfo is not None, "Timestamp must include timezone")
    return result


def validate_packet(packet, ticket, policy, now=None):
    keys = {"version", "ticket_id", "revision", "content_hash", "sequence", "expected_status",
            "solution_commit", "policy_commit", "policy_hash", "scope", "criteria", "criteria_hash",
            "environment_ref", "issued_at", "expires_at", "reason"}
    require(isinstance(packet, dict) and set(packet) == keys and type(packet["version"]) is int
            and packet["version"] == 1, "Invalid closure packet")
    require(type(packet["revision"]) is int and type(packet["sequence"]) is int
            and packet["revision"] == ticket["revision"] and packet["sequence"] == ticket.get("lifecycle_sequence", 0)
            and packet["ticket_id"] == ticket["id"] and packet["content_hash"] == ticket["content_hash"]
            and packet["expected_status"] == ticket["status"] and ticket["status"] in {"open", "dispatched"},
            "Stale closure ticket revision, sequence or state")
    require(all(packet[k] == policy[k] for k in ("policy_commit", "policy_hash", "scope")),
            "Closure trust policy changed")
    require(isinstance(packet["solution_commit"], str) and COMMIT.fullmatch(packet["solution_commit"]),
            "Full solution commit required")
    require(isinstance(packet["reason"], str) and 0 < len(packet["reason"].strip()) <= 4000,
            "Closure reason required")
    now = now or datetime.now(timezone.utc)
    issued, expires = timestamp(packet["issued_at"]), timestamp(packet["expires_at"])
    require(issued <= now < expires and timedelta(0) < expires - issued <= timedelta(hours=24),
            "Closure grant expired, future-dated or too long")
    require(issued >= timestamp(ticket.get("updated_at", ticket["created_at"])),
            "Closure predates ticket revision")
    criteria = ticket["content"]["acceptance_criteria"]
    require(packet["criteria_hash"] == digest(criteria) and isinstance(packet["criteria"], list)
            and len(packet["criteria"]) == len(criteria), "Closure must cover every acceptance criterion")
    refs = set()
    for index, row in enumerate(packet["criteria"]):
        require(isinstance(row, dict) and set(row) == {"index", "criterion_hash", "outcome", "evidence_refs"}
                and type(row["index"]) is int and row["index"] == index
                and row["criterion_hash"] == digest(criteria[index]), "Acceptance criterion identity mismatch")
        require(row["outcome"] == "passed", "Every acceptance criterion must pass")
        require(isinstance(row["evidence_refs"], list) and 0 < len(row["evidence_refs"]) <= 20
                and all(isinstance(ref, str) and REF.fullmatch(ref) for ref in row["evidence_refs"]),
                "Immutable criterion evidence required")
        refs.update(row["evidence_refs"])
    require(isinstance(packet["environment_ref"], str) and REF.fullmatch(packet["environment_ref"]),
            "Immutable environment evidence required")
    refs.add(packet["environment_ref"])
    return refs


def validate_evidence(document, packet, *, environment=False):
    """Evidence is an attested, bound observation; a naked `passed` flag has no authority."""
    require(isinstance(document, dict) and document.get("kind") ==
            ("ticket-environment-v1" if environment else "ticket-criterion-evidence-v1"),
            "Wrong closure evidence kind")
    require(all(document.get(k) == packet[k] for k in ("ticket_id", "revision", "content_hash", "solution_commit")),
            "Stale or unrelated closure evidence")
    require(type(document.get("revision")) is int, "Evidence revision must be an integer")
    observed = timestamp(document.get("observed_at"))
    require(observed <= timestamp(packet["issued_at"]), "Evidence postdates signed closure packet")
    require(isinstance(document.get("details"), dict) and document["details"], "Evidence details required")
    if not environment:
        require(document.get("outcome") == "passed" and type(document.get("criterion_index")) is int,
                "Criterion evidence must record a passing observation")
