"""Operation manifest: the one host-authored input of `zeus operate run` (INV-OPERATION-001).

The manifest is trusted local operator input, not authentication. It names one pinned goal
document, one predesigned plan, the machine call ceilings that authorize this operation and the
explicit Claude controls. Unknown fields, wrong types, booleans standing in for numbers, nonfinite
numbers, unsafe paths or ids and empty required values are refused before anything is read from
Git, PostgreSQL or a provider. The provider limits are validated by the existing provider policy
validators, never by a second copy of their rules. Credentials and endpoints are host settings and
have no field here.
"""
from __future__ import annotations

import math
import re
from uuid import UUID, uuid5

from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.providers import parse_configuration

SCHEMA = "urn:zeus:operation:1"
FIELDS = {"schema", "id", "base_revision", "goal", "plan", "budget", "claude"}
GOAL_FIELDS = {"path", "sha256", "criterion", "rationale"}
PLAN_FIELDS = {"objective", "acceptance_criteria", "allowed_paths"}
BUDGET_FIELDS = {"per_host", "total"}
CLAUDE_FIELDS = {"model", "timeout_seconds", "max_budget_usd"}
# Fixed by this contract, never by the manifest: two executor starts (one worker, one lead), the
# packaged worker profile and the restricted file surface.
MAX_EXECUTIONS = 2
WORKER_PROFILE = "worker-v1"
RESTRICTED = True
WORKER = "worker:implementation"
LEAD = "lead:improvement"
ACTION = "implement"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
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


def safe_relative_path(value) -> bool:
    """A forward-slash relative repository path: no traversal, no `.git`, no drive or root."""
    if type(value) is not str or not value or len(value) > 1024 or "\\" in value or value.startswith("/"):
        return False
    segments = value.split("/")
    return all(SEGMENT.fullmatch(s) is not None and s not in {".", "..", ".git"} and not s.startswith(".git/")
               for s in segments)


def _fields(document, expected, name):
    if not isinstance(document, dict):
        raise ManifestError(f"Operation manifest {name} must be an object")
    unknown = sorted(set(document) - expected)
    missing = sorted(expected - set(document))
    if unknown or missing:
        raise ManifestError(f"Operation manifest {name} has unknown or missing fields: "
                            + ", ".join(["+" + k for k in unknown] + ["-" + k for k in missing]))


def validate_manifest(document, policy) -> dict:
    """Strict validation; returns a canonical copy. `policy` is the packaged provider policy."""
    _fields(document, FIELDS, "root")
    if document["schema"] != SCHEMA:
        raise ManifestError("Operation manifest schema is not " + SCHEMA)
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
    plan = document["plan"]
    _fields(plan, PLAN_FIELDS, "plan")
    if not _text(plan["objective"]):
        raise ManifestError("Operation manifest plan.objective is required text")
    criteria = plan["acceptance_criteria"]
    if not (isinstance(criteria, list) and criteria and all(_text(c, 4000) for c in criteria)):
        raise ManifestError("Operation manifest plan.acceptance_criteria must be a non-empty list of text")
    paths = plan["allowed_paths"]
    if not (isinstance(paths, list) and paths and all(safe_relative_path(p) for p in paths)
            and len(set(paths)) == len(paths)):
        raise ManifestError("Operation manifest plan.allowed_paths must be distinct safe relative paths")
    budget = document["budget"]
    _fields(budget, BUDGET_FIELDS, "budget")
    if not (_integer(budget["per_host"]) and _integer(budget["total"]) and budget["per_host"] > 0
            and budget["total"] >= budget["per_host"]):
        raise ManifestError("Operation manifest budget needs positive integer per_host and total >= per_host")
    claude = document["claude"]
    _fields(claude, CLAUDE_FIELDS, "claude")
    if not (_text(claude["model"], 100) and _integer(claude["timeout_seconds"]) and _number(claude["max_budget_usd"])):
        raise ManifestError("Operation manifest claude needs a model, an integer timeout_seconds and a finite max_budget_usd")
    # The existing provider validators decide the limits (pattern, minimum, maximum).
    try:
        parse_configuration(policy, provider_settings({"claude": claude}))
    except ContractError as exc:
        raise ManifestError("Operation manifest claude controls are refused by the provider policy") from exc
    return {"schema": SCHEMA, "id": document["id"], "base_revision": document["base_revision"],
            "goal": {k: goal[k] for k in sorted(GOAL_FIELDS)},
            "plan": {"objective": plan["objective"], "acceptance_criteria": list(criteria),
                     "allowed_paths": list(paths)},
            "budget": {"per_host": budget["per_host"], "total": budget["total"]},
            "claude": {"model": claude["model"], "timeout_seconds": claude["timeout_seconds"],
                       "max_budget_usd": claude["max_budget_usd"]}}


def provider_settings(manifest) -> dict:
    """The host-setting names the provider policy reads, valued from the manifest's controls."""
    claude = manifest["claude"]
    return {"ZEUS_CLAUDE_ASSIGNMENTS": WORKER + "/" + ACTION, "ZEUS_CLAUDE_MODEL": str(claude["model"]),
            "ZEUS_CLAUDE_MAX_BUDGET_USD": repr(claude["max_budget_usd"]),
            "ZEUS_CLAUDE_TIMEOUT_SECONDS": str(claude["timeout_seconds"])}


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
