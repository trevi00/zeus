"""Operation manifest: the one host-authored input of `zeus operate run` (INV-OPERATION-001).

Layer: domain
Context: coordination
Owns: the operation manifest values and validation (M7 `domain/operation.py` moved verbatim in S5; the identifier and path grammars live in kernel.ids, TRACE C3) and the evidence-handoff vocabulary Fleet reads
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

import math
from uuid import UUID, uuid5

from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import ID, REVISION, SEGMENT, SHA256, digest, safe_relative_path  # noqa: F401
from codex_harness.kernel.usage import (
    NUMERIC_FIELDS,
    UsagePolicyError,
    accounting_mode,
    validate_budget,
)
from codex_harness.routing.domain.providers import parse_configuration

SCHEMA = "urn:zeus:operation:1"
# INV-DGE-001: v2 is v1 plus one `design` block naming the approved debate session; nothing else
# differs, so v1 manifests keep their exact semantics and canonical form.
SCHEMA_V2 = "urn:zeus:operation:2"
FIELDS = {"schema", "id", "base_revision", "goal", "plan", "budget", "claude"}
FIELDS_V2 = FIELDS | {"design"}
GOAL_FIELDS = {"path", "sha256", "criterion", "rationale"}
PLAN_FIELDS = {"objective", "acceptance_criteria", "allowed_paths"}
DESIGN_FIELDS = {"session_id", "packet_digest"}
BUDGET_FIELDS = set(NUMERIC_FIELDS)  # the legacy finite shape; `mode` is optional (usage_policy)
CLAUDE_FIELDS = {"model", "timeout_seconds", "max_budget_usd"}
# Fixed by this contract, never by the manifest: two executor starts (one worker, one lead), the
# packaged worker profile and the restricted file surface.
MAX_EXECUTIONS = 2
WORKER_PROFILE = "worker-v1"
RESTRICTED = True
WORKER = "worker:implementation"
LEAD = "lead:improvement"
ACTION = "implement"
OPERATION_NAMESPACE = UUID("6f1c8f1e-4a4b-4d0a-9d3e-2a4b5c6d7e8f")
TEXT_LIMIT = 12000


class ManifestError(ContractError):
    """The manifest is refused; the message names the field, never the value."""


def _text(value, limit=TEXT_LIMIT) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def _integer(value) -> bool:
    return type(value) is int  # bool is refused: its type is bool, not int


def _number(value) -> bool:
    return (type(value) is int or type(value) is float) and math.isfinite(value)


def _fields(document, expected, name):
    if not isinstance(document, dict):
        raise ManifestError(f"Operation manifest {name} must be an object")
    unknown = sorted(set(document) - expected)
    missing = sorted(expected - set(document))
    if unknown or missing:
        raise ManifestError(f"Operation manifest {name} has unknown or missing fields: "
                            + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))


def validate_plan(plan, error=ManifestError) -> dict:
    """The one plan shape shared by the operation manifest and the research packet (INV-DGE-001);
    returns a canonical copy so both sides compare the same bytes."""
    if not isinstance(plan, dict):
        raise error("Operation manifest plan must be an object")
    unknown, missing = sorted(set(plan) - PLAN_FIELDS), sorted(PLAN_FIELDS - set(plan))
    if unknown or missing:
        raise error("Operation manifest plan has unknown or missing fields: "
                    + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))
    if not _text(plan["objective"]):
        raise error("Operation manifest plan.objective is required text")
    criteria = plan["acceptance_criteria"]
    if not (isinstance(criteria, list) and criteria and all(_text(c, 4000) for c in criteria)):
        raise error("Operation manifest plan.acceptance_criteria must be a non-empty list of text")
    paths = plan["allowed_paths"]
    if not (isinstance(paths, list) and paths and all(safe_relative_path(p) for p in paths)
            and len(set(paths)) == len(paths)):
        raise error("Operation manifest plan.allowed_paths must be distinct safe relative paths")
    return {"objective": plan["objective"], "acceptance_criteria": list(criteria), "allowed_paths": list(paths)}


def validate_manifest(document, policy) -> dict:
    """Strict validation; returns a canonical copy. `policy` is the packaged provider policy."""
    if not isinstance(document, dict) or document.get("schema") not in {SCHEMA, SCHEMA_V2}:
        raise ManifestError("Operation manifest schema is not " + SCHEMA + " or " + SCHEMA_V2)
    schema = document["schema"]
    _fields(document, FIELDS_V2 if schema == SCHEMA_V2 else FIELDS, "root")
    if type(document["id"]) is not str or ID.fullmatch(document["id"]) is None:
        raise ManifestError("Operation manifest id must be a short safe token")
    if type(document["base_revision"]) is not str or REVISION.fullmatch(document["base_revision"]) is None:
        raise ManifestError("Operation manifest base_revision must be a 40-hex commit id")
    goal = document["goal"]
    _fields(goal, GOAL_FIELDS, "goal")
    if not (safe_relative_path(goal["path"]) and goal["path"].lower().endswith(".md")):
        raise ManifestError("Operation manifest goal.path must be a safe relative Markdown path")
    if type(goal["sha256"]) is not str or SHA256.fullmatch(goal["sha256"]) is None:
        raise ManifestError("Operation manifest goal.sha256 must be 64 lowercase hex")
    if not (_text(goal["criterion"], 400) and _text(goal["rationale"])):
        raise ManifestError("Operation manifest goal.criterion and goal.rationale are required text")
    plan = validate_plan(document["plan"])
    design = None
    if schema == SCHEMA_V2:
        design = document["design"]
        _fields(design, DESIGN_FIELDS, "design")
        if type(design["session_id"]) is not str or ID.fullmatch(design["session_id"]) is None:
            raise ManifestError("Operation manifest design.session_id must be a short safe token")
        if type(design["packet_digest"]) is not str or SHA256.fullmatch(design["packet_digest"]) is None:
            raise ManifestError("Operation manifest design.packet_digest must be 64 lowercase hex")
    # One shared usage policy (domain.usage_policy) decides the budget shape for the operation,
    # the fleet and the research program; the finite canonical form is the unchanged legacy one.
    try:
        budget = validate_budget(document["budget"])
    except UsagePolicyError as exc:
        if exc.reason_code == "fields":
            raise ManifestError("Operation manifest budget has unknown or missing fields") from exc
        raise ManifestError("Operation manifest budget needs positive integer per_host and total >= per_host "
                            "and an optional mode of finite or subscription") from exc
    claude = document["claude"]
    _fields(claude, CLAUDE_FIELDS, "claude")
    if not (_text(claude["model"], 100) and _integer(claude["timeout_seconds"]) and _number(claude["max_budget_usd"])):
        raise ManifestError("Operation manifest claude needs a model, an integer timeout_seconds and a finite max_budget_usd")
    # The existing provider validators decide the limits (pattern, minimum, maximum). The budget's
    # accounting mode travels with the controls, so a subscription manifest is checked exactly as
    # the operation will bind it (the dollar cap stays validated metadata there).
    try:
        parse_configuration(policy, provider_settings({"claude": claude, "budget": budget}))
    except ContractError as exc:
        raise ManifestError("Operation manifest claude controls are refused by the provider policy") from exc
    canonical = {"schema": schema, "id": document["id"], "base_revision": document["base_revision"],
                 "goal": {k: goal[k] for k in sorted(GOAL_FIELDS)}, "plan": plan,
                 "budget": budget,
                 "claude": {"model": claude["model"], "timeout_seconds": claude["timeout_seconds"],
                            "max_budget_usd": claude["max_budget_usd"]}}
    if design is not None:
        canonical["design"] = {"session_id": design["session_id"], "packet_digest": design["packet_digest"]}
    return canonical


def provider_settings(manifest) -> dict:
    """The host-setting names the provider policy reads, valued from the manifest's controls.

    The accounting mode is always explicit (finite or subscription, from the manifest budget), so a
    host environment value can never decide it. `max_budget_usd` stays a positive number for
    compatibility; under subscription the provider policy retains it as metadata and forwards no
    active dollar ceiling (domain.providers)."""
    claude = manifest["claude"]
    return {"ZEUS_CLAUDE_ASSIGNMENTS": WORKER + "/" + ACTION, "ZEUS_CLAUDE_MODEL": str(claude["model"]),
            "ZEUS_CLAUDE_MAX_BUDGET_USD": repr(claude["max_budget_usd"]),
            "ZEUS_CLAUDE_TIMEOUT_SECONDS": str(claude["timeout_seconds"]),
            "ZEUS_CLAUDE_ACCOUNTING_MODE": accounting_mode(manifest["budget"])}


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
