"""Operation manifest: the one host-authored input of `zeus operate run` (INV-OPERATION-001).

Layer: domain
Context: coordination
Owns: the operation manifest identities and the evidence-handoff vocabulary Fleet reads (M7 `domain/operation.py` moved verbatim in S5; the identifier and path grammars live in kernel.ids, TRACE C3); the manifest values and validators moved to intake.domain.operation_manifest in S6 (V2) and are imported back here, every public name unchanged
Does not own: manifest reading and Git binding (coordination.application), the provider policy (routing.domain.providers)
Entry points: SCHEMA, SCHEMA_V2, ManifestError, validate_plan, validate_manifest, provider_settings, manifest_digest, correlation_id, cycle_id, assignment_message_id, goal_binding, HANDOFF_SCHEMA
Contracts: INV-OPERATION-001, INV-DGE-001

The manifest is trusted local operator input, not authentication. It names one pinned goal
document, one predesigned plan, the machine call ceilings that authorize this operation and the
explicit Claude controls. Unknown fields, wrong types, booleans standing in for numbers, nonfinite
numbers, unsafe paths or ids and empty required values are refused before anything is read from
Git, PostgreSQL or a provider. The provider limits are validated by the existing provider policy
validators, never by a second copy of their rules. Credentials and endpoints are host settings and
have no field here."""
from __future__ import annotations

from uuid import UUID, uuid5

from codex_harness.intake.domain.operation_manifest import (  # noqa: F401
    ACTION,
    CLAUDE_FIELDS,
    DESIGN_FIELDS,
    FIELDS,
    FIELDS_V2,
    GOAL_FIELDS,
    PLAN_FIELDS,
    SCHEMA,
    SCHEMA_V2,
    TEXT_LIMIT,
    WORKER,
    ManifestError,
    _fields,
    _integer,
    _number,
    _text,
    provider_settings,
    validate_manifest,
    validate_plan,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import ID, REVISION, SEGMENT, SHA256, digest, safe_relative_path  # noqa: F401
from codex_harness.kernel.usage import NUMERIC_FIELDS

BUDGET_FIELDS = set(NUMERIC_FIELDS)  # the legacy finite shape; `mode` is optional (usage_policy)
# Fixed by this contract, never by the manifest: two executor starts (one worker, one lead), the
# packaged worker profile and the restricted file surface.
MAX_EXECUTIONS = 2
WORKER_PROFILE = "worker-v1"
RESTRICTED = True
LEAD = "lead:improvement"
OPERATION_NAMESPACE = UUID("6f1c8f1e-4a4b-4d0a-9d3e-2a4b5c6d7e8f")


def manifest_digest(manifest) -> str:
    return digest(manifest)


def correlation_id(manifest) -> str:
    return "operation:" + manifest["id"]


def cycle_id(manifest) -> str:
    return "operation:" + manifest["id"]


def assignment_message_id(manifest) -> str:
    """Deterministic six-W identity: the same manifest always names the same initial assignment,
    so a replayed claim reuses the outbox duplicate semantics instead of publishing twice."""
    return str(uuid5(OPERATION_NAMESPACE, "assignment:" + manifest_digest(manifest)))


def goal_binding(manifest, mode, data: bytes) -> dict:
    """Bind the manifest's goal to the exact Git bytes at base; a mismatch is a refusal."""
    import hashlib
    require(mode == "100644", "Operation goal must be a regular file at base")
    observed = hashlib.sha256(data).hexdigest()
    if observed != manifest["goal"]["sha256"]:
        raise ManifestError("Operation goal bytes at base do not match goal.sha256")
    return {"path": manifest["goal"]["path"], "sha256": observed, "base_revision": manifest["base_revision"],
            "criterion": manifest["goal"]["criterion"], "bytes": len(data)}

# Evidence-handoff vocabulary (verbatim from M7 `application/operation.py`; Fleet reads it, DESIGN-s5 L/Op).
HANDOFF_SCHEMA = "urn:zeus:operation-evidence-handoff:1"
HANDOFF_REASON = "evidence_gate_refused"
HANDOFF_OWNER = "lead:improvement"
HANDOFF_NEXT_ACTION = "inspect_evidence_contract"
HANDOFF_STATUS = "pending_owner"
MAX_HANDOFF_ITEMS = 32
