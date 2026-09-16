"""The `dge_role` executor action (INV-AUTONOMOUS-001): one read-only role execution in a clean
detached checkout at the pinned base, one provider entry, output shape fixed by the host.

Roles never select tools or host commands; the packet, prior outputs and the SSOT brief arrive as
evidence through the existing context compiler. The executor's lease, reservation, breaker,
observation and checkpoint paths are reused unchanged through `Executor._run`; only the handoff
cap differs (one entry per role, no implicit retry).
"""
from __future__ import annotations

from codex_harness.domain.autonomous import DEBATE_ROLES, MAX_ROLE_ENTRIES, RESEARCHER, ROLE_ORDER
from codex_harness.domain.model import require

TEXT = {"type": "string"}
STRINGS = {"type": "array", "items": TEXT}


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


NULLABLE_TEXT = {"type": ["string", "null"]}
SOURCE = _object({"id": TEXT, "path": TEXT, "sha256": TEXT, "locator": TEXT, "revision": TEXT, "read_scope": TEXT})
CLAIM = _object({"id": TEXT, "kind": TEXT, "text": TEXT, "source_ids": STRINGS})
QUESTION = _object({"id": TEXT, "question": TEXT, "blocking": {"type": "boolean"}, "status": TEXT, "claim_ids": STRINGS})
TRANSITION = {"type": ["object", "null"], "additionalProperties": False,
              "properties": {"compatibility": TEXT, "rollback": TEXT, "retirement": TEXT},
              "required": ["compatibility", "rollback", "retirement"]}
SSOT = _object({"searched_paths": STRINGS, "searched_symbols": STRINGS, "authoritative_definition": NULLABLE_TEXT,
                "callers": STRINGS, "evidence": STRINGS, "unknowns": STRINGS, "decision": TEXT, "rationale": TEXT,
                "transition": TRANSITION})
RESEARCH_OUTPUT = _object({"sources": {"type": "array", "items": SOURCE}, "claims": {"type": "array", "items": CLAIM},
                           "questions": {"type": "array", "items": QUESTION}, "ssot": SSOT,
                           "needs_user": {"type": "boolean"}, "user_question": NULLABLE_TEXT})
PROPOSER_OUTPUT = _object({"summary": TEXT, "claim_ids": STRINGS})
FINDING = _object({"id": TEXT, "criterion": TEXT, "severity": TEXT, "scenario": TEXT, "claim_ids": STRINGS,
                   "trigger": NULLABLE_TEXT, "impact": NULLABLE_TEXT, "mitigation": NULLABLE_TEXT})
ATTACKER_OUTPUT = _object({"findings": {"type": "array", "items": FINDING}})
DISPOSITION = _object({"finding_id": TEXT, "decision": TEXT, "reason": TEXT})
ARBITER_OUTPUT = _object({"verdict": TEXT, "rationale": TEXT, "dispositions": {"type": "array", "items": DISPOSITION},
                          "research_question": NULLABLE_TEXT})
SCHEMAS = {RESEARCHER: RESEARCH_OUTPUT, "proposer": PROPOSER_OUTPUT, "attacker": ATTACKER_OUTPUT, "arbiter": ARBITER_OUTPUT}
OBJECTIVES = {
    RESEARCHER: ("SSOT-first research. Read only the pinned base revision. Search the named scope for existing "
                 "definitions, callers, tests and operating evidence; an unfound symbol is unknown, not absent. "
                 "Return sources with the exact sha256 of the tracked file bytes at base, claims and questions, "
                 "and an ssot decision (reuse/improve/migrate/new with compatibility, rollback and retirement for "
                 "improve/migrate). Set needs_user only for a consequential product choice you cannot settle."),
    "proposer": "Propose the design for the fixed plan citing packet claims only; do not change the plan.",
    "attacker": ("Identify only material blockers as critical: concrete reachable trigger, cited packet claims, the "
                 "exact fixed criterion, material impact and minimal mitigation. Everything else is minor."),
    "arbiter": ("Judge materiality independently. Name every finding exactly once; refute an unsupported critical "
                "allegation with cited reasoning; never defer a critical finding; accept only without blockers."),
}


def execute_role(executor, task: dict, heartbeat) -> dict:
    """Run one role in a clean review checkout at base; assert a clean HEAD before and after."""
    message = task["message"]
    details = message["what"]["details"]
    role = details.get("role")
    require(role in ROLE_ORDER, "Unknown autonomous role")
    require(task["agent"] == "lead:" + role, "Role task assigned to the wrong lead")
    base = details["base_revision"]
    require(message["where"]["revision"] == base, "Role base revision mismatch")
    cwd = executor.git.review_workspace(base, task["id"])
    require(executor.git._git("rev-parse", "HEAD", cwd=cwd) == base, "Role checkout is not at base")
    stage = "dge:" + role
    result = executor._run(task["agent"], task["id"], OBJECTIVES[role], details, cwd, SCHEMAS[role], True, heartbeat, task,
                           stage=stage, workload="design", action="dge_role", max_handoffs=MAX_ROLE_ENTRIES)
    require(not executor.git._git("status", "--porcelain", cwd=cwd), "Role execution modified its checkout")
    require(executor.git._git("rev-parse", "HEAD", cwd=cwd) == base, "Role execution changed its commit")
    if role in DEBATE_ROLES:
        require(details.get("packet_digest") == (details.get("packet_digest") or ""), "Packet digest required")
    result["role_execution"] = {"role": role, "stage": stage, "read_only": True, "provider_entries_cap": MAX_ROLE_ENTRIES}
    return result
