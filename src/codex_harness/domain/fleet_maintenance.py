"""The one-job maintenance canary permit of an active-generation maintenance (INV-FLEET-001 amendment,
INV-HOST-DELIVERY-MAINTENANCE-001).

A maintenance permit is an operator-authorized, one-use admission for exactly ONE owner-created canary
job while the Fleet stays owner-paused. It is not a budget, a scheduler grant or a resume: every other
admission blocker still applies, and the job it may admit is derived from the owner action's immutable
binding, never taken from the caller. The lane (HostDelivery) builds the permit and pins the proof from
its own generation record; the Fleet stores the permit in `fleet_maintenance_admissions` and validates
both here. Everything is pure policy over dictionaries; a refusal carries a fixed code and at most a
fixed field name, never a value.
"""
from __future__ import annotations

import re
from datetime import datetime

from codex_harness.domain.fleet import QUEUED, RESERVING, TOKEN, FleetRefused
from codex_harness.domain.model import digest
from codex_harness.domain.owner_actions import DELIVERY_CANARY, REQUESTED, action_id, canary_job_id

PERMIT_SCHEMA = "urn:zeus:fleet-maintenance-permit:1"
EXECUTION_SCHEMA = "urn:zeus:fleet-maintenance-execution:1"
BINDING_FIELDS = ("plan_id", "plan_sha256", "target_id", "descriptor_sha256", "instance_id")
PERMIT_FIELDS = frozenset({"schema", "maintenance_id", "evidence_ref", *BINDING_FIELDS, "action_id", "job_id",
                           "deadline"})
PROOF_FIELDS = frozenset({"maintenance_id", "permit_sha256", "generation_state", "acknowledged", "deadline",
                          "instance_id", "descriptor_sha256"})
MAINTENANCE_ID = re.compile(r"^active_generation_1:[0-9a-f]{64}$")
EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_HEX = re.compile(r"^[0-9a-f]{64}$")
INSTANCE = re.compile(r"^[0-9a-f]{32}$")
MAX_INSTANT_CHARS = 64

GRANTED, ADMITTED, CLOSED = "granted", "admitted", "closed"
PERMIT_STATES = frozenset({GRANTED, ADMITTED, CLOSED})
MAINTENANCE_EXPIRED = "maintenance_expired"
MAINTENANCE_CANCELLED = "maintenance_cancelled"
MAINTENANCE_SETTLED = "maintenance_settled"
CLOSE_REASONS = frozenset({MAINTENANCE_EXPIRED, MAINTENANCE_CANCELLED, MAINTENANCE_SETTLED})
# Closing without a launch: the queued canary is failed with the reason and no process ever existed.
UNLAUNCHED_REASONS = frozenset({MAINTENANCE_EXPIRED, MAINTENANCE_CANCELLED})
ARMED = "armed"
# INV-OWNER-ACTIONS-001 control-store bucket; the Fleet only READS the owner action here.
OWNER_ACTIONS_BUCKET = "owner_actions"

PERMIT_VIEW_FIELDS = ("maintenance_id", "permit_sha256", "state", "action_id", "job_id", "deadline", "lane",
                      "manifest_sha256", "granted_at", "admitted_at", "closed_at", "close_reason", "job_status",
                      "launched")


