"""Context ports: the sources a composition reads, declared by their consumer (§2.5).

Layer: ports
Context: context
Owns: OWNED_BUCKETS of the context context; the Protocols ContextComposer depends on
Does not own: their implementations (context.adapters, knowledge.adapters; research implements
ThresholdPolicySource and CompositionAdmission in S8; composition wires them)
Entry points: ThresholdPolicySource, SkillSelection, SkillHistoryPort, KnowledgeHits, Repository, CompositionAdmission, OWNED_BUCKETS
Contracts: INV-CONTEXT-001, INV-SKILL-001, INV-SKILL-HISTORY-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("skill_history", "skill_observations", "legacy_skill_imports")


class ThresholdPolicySource(Protocol):
    def effective_policy(self) -> dict:
        """The resolved native threshold definition: {"values", "definition_hash", "definition"}."""
        ...


class SkillSelection(Protocol):
    def select(self, cwd: str, revision: str, objective: str) -> tuple[list, dict]:
        """Project skill/pipeline items and the selection summary for one pinned revision."""
        ...


class SkillHistoryPort(Protocol):
    def prepare(self, selection: dict, agent: str, task: str, objective: str, items: list) -> tuple[list, object]: ...

    def finalize(self, observation, packet): ...

    def record(self, observation, context_ref: str, guard=None) -> dict: ...


class KnowledgeHits(Protocol):
    def hits(self, text: str, limit: int) -> list[dict]:
        """Hybrid knowledge hits: {id, body, source_ref, revision}; `runtime:` ids are unverified."""
        ...


class Repository(Protocol):
    def revision(self, cwd: str) -> str:
        """The checked-out commit of `cwd` (the basis revision)."""
        ...

    def show(self, revision: str, path: str) -> str:
        """The blob text at `revision:path` of the configured repository; a Git failure raises."""
        ...


class CompositionAdmission(Protocol):
    """DESIGN-s8 §30 R-cd1 / §30.1: the council-delivery and correction-feedback admission rules of research,
    reached by composition only through this port (context never imports research). A request carrying a delivery
    or correction feedback is refused without one."""

    council_policy: str

    def admit_delivery(self, agent: str, action: str | None, read_only: bool, stage: str | None, evidence: dict,
                       delivery: dict) -> dict:
        """The admitted measurements of a supplied delivery (the exact projection of this task) or a refusal."""
        ...

    def council_budget(self) -> tuple:
        """(window, reserved) bytes of an admitted council delivery."""
        ...

    def admit_council(self, rendered_bytes: int, delivery_bytes: int) -> dict:
        """The byte measurements of a rendered prompt against the council policy, or the typed overflow refusal."""
        ...

    def admit_feedback(self, rendered_bytes: int, usable_bytes: int) -> None:
        """Refuses (fixed code) a required envelope that cannot carry the correction findings."""
        ...
