"""The research side of context's CompositionAdmission port (DESIGN-s8 §30 R-cd5, §30.1).

Context composes the council delivery and the correction feedback of one provider turn but may not import research
(import_rules DAG); this adapter hands it research's admission rules through `context.ports.CompositionAdmission`.
Pure delegation: every method calls the one research function that owns the rule and adds none.

Layer: adapters
Context: research
Owns: CouncilCompositionAdmission (the delegation of the four admission methods and the council policy name)
Does not own: the delivery admission (research.adapters.autonomous_roles.admitted_delivery), the council input policy
(research.domain.council_input), the feedback context check (research.adapters.correction_feedback.require_context),
the composition (context.application.compose) and its wiring into RunTask (composition, S10)
Entry points: CouncilCompositionAdmission
Contracts: INV-CONTEXT-001, INV-CONTINUATION-001
"""
from __future__ import annotations

from codex_harness.research.adapters import autonomous_roles, correction_feedback
from codex_harness.research.domain import council_input


class CouncilCompositionAdmission:
    council_policy = council_input.SCHEMA

    def __init__(self, feedback_require=correction_feedback.require_context):
        self.feedback_require = feedback_require

    def admit_delivery(self, agent, action, read_only, stage, evidence, delivery) -> dict:
        return autonomous_roles.admitted_delivery(agent, action, read_only, stage, evidence, delivery)

    def council_budget(self) -> tuple:
        return council_input.council_budget()

    def admit_council(self, rendered_bytes, delivery_bytes) -> dict:
        return council_input.admit_required(rendered_bytes, delivery_bytes)

    def admit_feedback(self, rendered_bytes, usable_bytes) -> None:
        return self.feedback_require(rendered_bytes, usable_bytes)
