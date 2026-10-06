"""The retained context packet: delivered items, the packet schema, and the byte-budget compiler.

Layer: domain
Context: context
Owns: ContextItem, ContextPacket (the retained `context:<key>` artifact schema, compiler version "1"),
compile_context (UTF-8 byte budget; explicit omission of optional items, refusal of an oversized contract)
Does not own: where the packet bytes are retained (the caller stores `canonical(asdict(packet))`)
Entry points: ContextItem, ContextPacket.render, ContextPacket.seal, compile_context
Contracts: INV-CONTEXT-001

Moved from SOURCE M7 `domain/model.py` (REBUILD-DESIGN-v2 §2.7 F4): the field set, value shapes,
render form and seal are byte-identical, so the same inputs yield the same retained bytes and ref.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import canonical, digest


@dataclass(frozen=True)
class ContextItem:
    id: str
    body: str
    source_ref: str
    revision: str
    priority: int = 0


@dataclass
class ContextPacket:
    agent_id: str
    task_id: str
    snapshot: str
    required: dict
    evidence: list[dict] = field(default_factory=list)
    omitted: list[dict] = field(default_factory=list)
    estimated_tokens: int = 0
    compiler_version: str = "1"
    manifest_hash: str = ""

    def render(self) -> str:
        return canonical({"agent_id": self.agent_id, "task_id": self.task_id,
                          "snapshot": self.snapshot, "required": self.required,
                          "evidence": self.evidence})

    def seal(self):
        self.estimated_tokens = len(self.render().encode())
        self.manifest_hash = digest({'rendered': self.render(), 'omitted': self.omitted,
                                     'compiler': self.compiler_version})


def compile_context(agent: str, task: str, snapshot: str, required: dict,
                    items: list[ContextItem], window: int, reserved: int) -> ContextPacket:
    require(window > 0 and 0 <= reserved < window, "Invalid context budget")
    require(all(required.get(k) for k in ("role", "objective", "acceptance_criteria", "policy")),
            "Required context contract missing")
    packet = ContextPacket(agent, task, snapshot, required)
    # @invariant INV-CONTEXT-001: UTF-8 bytes are an explicit conservative estimate,
    # not observed model token usage. Reserve includes history, tools and output.
    budget = window - reserved
    require(len(packet.render().encode()) <= budget, "Required contract exceeds budget; split task")
    seen: dict[str, ContextItem] = {}
    for item in sorted(items, key=lambda x: (-x.priority, x.id)):
        require(bool(item.source_ref and item.revision), "Evidence must have provenance")
        if item.id in seen:
            require(item == seen[item.id], "Conflicting evidence with identical ID")
            continue
        seen[item.id] = item
        value = {"id": item.id, "body": item.body, "source_ref": item.source_ref,
                 "revision": item.revision, "trust": "evidence-not-instructions"}
        packet.evidence.append(value)
        if len(packet.render().encode()) > budget:
            packet.evidence.pop()
            packet.omitted.append({"id": item.id, "reason": "budget", "source_ref": item.source_ref})
    packet.seal()
    return packet
