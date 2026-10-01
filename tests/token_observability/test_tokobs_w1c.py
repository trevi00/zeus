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
from tokobs.__main__ import main
from tokobs.ledger import open_ledger
from tokobs.report import invocation_report, task_report

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


# ----------------------------------------------------------------------------- F4

COUNTER_TABLES = ("contributions", "cost_contributions", "unknown_shares", "reasoning_contributions",
                  "unbound_contributions")


def _published(rig):
    """Everything a counter is built from, plus every finalized outcome: it must not move on a late fact."""
    tables = {t: rig.sql(f"SELECT * FROM {t} ORDER BY rowid") for t in COUNTER_TABLES}
    tables["outcomes"] = rig.sql("SELECT id,lifecycle_state,outcome,unknown_reason,predecessor_state,finalized_at "
                                 "FROM invocations ORDER BY id")
    return tables


def _core(prom):
    return {k: v for k, v in prom.series.items() if k[0].startswith(("zeus_llm_", "zeus_task_"))}


def _task_report(rig, task):
    ledger = open_ledger(rig.data)
    try:
        return task_report(ledger, task)
    finally:
        ledger.close()


def _inv_report(rig, ref):
    ledger = open_ledger(rig.data)
    try:
        return invocation_report(ledger, ref)
    finally:
        ledger.close()


def _missing_predecessor(rig, version="2.1.286"):
    """Attempt 1's terminal row exists but its events do not; attempt 2 (cumulative 150, M = 20) finalizes
    `no_baseline`."""
    rig.record(TASK, start_row(TASK, 1, T0, advisor=None), terminal_row("finished", 1, T0 + 30),
               start_row(TASK, 2, T0 + 100, resumed=True, advisor=None), terminal_row("finished", 2, T0 + 200))
    rig.events(TASK, 2, claude_init(version=version),
               claude_result("r2", usage(0, 20, 0, 0), {SONNET: entry(0, 150, 0, 0)}))
    return rig.scan(advance=300)


def _late_events_1(rig):
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(0, 100, 0, 0), {SONNET: entry(0, 100, 0, 0)}))


def test_f4_a_predecessor_arriving_after_the_successor_finalized_is_a_linked_late_predecessor(tmp_path):
    rig = Rig(tmp_path)
    before = _missing_predecessor(rig)
    assert rig.invocation(TASK, 2)["unknown_reason"] == "no_baseline"
    assert before.sum("zeus_llm_tokens_total", token_type="output") == 20  # M only
    frozen, frozen_core = _published(rig), _core(before)

    _late_events_1(rig)
    after = rig.scan(advance=30)
    assert after.sum("zeus_tokobs_ledger_corrections_total", kind="late_predecessor") == 1  # 0 on 459dcd5
    assert after.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1  # the growth fact stays
    assert _published(rig) == frozen and _core(after) == frozen_core  # nothing published, nothing re-finalized
    assert rig.sql("SELECT COUNT(*) FROM late_results WHERE invocation_id=?", f"routine:{TASK}:1") == [(1,)]
    assert rig.sql("SELECT linked_ref FROM corrections WHERE kind='late_predecessor'") == [(f"routine:{TASK}:1",)]

    report = _task_report(rig, TASK)
    first, second = report["invocations"]
    assert first["late"]["late_results"][0]["cumulative"][0]["output"] == 100
    refined = second["late"]["refined_allocation"]
    assert (refined["state"], refined["predecessor"], refined["published"]) == ("refined", f"routine:{TASK}:1", False)
    assert refined["remainder"] == [{"model": SONNET, "role": "nested_unattributed", "token_type": "output",
                                     "value": 30}]  # 150 - 100 - M 20
    assert second["unknown_reason"] == "no_baseline"  # the finalized unknown is untouched

    replay = rig.scan(advance=30)  # a replay adds no correction twice
    assert replay.sum("zeus_tokobs_ledger_corrections_total", kind="late_predecessor") == 1
    assert _published(rig) == frozen


def test_f4_a_late_predecessor_that_still_cannot_refine_reports_still_unknown(tmp_path):
    rig = Rig(tmp_path)
    _missing_predecessor(rig, version="9.9.1")  # an uncharacterized version: the unknown stays
    _late_events_1(rig)
    rig.scan(advance=30)
    refined = _task_report(rig, TASK)["invocations"][1]["late"]["refined_allocation"]
    assert (refined["state"], refined["reason"], refined["remainder"]) == ("still_unknown",
                                                                           "unknown_version_semantics", [])


