"""W1 review round-1 corrections F1-F6 (REVIEW-W1-r1): regression tests built from the reviewer's discriminators.

Each test here fails on 459dcd5. Every number is derived by hand in the test body.
"""

import json

import pytest
from fixtures import (
    OPUS,
    SONNET,
    T0,
    Rig,
    assistant,
    claude_init,
    claude_result,
    codex_thread_started,
    codex_turn_completed,
    codex_usage,
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


# ----------------------------------------------------------------------------- F1

HORIZON = 14_400
THREAD = "01a0e11e-synthetic-thread"
CODEX_P0 = codex_usage(1000, 800, 100, 30)
CODEX_P1 = codex_usage(1500, 1200, 160, 40)  # the unnamed stream's interval over P0: output 60
CODEX_IDLE = 2 * 900 + 60


def _append(path, *lines):
    with path.open("a") as handle:
        for line in lines:
            handle.write(json.dumps(line, sort_keys=True) + "\n")


def _claude_lines():
    return (claude_init(model=SONNET), claude_result("x1", usage(0, 100, 0, 0), {SONNET: entry(0, 100, 0, 0)}))


def _unbound_claude(rig):
    return rig.sql("SELECT model, SUM(value) FROM unbound_contributions WHERE token_type='output' GROUP BY model")


def test_f1_a_claude_alias_split_across_scans_publishes_the_fact_once_under_the_init_model(tmp_path):
    rig = Rig(tmp_path)
    init, result_line = _claude_lines()
    path = rig.stream("fleet-split-events.jsonl", init)
    rig.scan(advance=30)  # init only
    rig.scan(advance=30)  # a collector restart: every scan opens the ledger anew
    _append(path, result_line)
    rig.touch(path)
    rig.scan(advance=30)
    whole = rig.stream("fleet-whole-events.jsonl", init, result_line)  # a renamed complete copy
    rig.touch(whole)
    prom = rig.scan(advance=HORIZON + 100)
    assert prom.sum("zeus_llm_tokens_total", token_type="output", task_class="identity_unavailable") == 100
    assert _unbound_claude(rig) == [(SONNET, 100)]  # not 100 under `other` plus 100 under Sonnet
    assert rig.sql("SELECT COUNT(*) FROM invocations")[0][0] == 0
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert prom.sum("zeus_llm_tokens_total", token_type="output", task_class="identity_unavailable") == \
        rig.scan(advance=60).sum("zeus_llm_tokens_total", token_type="output", task_class="identity_unavailable")


def test_f1_the_split_result_is_read_in_bounded_chunks_with_the_same_totals(tmp_path):
    rig = Rig(tmp_path)
    init, result_line = _claude_lines()
    path = rig.stream("fleet-chunk-events.jsonl", init, result_line)
    rig.touch(path)
    for _ in range(12):  # a one-line chunk per scan: the init is read several scans before the result
        rig.scan(advance=30, max_read_bytes=64)
    prom = rig.scan(advance=HORIZON + 100, max_read_bytes=64)
    assert _unbound_claude(rig) == [(SONNET, 100)]
    assert prom.sum("zeus_llm_tokens_total", token_type="output", task_class="identity_unavailable") == 100


def test_f1_two_unbound_copies_with_different_provisional_labels_publish_one_fact(tmp_path):
    rig = Rig(tmp_path)
    init, result_line = _claude_lines()
    with_init = rig.stream("fleet-a-events.jsonl", init, result_line)
    without_init = rig.stream("fleet-b-events.jsonl", result_line)  # no init: the provisional label is `other`
    rig.touch(with_init)
    rig.touch(without_init)
    prom = rig.scan(advance=HORIZON + 100)
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 100
    assert rig.sql("SELECT COUNT(*) FROM unbound_contributions WHERE token_type='output'") == [(1,)]


def test_f1_a_new_read_identity_does_not_inherit_the_previous_context(tmp_path):
    rig = Rig(tmp_path)
    init, result_line = _claude_lines()
    path = rig.stream("fleet-rot-events.jsonl", init)
    rig.scan(advance=30)
    path.unlink()
    rig.stream("fleet-rot-events.jsonl", claude_result("y1", usage(0, 7, 0, 0), {OPUS: entry(0, 7, 0, 0)}))
    rig.scan(advance=30)
    rig.scan(advance=HORIZON + 100)
    assert rig.sql("SELECT model, SUM(value) FROM unbound_contributions WHERE token_type='output' GROUP BY model") \
        == [("other", 7)]  # the rotated file has no init of its own


def test_f1_canonical_arrival_after_a_split_alias_publishes_nothing_twice(tmp_path):
    rig = Rig(tmp_path)
    init, result_line = _claude_lines()
    path = rig.stream("fleet-split-events.jsonl", init)
    rig.scan(advance=30)
    _append(path, result_line)
    rig.touch(path)
    rig.scan(advance=HORIZON + 100)
    assert _unbound_claude(rig) == [(SONNET, 100)]
    rig.record("late-task", start_row("late-task", 1, rig.now - 100, advisor=None),
               terminal_row("finished", 1, rig.now))
    rig.events("late-task", 1, init, result_line)
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 100
    assert prom.sum("zeus_llm_invocations_total") == 1  # the canonical outcome exists once


def _codex_total(prom):
    return prom.sum("zeus_llm_tokens_total", token_type="output")


def _codex_run_x(rig):
    rig.codex_script("x", resume=False)
    rig.codex_events("x", codex_thread_started(THREAD), codex_turn_completed(CODEX_P0))


def test_f1_a_codex_alias_split_after_thread_started_keeps_its_point(tmp_path):
    whole = Rig(tmp_path / "whole")
    _codex_run_x(whole)
    path = whole.codex_events("unnamed", codex_thread_started(THREAD), codex_turn_completed(CODEX_P1))
    whole.touch(path)
    expected = _codex_total(whole.scan(advance=CODEX_IDLE))
    assert expected == 100 + 60  # the named run's P0 and the unnamed stream's interval

    rig = Rig(tmp_path / "split")
    _codex_run_x(rig)
    path = rig.codex_events("unnamed", codex_thread_started(THREAD))
    rig.scan(advance=30)  # thread.started only
    rig.scan(advance=30)  # a restart between the scans
    _append(path, codex_turn_completed(CODEX_P1))
    rig.touch(path)
    prom = rig.scan(advance=CODEX_IDLE)
    assert rig.sql("SELECT COUNT(*) FROM alias_codex_points") == [(1,)]  # 0 on 459dcd5
    assert _codex_total(prom) == expected
    copy = rig.codex_events("renamed", codex_thread_started(THREAD), codex_turn_completed(CODEX_P1))
    rig.touch(copy)
    again = rig.scan(advance=CODEX_IDLE)
    assert _codex_total(again) == expected  # a duplicate copy adds nothing before or after the horizon
    assert rig.sql("SELECT COUNT(*) FROM invocations")[0][0] == 1  # only the named run
