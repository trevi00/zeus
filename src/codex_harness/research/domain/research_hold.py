"""The published language of a continuation research hold: refusals, route and state names, the attempt scope claim identity and the held attempt set (INV-CONTINUATION-001, INV-RESEARCH-ATTEMPT-SCOPE-001).

Layer: domain
Context: research
Owns: ContinuationRefused, refuse, RESEARCH, RESEARCH_REQUIRED, COMPLETED, REFUSED, EVIDENCE_REPAIR, CORRECTION, SUCCESSOR_ROUTES, FAILURE_ROUTES, ATTEMPT_SCOPE, ATTEMPT_SCOPE_PREFIX, attempt_scope_id, research_attempts, accepted_candidate: the 15 names research needs from M7 `domain/continuation.py` (DESIGN-s6 §1 V1), verbatim; TOKEN and SHA256 come from kernel.ids
Does not own: the continuation routing table, intent lifecycle and projection (coordination.domain.continuation, which imports these names back so `except ContinuationRefused` is one class)
Entry points: ContinuationRefused, refuse, attempt_scope_id, research_attempts, accepted_candidate, ATTEMPT_SCOPE, RESEARCH, RESEARCH_REQUIRED
Contracts: INV-CONTINUATION-001, INV-RESEARCH-ATTEMPT-SCOPE-001

Moved from M7 `domain/continuation.py` (SOURCE e38aa722) by A/evidence/rebuild/s6/domain-moves/transcribe.py: breaks the M7 research <-> continuation import cycle by moving the small direction (research needs these 15 names; coordination needs dozens from research). Names, bodies and comments are M7's unchanged; `ID as TOKEN` and `SHA256` are the kernel.ids patterns (identical to M7's local TOKEN and SHA256).
"""
from __future__ import annotations

from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import ID as TOKEN  # noqa: F401
from codex_harness.kernel.ids import SHA256

EVIDENCE_REPAIR = "evidence_repair"
CORRECTION = "correction"
RESEARCH = "research"
SUCCESSOR_ROUTES = frozenset({EVIDENCE_REPAIR, CORRECTION})
FAILURE_ROUTES = SUCCESSOR_ROUTES
RESEARCH_REQUIRED = "research_required"
REFUSED = "refused"
COMPLETED = "completed"


class ContinuationRefused(ContractError):
    """A refusal with a fixed reason code and the named owner who must act next."""

    def __init__(self, reason_code: str, owner: str = "operator", field: str | None = None):
        super().__init__("continuation refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.owner, self.field = reason_code, owner, field


def refuse(condition, reason_code: str, owner: str = "operator", field: str | None = None) -> None:
    if not condition:
        raise ContinuationRefused(reason_code, owner, field)


# INV-RESEARCH-ATTEMPT-SCOPE-001 (U2(b)): the ONE claim identity of an attempt-scoped research claim, derived
# from the held intent's own id, so every replay, restart and second controller derives the same key. It can
# never equal a bare 64-hex failure-family or audit id, nor a `<id>.recovery-N` key.
ATTEMPT_SCOPE = "attempt_scope"
ATTEMPT_SCOPE_PREFIX = "attempt-scope."


def attempt_scope_id(intent_id) -> str:
    """`attempt-scope.<intent id>` for a valid intent id (64-hex); anything else refuses, never truncates."""
    refuse(type(intent_id) is str and SHA256.fullmatch(intent_id) is not None, "research_scope_foreign", "operator",
           "intent_id")
    return ATTEMPT_SCOPE_PREFIX + intent_id


def research_attempts(intents: list, research: dict) -> list:
    """The COMPLETE failed attempt set a research intent holds: the family's distinct failure
    observations of the same policy since its last completed research (the rows `prior_failures`
    counted when the hold was raised), plus the research intent's own observation. Derived from the
    durable rows only, so a replay, a restart and a second controller derive the same set."""
    mark = (str(research.get("created_at")), research["id"])
    rows = sorted((row for row in intents if row.get("family") == research.get("family")
                   and row.get("policy_id") == research.get("policy_id")
                   and (str(row.get("created_at")), row["id"]) < mark),
                  key=lambda r: (str(r.get("created_at")), r["id"]))
    counted: set = set()
    for row in rows:
        if row["route"] == RESEARCH and row["state"] == COMPLETED:
            counted = set()
        elif row["route"] in FAILURE_ROUTES and row["state"] != REFUSED:
            counted.add((row["origin_job"], row["evidence_sha256"]))
    counted.add((research["origin_job"], research["evidence_sha256"]))
    return [{"job": job, "evidence_sha256": sha} for job, sha in sorted(counted)]


def accepted_candidate(binding: dict, run_id, acceptance) -> bool:
    """The accepted council's own promotion evidence, read mechanically from authoritative rows: the
    run row and the promotion receipt carry the same graph digest, the receipt names the decision,
    the implementation task succeeded with that candidate revision, and that decision is the
    succeeded accepting `review_lead` of the same revision."""
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    run, promotion = acceptance.get("run"), acceptance.get("promotion")
    task, decision = acceptance.get("task"), acceptance.get("decision")
    if not (isinstance(run, dict) and isinstance(run.get("promotion"), dict) and isinstance(promotion, dict)
            and isinstance(task, dict) and isinstance(decision, dict)):
        return False
    candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task.get("result"), dict) else {}
    reviewed = ((decision.get("input") or {}).get("candidate") or {}) if isinstance(decision.get("input"), dict) else {}
    verdict = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    return (run.get("id") == run_id and run["promotion"].get("graph_sha256") == binding["graph_sha256"]
            and promotion.get("id") == run_id and promotion.get("graph_sha256") == binding["graph_sha256"]
            and (promotion.get("evidence") or {}).get("decision_id") == binding["decision_id"]
            and (promotion.get("evidence") or {}).get("implementation_task_id") == task.get("id")
            and task.get("status") == "succeeded" and candidate.get("revision") == binding["candidate_revision"]
            and decision.get("id") == binding["decision_id"] and decision.get("status") == "succeeded"
            and decision.get("phase") == "review_lead" and verdict.get("accepted") is True
            and reviewed.get("revision") == binding["candidate_revision"])
