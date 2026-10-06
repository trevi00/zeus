"""Compose the delivered context of one provider turn and retain its packet (REBUILD-DESIGN-v2 §2.7).

Layer: application
Context: context
Owns: ContextComposer (select, order and budget the delivered parts; report omissions; retain the
`context:<key>` packet artifact; bind it to skill history), ComposedContext (CompositionRequest, the request
value, is context.domain.composition's since S4 so RunTask can build it; re-imported here)
Does not own: the task lease, snapshot and recovery records (coordination; passed in the request),
review/role context facts of the isolation profile (execution; passed in), provider invocation
(execution), the council admission and correction-feedback rules (research; injected as
context.ports.CompositionAdmission)
Entry points: ContextComposer.compose, ContextComposer.retain
Contracts: INV-CONTEXT-001, INV-SESSION-001, INV-SKILL-HISTORY-001, INV-ARTIFACT-001

CHANGE (S8 V32, DESIGN-s8 §30/§30.1): council delivery and correction feedback are composed here, in M7's order, through
the injected `admission` port; without one a request carrying either refuses first. The legacy path is unchanged.

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
    CompositionRequest,
    artifact_reader_handle,
    evidence_json,
    recovery_bound,
    task_contract,
)
from codex_harness.context.domain.packet import ContextItem, ContextPacket, compile_context
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical, digest


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

    observer = None  # optional, injected by composition only (S10 A5-2)

    def _emit_skill_selection(self, skill_items, packet) -> None:
        """One `development.skill_selected` per project-skill item the selector returned: selected when the sealed
        packet carries it, otherwise omitted by the budget. The selection record carries no per-skill reason, so it
        is `other`; the skill ref is a digest of the item id, never the path."""
        if self.observer is None:
            return
        admitted = {item["id"] for item in packet.evidence}
        for item in skill_items:
            self.observer.emit(
                "development.skill_selected", "observed",
                attributes={"skill_ref": "sha256:" + hashlib.sha256(item.id.encode("utf-8")).hexdigest(),
                            "selected": item.id in admitted, "selection_reason": "other"})

    def compose(self, request: CompositionRequest, *, admission=None) -> ComposedContext:
        """The sealed packet of one turn. Refuses (ContractError) when the required contract exceeds the
        budget; stores the task evidence, skill, guidance and recovery artifacts it references."""
        require(admission is not None or (request.delivery is None and request.correction_feedback is None),
                "Composition admission is not wired")
        r = request
        raw = self.artifacts.put(canonical(r.evidence), "task:" + r.key)
        basis_revision = r.basis_revision if r.basis_revision is not None else self.repository.revision(r.cwd)
        contract_fields = task_contract(r.evidence)
        # urn:zeus:council-input:2 (M7): the council budget is granted only to an admitted delivery; the admission
        # runs right after the raw task is stored. Every other composition keeps the legacy budget exactly.
        council = (admission.admit_delivery(r.agent, r.action, r.read_only, r.stage, r.evidence, r.delivery)
                   if r.delivery is not None else None)
        window, reserved = admission.council_budget() if council is not None else (LEGACY_WINDOW, LEGACY_RESERVED)
        if r.delivery is not None:
            contract_fields = {k: v for k, v in contract_fields.items() if k not in r.delivery["inline"]}
        # A delivery prompt omits an EMPTY task_contract (every contract field is inline); a nonempty one and every
        # non-delivery prompt keep the key exactly.
        omit_task_contract = r.delivery is not None and not contract_fields
        items = ([] if r.delivery is not None
                 else [ContextItem(raw["ref"], canonical(r.evidence), raw["ref"], digest(r.evidence), 10)])
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
                    "external_context": artifact_reader_handle(self.artifact_root, raw["ref"], r.reader_python,
                                                               file=r.delivery is None),
                    "artifact_reader": ARTIFACT_READER if r.delivery is None else r.delivery_reader,
                    "policy": DELIVERY_POLICY}
        if omit_task_contract:
            del required["task_contract"]
        if r.delivery is not None:
            required["council_delivery"] = r.delivery
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
        if r.correction_feedback is not None:
            # Required, never an evictable evidence item: the findings themselves, not a host path.
            required["correction_feedback"] = r.correction_feedback
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
        # A recovery source has no operation listed in the delivery; its read needs the full catalogue.
        reader = ARTIFACT_READER if recovery_refs else required["artifact_reader"]
        # A delivery prompt with NO recovery source carries the bare empty source map; any recovery source, and
        # every non-delivery prompt, keeps the complete instruction.
        recovery_block = ({"sources": recovery_refs} if r.delivery is not None and not recovery_refs
                          else {"sources": recovery_refs, "instruction": RECOVERY_INSTRUCTION})
        contract = {**required, 'project_skills': {**skill_selection, 'included': skill_selection['selected'],
                                                   'omitted': skill_selection['selected']},
                    "artifact_reader": reader,
                    "recovery": recovery_block}
        if council is not None:
            # urn:zeus:council-input:2 preflight: the COMPLETE required envelope is rendered through the same
            # ContextPacket before compile_context, so a host or whole-prompt overflow is the typed
            # needs_scope_split refusal and never the generic budget ContractError.
            admission.admit_council(len(ContextPacket(r.agent, r.key, r.snapshot, contract).render().encode("utf-8")),
                                    council["delivery_bytes"])
        if r.correction_feedback is not None:
            # The complete required envelope with the findings is measured before compilation, so an overflow is
            # the fixed `feedback_context_insufficient` refusal before any provider.
            admission.admit_feedback(len(ContextPacket(r.agent, r.key, r.snapshot, contract).render().encode("utf-8")),
                                     window - reserved)
        packet = compile_context(r.agent, r.key, r.snapshot, contract, items + recovery_items, window, reserved)
        before_counts = packet.estimated_tokens
        included = sum(item['id'].startswith('project-skill:') for item in packet.evidence)
        packet.required['project_skills'].update(included=included, omitted=skill_selection['selected'] - included)
        self._emit_skill_selection(skill_items, packet)
        packet.seal()
        require(packet.estimated_tokens <= before_counts, 'Skill counts increased context size')
        # Named byte measurements of the FINAL rendered prompt; never a token estimate.
        measurement = {"policy": admission.council_policy if council is not None else "legacy",
                       "unit": "utf8_bytes", "window": window, "reserved": reserved,
                       "usable": window - reserved, "rendered_bytes": packet.estimated_tokens}
        if council is not None:
            measurement.update(admission.admit_council(packet.estimated_tokens, council["delivery_bytes"]),
                               sections=council["sections"], payload_bytes=council["payload_bytes"],
                               reserved_bytes=council["reserved_bytes"],
                               delivery_overhead_bytes=council["delivery_overhead_bytes"])
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