def _str(value, pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def instant(value) -> datetime | None:
    """An explicit timezone-aware ISO 8601 instant of bounded length, or None."""
    if type(value) is not str or not 1 <= len(value) <= MAX_INSTANT_CHARS:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def deadline_passed(deadline: str, now: str) -> bool:
    """`now >= deadline`. The Fleet clock is always an aware instant; an unreadable one is refused as a
    contract error rather than read as either side of the deadline."""
    end, current = instant(deadline), instant(now)
    if end is None or current is None:
        raise FleetRefused("maintenance_invalid", "deadline")
    return current >= end


def canary_binding_of(permit: dict) -> dict:
    """The owner canary binding (`domain.owner_actions.canary_binding`) the permit names."""
    return {key: permit[key] for key in BINDING_FIELDS}


def validate_permit(permit) -> dict:
    """Exact keys and grammar of the one-job permit; returns the canonical copy.

    The job id must be the owner canary job id of the action, and the action id must be the owner
    action identity of exactly this binding, so a permit can only ever name the canary job the
    unchanged owner-actions code would create for this generation's new instance."""
    if not isinstance(permit, dict) or set(permit) != PERMIT_FIELDS:
        raise FleetRefused("maintenance_invalid", "permit")
    if permit["schema"] != PERMIT_SCHEMA:
        raise FleetRefused("maintenance_invalid", "schema")
    checks = (("maintenance_id", MAINTENANCE_ID), ("evidence_ref", EVIDENCE_REF), ("plan_id", TOKEN),
              ("plan_sha256", DIGEST_HEX), ("target_id", TOKEN), ("descriptor_sha256", DIGEST_HEX),
              ("instance_id", INSTANCE), ("action_id", DIGEST_HEX))
    for key, pattern in checks:
        if not _str(permit[key], pattern):
            raise FleetRefused("maintenance_invalid", key)
    if permit["action_id"] != action_id(DELIVERY_CANARY, canary_binding_of(permit)):
        raise FleetRefused("maintenance_invalid", "action_id")
    if type(permit["job_id"]) is not str or permit["job_id"] != canary_job_id(permit["action_id"]):
        raise FleetRefused("maintenance_invalid", "job_id")
    if instant(permit["deadline"]) is None:
        raise FleetRefused("maintenance_invalid", "deadline")
    return {key: permit[key] for key in sorted(PERMIT_FIELDS)}


def permit_digest(permit) -> str:
    return digest(validate_permit(permit))


def owner_action_matches(permit: dict, action) -> bool:
    """The stored owner action IS this permit's canary action: identity, kind, immutable binding and
    digest, and the deterministic job id. The action's state is not part of the identity."""
    binding = canary_binding_of(permit)
    return (isinstance(action, dict) and action.get("id") == permit["action_id"]
            and permit["action_id"] == action_id(DELIVERY_CANARY, binding)
            and action.get("kind") == DELIVERY_CANARY and action.get("binding") == binding
            and action.get("binding_sha256") == digest(binding) and action.get("job_id") == permit["job_id"])


def check_owner_action(permit: dict, action) -> None:
    """Admission needs the REAL owner action, still REQUESTED, under exactly the permit's binding; the
    job id comes from that action, never from the caller (INV-OWNER-ACTIONS-001)."""
    if not (owner_action_matches(permit, action) and action.get("state") == REQUESTED):
        raise FleetRefused("maintenance_admission_refused", "action")


def check_canary_job(permit: dict, job) -> None:
    """The job is exactly the permit's canary job and still QUEUED (never dispatched before)."""
    if not (isinstance(job, dict) and job.get("id") == permit["job_id"] and job.get("status") == QUEUED):
        raise FleetRefused("maintenance_admission_refused", "job")


def validate_proof(proof, permit: dict, permit_sha256: str) -> dict:
    """The lane's current-generation proof: the acknowledged ARMED generation of exactly this permit.

    An orphan grant (lane request lost, never acknowledged) or a generation that moved on has no such
    proof, so it cannot launch anything."""
    if not (isinstance(proof, dict) and set(proof) == PROOF_FIELDS
            and proof["maintenance_id"] == permit["maintenance_id"]
            and type(proof["permit_sha256"]) is str and proof["permit_sha256"] == permit_sha256
            and proof["generation_state"] == ARMED and proof["acknowledged"] is True
            and proof["deadline"] == permit["deadline"] and proof["instance_id"] == permit["instance_id"]
            and proof["descriptor_sha256"] == permit["descriptor_sha256"]):
        raise FleetRefused("maintenance_admission_refused", "proof")
    return {key: proof[key] for key in sorted(PROOF_FIELDS)}


def permit_view(row: dict) -> dict:
    """The safe projection of one permit row: identities, digests, states and times. Never the
    admitted job's owner token, the lane acknowledgement or the evidence document."""
    permit = row.get("permit") if isinstance(row.get("permit"), dict) else {}
    view = {key: row.get(key) for key in PERMIT_VIEW_FIELDS}
    view.update(action_id=permit.get("action_id"), job_id=permit.get("job_id"), deadline=permit.get("deadline"))
    return view


def open_permit(row: dict, job) -> bool:
    """Maintenance control debt: the permit is not closed, or it is closed while its canary job is
    still queued (a stale canary enqueued after the close must be failed before any ordinary resume)
    or still reserving."""
    if row.get("state") != CLOSED:
        return True
    return isinstance(job, dict) and (job.get("status") == QUEUED or job.get("status") in RESERVING)


__all__ = ["ADMITTED", "ARMED", "BINDING_FIELDS", "CLOSED", "CLOSE_REASONS", "EXECUTION_SCHEMA", "GRANTED",
           "MAINTENANCE_CANCELLED", "MAINTENANCE_EXPIRED", "MAINTENANCE_ID", "MAINTENANCE_SETTLED",
           "OWNER_ACTIONS_BUCKET", "PERMIT_FIELDS", "PERMIT_SCHEMA", "PERMIT_STATES", "PERMIT_VIEW_FIELDS",
           "PROOF_FIELDS", "UNLAUNCHED_REASONS", "canary_binding_of", "check_canary_job", "check_owner_action",
           "deadline_passed", "instant", "open_permit", "owner_action_matches", "permit_digest", "permit_view",
           "validate_permit", "validate_proof"]
