"""The `dge_role` executor action (INV-AUTONOMOUS-001): one read-only role execution in a clean
detached checkout at the pinned base, one provider entry, output shape fixed by the host.

Roles never select tools or host commands; the packet, prior outputs and the SSOT brief arrive as
evidence through the existing context compiler. The executor's lease, reservation, breaker,
observation and checkpoint paths are reused unchanged through `Executor._run`; only the handoff
cap differs (one entry per role, no implicit retry).

The model-facing output schemas are the producer side of the packet and debate contracts. Every
finite field (claim kind, question status, SSOT decision, finding severity, arbiter verdict and
disposition decision) is an enum built from the same domain constants the consumers check
(`domain.dge`, `domain.autonomous`), so a value the schema admits is a value the consumer accepts
and the provider's structured output is refused at the model boundary instead of at
`packet_from_research` (live canary autonomous-ssot-canary-001). Claim citation cardinality is the
same boundary (live canary autonomous-ssot-canary-002, claim c6): the packet consumer requires
source_ids for every kind except unknown, so the model-facing claim is a nested anyOf of typed
variants, sourced fact/inference with minItems 1 and unknown with any list, never if/then or allOf.
The consumers are not loosened and no output is coerced or repaired here.
"""
from __future__ import annotations

from codex_harness.domain.autonomous import (
    DEBATE_ROLES,
    MAX_ROLE_ENTRIES,
    RESEARCHER,
    ROLE_ORDER,
    SSOT_DECISIONS,
)
from codex_harness.domain.dge import CLAIM_KINDS, DECISIONS, QUESTION_STATUSES, SEVERITIES, VERDICTS
from codex_harness.domain.model import require

TEXT = {"type": "string"}
STRINGS = {"type": "array", "items": TEXT}


def _object(properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}


def _enum(values) -> dict:
    """A closed string set from a domain constant; `type` is explicit as the output-schema subset requires."""
    return {"type": "string", "enum": sorted(values)}


NULLABLE_TEXT = {"type": ["string", "null"]}
# Field -> the consumer constant it must match; kept as one table so the contract test and the schemas agree.
CONSUMER_ENUMS = {"claim.kind": CLAIM_KINDS, "question.status": QUESTION_STATUSES, "ssot.decision": SSOT_DECISIONS,
                  "finding.severity": SEVERITIES, "arbiter.verdict": VERDICTS, "disposition.decision": DECISIONS}
SOURCE = _object({"id": TEXT, "path": TEXT, "sha256": TEXT, "locator": TEXT, "revision": TEXT, "read_scope": TEXT})
# `domain.dge._claims` demands nonempty source_ids for every kind but unknown; the model-facing claim states the
# same rule as two typed variants under a nested anyOf (nested anyOf and array minItems are inside the provider's
# subset, if/then/else and allOf are not). Unknown keeps an ordinary list: an empty one is valid, none is forced.
UNSOURCED_KIND = "unknown"
SOURCED_KINDS = CLAIM_KINDS - {UNSOURCED_KIND}
CITED = {"type": "array", "items": TEXT, "minItems": 1}


def _claim(kinds, source_ids: dict) -> dict:
    return _object({"id": TEXT, "kind": _enum(kinds), "text": TEXT, "source_ids": source_ids})


CLAIM = {"anyOf": [_claim(SOURCED_KINDS, CITED), _claim({UNSOURCED_KIND}, STRINGS)]}
QUESTION = _object({"id": TEXT, "question": TEXT, "blocking": {"type": "boolean"}, "status": _enum(QUESTION_STATUSES),
                    "claim_ids": STRINGS})
TRANSITION = {"type": ["object", "null"], "additionalProperties": False,
              "properties": {"compatibility": TEXT, "rollback": TEXT, "retirement": TEXT},
              "required": ["compatibility", "rollback", "retirement"]}
SSOT = _object({"searched_paths": STRINGS, "searched_symbols": STRINGS, "authoritative_definition": NULLABLE_TEXT,
                "callers": STRINGS, "evidence": STRINGS, "unknowns": STRINGS, "decision": _enum(SSOT_DECISIONS),
                "rationale": TEXT, "transition": TRANSITION})
