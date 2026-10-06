"""The typed one-use Fleet admission permit of the rebuilt payload (INV-FLEET-001, FA-SPEC + Amendment A).

Layer: domain
Context: coordination
Owns: the permit and template grammar, the closed kind set, the consumption-deadline derivation, the state and close vocabulary and the safe view of the Fleet's admission permits
Does not own: the store, the permit bucket's writes (coordination.application.fleet.admission_permit), the PR-3 maintenance permit (coordination.domain.fleet_maintenance)
Entry points: validate_template, validate_permit, kind_of, build_permit, build_verification_permit, verification_permit_id, consumption_deadline, permit_id_of, permit_view, permit_names_job, expired
Contracts: INV-FLEET-001

A separate bucket from PR-3's `fleet_maintenance_admissions` (Amendment A1): the PR-3 kinds are not generalized and
this module never reads their grammar except to refuse a job a PR-3 permit already names. The closed kind set is
{`delivery_canary`, `verification_job`} (the latter added in its own revertible commit, Amendment A4); an unknown kind is refused before any write.
The `delivery_canary` permit admits ONE job, bound to the OA action's immutable canary binding; the `verification_job` permit admits ONE enumerated V job, bound to its job id, lane, manifest digest and an FA-VPLAN row id and digest (recorded, not interpreted here); the template
(digest-bound, issuer and approver distinct) carries only the window-independent fields. Everything is pure policy over
dictionaries; a refusal carries a fixed code and at most a fixed field name, never a value.
"""
from __future__ import annotations

import re
from datetime import timedelta

from codex_harness.coordination.domain.fleet import TOKEN, FleetRefused
from codex_harness.coordination.domain.fleet_maintenance import (
    BINDING_FIELDS,
    DIGEST_HEX,
    EVIDENCE_REF,
    INSTANCE,
    canary_binding_of,
    instant,
)
from codex_harness.coordination.domain.owner_actions import (
    ACTOR,
    DELIVERY_CANARY,
    action_id,
    canary_job_id,
)
from codex_harness.delivery.domain.host_delivery import AWAITING_CONSUMPTION, MAX_CONSUMPTION_TIMEOUT
from codex_harness.kernel.ids import digest

PERMIT_SCHEMA = "urn:zeus:fleet-admission-permit:1"
TEMPLATE_SCHEMA = "urn:zeus:fleet-admission-permit-template:1"
EXECUTION_SCHEMA = "urn:zeus:fleet-admission-execution:1"
# The closed kind set (FA-SPEC §2, Amendment A1/A4). `maintenance_canary` and `forward_candidate` stay PR-3's.
VERIFICATION_JOB = "verification_job"
KINDS = frozenset({DELIVERY_CANARY, VERIFICATION_JOB})
PERMIT_ID = re.compile(r"^fleet_admission:[0-9a-f]{64}$")
TEMPLATE_FIELDS = frozenset({"schema", "kind", "plan_id", "plan_sha256", "target_id", "lane", "evidence_ref",
                             "issuer", "approver"})
PERMIT_FIELDS = frozenset({"schema", "kind", "permit_id", "evidence_ref", *BINDING_FIELDS, "action_id", "job_id",
                           "lane", "manifest_sha256", "deadline", "issuer", "approver", "template_sha256"})
# `verification_job` (Amendment A4): the V job's own binding, no owner action and no consumption record; the deadline is
# the template's (each V job gets a manifest digest and a deadline in the owner record).
VERIFICATION_BINDING = ("job_id", "lane", "manifest_sha256", "vplan_row_id", "vplan_row_sha256")
VERIFICATION_TEMPLATE_FIELDS = frozenset({"schema", "kind", "evidence_ref", "deadline", "issuer", "approver",
                                          *VERIFICATION_BINDING})
VERIFICATION_PERMIT_FIELDS = frozenset({"schema", "kind", "permit_id", "evidence_ref", "deadline", "issuer", "approver",
                                        "template_sha256", *VERIFICATION_BINDING})

