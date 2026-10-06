"""The one-job maintenance canary permit of an active-generation maintenance, and the typed forward-candidate permit (INV-FLEET-001
maintenance amendment, INV-HOST-DELIVERY-MAINTENANCE-001).

Layer: domain
Context: coordination
Owns: the permit grammar, proof, job/owner-action/backlog-item checks, open-permit debt and safe view of the Fleet's maintenance permits
Does not own: the store, the permit bucket's writes (coordination.application.fleet.maintenance), the lane that builds the permit (delivery)
Entry points: validate_permit, validate_proof, kind_of, validate_forward_permit, check_owner_action, check_canary_job, check_forward_job, check_backlog_item, open_permit, permit_view, owner_action_matches, deadline_passed
Contracts: INV-FLEET-001, INV-HOST-DELIVERY-MAINTENANCE-001

Ported from PR-3 (`feat/host-delivery-maintain-pr3`, e6e15f00 `domain/fleet_maintenance.py`); the bodies are PR-3's.

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

from codex_harness.coordination.domain.fleet import QUEUED, RESERVING, TOKEN, FleetRefused
from codex_harness.coordination.domain.owner_actions import (
    DELIVERY_CANARY,
    REQUESTED,
    action_id,
    canary_job_id,
)
from codex_harness.kernel.ids import digest

PERMIT_SCHEMA = "urn:zeus:fleet-maintenance-permit:1"
EXECUTION_SCHEMA = "urn:zeus:fleet-maintenance-execution:1"
BINDING_FIELDS = ("plan_id", "plan_sha256", "target_id", "descriptor_sha256", "instance_id")
PERMIT_FIELDS = frozenset({"schema", "maintenance_id", "evidence_ref", *BINDING_FIELDS, "action_id", "job_id",
                           "deadline"})
# The typed permit kinds (G1-04c). `maintenance_canary` is the original row and the default of every
# permit without a `kind`; its canonical form never carries the field, so existing digests are unchanged.
MAINTENANCE_CANARY, FORWARD_CANDIDATE = "maintenance_canary", "forward_candidate"
PERMIT_KINDS = frozenset({MAINTENANCE_CANARY, FORWARD_CANDIDATE})
FORWARD_FIELDS = frozenset({"schema", "kind", "maintenance_id", "evidence_ref", "backlog_item_id", "manifest_sha256",
                            "lane", "base_revision", "allowed_paths", "deadline", "issuer", "approver"})
# A forward candidate may only touch paths under these prefixes (AMD-1 D.2): nothing that ships.
NON_SHIPPED_PREFIXES = ("docs/cutover/",)
MAX_ALLOWED_PATHS = 16
BASE_REVISION = re.compile(r"^[0-9a-f]{40}$")
ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
FORWARD_PROOF_FIELDS = frozenset({"maintenance_id", "permit_sha256", "acknowledged", "deadline"})
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


def kind_of(permit) -> str:
    """The permit kind: `maintenance_canary` when the field is absent. An unknown or non-string kind is
    refused before anything else is read."""
    kind = permit.get("kind", MAINTENANCE_CANARY) if isinstance(permit, dict) else MAINTENANCE_CANARY
    if type(kind) is not str or kind not in PERMIT_KINDS:
        raise FleetRefused("maintenance_invalid", "kind")
    return kind


def _non_shipped_path(path) -> bool:
    """Canonical, relative, glob-free and under a non-shipped prefix; `..`, absolute and backslash forms fail."""
    if type(path) is not str or not path or path.startswith("/") or "\\" in path or any(c in path for c in "*?[]{}"):
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts) or path[-1] == "/":
        return False
    return any(path.startswith(prefix) and len(path) > len(prefix) for prefix in NON_SHIPPED_PREFIXES)


def validate_forward_permit(permit) -> dict:
    """Exact keys and grammar of the typed `forward_candidate` permit (G1-03 ruling g, DEC-CAND option 1).

    It binds one owner-registered backlog item, its job manifest digest, the lane, a full base commit
    and a closed list of non-shipped paths; the Fleet derives the one job from the digest, never from
    the caller. The registered item is checked by the Fleet against its backlog plans."""
    if not isinstance(permit, dict) or set(permit) != FORWARD_FIELDS:
        raise FleetRefused("maintenance_invalid", "permit")
    if permit["schema"] != PERMIT_SCHEMA:
        raise FleetRefused("maintenance_invalid", "schema")
    checks = (("maintenance_id", MAINTENANCE_ID), ("evidence_ref", EVIDENCE_REF), ("backlog_item_id", TOKEN),
              ("manifest_sha256", DIGEST_HEX), ("lane", TOKEN), ("base_revision", BASE_REVISION),
              ("issuer", ACTOR), ("approver", ACTOR))
    for key, pattern in checks:
        if not _str(permit[key], pattern):
            raise FleetRefused("maintenance_invalid", key)
    if permit["issuer"] == permit["approver"]:
        raise FleetRefused("maintenance_invalid", "approver")
    paths = permit["allowed_paths"]
    if type(paths) is not list or not 1 <= len(paths) <= MAX_ALLOWED_PATHS or len(set(paths)) != len(paths):
        raise FleetRefused("maintenance_invalid", "allowed_paths")
    if not all(_non_shipped_path(path) for path in paths):
        raise FleetRefused("path_not_non_shipped", "allowed_paths")
    if instant(permit["deadline"]) is None:
        raise FleetRefused("maintenance_invalid", "deadline")
    return {**{key: permit[key] for key in sorted(FORWARD_FIELDS)}, "allowed_paths": list(paths)}


def validate_permit(permit) -> dict:
    """Exact keys and grammar of the one-job permit; returns the canonical copy.

    The job id must be the owner canary job id of the action, and the action id must be the owner
    action identity of exactly this binding, so a permit can only ever name the canary job the
    unchanged owner-actions code would create for this generation's new instance."""
    if kind_of(permit) == FORWARD_CANDIDATE:
        return validate_forward_permit(permit)
    if isinstance(permit, dict) and permit.get("kind") == MAINTENANCE_CANARY:
        permit = {key: value for key, value in permit.items() if key != "kind"}
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


