"""ACCEPTANCE A34-A38, A42 (R1 partition) and A22 (model normalization): arithmetic derived by hand."""

import pytest
from fixtures import (
    OPUS,
    SONNET,
    T0,
    Rig,
    assistant,
    claude_init,
    claude_result,
    entry,
    start_row,
    terminal_row,
    usage,
)
from tokobs.partition import Baseline, ResultFacts, plan_partition
from tokobs.vocab import is_model_mismatch, normalize_model

TASK = "partition-task"
HAIKU = "claude-haiku-4-5"


def run_fresh(rig, *, usage_value, models, blocks=0, spawned=0, advisor=OPUS):
    rig.record(TASK, start_row(TASK, 1, T0, advisor=advisor), terminal_row("finished", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), assistant(advisor_blocks=blocks),
               claude_result("r1", usage_value, models, spawned=spawned))
    return rig.scan(advance=60)


def test_a34_partition_arithmetic_150_not_100_and_not_250(tmp_path):
    rig = Rig(tmp_path)
    # M = 100 in every type scaled (10/100/1000/50), T_e = 150 in every type scaled (15/150/1500/75)
    prom = run_fresh(rig, usage_value=usage(10, 100, 1000, 50), models={SONNET: entry(15, 150, 1500, 75)})
    for tau, m_value, t_value in (("input", 10, 15), ("output", 100, 150), ("cache_read", 1000, 1500),
                                  ("cache_write", 50, 75)):
        assert prom.sum("zeus_llm_tokens_total", role="implementer", token_type=tau) == m_value
        assert prom.sum("zeus_llm_tokens_total", role="nested_unattributed", token_type=tau) == t_value - m_value
        assert prom.sum("zeus_llm_tokens_total", token_type=tau) == t_value  # each model delta exactly once
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 150


def test_a35_shared_advisor_model_counted_once_as_advisor_or_nested(tmp_path):
    rig = Rig(tmp_path)
    prom = run_fresh(rig, usage_value=usage(1, 10, 10, 1), blocks=1, spawned=1,
                     models={SONNET: entry(1, 10, 10, 1), OPUS: entry(0, 80, 0, 0)})
    assert prom.sum("zeus_llm_tokens_total", model=OPUS) == 80
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="advisor_or_nested", token_type="output") == 80
    assert prom.sum("zeus_llm_tokens_total", role="advisor") == 0
    assert prom.sum("zeus_llm_advisor_consultations_total") == 1


def test_a36_carried_advisor_entry_is_zero_delta():
    carried = {OPUS: {"input": 40, "output": 20, "cache_read": 0, "cache_write": 0, "cost_usd": 0.6}}
    results = [ResultFacts({"input": 2, "output": 9, "cache_read": 0, "cache_write": 0},
                           {SONNET: {"input": 2, "output": 109, "cache_read": 0, "cache_write": 0, "cost_usd": 2.5},
                            OPUS: dict(carried[OPUS])})]
    base = Baseline("cumulative", {SONNET: {"input": 0, "output": 100, "cache_read": 0, "cache_write": 0,
                                            "cost_usd": 2.0}, OPUS: dict(carried[OPUS])})
    plan = plan_partition(results, SONNET, OPUS, 0, base, set())
    assert plan.reasons == set() and plan.remainder == []  # T_a = 0 -> no advisor contribution, no remainder
    assert plan.costs == {SONNET: pytest.approx(0.5)}


def test_a37_no_baseline_and_inconsistent_publish_m_only_never_m_plus_t(tmp_path):
    rig = Rig(tmp_path)
    # (b) T_e < M in one type: output 100 reported by `usage`, but modelUsage says 90
    prom = run_fresh(rig, usage_value=usage(1, 100, 10, 1), models={SONNET: entry(1, 90, 10, 1)})
    assert rig.invocation(TASK, 1)["unknown_reason"] == "inconsistent"
    assert prom.sum("zeus_llm_tokens_total", role="implementer", token_type="output") == 100
    assert prom.sum("zeus_llm_tokens_total", role="nested_unattributed") == 0
    # (a) predecessor missing is exercised in test_a05_a45 (s1 lifecycle); here the pure plan
    plan = plan_partition([ResultFacts({"input": 1, "output": 5, "cache_read": 0, "cache_write": 0},
                                       {SONNET: {"input": 1, "output": 5, "cache_read": 0, "cache_write": 0,
                                                 "cost_usd": 0.0}})], SONNET, None, 0, Baseline("missing"), set())
    assert plan.reasons == {"no_baseline"} and plan.remainder == [] and plan.share_models == [SONNET]


