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
Question shape is the same boundary again (research-program-001 live cycle 1, question q3): the packet
consumer requires nonempty claim_ids for an answered question and refuses a blocking unknown one, so
the model-facing question is a nested anyOf of typed variants, answered with minItems 1 and either
blocking value, unknown with blocking false and any list. What no local schema can state is the
cross-array rule that an answered question cites only fact/inference claims: that stays the domain
validator's authority (`domain.dge._questions`) and is carried to the model as guidance only.
The consumers are not loosened and no output is coerced or repaired here.
"""
from __future__ import annotations

import copy

from codex_harness.domain.autonomous import (
    DEBATE_ROLES,
    MAX_ROLE_ENTRIES,
    RESEARCHER,
    SSOT_DECISIONS,
)
from codex_harness.domain.council import (
    AGENTS,
    CONDUCTOR_ROLE,
    DBA,
    IMPROVEMENT_LEAD,
    RESEARCH_LEAD,
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
# `domain.dge._questions` demands nonempty claim_ids for an answered question and refuses a blocking unknown one
# (INV-DGE-001: research first). The model-facing question states those two LOCAL rules as typed variants under
# the same nested anyOf: answered keeps an ordinary boolean, unknown is pinned to blocking false with a typed
# single-value enum (the subset requires an explicit type next to enum). Neither variant can see the claims
# array, so "answered cites only non-unknown claims" remains the packet consumer's check, not a schema promise.
UNRESOLVED_STATUS = "unknown"
ANSWERED_STATUSES = QUESTION_STATUSES - {UNRESOLVED_STATUS}
BOOLEAN = {"type": "boolean"}
NONBLOCKING = {"type": "boolean", "enum": [False]}


def _question(statuses, blocking: dict, claim_ids: dict) -> dict:
    return _object({"id": TEXT, "question": TEXT, "blocking": blocking, "status": _enum(statuses), "claim_ids": claim_ids})


QUESTION = {"anyOf": [_question(ANSWERED_STATUSES, BOOLEAN, CITED), _question({UNRESOLVED_STATUS}, NONBLOCKING, STRINGS)]}
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
# INV-COUNCIL-001 council roles: every downstream output names the snapshot (and report) digest it worked from.
DBA_OUTPUT = _object({"snapshot_digest": TEXT, "summary": TEXT, "claim_ids": STRINGS, "unknowns": STRINGS})
RESEARCH_LEAD_OUTPUT = _object({"summary": TEXT, "claim_ids": STRINGS, "snapshot_digest": TEXT, "report_digest": TEXT})
IMPROVEMENT_LEAD_OUTPUT = _object({"summary": TEXT, "decision": _enum(SSOT_DECISIONS), "rationale": TEXT, "transition": TRANSITION,
                                   "claim_ids": STRINGS, "findings": {"type": "array", "items": FINDING},
                                   "snapshot_digest": TEXT, "report_digest": TEXT})
CONDUCTOR_OUTPUT = _object({**ARBITER_OUTPUT["properties"], "snapshot_digest": TEXT, "report_digest": TEXT})
SCHEMAS = {RESEARCHER: RESEARCH_OUTPUT, "proposer": PROPOSER_OUTPUT, "attacker": ATTACKER_OUTPUT, "arbiter": ARBITER_OUTPUT,
           DBA: DBA_OUTPUT, RESEARCH_LEAD: RESEARCH_LEAD_OUTPUT, IMPROVEMENT_LEAD: IMPROVEMENT_LEAD_OUTPUT,
           CONDUCTOR_ROLE: CONDUCTOR_OUTPUT}


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
                 "are not asked to certify that the future fix works. "
                 "Question references are checked across both arrays and the whole packet is refused, never "
                 "repaired, on one bad reference: an answered question cites at least one claim id and only "
                 + _listed(SOURCED_KINDS) + " claims, never an unknown claim; an unknown question has blocking false "
                 "and cites an unknown claim or nothing. Self-check every answered question before you return: each "
                 "cited id exists in claims and its kind is fact or inference. Never relabel an unknown claim as "
                 "fact or inference, and never drop or invent a citation, so that a question can pass as answered: "
                 "unknown evidence stays unknown. A question such as 'what remains unknown?' has two honest forms: "
                 "answered, citing a fact or inference about a DOCUMENTED limitation (a source at base records it) "
                 "while the uncertainty itself stays a separate nonblocking unknown question citing its unknown "
                 "claim; or unknown itself, blocking false, citing that unknown claim. A design choice you truly "
                 "cannot settle is status unknown with blocking true: the output is refused and research continues; "
                 "do not mark it nonblocking or answered to pass the check."),
    "proposer": "Propose the design for the fixed plan citing packet claims only; do not change the plan.",
    "attacker": ("Identify only material blockers as critical: concrete reachable trigger, cited packet claims, the "
                 "exact fixed criterion, material impact and minimal mitigation. Everything else is minor. "
                 "A severity is exactly one of " + _listed(SEVERITIES) + "; a critical finding without text in "
                 "trigger, impact and mitigation is refused, a minor finding leaves them null."),
    "arbiter": ("Judge materiality independently. Name every finding exactly once; refute an unsupported critical "
                "allegation with cited reasoning; never defer a critical finding; accept only without blockers. "
                "A verdict is exactly one of " + _listed(VERDICTS) + " (research_question only with needs_research) "
                "and a disposition decision is exactly one of " + _listed(DECISIONS) + "."),
    DBA: ("Interpret the frozen read-only database snapshot you were given against the research packet. "
          "Name the exact snapshot_digest, summarize what the selected records show (found/missing/unknown and "
          "their whitelisted status fields), cite only packet claim ids, and list unknowns. A missing key is absent "
          "at that snapshot in the explicit scope only; an unknown record is not a success. Your report is an "
          "interpretation, never a new Git-supported fact and never a substitute for the observation."),
    RESEARCH_LEAD: ("Propose the design for the fixed plan from the packet AND the frozen DBA report, citing packet "
                    "claims only; echo the snapshot_digest and report_digest you worked from; do not change the plan."),
    IMPROVEMENT_LEAD: ("Respond with a constructive alternative: summary, decision (" + _listed(SSOT_DECISIONS) + "), "
                       "rationale, transition (compatibility, rollback, retirement for improve/migrate, null otherwise), "
                       "claim ids, plus findings under the existing rule: only material blockers are critical (concrete "
                       "reachable trigger, cited claims, exact fixed criterion, impact, minimal mitigation); everything "
                       "else is minor, and no objection is compulsory. Echo the snapshot_digest and report_digest."),
    CONDUCTOR_ROLE: ("Arbitrate the research lead proposal and the improvement lead alternative with the existing rules: "
                     "name every finding exactly once, never defer a critical finding, accept only without blockers; a "
                     "verdict is exactly one of " + _listed(VERDICTS) + " and a disposition decision one of "
                     + _listed(DECISIONS) + ". Echo the snapshot_digest and report_digest."),
}


CRITERION_ROLES = ("attacker", IMPROVEMENT_LEAD)


def role_schema(role: str, details: dict) -> dict:
    """A deep copy of the role's output schema for ONE execution. For the finding-producing roles
    `finding.criterion` becomes the enum of this plan's pinned acceptance_criteria, so the provider
    boundary states the exact membership `domain.dge` enforces; nothing is normalized or coerced,
    and the static constants stay unmodified for the next plan."""
    schema = copy.deepcopy(SCHEMAS[role])
    if role in CRITERION_ROLES:
        criteria = details.get("acceptance_criteria")
        require(isinstance(criteria, list) and criteria and all(type(c) is str and c for c in criteria)
                and len(set(criteria)) == len(criteria), "Role details must carry the pinned plan acceptance_criteria")
        schema["properties"]["findings"]["items"]["properties"]["criterion"] = {"type": "string", "enum": list(criteria)}
    return schema


def execute_role(executor, task: dict, heartbeat) -> dict:
    """Run one role in a clean review checkout at base; assert a clean HEAD before and after."""
    message = task["message"]
    details = message["what"]["details"]
    role = details.get("role")
    require(role in AGENTS, "Unknown autonomous role")
    # v1 roles run on lead:<role>; the council roles on their real agents (lead:dba, lead:research,
    # lead:improvement, conductor). The mapping is the domain table, never derived from the name.
    require(task["agent"] == AGENTS[role], "Role task assigned to the wrong agent")
    base = details["base_revision"]
    require(message["where"]["revision"] == base, "Role base revision mismatch")
    cwd = executor.git.review_workspace(base, task["id"])
    require(executor.git._git("rev-parse", "HEAD", cwd=cwd) == base, "Role checkout is not at base")
    stage = "dge:" + role
    result = executor._run(task["agent"], task["id"], OBJECTIVES[role], details, cwd, role_schema(role, details), True, heartbeat, task,
                           stage=stage, workload="design", action="dge_role", max_handoffs=MAX_ROLE_ENTRIES)
    require(not executor.git._git("status", "--porcelain", cwd=cwd), "Role execution modified its checkout")
    require(executor.git._git("rev-parse", "HEAD", cwd=cwd) == base, "Role execution changed its commit")
    if role in DEBATE_ROLES:
        require(details.get("packet_digest") == (details.get("packet_digest") or ""), "Packet digest required")
    result["role_execution"] = {"role": role, "stage": stage, "read_only": True, "provider_entries_cap": MAX_ROLE_ENTRIES}
    return result