RESEARCH_OUTPUT = _object({"sources": {"type": "array", "items": SOURCE}, "claims": {"type": "array", "items": CLAIM},
                           "questions": {"type": "array", "items": QUESTION}, "ssot": SSOT,
                           "needs_user": {"type": "boolean"}, "user_question": NULLABLE_TEXT})
PROPOSER_OUTPUT = _object({"summary": TEXT, "claim_ids": STRINGS})
FINDING = _object({"id": TEXT, "criterion": TEXT, "severity": _enum(SEVERITIES), "scenario": TEXT, "claim_ids": STRINGS,
                   "trigger": NULLABLE_TEXT, "impact": NULLABLE_TEXT, "mitigation": NULLABLE_TEXT})
ATTACKER_OUTPUT = _object({"findings": {"type": "array", "items": FINDING}})
DISPOSITION = _object({"finding_id": TEXT, "decision": _enum(DECISIONS), "reason": TEXT})
ARBITER_OUTPUT = _object({"verdict": _enum(VERDICTS), "rationale": TEXT,
                          "dispositions": {"type": "array", "items": DISPOSITION}, "research_question": NULLABLE_TEXT})
SCHEMAS = {RESEARCHER: RESEARCH_OUTPUT, "proposer": PROPOSER_OUTPUT, "attacker": ATTACKER_OUTPUT, "arbiter": ARBITER_OUTPUT}


def _listed(values) -> str:
    return "/".join(sorted(values))


OBJECTIVES = {
    RESEARCHER: ("SSOT-first research. Read only the pinned base revision. Search the named scope for existing "
                 "definitions, callers, tests and operating evidence; an unfound symbol is unknown, not absent. "
                 "Return sources with the exact sha256 of the tracked file bytes at base, claims and questions, "
                 "and an ssot decision (" + _listed(SSOT_DECISIONS) + " with compatibility, rollback and retirement for "
                 "improve/migrate). Set needs_user only for a consequential product choice you cannot settle. "
                 "Output contract: a claim kind is exactly one of " + _listed(CLAIM_KINDS) + " and a question status "
                 "is exactly one of " + _listed(QUESTION_STATUSES) + "; the packet accepts nothing else. Commands "
                 "you ran, results you observed, recommendations and verdicts are not claim kinds: put them in "
                 "ssot.evidence (or ssot.unknowns) and state what they establish as fact/inference/unknown claims. "
                 "A " + _listed(SOURCED_KINDS) + " claim cites at least one source id from sources; only an "
                 "unknown claim may leave source_ids empty. What you observed about your runtime, test run or "
                 "clean checkout is not in the pinned sources: keep it in ssot.evidence rather than as a "
                 "Git-supported fact, and never invent a citation so that an observation passes as a fact. "
                 "A question is unknown only when the DESIGN cannot be settled from the sources at base; a blocking "
                 "unknown stops the debate for more research. Tests of the future implementation that have not "
                 "run yet are not unknown design questions: the fix does not exist at base, so record the "
                 "expected verification as an inference or evidence, not as an unknown. You are read-only and "
                 "are not asked to certify that the future fix works."),
    "proposer": "Propose the design for the fixed plan citing packet claims only; do not change the plan.",
    "attacker": ("Identify only material blockers as critical: concrete reachable trigger, cited packet claims, the "
                 "exact fixed criterion, material impact and minimal mitigation. Everything else is minor. "
                 "A severity is exactly one of " + _listed(SEVERITIES) + "; a critical finding without text in "
                 "trigger, impact and mitigation is refused, a minor finding leaves them null."),
    "arbiter": ("Judge materiality independently. Name every finding exactly once; refute an unsupported critical "
                "allegation with cited reasoning; never defer a critical finding; accept only without blockers. "
                "A verdict is exactly one of " + _listed(VERDICTS) + " (research_question only with needs_research) "
                "and a disposition decision is exactly one of " + _listed(DECISIONS) + "."),
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
