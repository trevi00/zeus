"""Shared native base-score admission and body budgeting.

Layer: domain
Context: context
Owns: native base-score admission of full skill bodies
Does not own: scoring (skills.ranking)
Entry points: select_bodies
Contracts: INV-SKILL-001
Moved from SOURCE M7 `src/codex_harness/domain/skill_admission.py` (behaviour unchanged unless noted).
"""
from codex_harness.context.domain.skills.ranking import (
    FULL_BODY_TOP_K,
    MAX_CONTEXT_CHARS,
    PER_BODY_CAP,
    apply_token_budget,
    fit_top_skill,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.numbers import finite_number

ADMISSION_MODEL = 'native-base-score-body-budget-v1'


def select_bodies(ranked, base_scores, threshold):
    require(finite_number(threshold), 'Invalid native admission threshold')
    ordered = sorted(ranked, key=lambda row: (-row[0], row[1]))
    full = [row for row in ordered if base_scores[row[1]] >= threshold][:FULL_BODY_TOP_K]
    capped, truncated = [], False
    for score, path, dimensions, body in full:
        reduced, cut = fit_top_skill(body, PER_BODY_CAP)
        capped.append((score, path, dimensions, reduced))
        truncated = truncated or cut
    fitted, budget_cut = apply_token_budget(capped, MAX_CONTEXT_CHARS)
    return fitted, truncated or budget_cut
