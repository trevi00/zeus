"""Owner-action state shared by the scheduler and its families: bucket names, the migration control
vocabulary, the lost-race exception and the pure module helpers.

Layer: application
Context: coordination
Owns: names and pure helpers (no writes)
Does not own: any write (the ActionStore and the families own them)
Entry points: ActionChanged, plan_json, digest_bytes, migration_ack
Contracts: INV-OWNER-ACTIONS-001, INV-OWNER-ACTIONS-MIGRATION-001

Split from M7 `application/owner_actions.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §4,
A/evidence/rebuild/s6/owner-actions-split/split_owner_actions.py); the bodies are M7's.
"""

from __future__ import annotations

import copy
import hashlib
import re

from codex_harness.coordination.domain.continuation import DELIVERY, MIGRATION_SOURCE_STATES, migration_source
from codex_harness.coordination.domain.owner_actions import (
    COMPLETED,
    EVIDENCE_REF,
    INTENDED,
    REFUSED,
    UNKNOWN,
    OwnerActionRefused,
    canary_request,
)
from codex_harness.delivery.domain.host_delivery import (
    CANARY_FLEET,
    MIGRATION_ACTIVE,
    MIGRATION_REGISTERED,
    migration_lineage_digest,
)
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import canonical, digest

# The research and intake buckets owner actions reads (their writers are research and intake; R3, the S5
# read precedent). Values from SOURCE.
BUCKET_BINDINGS = 'portfolio_bindings'
BUCKET_CYCLES = 'research_program_cycles'
BUCKET_DISPATCHES = 'research_investigation_dispatches'
BUCKET_HEADS = 'research_dispatch_heads'
BUCKET_INVESTIGATIONS = 'portfolio_investigations'
BUCKET_PROGRAMS = 'research_programs'
BUCKET_RECOVERIES = 'research_dispatch_recoveries'
BUCKET_SUCCESSORS = 'research_dispatch_successors'


BUCKET_POLICIES = "owner_action_policies"


BUCKET_ACTIONS = "owner_actions"


CONTINUATION_INTENTS = "continuation_intents"


CONTINUATION_RECEIPTS = "continuation_research_receipts"


CONTINUATION_POLICIES = "continuation_policies"


FLEET_JOBS = "fleet_jobs"


DECISIONS = "decisions_pending"


# INV-OWNER-ACTIONS-MIGRATION-001: the control half of an evaluator migration. A bucket of its own, keyed
# by the rejected SOURCE release, that a coordinator of an older release never scans (its `_advance`
# only knows the three action kinds), so no new kind is ever written into `owner_actions`.
BUCKET_MIGRATIONS = "owner_action_migrations"


FLEET_CONTROL, FLEET_ADMISSION = "fleet_control", "admission"


# The effective delivery binding of a migrated continuation intent, keyed by intent id. The conductor's
# own `release_id` on the intent stays untouched as provenance.
CONTINUATION_BINDINGS = "continuation_effective_bindings"


LANE_MIGRATIONS = "host_delivery_migrations"


EVALUATOR_MIGRATION = "evaluator_migration"


MIGRATION_DOCUMENT_FIELDS = frozenset({"policy_id", "intent_id", "lane", "target_id", "source_release_id",
                                       "source_policy_hash", "candidate_revision", "old_plan_id", "old_plan_sha256",
                                       "approval", "evidence", "actor"})


MIGRATION_APPROVAL_FIELDS = frozenset({"source_release_id", "base", "evaluator_revision", "evaluator_tree",
                                       "patch_sha256", "paths", "evidence", "approved_by"})


# INV-RELEASE-ENVIRONMENT-REVERIFY-001: the second migration kind, an environment reverification of an
# already migrated (and then rejected) successor. The document carries `kind`; an absent `kind` is the
# evaluator migration with its exact old shape, request and identity. The approval is exactly the
# Releases approval shape and must name the same source/plan/intent/policy/target/lane as the document.
ENVIRONMENT_REVERIFICATION = "environment_reverification"


MIGRATION_KINDS = frozenset({EVALUATOR_MIGRATION, ENVIRONMENT_REVERIFICATION})


ENVIRONMENT_APPROVAL_FIELDS = frozenset({"kind", "source_release_id", "source_policy_hash", "old_plan_id",
                                         "old_plan_sha256", "intent_id", "policy_id", "target_id", "lane",
                                         "fix_evidence", "controller_revision", "approved_by"})