GRANTED, ACKNOWLEDGED, ADMITTED, CLOSED = "granted", "acknowledged", "admitted", "closed"
PERMIT_STATES = frozenset({GRANTED, ACKNOWLEDGED, ADMITTED, CLOSED})
PERMIT_SETTLED, PERMIT_EXPIRED, PERMIT_CANCELLED = "permit_settled", "permit_expired", "permit_cancelled"
CLOSE_REASONS = frozenset({PERMIT_SETTLED, PERMIT_EXPIRED, PERMIT_CANCELLED})
# Closing without a launch: the queued job is failed with the reason and no process ever existed.
UNLAUNCHED_REASONS = frozenset({PERMIT_EXPIRED, PERMIT_CANCELLED})

PERMIT_VIEW_FIELDS = ("permit_id", "kind", "permit_sha256", "state", "action_id", "job_id", "deadline", "lane",
                      "manifest_sha256", "granted_at", "acknowledged_at", "admitted_at", "closed_at", "close_reason",
                      "job_status", "launched")


def _str(value, pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def kind_of(document) -> str:
    """The kind of a template or permit; absent, non-string or unknown is refused before anything else is read."""
    kind = document.get("kind") if isinstance(document, dict) else None
    if type(kind) is not str or kind not in KINDS:
        raise FleetRefused("permit_invalid", "kind")
    return kind


def permit_id_of(identity: str) -> str:
    """One permit per owner canary action: the deterministic id of the action's binding."""
    return "fleet_admission:" + identity


def validate_template(template) -> dict:
    """Exact keys and grammar of the digest-bound permit template; returns the canonical copy."""
    if kind_of(template) == VERIFICATION_JOB:
        return _validate_verification_template(template)
    if not isinstance(template, dict) or set(template) != TEMPLATE_FIELDS:
        raise FleetRefused("permit_invalid", "template")
    if template["schema"] != TEMPLATE_SCHEMA:
        raise FleetRefused("permit_invalid", "schema")
    for key, pattern in (("plan_id", TOKEN), ("plan_sha256", DIGEST_HEX), ("target_id", TOKEN), ("lane", TOKEN),
                         ("evidence_ref", EVIDENCE_REF), ("issuer", ACTOR), ("approver", ACTOR)):
        if not _str(template[key], pattern):
            raise FleetRefused("permit_invalid", key)
    if template["issuer"] == template["approver"]:
        raise FleetRefused("permit_invalid", "approver")
    return {key: template[key] for key in sorted(TEMPLATE_FIELDS)}


def _validate_verification_template(template: dict) -> dict:
    if set(template) != VERIFICATION_TEMPLATE_FIELDS:
        raise FleetRefused("permit_invalid", "template")
    if template["schema"] != TEMPLATE_SCHEMA:
        raise FleetRefused("permit_invalid", "schema")
    for key, pattern in (("job_id", TOKEN), ("lane", TOKEN), ("manifest_sha256", DIGEST_HEX), ("vplan_row_id", TOKEN),
                         ("vplan_row_sha256", DIGEST_HEX), ("evidence_ref", EVIDENCE_REF), ("issuer", ACTOR),
                         ("approver", ACTOR)):
        if not _str(template[key], pattern):
            raise FleetRefused("permit_invalid", key)
    if template["issuer"] == template["approver"]:
        raise FleetRefused("permit_invalid", "approver")
    if instant(template["deadline"]) is None:
        raise FleetRefused("permit_invalid", "deadline")
    return {key: template[key] for key in sorted(VERIFICATION_TEMPLATE_FIELDS)}


def verification_permit_id(binding: dict) -> str:
    """One permit per enumerated V job binding: the deterministic id of exactly these fields."""
    return permit_id_of(digest({"kind": VERIFICATION_JOB, **{key: binding[key] for key in VERIFICATION_BINDING}}))


def build_verification_permit(template: dict, template_sha256: str, now: str) -> dict:
    """The permit of ONE enumerated V job: every field is the owner-approved template's, none caller-supplied; the
    deadline must be fresh and at most the consumption maximum away."""
    end, current = instant(template["deadline"]), instant(now)
    if end is None or current is None:
        raise FleetRefused("permit_invalid", "deadline")
    if current >= end:
        raise FleetRefused("permit_expired", "deadline")
    if end - current > timedelta(seconds=MAX_CONSUMPTION_TIMEOUT):
        raise FleetRefused("permit_invalid", "deadline")
    permit = {"schema": PERMIT_SCHEMA, "kind": VERIFICATION_JOB, "permit_id": verification_permit_id(template),
              "evidence_ref": template["evidence_ref"], "deadline": template["deadline"],
              "issuer": template["issuer"], "approver": template["approver"], "template_sha256": template_sha256,
              **{key: template[key] for key in VERIFICATION_BINDING}}
    return validate_permit(permit)


def build_permit(template: dict, template_sha256: str, action: dict, job: dict, deadline: str) -> dict:
    """The permit of ONE owner canary: the binding, action and job ids come from the real action row, the lane and
    manifest digest from its queued job and the deadline from the consumption record; nothing is caller-supplied."""
    binding = action.get("binding") if isinstance(action, dict) else None
    if not isinstance(binding, dict) or set(binding) != set(BINDING_FIELDS):
        raise FleetRefused("permit_refused", "action")
    permit = {"schema": PERMIT_SCHEMA, "kind": kind_of(template), "permit_id": permit_id_of(str(action.get("id"))),
              "evidence_ref": template["evidence_ref"], **{key: binding[key] for key in BINDING_FIELDS},
              "action_id": action.get("id"), "job_id": action.get("job_id"), "lane": job.get("lane"),
              "manifest_sha256": job.get("manifest_sha256"), "deadline": deadline, "issuer": template["issuer"],
              "approver": template["approver"], "template_sha256": template_sha256}
    return validate_permit(permit)


def validate_permit(permit) -> dict:
    """Exact keys and grammar of the stored permit; returns the canonical copy.

    The action id must be the owner action identity of exactly the binding and the job id the owner canary job id of
    that action, so a permit can only name the canary job the unchanged owner-actions code creates for the new
    instance. The kind is checked first: an unknown kind never reaches a store."""
    if kind_of(permit) == VERIFICATION_JOB:
        return _validate_verification_permit(permit)
    if not isinstance(permit, dict) or set(permit) != PERMIT_FIELDS:
        raise FleetRefused("permit_invalid", "permit")
    if permit["schema"] != PERMIT_SCHEMA:
        raise FleetRefused("permit_invalid", "schema")
    for key, pattern in (("permit_id", PERMIT_ID), ("evidence_ref", EVIDENCE_REF), ("plan_id", TOKEN),
                         ("plan_sha256", DIGEST_HEX), ("target_id", TOKEN), ("descriptor_sha256", DIGEST_HEX),
                         ("instance_id", INSTANCE), ("action_id", DIGEST_HEX), ("lane", TOKEN),
                         ("manifest_sha256", DIGEST_HEX), ("issuer", ACTOR), ("approver", ACTOR),
                         ("template_sha256", DIGEST_HEX)):
        if not _str(permit[key], pattern):
            raise FleetRefused("permit_invalid", key)
    if permit["action_id"] != action_id(DELIVERY_CANARY, canary_binding_of(permit)):
        raise FleetRefused("permit_invalid", "action_id")
    if permit["permit_id"] != permit_id_of(permit["action_id"]):
        raise FleetRefused("permit_invalid", "permit_id")
    if type(permit["job_id"]) is not str or permit["job_id"] != canary_job_id(permit["action_id"]):
        raise FleetRefused("permit_invalid", "job_id")
    if permit["issuer"] == permit["approver"]:
        raise FleetRefused("permit_invalid", "approver")
    if instant(permit["deadline"]) is None:
        raise FleetRefused("permit_invalid", "deadline")
    return {key: permit[key] for key in sorted(PERMIT_FIELDS)}


def _validate_verification_permit(permit: dict) -> dict:
    if set(permit) != VERIFICATION_PERMIT_FIELDS:
        raise FleetRefused("permit_invalid", "permit")
    if permit["schema"] != PERMIT_SCHEMA:
        raise FleetRefused("permit_invalid", "schema")
    for key, pattern in (("permit_id", PERMIT_ID), ("job_id", TOKEN), ("lane", TOKEN), ("manifest_sha256", DIGEST_HEX),
                         ("vplan_row_id", TOKEN), ("vplan_row_sha256", DIGEST_HEX), ("evidence_ref", EVIDENCE_REF),
                         ("issuer", ACTOR), ("approver", ACTOR), ("template_sha256", DIGEST_HEX)):
        if not _str(permit[key], pattern):
            raise FleetRefused("permit_invalid", key)
    if permit["permit_id"] != verification_permit_id(permit):
        raise FleetRefused("permit_invalid", "permit_id")
    if permit["issuer"] == permit["approver"]:
        raise FleetRefused("permit_invalid", "approver")
    if instant(permit["deadline"]) is None:
        raise FleetRefused("permit_invalid", "deadline")
    return {key: permit[key] for key in sorted(VERIFICATION_PERMIT_FIELDS)}


def expired(deadline: str, now: str) -> bool:
    """`now >= deadline`; an unreadable instant is a contract error, never either side of the deadline."""
    end, current = instant(deadline), instant(now)
    if end is None or current is None:
        raise FleetRefused("permit_invalid", "deadline")
    return current >= end


def consumption_deadline(intent, binding: dict, now: str) -> str:
    """The deadline of the consumption record (A2): the delivery of exactly this plan, target and descriptor still
    awaits consumption and states its stage deadline, which is fresh and at most the consumption maximum away."""
    if not (isinstance(intent, dict) and intent.get("stage") == AWAITING_CONSUMPTION
            and intent.get("plan_sha256") == binding["plan_sha256"] and intent.get("target_id") == binding["target_id"]
            and intent.get("descriptor_sha256") == binding["descriptor_sha256"]):
        raise FleetRefused("permit_refused", "consumption")
    deadline = intent.get("stage_deadline")
    end, current = instant(deadline), instant(now)
    if end is None or current is None:
        raise FleetRefused("permit_refused", "consumption")
    if current >= end:
        raise FleetRefused("permit_expired", "deadline")
    if end - current > timedelta(seconds=MAX_CONSUMPTION_TIMEOUT):
        raise FleetRefused("permit_invalid", "deadline")
    return deadline


def permit_names_job(maintenance_row, job_id: str, action_ids) -> bool:
    """A PR-3 maintenance permit row (read only) already names this job or one of its owner actions."""
    permit = maintenance_row.get("permit") if isinstance(maintenance_row, dict) else None
    return isinstance(permit, dict) and (permit.get("job_id") == job_id or maintenance_row.get("job_id") == job_id
                                         or permit.get("action_id") in action_ids)


def permit_view(row: dict) -> dict:
    """The safe projection of one permit row: identities, digests, states and times. Never the admitted job's owner
    token, the acknowledgement or the evidence document."""
    permit = row.get("permit") if isinstance(row.get("permit"), dict) else {}
    view = {key: row.get(key) for key in PERMIT_VIEW_FIELDS}
    view.update(permit_id=row.get("id"), kind=permit.get("kind"), action_id=permit.get("action_id"),
                job_id=permit.get("job_id"), deadline=permit.get("deadline"))
    return view


__all__ = ["ACKNOWLEDGED", "ADMITTED", "CLOSED", "CLOSE_REASONS", "EXECUTION_SCHEMA", "GRANTED", "KINDS",
           "PERMIT_CANCELLED", "PERMIT_EXPIRED", "PERMIT_FIELDS", "PERMIT_ID", "PERMIT_SCHEMA", "PERMIT_SETTLED",
           "PERMIT_STATES", "PERMIT_VIEW_FIELDS", "TEMPLATE_FIELDS", "TEMPLATE_SCHEMA", "UNLAUNCHED_REASONS", "VERIFICATION_BINDING", "VERIFICATION_JOB",
           "VERIFICATION_PERMIT_FIELDS", "VERIFICATION_TEMPLATE_FIELDS", "build_verification_permit",
           "verification_permit_id",
           "build_permit", "consumption_deadline", "expired", "kind_of", "permit_id_of",
           "permit_names_job", "permit_view", "validate_permit", "validate_template"]
