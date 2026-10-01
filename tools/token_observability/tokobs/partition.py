"""The disjoint token partition of one finalized Claude process (R1).

Purpose: given the distinct results of a process and its baseline, decide what the whole-tree remainder is and
which role each model's share takes, so each model's delta is counted exactly once. Pure functions: no I/O.
Layer: tooling. Owns: DESIGN §3.4 steps 1-8, §3.7 baseline selection inputs. Does-not-own: reading streams,
choosing the baseline (s1_routine), or writing contributions (publication).
Implements: ACCEPTANCE A01, A04, A31, A34, A35, A36, A37, A38, A42 (shares), A05/A45 (no_baseline).

Partition rules in one line: published(P) = M + N_e + sum over m != e of T_m = sum over m of T_m, where M is the
sum of distinct `usage` (published per result, outside this module) and this module returns only the remainder.
Only the accounting reasons (baseline, version, non_monotonic, inconsistent) publish M only (§3.4 step 6, C-W1-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .vocab import TOKEN_TYPES

# result_models / cumulative column names for the four normalized token types (K4).
USAGE_FIELDS = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
                "cache_write": "cache_creation_input_tokens"}
MODEL_USAGE_FIELDS = {"input": "inputTokens", "output": "outputTokens", "cache_read": "cacheReadInputTokens",
                      "cache_write": "cacheCreationInputTokens"}
COST_EPSILON = 1e-9
# `subagent_stats` evidence of one result (DESIGN §3.4 step 4). Absent, partial or wrong-typed counters are NOT zero.
NESTED_NONE = "none"  # both counters present as non-negative integers, both 0
NESTED_PRESENT = "present"  # a counter reports nested agents (> 0)
NESTED_UNKNOWN = "unknown"  # nested exclusivity cannot be established


@dataclass(frozen=True)
class ResultFacts:
    """What the partition needs of one distinct result (numbers and flags only)."""
    usage: dict[str, int] | None  # token_type -> value; None when absent or invalid
    models: dict[str, dict[str, float]] | None  # model label -> token_type/cost_usd; None when absent or invalid
    is_error: bool = False
    zeroed: bool = False
    nested: str = NESTED_UNKNOWN  # NESTED_NONE only on explicit zero/zero counters (DESIGN §3.4 step 4)

    @property
    def usable(self) -> bool:
        return self.zeroed or self.usage is not None


@dataclass(frozen=True)
class Baseline:
    """kind: `zero` (fresh process, or resumed before 2.1.277), `cumulative` (proven predecessor; `models` is
    its absolute last modelUsage), `unknown_version` (resumed, version missing), `missing`, `unproven`."""
    kind: str
    models: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class Plan:
    remainder: list[tuple[str, str, str, int]] = field(default_factory=list)  # (model, role, token_type, value)
    costs: dict[str, float] = field(default_factory=dict)
    reasons: set[str] = field(default_factory=set)
    share_models: list[str] = field(default_factory=list)
    cumulative: dict[str, dict[str, float]] | None = None  # the last good result's absolute modelUsage


def last_good(results: list[ResultFacts]) -> ResultFacts | None:
    """The newest result with a usable, non-zeroed modelUsage; a zeroed crash result carries no cumulative."""
    for result in reversed(results):
        if not result.zeroed and result.models:
            return result
    return None


def nested_state(results: list[ResultFacts]) -> str:
    """Process-level nested evidence: any reported nested agent wins; exclusivity needs explicit zero/zero counters
    on EVERY result, otherwise it is unknown (F2: missing evidence never proves advisor exclusivity)."""
    states = {r.nested for r in results}
    if NESTED_PRESENT in states:
        return NESTED_PRESENT
    return NESTED_NONE if states == {NESTED_NONE} else NESTED_UNKNOWN


def advisor_role(model: str, advisor: str | None, consultations: int, nested: str) -> str:
    """DESIGN §3.4 step 4: configuration alone never proves advisor use; exclusive `advisor` additionally needs
    explicit zero nested counters, else the ambiguous `advisor_or_nested`."""
    if advisor is not None and model == advisor and consultations >= 1:
        return "advisor" if nested == NESTED_NONE else "advisor_or_nested"
    return "nested_unattributed"


ACCOUNTING_REASONS = frozenset({"no_baseline", "unknown_version_semantics", "non_monotonic", "inconsistent"})


def plan_partition(results: list[ResultFacts], executor: str, advisor: str | None, consultations: int,
                   baseline: Baseline, external_reasons: set[str]) -> Plan:
    """C-W1-1: only the four accounting reasons (DESIGN §3.4 step 6) suppress the remainder. Lifecycle reasons
    (no_result, error_zeroed, terminal_unproven, incomplete_tail, malformed) are coverage facts: the remainder is
    evaluated against the last complete result with a valid modelUsage that is not a zeroed error result."""
    plan = Plan(reasons=set(external_reasons))
    if any(r.zeroed for r in results):
        plan.reasons.add("error_zeroed")
    if any(not r.usable for r in results):
        plan.reasons.add("malformed")  # a result without usable usage contributes no M
    good = last_good(results)
    if good is None:
        if results and not plan.reasons:
            plan.reasons.add("malformed")  # results exist but none carries a modelUsage
        return plan
    plan.cumulative = good.models
    accounting: set[str] = set()
    if "unknown_version_semantics" in plan.reasons:
        accounting.add("unknown_version_semantics")
    if baseline.kind == "unknown_version":
        accounting.add("unknown_version_semantics")
    elif baseline.kind in ("missing", "unproven"):
        accounting.add("no_baseline")
    base = baseline.models if baseline.kind == "cumulative" else {}
    deltas: dict[str, dict[str, int]] = {}
    if baseline.kind in ("zero", "cumulative"):
        for model, cum in good.models.items():
            ref = base.get(model, {})
            deltas[model] = {}
            for tau in TOKEN_TYPES:
                delta = int(cum[tau]) - int(ref.get(tau, 0))
                if delta < 0:
                    accounting.add("non_monotonic")  # step 2: never a negative contribution
                deltas[model][tau] = delta
    if "non_monotonic" not in accounting and deltas and "unknown_version_semantics" not in accounting:
        m_total = {tau: sum((r.usage or {}).get(tau, 0) for r in results if r.usable and not r.zeroed)
                   for tau in TOKEN_TYPES}
        exec_delta = deltas.get(executor, dict.fromkeys(TOKEN_TYPES, 0))
        if any(exec_delta[tau] - m_total[tau] < 0 for tau in TOKEN_TYPES):
            accounting.add("inconsistent")  # step 3: T_e < M
        else:
            nested = nested_state(results)
            for tau in TOKEN_TYPES:
                _push(plan, executor, "nested_unattributed", tau, exec_delta[tau] - m_total[tau])
            for model in sorted(deltas):
                if model == executor:
                    continue
                role = advisor_role(model, advisor, consultations, nested)
                for tau in TOKEN_TYPES:
                    _push(plan, model, role, tau, deltas[model][tau])
            for model in sorted(good.models):
                cost = float(good.models[model].get("cost_usd", 0.0)) - float(base.get(model, {}).get("cost_usd", 0.0))
                if cost > COST_EPSILON:
                    plan.costs[model] = cost
    plan.reasons |= accounting
    if accounting:
        plan.remainder.clear()
        plan.costs.clear()
        plan.share_models = sorted(good.models)
    return plan


def _push(plan: Plan, model: str, role: str, tau: str, value: int) -> None:
    if value > 0:
        plan.remainder.append((model, role, tau, value))