_FIX_EVIDENCE = re.compile(r"^sha256:[0-9a-f]{64}$")


_REVISION40 = re.compile(r"^[0-9a-f]{40}$")


# Control states, each naming the step BEFORE its effect: `intended` (lane stage owed), `staged` (lane
# receipt recorded; successor plan action owed), `planning` (successor DELIVERY_PLAN action exists; its
# publication, canary request and held registration owed), `bound` (continuation effective binding
# recorded; the lane readiness acknowledgement owed).
M_STAGED, M_PLANNING, M_BOUND = "staged", "planning", "bound"


MIGRATION_TRANSITIONS = {INTENDED: {M_STAGED, REFUSED, UNKNOWN}, M_STAGED: {M_PLANNING, REFUSED, UNKNOWN},
                         M_PLANNING: {M_BOUND, REFUSED, UNKNOWN}, M_BOUND: {COMPLETED, REFUSED, UNKNOWN}}


# Lane refusals that name a transient condition, never a verdict: the row waits where it is. The
# controller-code preflight (INV-RELEASE-ENVIRONMENT-REVERIFY-001) waits too: code that changed after
# the request never consumes the one successor, and the approved deployed code stages it later.
MIGRATION_RETRYABLE = frozenset({"migration_unobservable", "migration_controller_running",
                                 "migration_controller_code_unavailable", "migration_controller_code_mismatch"})


LAUNCH_RUNNING, LAUNCH_ABSENT, LAUNCH_UNKNOWN, LAUNCH_EXITED = "running", "absent", "unknown", "exited"


def _job_snapshot(job: dict) -> dict:
    """The exact job facts the recovery compared (status, calls, updated_at); the job is never written."""
    return {"id": job.get("id"), "lane": job.get("lane"), "status": job.get("status"),
            "reason_code": job.get("reason_code"), "calls": copy.deepcopy(job.get("calls")),
            "updated_at": job.get("updated_at")}


class ActionChanged(ContractError):
    """Another coordinator (or a restart replay) moved the action first; nothing was written here."""


def _request_of(plan_action: dict) -> dict:
    """The one canary request a published plan files: a function of its immutable action row only."""
    return canary_request(plan_action, plan_action["plan"], plan_action["plan_sha256"], plan_action["published_at"])


def _kind(document: dict) -> str:
    """The migration kind of a document or control row; absent is the evaluator migration."""
    return document.get("kind") or EVALUATOR_MIGRATION


def _migration_document(document) -> dict:
    """The exact owner-only migration document shape (INV-OWNER-ACTIONS-MIGRATION-001). An optional
    `kind` selects the environment reverification (INV-RELEASE-ENVIRONMENT-REVERIFY-001); an explicit
    `evaluator_migration` is normalized away so the evaluator document keeps its one identity."""
    if not isinstance(document, dict) or set(document) - {"kind"} != MIGRATION_DOCUMENT_FIELDS:
        raise OwnerActionRefused("migration_document_invalid", "document")
    if "kind" in document:
        if document["kind"] not in MIGRATION_KINDS:
            raise OwnerActionRefused("migration_document_invalid", "kind")
        if document["kind"] == EVALUATOR_MIGRATION:
            document = {k: v for k, v in document.items() if k != "kind"}
    for key in MIGRATION_DOCUMENT_FIELDS - {"approval"}:
        if type(document[key]) is not str or not document[key]:
            raise OwnerActionRefused("migration_document_invalid", key)
    if not EVIDENCE_REF.fullmatch(document["evidence"]):
        raise OwnerActionRefused("migration_document_invalid", "evidence")
    approval = document["approval"]
    if _kind(document) == ENVIRONMENT_REVERIFICATION:
        _check_environment_approval(document, approval)
        return document
    if not isinstance(approval, dict) or set(approval) != MIGRATION_APPROVAL_FIELDS:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if approval["source_release_id"] != document["source_release_id"] or approval["evidence"] != document["evidence"]:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    return document


