"""The invocation-outcome vocabulary: what one execution's own output was classified as (INV-INVOCATION-001).

Layer: domain
Context: execution
Owns: INVOCATION_OUTCOMES, invocation_outcome and the closed code vocabularies OUTPUT_REASONS, FAILURE_OWNERS,
    PROVIDER_CAUSES, TERMINAL_SUBTYPES, STRUCTURAL_CHECKS, SUBTYPE_REASONS (M7 `domain/observation.py`, moved in S4
    unchanged: named coverage correction observation→execution, DESIGN-run-task D9; RunTask classifies its own
    output with them, and observation re-imports them for its events)
Does not own: the observation event contract (observation.domain.observation)
Entry points: invocation_outcome, INVOCATION_OUTCOMES, OUTPUT_REASONS, FAILURE_OWNERS, PROVIDER_CAUSES,
    TERMINAL_SUBTYPES, STRUCTURAL_CHECKS, SUBTYPE_REASONS
Contracts: INV-INVOCATION-001, INV-OBSERVATION-001
"""

from __future__ import annotations

from codex_harness.kernel.errors import require

# Runner classification (INV-INVOCATION-001) → observation outcome. Only `accepted` succeeds.
INVOCATION_OUTCOMES = {"accepted": "succeeded", "empty_answer": "failed", "invalid_output": "failed",
                       "tool_only": "failed", "provider_failure": "failed", "interrupted": "aborted",
                       "inspection_blocked": "blocked"}

# Closed code vocabularies for the boundary events above (operating-portfolio-001). Each lists the
# values this harness itself produces: the structural output reasons and owners of
# adapters.execution_output, the provider failure causes of the Codex and Claude adapters, the
# provider result subtypes those adapters read, and the structural check states. `safe_code` maps
# anything else, including a value a future provider version invents, to "unknown" rather than
# letting a foreign string become a Zeus code.
OUTPUT_REASONS = ("empty", "invalid_text", "invalid_json", "schema_mismatch", "schema_configuration")
FAILURE_OWNERS = ("agent_output", "configuration", "provider")
PROVIDER_CAUSES = ("codex-provider-usage-limit-exceeded", "claude-provider-budget-exhausted",
                   "claude-provider-usage-limit-exceeded", "claude-provider-authentication-failed",
                   "claude-provider-cancelled", "claude-provider-conflicting-terminal",
                   "claude-provider-error-result", "claude-provider-exit-conflict",
                   "claude-provider-max-turns", "claude-provider-missing-terminal",
                   "claude-provider-model-mismatch", "claude-provider-read-only-violation",
                   "claude-provider-session-conflicting",
                   "claude-provider-session-mismatch", "claude-provider-session-unreported",
                   "claude-provider-startup-failed", "claude-provider-stream-truncated",
                   "claude-provider-timeout")
TERMINAL_SUBTYPES = ("success", "error_during_execution", "error_max_turns",
                     "error_max_structured_output_retries")
STRUCTURAL_CHECKS = ("checked", "unchecked", "failed", "configuration_error")

# A terminal subtype that names its own actionable failure also names the projected reason, so an
# operator can tell it apart from every other provider failure without reading a raw stream. Only a
# subtype this harness declares can reach this map, because `safe_code` runs first and a foreign or
# future string is `unknown`; nothing about the output itself is inferred from the subtype, and a
# structural output reason, when there is one, stays the reason.
SUBTYPE_REASONS = {"error_max_structured_output_retries": "output_structured_retries_exhausted"}


def invocation_outcome(classification: str) -> str:
    require(classification in INVOCATION_OUTCOMES, "Unknown invocation classification")
    return INVOCATION_OUTCOMES[classification]