def check_forward_job(permit: dict, job) -> None:
    """The job is exactly the forward candidate the permit binds: still QUEUED, the bound manifest digest and
    lane, the bound base revision, and no path outside the permit's own (non-shipped) allowed paths."""
    manifest = job.get("manifest") if isinstance(job, dict) else None
    plan = manifest.get("plan") if isinstance(manifest, dict) else None
    paths = plan.get("allowed_paths") if isinstance(plan, dict) else None
    goal = job.get("goal") if isinstance(job, dict) else None
    if not (isinstance(job, dict) and job.get("status") == QUEUED and job.get("manifest_sha256") == permit["manifest_sha256"]
            and job.get("lane") == permit["lane"] and isinstance(goal, dict)
            and goal.get("base_revision") == permit["base_revision"]):
        raise FleetRefused("maintenance_admission_refused", "job")
    if type(paths) is not list or not paths or not all(path in permit["allowed_paths"] for path in paths):
        raise FleetRefused("maintenance_admission_refused", "path_not_non_shipped")


def check_backlog_item(permit: dict, plans, code: str = "maintenance_admission_refused") -> None:
    """The permit's backlog item exists in an owner-registered backlog plan (a Git-pinned owner document
    registered through `BacklogRegistry.register`) under exactly the permit's lane and manifest digest."""
    for row in plans:
        for item in (row.get("plan") or {}).get("items", ()):
            if (item.get("id") == permit["backlog_item_id"] and item.get("lane") == permit["lane"]
                    and item.get("manifest_sha256") == permit["manifest_sha256"]):
                return
    raise FleetRefused(code, "backlog_item")


def validate_proof(proof, permit: dict, permit_sha256: str) -> dict:
    """The lane's current-generation proof: the acknowledged ARMED generation of exactly this permit.

    An orphan grant (lane request lost, never acknowledged) or a generation that moved on has no such
    proof, so it cannot launch anything. A forward candidate has no generation: its proof is the lane's
    acknowledgement of exactly this permit and deadline."""
    if kind_of(permit) == FORWARD_CANDIDATE:
        if not (isinstance(proof, dict) and set(proof) == FORWARD_PROOF_FIELDS
                and proof["maintenance_id"] == permit["maintenance_id"]
                and type(proof["permit_sha256"]) is str and proof["permit_sha256"] == permit_sha256
                and proof["acknowledged"] is True and proof["deadline"] == permit["deadline"]):
            raise FleetRefused("maintenance_admission_refused", "proof")
        return {key: proof[key] for key in sorted(FORWARD_PROOF_FIELDS)}
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
    if permit.get("kind") == FORWARD_CANDIDATE:
        view.update(kind=FORWARD_CANDIDATE, job_id=row.get("job_id"), backlog_item_id=permit.get("backlog_item_id"))
    return view


def open_permit(row: dict, job) -> bool:
    """Maintenance control debt: the permit is not closed, or it is closed while its canary job is
    still queued (a stale canary enqueued after the close must be failed before any ordinary resume)
    or still reserving."""
    if row.get("state") != CLOSED:
        return True
    return isinstance(job, dict) and (job.get("status") == QUEUED or job.get("status") in RESERVING)


__all__ = ["ADMITTED", "ARMED", "BINDING_FIELDS", "CLOSED", "CLOSE_REASONS", "EXECUTION_SCHEMA", "FORWARD_CANDIDATE",
           "FORWARD_FIELDS", "FORWARD_PROOF_FIELDS", "GRANTED", "MAINTENANCE_CANARY", "NON_SHIPPED_PREFIXES",
           "PERMIT_KINDS", "check_backlog_item", "check_forward_job", "kind_of", "validate_forward_permit",
           "MAINTENANCE_CANCELLED", "MAINTENANCE_EXPIRED", "MAINTENANCE_ID", "MAINTENANCE_SETTLED",
           "OWNER_ACTIONS_BUCKET", "PERMIT_FIELDS", "PERMIT_SCHEMA", "PERMIT_STATES", "PERMIT_VIEW_FIELDS",
           "PROOF_FIELDS", "UNLAUNCHED_REASONS", "canary_binding_of", "check_canary_job", "check_owner_action",
           "deadline_passed", "instant", "open_permit", "owner_action_matches", "permit_digest", "permit_view",
           "validate_permit", "validate_proof"]