def test_f4_late_results_without_numbers_link_nothing(tmp_path):
    rig = Rig(tmp_path)
    _missing_predecessor(rig)
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(0, 5, 0, 0), None))  # no modelUsage
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_predecessor") == 0
    assert "late" not in _task_report(rig, TASK)["invocations"][1]


def _codex_horizon_run(rig):
    rig.codex_script("h", resume=False)
    path = rig.codex_events("h", codex_thread_started(THREAD), {"type": "turn.started"})
    rig.scan(advance=CODEX_IDLE)
    assert rig.inv("codex:h")["terminal_evidence"] == "horizon"
    return path


def test_f4_a_codex_terminal_after_the_horizon_is_a_late_terminal_not_only_late_tail(tmp_path):
    rig = Rig(tmp_path)
    path = _codex_horizon_run(rig)
    frozen = _published(rig)
    _append(path, codex_turn_completed(CODEX_P0))
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1  # 0 on 459dcd5
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1  # distinct growth fact
    assert _published(rig) == frozen  # the finalized outcome and counters stay
    assert rig.inv("codex:h")["outcome"] == "terminal_unproven"
    again = rig.scan(advance=30)
    assert again.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1  # idempotent

    for ref in ("h", "codex:h"):  # a run stem and the canonical ID both resolve, without a task binding
        late = _inv_report(rig, ref)["invocation"]["late"]
        assert late["late_terminal"] == {"turn": "completed", "thread_id": THREAD, "usage_state": "ok",
                                         "input_tokens": 1000, "cached": 800, "cache_write": 0, "output": 100,
                                         "reasoning": 30}
        assert _inv_report(rig, ref)["invocation"]["task_id"] is None


def test_f4_a_codex_failed_terminal_after_the_horizon_is_recognized_too(tmp_path):
    rig = Rig(tmp_path)
    path = _codex_horizon_run(rig)
    _append(path, {"type": "turn.failed", "error": {"message": "x"}})
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1
    assert _inv_report(rig, "h")["invocation"]["late"]["late_terminal"]["turn"] == "failed"


def test_f4_a_late_codex_point_is_linked_and_reported_as_a_split_of_the_published_interval(tmp_path):
    rig = Rig(tmp_path)
    for stem, point, resume in (("r0", CODEX_P0, False), ("r2", codex_usage(2100, 1700, 250, 55), True)):
        rig.codex_script(stem, resume=resume)
        rig.codex_events(stem, codex_thread_started(THREAD), codex_turn_completed(point))
    first = rig.scan(advance=30)
    frozen = _published(rig)
    rig.codex_script("r1", resume=True)
    rig.codex_events("r1", codex_thread_started(THREAD), codex_turn_completed(CODEX_P1))
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_point") == 1
    assert late.sum("zeus_llm_tokens_total") == first.sum("zeus_llm_tokens_total")  # counters unchanged
    assert {k: v for k, v in _published(rig).items() if k != "outcomes"} == {
        k: v for k, v in frozen.items() if k != "outcomes"}  # no contribution, share or cost was added

    for ref in ("r1", "codex:r1"):  # both resolved to null on 459dcd5
        item = _inv_report(rig, ref)["invocation"]["late"]["late_points"][0]
        assert item["state"] == "refined" and item["published"] is False
        assert item["before"]["deltas"]["output"] == 60  # p1 - p0: 160 - 100
        assert item["after"]["deltas"]["output"] == 90  # p2 - p1: 250 - 160
        assert item["previous_point_id"] is not None and item["next_point_id"] is not None
    correction = rig.sql("SELECT linked_ref FROM corrections WHERE kind='late_point'")
    assert correction == [(str(item["point"]["point_id"]),)]
    assert rig.scan(advance=30).sum("zeus_tokobs_ledger_corrections_total", kind="late_point") == 1


def test_f4_report_cli_looks_up_an_invocation_without_a_task_binding(tmp_path, capsys):
    rig = Rig(tmp_path)
    _codex_horizon_run(rig)
    capsys.readouterr()
    assert main(["report", "--data", str(rig.data), "--invocation", "h"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["invocation"]["id"] == "codex:h" and "task" not in out
    assert main(["report", "--data", str(rig.data), "--invocation", "nothing"]) == 1
