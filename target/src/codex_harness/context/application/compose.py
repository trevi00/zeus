"""Compose the delivered context of one provider turn and retain its packet (REBUILD-DESIGN-v2 §2.7).

Layer: application
Context: context
Owns: ContextComposer (select, order and budget the delivered parts; report omissions; retain the
`context:<key>` packet artifact; bind it to skill history), CompositionRequest, ComposedContext
Does not own: the task lease, snapshot and recovery records (coordination; passed in the request),
review/role context facts of the isolation profile (execution; passed in), provider invocation
(execution), council delivery and correction feedback (research, S8: not composed here)
Entry points: ContextComposer.compose, ContextComposer.retain
Contracts: INV-CONTEXT-001, INV-SESSION-001, INV-SKILL-HISTORY-001, INV-ARTIFACT-001

Extracted from SOURCE M7 `adapters/executor.py` `Executor._run` (the part between provider selection
and the transport), for the legacy (non-council) budget. The retained artifact is exactly M7's
`canonical(asdict(packet))` under the source label `"context:" + key`, so the same inputs yield the
same bytes and the same `context_ref` (§2.7 class 2). Nothing is truncated silently: an optional item
that does not fit is listed in `omitted`; a required contract that does not fit refuses.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

from codex_harness.context.domain.composition import (
    ACCEPTANCE,
    ARTIFACT_READER,
    DELIVERY_POLICY,
    LEGACY_RESERVED,
    LEGACY_WINDOW,
    RECOVERY_INSTRUCTION,
    artifact_reader_handle,
    evidence_json,
    recovery_bound,
    task_contract,
)
from codex_harness.context.domain.packet import ContextItem, ContextPacket, compile_context
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical, digest


@dataclass(frozen=True)
class CompositionRequest:
    """Everything one composition reads that another context owns, as values (never objects)."""
    agent: str
    key: str
    objective: str
    evidence: dict
    cwd: str
    snapshot: str
    runtime_policy_digest: str
    reader_python: str
    provider: str
    default_provider: str
    read_only: bool = False
    action: str | None = None
    stage: str | None = None
    deployed_revision: str | None = None
    checkpoint: dict | None = None
    progress: dict | None = None
    review_context: dict | None = None
    role_context: dict | None = None
    project_evidence: dict | None = None
    # S4 turn loop (DESIGN-run-task D7), additive; both default to turn 1's S2 behaviour. From the second
    # handoff turn M7 recovers from that run's own state ({"checkpoint": state, "completed": [...]}), not from
    # the stored rows, and keeps the basis revision it read once before the loop.
    recovery: dict | None = None
    basis_revision: str | None = None


@dataclass
class ComposedContext:
    packet: ContextPacket
    rendered: str
    measurement: dict
    binding: dict
    context_bound: bool
    evidence_ref: str
    basis_revision: str
    skill_selection: dict
    observation: object = None
    recovery_refs: dict = field(default_factory=dict)


class ContextComposer:
    """One composition service per process; holds its source ports only (no per-run state)."""

    def __init__(self, artifacts, artifact_root, repository, skills, history=None, knowledge=None):
        self.artifacts, self.artifact_root = artifacts, artifact_root
        self.repository, self.skills, self.history, self.knowledge = repository, skills, history, knowledge

    def compose(self, request: CompositionRequest) -> ComposedContext:
        """The sealed packet of one turn. Refuses (ContractError) when the required contract exceeds the
        budget; stores the task evidence, skill, guidance and recovery artifacts it references."""
        r = request
        raw = self.artifacts.put(canonical(r.evidence), "task:" + r.key)
        basis_revision = r.basis_revision if r.basis_revision is not None else self.repository.revision(r.cwd)
        contract_fields = task_contract(r.evidence)
        window, reserved = LEGACY_WINDOW, LEGACY_RESERVED
        items = [ContextItem(raw["ref"], canonical(r.evidence), raw["ref"], digest(r.evidence), 10)]
        skill_items, skill_selection = self.skills.select(r.cwd, basis_revision, r.objective)
        observation = None
        if skill_selection.get('manifest_ref') and self.history is not None:
            skill_items, observation = self.history.prepare(skill_selection, r.agent, r.key, r.objective, skill_items)
        items.extend(skill_items)
        if self.knowledge is not None:
            query = contract_fields.get("objective", r.objective)
            for hit in self.knowledge.hits(query[:1000], 5):
                if not hit["id"].startswith("runtime:"):
                    # A hit is delivered only when its blob at the basis revision still hashes to the
                    # indexed revision. A value refusal skips it; any other Git failure propagates (M7).
                    try:
                        source = self.repository.show(basis_revision, hit["source_ref"].split(":")[0])
                    except ValueError:
                        continue
                    if hashlib.sha256(source.encode()).hexdigest() != hit["revision"]:
                        continue
                items.append(ContextItem(hit["id"], hit["body"], hit["source_ref"], hit["revision"]))
        required = {"role": r.agent, "objective": r.objective, "project_skills": skill_selection,
                    "acceptance_criteria": list(ACCEPTANCE), "task_contract": contract_fields,
                    "versions": {"repository": basis_revision, "deployed": r.deployed_revision,
                                 "runtime_policy": r.runtime_policy_digest},
                    "external_context": artifact_reader_handle(self.artifact_root, raw["ref"], r.reader_python),
                    "artifact_reader": ARTIFACT_READER, "policy": DELIVERY_POLICY}
        if r.read_only and r.action == "dge_role":
            require(r.role_context is not None, "A dge_role composition needs its role context")
            required["role_context"] = r.role_context
        elif r.read_only:
            require(r.review_context is not None, "A read-only composition needs its review context")
            required["review_context"] = dict(r.review_context)
            if r.project_evidence is not None:
                required["review_context"]["project_evidence"] = r.project_evidence
        elif r.action == "implement" and r.project_evidence is not None:
            required["project_evidence"] = r.project_evidence
        # INV-SESSION-001: task identity is stable, but recovery belongs to one stage, evidence set and
        # harness revision; never replay shortlist as final.
        binding = {"stage": r.stage, "evidence_ref": raw["ref"], "basis_revision": basis_revision}
        if skill_selection.get('manifest_ref'):
            binding['project_skills_ref'] = skill_selection['manifest_ref']
        context_bound = bool(r.stage or skill_selection.get('manifest_ref'))
        if context_bound:
            required["research_context"] = {**binding, **r.evidence.get("provenance", {})}

        def bound(value):
            return recovery_bound(value, binding=binding, context_bound=context_bound, provider=r.provider,
                                  default_provider=r.default_provider, worktree=r.cwd)

        if r.recovery is not None:
            recovery = dict(r.recovery)  # turn >= 2: M7's in-run recovery sources, in their order (D7)
        else:
            recovery = {}
            if r.checkpoint and r.checkpoint["checkpoint"].get("task_id") == r.key and bound(r.checkpoint["checkpoint"]):
                recovery["checkpoint"] = r.checkpoint
            if r.progress and bound(r.progress):
                recovery["progress"] = r.progress
        # @invariant INV-CONTEXT-001: every actual prompt, including recovery, passes the same compiler.
        # History stays available by immutable handle.
        recovery_refs, recovery_items = {}, []
        for name, value in recovery.items():
            body = evidence_json(value)
            receipt = self.artifacts.put(body, "recovery:" + r.key + ":" + name)
            recovery_refs[name] = artifact_reader_handle(self.artifact_root, receipt["ref"], r.reader_python)
            recovery_items.append(ContextItem(receipt["ref"], body, receipt["ref"],
                                              hashlib.sha256(body.encode('utf-8')).hexdigest(), 20))
        contract = {**required, 'project_skills': {**skill_selection, 'included': skill_selection['selected'],
                                                   'omitted': skill_selection['selected']},
                    "artifact_reader": ARTIFACT_READER,
                    "recovery": {"sources": recovery_refs, "instruction": RECOVERY_INSTRUCTION}}
        packet = compile_context(r.agent, r.key, r.snapshot, contract, items + recovery_items, window, reserved)
        before_counts = packet.estimated_tokens
        included = sum(item['id'].startswith('project-skill:') for item in packet.evidence)
        packet.required['project_skills'].update(included=included, omitted=skill_selection['selected'] - included)
        packet.seal()
        require(packet.estimated_tokens <= before_counts, 'Skill counts increased context size')
        # Named byte measurements of the FINAL rendered prompt; never a token estimate.
        measurement = {"policy": "legacy", "unit": "utf8_bytes", "window": window, "reserved": reserved,
                       "usable": window - reserved, "rendered_bytes": packet.estimated_tokens}
        return ComposedContext(packet=packet, rendered=packet.render(), measurement=measurement, binding=binding,
                               context_bound=context_bound, evidence_ref=raw["ref"], basis_revision=basis_revision,
                               skill_selection=skill_selection, observation=observation, recovery_refs=recovery_refs)

    def retain(self, composed: ComposedContext, key: str, guard=None) -> dict:
        """Store the packet as the restricted content-addressed `context:<key>` artifact (§2.7 class 2)
        and bind its ref to the skill-history observation. Returns {"context_ref", "history"}."""
        context_ref = self.artifacts.put(canonical(asdict(composed.packet)), "context:" + key)
        recording = None
        if composed.observation and self.history is not None:
            recording = self.history.record(self.history.finalize(composed.observation, composed.packet),
                                            context_ref["ref"], guard)
        return {"context_ref": context_ref["ref"], "history": recording}
