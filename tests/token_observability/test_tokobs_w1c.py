"""W1 review round-1 corrections F1-F6 (REVIEW-W1-r1): regression tests built from the reviewer's discriminators.

Each test here fails on 459dcd5. Every number is derived by hand in the test body.
"""

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

TASK = "w1c-task"


# ----------------------------------------------------------------------------- F2


def _advisor_run(rig, mutate):
    """Sonnet main 100 output, Opus 80 output, one observed advisor consultation; total T = 180."""
    result = claude_result("r1", usage(0, 100, 0, 0), {SONNET: entry(0, 100, 0, 0), OPUS: entry(0, 80, 0, 0)})
    mutate(result)
    rig.record(TASK, start_row(TASK, 1, T0, advisor=OPUS), terminal_row("finished", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), assistant(advisor_blocks=1), result)
    return rig.scan(advance=60)


def _drop_stats(result):
    del result["subagent_stats"]


def _drop_field(result):
    del result["subagent_stats"]["spawned_by_subagents"]


def _wrong_type(result):
    result["subagent_stats"]["spawned"] = "0"


def _bool_field(result):
    result["subagent_stats"]["spawned_by_subagents"] = False


def _positive(result):
    result["subagent_stats"]["spawned"] = 2


def _explicit_zero(result):
    pass


@pytest.mark.parametrize("mutate,advisor_tokens,ambiguous_tokens", [
    (_drop_stats, 0, 80),
    (_drop_field, 0, 80),
    (_wrong_type, 0, 80),
    (_bool_field, 0, 80),
    (_positive, 0, 80),
    (_explicit_zero, 80, 0),  # the positive control: explicit zero/zero proves exclusivity
])
def test_f2_exclusive_advisor_needs_explicit_zero_nested_counters(tmp_path, mutate, advisor_tokens, ambiguous_tokens):
    rig = Rig(tmp_path)
    prom = _advisor_run(rig, mutate)
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="advisor", token_type="output") == advisor_tokens
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="advisor_or_nested", token_type="output") \
        == ambiguous_tokens
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 180  # the total never changes
    assert prom.sum("zeus_llm_advisor_consultations_total") == 1


def test_f2_no_consultation_stays_nested_unattributed_without_stats(tmp_path):
    rig = Rig(tmp_path)
    result = claude_result("r1", usage(0, 100, 0, 0), {SONNET: entry(0, 100, 0, 0), OPUS: entry(0, 80, 0, 0)})
    del result["subagent_stats"]
    rig.record(TASK, start_row(TASK, 1, T0, advisor=OPUS), terminal_row("finished", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), assistant(advisor_blocks=0), result)
    prom = rig.scan(advance=60)
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="nested_unattributed", token_type="output") == 80
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 180


def test_f2_one_result_without_the_zero_evidence_makes_the_process_unknown(tmp_path):
    rig = Rig(tmp_path)
    first = claude_result("r1", usage(0, 50, 0, 0), {SONNET: entry(0, 50, 0, 0)})
    second = claude_result("r2", usage(0, 50, 0, 0), {SONNET: entry(0, 100, 0, 0), OPUS: entry(0, 80, 0, 0)}, index=1)
    del second["subagent_stats"]
    rig.record(TASK, start_row(TASK, 1, T0, advisor=OPUS), terminal_row("finished", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), assistant(advisor_blocks=1), first, second)
    prom = rig.scan(advance=60)
    assert prom.sum("zeus_llm_tokens_total", role="advisor") == 0
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="advisor_or_nested", token_type="output") == 80


# ----------------------------------------------------------------------------- F3


def _resumed_pair(rig, version):
    """Attempt 1 cumulative 100; attempt 2 (resumed, init version `version`): M = 20, cumulative 150."""
    rig.record(TASK, start_row(TASK, 1, T0, advisor=None), terminal_row("finished", 1, T0 + 30),
               start_row(TASK, 2, T0 + 100, resumed=True, advisor=None), terminal_row("finished", 2, T0 + 200))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(0, 100, 0, 0), {SONNET: entry(0, 100, 0, 0)}))
    rig.events(TASK, 2, claude_init(version=version),
               claude_result("r2", usage(0, 20, 0, 0), {SONNET: entry(0, 150, 0, 0)}))
    return rig.scan(advance=300)


@pytest.mark.parametrize("version", ["9.9.1", "2.2.0", "3.0.0"])
def test_f3_an_uncharacterized_major_or_minor_publishes_m_only_with_one_unknown(tmp_path, version):
    rig = Rig(tmp_path)
    prom = _resumed_pair(rig, version)
    second = rig.invocation(TASK, 2)
    assert second["unknown_reason"] == "unknown_version_semantics"
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE invocation_id=? AND kind='tree_remainder'",
                   second["id"])[0][0] == 0
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 120  # 100 + M 20; the remainder 30 is withheld
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="unknown_version_semantics") == 1
    assert prom.sum("zeus_llm_unknown_shares_total", reason="unknown_version_semantics") == 1


def test_f3_a_supported_version_still_publishes_the_remainder(tmp_path):
    rig = Rig(tmp_path)
    prom = _resumed_pair(rig, "2.1.286")
    assert rig.invocation(TASK, 2)["unknown_reason"] is None
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 150  # 100 + M 20 + remainder 30 (150 - 100 - 20)


def test_f3_one_policy_distinguishes_parseable_from_supported():
    from tokobs.vocab import parse_version, version_semantics
    assert version_semantics(parse_version("2.1.270")) == "restart_zero"
    assert version_semantics(parse_version("2.1.277")) == "cumulative"
    assert version_semantics(parse_version("2.1.999")) == "cumulative"
    assert version_semantics(parse_version("2.2.0")) == "uncharacterized"
    assert version_semantics(parse_version("9.9.1")) == "uncharacterized"
