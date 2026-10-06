"""The successor identity, the research handoff and the inherited Portfolio ownership.

Layer: application
Context: coordination
Owns: no bucket of its own (Portfolio bindings through intake's PortfolioLineage port)
Does not own: the intent rows (IntentStore), portfolio_bindings (intake)
Entry points: Successors
Contracts: INV-CONTINUATION-001

Split from M7 `application/continuation.py` (SOURCE e38aa722) by the named S6 split (DESIGN-s6 §3,
A/evidence/rebuild/s6/continuation-split/split_continuation.py); the bodies are M7's.
"""

from __future__ import annotations

from codex_harness.coordination.application.continuation.state import BUCKET_INTENTS, BUCKET_RESEARCH_RECEIPTS
from codex_harness.coordination.domain.continuation import (
    BINDING_SCHEMA,
    CORRECTION,
    EVIDENCE_REPAIR,
    ContinuationRefused,
    research_handoff,
    research_reference,
    successor_id,
    successor_manifest,
)
from codex_harness.intake.domain.portfolio import PortfolioRefused
from codex_harness.kernel.errors import ContractError, require
from codex_harness.kernel.ids import utcnow


class Successors:
    """The successor identity of an intent (manifest, lane binding, session mode), the research
    handoff reference, and the Portfolio ownership a successor inherits."""

    def __init__(self, store, *, clock=utcnow, validate=None, portfolio=None):
        self.store = store
        self.clock = clock
        self.validate = validate
        self.portfolio = portfolio

    def research_handoff(self, policy_id: str, family: str, key: str) -> dict | None:
        """The binding reference of the first successor after a completed research intent of this
        policy and family (`domain.continuation.research_handoff`), bound to exactly its stored receipt;
        None for every other successor. A receipt that no longer matches refuses by name."""
        with self.store.transaction() as tx:
            intents = tx.scan(BUCKET_INTENTS)
            research = research_handoff(intents, policy_id, family, key)
            stored = tx.get(BUCKET_RESEARCH_RECEIPTS, research["id"]) if research is not None else None
        return research_reference(research, stored) if research is not None else None

    def successor_plan(self, sha, family, job, evidence, route, routed, key, lane, research=None) -> dict | None:
        """The complete successor identity of intent `key`: manifest (the existing validator decides;
        None when it refuses), lane binding and session mode. Shared by a new observation and an
        owner capacity grant, so both derive the same successor for the same intent. `research` (the
        `_research_handoff` reference, or None) is added to the binding predecessor only when present,
        so every other binding keeps its exact shape."""
        operation = evidence["operation"]
        task = evidence.get("task") or {}
        candidate = ((task.get("result") or {}).get("candidate") or {}) if isinstance(task, dict) else {}
        successor = successor_id(key)
        decision = evidence.get("conductor") if routed["reason_code"] == "conductor_rejected" else evidence.get("lead")
        references = {"predecessor_job": job["id"], "candidate_revision": candidate.get("revision"),
                      "candidate_tree": candidate.get("tree"),
                      "review_decision": (decision or {}).get("id") if route == CORRECTION else None,
                      "review_execution_ref": ((decision or {}).get("result") or {}).get("execution_ref")
                      if route == CORRECTION else None,
                      "inspection": ((operation.get("owner_handoff") or {}).get("inspection") or {}).get("id")
                      if route == EVIDENCE_REPAIR else None}
        manifest = successor_manifest(job["manifest"], route, successor, references)
        if self.validate is not None:
            try:
                manifest = self.validate(manifest)
            except ContractError:
                return None
        # The logical session of a family is keyed by its root job (see `_bind_initial`). Only a
        # correction of a session the owner moved to `correction_ready` on THIS review decision is
        # eligible for native resume; everything else is an explicit fresh evidence handoff.
        session, mode = None, "fresh_evidence_handoff"
        binding = evidence.get("binding") if isinstance(evidence.get("binding"), dict) else {}
        logical = {"task_id": family, "repository": job["repository"]}
        if route == CORRECTION and isinstance(decision, dict) and lane.sessions is not None:
            try:
                row = lane.record_review(logical["task_id"], decision["id"])
            except ContractError as exc:  # missing session, candidate mismatch: never a resume
                mode = "fresh_evidence_handoff:" + str(getattr(exc, "reason", "refused"))
            else:
                if isinstance(row, dict) and row.get("state") == "correction_ready":
                    session, mode = logical, "native_resume_eligible"
        workspace = None
        if isinstance(task.get("id"), str) and candidate.get("revision") and candidate.get("base"):
            workspace = {"origin_task_id": (binding.get("workspace") or {}).get("origin_task_id") or task["id"],
                         "head": candidate["revision"], "base": candidate["base"]}
        document = {"schema": BINDING_SCHEMA, "operation_id": successor, "policy_sha256": sha, "intent_id": key,
                    "family": family, "route": route, "session": session, "workspace": workspace,
                    "predecessor": {"job_id": job["id"], "task_id": task.get("id"),
                                    "candidate_revision": candidate.get("revision"),
                                    "decision_id": (decision or {}).get("id") if route == CORRECTION else None,
                                    "review_execution_ref": references["review_execution_ref"],
                                    "inspection_id": references["inspection"]}}
        if research is not None:
            document["predecessor"]["research"] = research
        return {"successor_job": successor, "manifest": manifest, "binding": document, "session_mode": mode,
                "evidence_refs": [ref for ref in (references["review_execution_ref"],) if ref]}

    def inherit(self, tx, intent: dict) -> tuple[dict, bool]:
        """The successor inherits exactly its origin's Portfolio binding through this persisted intent
        (`portfolio.inherit_binding`); an unbound origin stays unbound, never guessed. Returns the
        ownership recorded on the intent and whether the binding already existed."""
        try:
            # R3: intake's owner operation joins this unit through the PortfolioLineage port (DESIGN-s6 §5).
            require(self.portfolio is not None, "Portfolio lineage is not wired")
            bound = self.portfolio.inherit(tx, intent["successor_job"], intent["origin_job"],
                                           {"intent_id": intent["id"]}, self.clock())
        except PortfolioRefused as exc:
            raise ContinuationRefused("successor_" + exc.reason_code, "portfolio", "binding") from None
        if bound is None:
            return {"state": "origin_unbound", "project_id": None, "criterion_id": None}, False
        binding = bound["binding"]
        return ({"state": "inherited", "project_id": binding["project_id"], "criterion_id": binding["criterion_id"]},
                bound["cached"])
