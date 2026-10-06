"""Shared native base-score admission and body budgeting."""
from codex_harness.domain.model import require
from codex_harness.domain.skill_ranking import (
    FULL_BODY_TOP_K,
    MAX_CONTEXT_CHARS,
    PER_BODY_CAP,
    apply_token_budget,
    fit_top_skill,
)
from codex_harness.domain.threshold_replay import finite_number

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