def test_a37_non_monotonic_never_a_negative_contribution():
    cum = lambda out: {"input": 0, "output": out, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}  # noqa: E731
    plan = plan_partition([ResultFacts({"input": 0, "output": 1, "cache_read": 0, "cache_write": 0}, {SONNET: cum(5)})],
                          SONNET, None, 0, Baseline("cumulative", {SONNET: cum(9)}), set())
    assert plan.reasons == {"non_monotonic"} and plan.remainder == []


def test_a38_advisor_model_without_a_consultation_is_nested_unattributed(tmp_path):
    rig = Rig(tmp_path)
    prom = run_fresh(rig, usage_value=usage(1, 10, 10, 1), blocks=0,
                     models={SONNET: entry(1, 10, 10, 1), OPUS: entry(5, 25, 0, 0)})
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="nested_unattributed", token_type="output") == 25
    assert prom.sum("zeus_llm_tokens_total", role="advisor") == 0  # configuration alone proves nothing
    assert prom.sum("zeus_llm_advisor_consultations_total") == 0


def test_a42_multiple_unknown_shares_count_one_unknown_invocation(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 10),
               start_row(TASK, 2, T0 + 20, resumed=True), terminal_row("failed", 2, T0 + 30))  # no file for attempt 1
    rig.events(TASK, 2, claude_init(), claude_result("r2", usage(1, 5, 5, 1), {
        SONNET: entry(1, 5, 5, 1), OPUS: entry(1, 5, 5, 1), HAIKU: entry(1, 5, 5, 1)}))
    prom = rig.scan(advance=60)
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="no_baseline") == 1
    assert prom.sum("zeus_llm_unknown_shares_total", reason="no_baseline") == 3
    assert prom.sum("zeus_llm_unknown_invocations_total") <= prom.sum("zeus_llm_invocations_total")


def test_a22_model_aliases_variants_unrecognized_and_mismatch(tmp_path):
    assert normalize_model("claude-opus-5-5[1m]").label == OPUS
    assert normalize_model("opus").label == OPUS and normalize_model("sonnet").label == SONNET
    foo = normalize_model("foo-model")
    assert (foo.label, foo.recognized) == ("other", False)
    assert normalize_model(None).recognized is None
    assert is_model_mismatch("opus", "claude-opus-5-5[1m]") is False
    assert is_model_mismatch(SONNET, OPUS) is True
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0, model="opus"), terminal_row("finished", 1, T0 + 10))
    rig.events(TASK, 1, claude_init(model="claude-opus-5-5[1m]"),
               claude_result("r1", usage(1, 5, 5, 1), {"claude-opus-5-5[1m]": entry(1, 5, 5, 1)}))
    rig.record("odd-task", start_row("odd-task", 1, T0, model=SONNET), terminal_row("finished", 1, T0 + 10))
    rig.events("odd-task", 1, claude_init(model="foo-model"),
               claude_result("o1", usage(1, 5, 5, 1), {"foo-model": entry(1, 5, 5, 1)}))
    prom = rig.scan(advance=60)
    assert prom.sum("zeus_llm_tokens_total", model=OPUS) == 1 + 5 + 5 + 1  # the `[1m]` variant and the alias
    assert prom.sum("zeus_llm_tokens_total", model="other") == 12
    assert prom.sum("zeus_llm_model_unrecognized_total") == 1
    assert prom.sum("zeus_llm_model_mismatch_total") == 1  # odd-task: requested sonnet, observed foo-model
    assert rig.invocation(TASK, 1)["executor_model_raw"] == "claude-opus-5-5[1m]"  # raw kept in the ledger