def _check_environment_approval(document: dict, approval) -> None:
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: exactly the Releases approval shape, consistent with the
    document in every shared identity; refused before any read or effect."""
    if not isinstance(approval, dict) or set(approval) != ENVIRONMENT_APPROVAL_FIELDS:
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if any(type(value) is not str or not value for value in approval.values()):
        raise OwnerActionRefused("migration_approval_invalid", "approval")
    if approval["kind"] != ENVIRONMENT_REVERIFICATION:
        raise OwnerActionRefused("migration_approval_invalid", "kind")
    for key in ("source_release_id", "source_policy_hash", "old_plan_id", "old_plan_sha256", "intent_id",
                "policy_id", "target_id", "lane"):
        if approval[key] != document[key]:
            raise OwnerActionRefused("migration_approval_invalid", key)
    if not _FIX_EVIDENCE.fullmatch(approval["fix_evidence"]):
        raise OwnerActionRefused("migration_approval_invalid", "fix_evidence")
    if not _REVISION40.fullmatch(approval["controller_revision"]):
        raise OwnerActionRefused("migration_approval_invalid", "controller_revision")


def _check_environment_source(document: dict, intent: dict, bound, get) -> None:
    """INV-RELEASE-ENVIRONMENT-REVERIFY-001: the source of an environment reverification is the
    SUCCESSOR of a completed evaluator migration of this very intent: the intent's effective binding
    names it (and the old plan) and the migration row of the conductor's release is completed. The
    conductor's `release_id` on the intent stays the provenance (the first hop's source)."""
    binding = (bound or {}).get("binding") if isinstance(bound, dict) else None
    if not (isinstance(binding, dict) and binding.get("successor_release_id") == document["source_release_id"]
            and binding.get("plan_id") == document["old_plan_id"]
            and binding.get("source_release_id") == intent.get("release_id")
            and binding.get("target_id") == document["target_id"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")
    first = get(BUCKET_MIGRATIONS, binding["source_release_id"])
    if not (isinstance(first, dict) and first.get("state") == COMPLETED and _kind(first) == EVALUATOR_MIGRATION
            and first.get("successor_release_id") == document["source_release_id"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")


def _check_migration_source(document: dict, policy_row, intent, plans: list) -> None:
    """The control records the document must name exactly; the original plan action stays history."""
    if not isinstance(policy_row, dict):
        raise OwnerActionRefused("policy_unregistered", "policy_id")
    policy = policy_row["policy"]
    if policy["delivery"]["target_id"] != document["target_id"]:
        raise OwnerActionRefused("delivery_target_mismatch", "target_id")
    if not (isinstance(intent, dict) and intent.get("route") == DELIVERY
            and intent.get("state") in MIGRATION_SOURCE_STATES and type(intent.get("version")) is int
            and intent.get("policy_id") == policy["continuation_policy"]
            # an environment reverification's source is the intent's effective successor, checked apart
            and (_kind(document) == ENVIRONMENT_REVERIFICATION
                 or intent.get("release_id") == document["source_release_id"])
            and intent.get("delivery_target") == document["target_id"] and intent.get("lane") == document["lane"]):
        raise OwnerActionRefused("migration_intent_mismatch", "intent_id")
    if len(plans) != 1:
        raise OwnerActionRefused("migration_plan_action_missing", "old_plan_id")
    plan = plans[0]
    binding = plan.get("binding") or {}
    if not (plan.get("state") == COMPLETED and plan.get("policy_id") == document["policy_id"]
            and plan.get("plan_sha256") == document["old_plan_sha256"]
            and (plan.get("subject") or {}).get("intent_id") == document["intent_id"]
            and binding.get("release_id") == document["source_release_id"]
            and binding.get("revision") == document["candidate_revision"]
            and binding.get("policy_hash") == document["source_policy_hash"]
            and binding.get("target_id") == document["target_id"]):
        raise OwnerActionRefused("migration_plan_action_mismatch", "old_plan_id")


def _source_unchanged(row: dict, intent) -> bool:
    """The recorded source snapshot still names exactly this intent; a row without one never proceeds."""
    document, recorded = row["document"], row.get("source_intent")
    return (isinstance(intent, dict) and isinstance(recorded, dict) and migration_source(intent) == recorded
            and (_kind(document) == ENVIRONMENT_REVERIFICATION
                 or intent.get("release_id") == document["source_release_id"])
            and intent.get("delivery_target") == document["target_id"] and intent.get("lane") == document["lane"]
            and intent.get("route") == DELIVERY)


def _stage_receipt(row: dict, record) -> dict | None:
    """The lane's stage receipt, exactly hash-linked to this row's request; None on any mismatch."""
    request = row["request"]
    if not (isinstance(record, dict) and record.get("migration_id") == row["migration_id"]
            and record.get("request_sha256") == digest(request)
            and record.get("source_release_id") == request["source_release_id"]
            and record.get("target_id") == request["target_id"]
            and record.get("old_plan_id", request["old_plan_id"]) == request["old_plan_id"]
            and record.get("state") in {"staged", MIGRATION_REGISTERED, MIGRATION_ACTIVE}
            and type(record.get("successor_release_id")) is str and record["successor_release_id"]
            and record["successor_release_id"] != request["source_release_id"]):
        return None
    return {"migration_id": record["migration_id"], "request_sha256": record["request_sha256"],
            "source_release_id": record["source_release_id"], "successor_release_id": record["successor_release_id"],
            "target_id": record["target_id"], "old_plan_id": request["old_plan_id"]}


def lineage_of(row: dict, plan_action: dict) -> dict:
    return {"source_release_id": row["id"], "successor_release_id": row["successor_release_id"],
            "old_plan_id": row["subject"]["old_plan_id"], "plan_id": plan_action["plan_id"],
            "migration_id": row["migration_id"]}


def migration_ack(row: dict, plan_action: dict) -> dict:
    """The readiness acknowledgement: a function of durable control rows only, so a replay is identical."""
    fleet = plan_action["plan"]["canary_check_id"] == CANARY_FLEET
    return {"control_action_id": plan_action["id"], "plan_id": plan_action["plan_id"],
            "plan_sha256": plan_action["plan_sha256"], "request_sha256": row["lane_receipt"]["request_sha256"],
            "canary_request_id": digest(_request_of(plan_action)) if fleet else "not_requested",
            "lineage_sha256": migration_lineage_digest(**lineage_of(row, plan_action))}


def _migration_status(row: dict) -> dict:
    """R-OBS: one migration's owner-facing status (read-only): state, its phase history and last reason,
    the lineage identities and the effective owner (policy/lane) of the source intent."""
    subject = row.get("subject") or {}
    return {"source_release_id": row.get("id"), "kind": _kind(row), "state": row.get("state"),
            "reason_code": row.get("reason_code"),
            "phases": [{"state": h.get("state"), "reason_code": h.get("reason_code"), "at": h.get("at")}
                       for h in (row.get("history") or [])][-8:],
            "successor_release_id": row.get("successor_release_id"), "plan_id": row.get("plan_id"),
            "intent_id": subject.get("intent_id"), "source_intent_state": (row.get("source_intent") or {}).get("state"),
            "owner": {"policy_id": row.get("policy_id"), "lane": subject.get("lane")},
            "version": row.get("version")}


def _migration_view(row: dict) -> dict:
    shown = {k: row.get(k) for k in ("id", "action_id", "kind", "state", "reason_code", "migration_id",
                                     "document_sha256", "policy_id", "subject", "old_action_id",
                                     "successor_release_id", "plan_action_id", "plan_id", "lane_receipt_sha256",
                                     "effective_sha256", "created_at", "updated_at", "version")}
    for key in ("ack", "lineage"):
        if row.get(key) is not None:
            shown[key] = row[key]
    return shown


# Requalification refusals that are an outage or another owner's open work, never a verdict on this action:
# the row stays where it is and the next tick replays the same persisted document.
REQUALIFY_WAITS = frozenset({"requalification_main_unreadable", "policy_unavailable", "requalification_family_open"})


def _probe_view(probe) -> dict:
    probe = probe if isinstance(probe, dict) else {}
    return {k: probe.get(k) for k in ("ok", "reason_code", "error_type", "codex", "node")}


def _launch_view(launch: dict) -> dict:
    return {k: launch.get(k) for k in ("state", "exit_code", "cleanup_confirmed", "reason_code")}


def _decided(verdict: dict) -> dict:
    """The executed decision's verdict as retained evidence; it is not a promotion by itself."""
    return {k: verdict.get(k) for k in ("verdict", "reason_code", "decision_id", "execution_ref")}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_json(plan: dict) -> bytes:
    """The exact bytes a plan is published as: canonical JSON and one newline."""
    return (canonical(plan) + "\n").encode("utf-8")
