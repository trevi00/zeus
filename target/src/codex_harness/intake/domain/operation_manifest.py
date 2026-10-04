"""Operation manifest values and validation: the schemas, field sets and the strict validators (INV-OPERATION-001).

Layer: domain
Context: intake
Owns: SCHEMA, SCHEMA_V2, validate_manifest, validate_plan, provider_settings and every name they reference (the field sets, TEXT_LIMIT, ManifestError, the `_text`/`_integer`/`_number`/`_fields` helpers, WORKER, ACTION), verbatim from the S5 transcription of M7 `domain/operation.py` (DESIGN-s6 §13 V2, S5 carry C3)
Does not own: the digests and ids of a validated manifest, the goal binding and the evidence-handoff vocabulary (coordination.domain.operation, which imports every name here back)
Entry points: SCHEMA, SCHEMA_V2, ManifestError, validate_plan, validate_manifest, provider_settings
Contracts: INV-OPERATION-001, INV-DGE-001

Split out of `coordination/domain/operation.py` (S5, M7 `domain/operation.py` verbatim) by A/evidence/rebuild/s6/domain-moves/transcribe.py; the names are the AST closure of validate_manifest and validate_plan, moved with their comments and bodies unchanged. Module docstring of the M7 manifest:
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

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import ID, REVISION, SHA256, safe_relative_path
from codex_harness.kernel.usage import UsagePolicyError, accounting_mode, validate_budget
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
CLAUDE_FIELDS = {"model", "timeout_seconds", "max_budget_usd"}
# G20-D4 (DESIGN-s10 §14): the optional declared research exemption. The class names equal
# research.domain.research_package.EXEMPTION_CLASSES (research depends on intake, so intake keeps its own copy; a test pins them equal).
EXEMPTION_CLASSES = ("refactor-same-meaning", "bugfix-with-failing-test", "docs-only", "objective-quality",
                     "unchanged-accepted-procedure", "research-approved-audit")
EXEMPTION_REASON_LIMIT = 500
WORKER = "worker:implementation"
ACTION = "implement"
TEXT_LIMIT = 12000


class ManifestError(ContractError):
    """The manifest is refused; the message names the field, never the value."""


def _text(value, limit=TEXT_LIMIT) -> bool:
    return type(value) is str and 0 < len(value.strip()) <= limit


def valid_research_exemption(value) -> bool:
    """G20-D4: `{class, reason}` with a known class and a non-empty reason of at most 500 characters."""
    return (isinstance(value, dict) and set(value) == {"class", "reason"} and value["class"] in EXEMPTION_CLASSES
            and _text(value["reason"], EXEMPTION_REASON_LIMIT))


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
    # G20-D4: `research_exemption` is the one optional root field; absent, the canonical form is unchanged.
    _fields({k: v for k, v in document.items() if k != "research_exemption"},
            FIELDS_V2 if schema == SCHEMA_V2 else FIELDS, "root")
    if "research_exemption" in document and not valid_research_exemption(document["research_exemption"]):
        raise ManifestError("Operation manifest research_exemption needs a known class and a reason of at most 500 characters")
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
    if "research_exemption" in document:
        canonical["research_exemption"] = dict(document["research_exemption"])
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
