"""ACCEPTANCE A01-A11, A19, A31, A39, A40, A44, A45 on synthetic S1 sources (DESIGN §3.2-§3.7)."""

from fixtures import (
    OPUS,
    SONNET,
    T0,
    Rig,
    assistant,
    claude_init,
    claude_result,
    completed_row,
    entry,
    start_row,
    terminal_row,
    usage,
)

TASK = "synthetic-task"


def tokens(prom, **labels):
    return prom.sum("zeus_llm_tokens_total", **labels)


def fresh_attempt_with_advisor(rig, task=TASK, attempt=1, terminal="finished", *, resumed=False, uuid="r1"):
    rig.record(task, start_row(task, attempt, rig.now, resumed=resumed))
    rig.events(task, attempt, claude_init(), assistant(advisor_blocks=1),
               claude_result(uuid, usage(5, 100, 2000, 300),
                             {SONNET: entry(5, 100, 2000, 300, 2.0), OPUS: entry(40, 20, 0, 0, 0.6)}))
    rig.receipt(task, attempt)
    if terminal:
        rig.record(task, terminal_row(terminal, attempt, rig.now + 60))


def test_a01_fresh_attempt_partition_roles_and_total(tmp_path):
    rig = Rig(tmp_path)
    fresh_attempt_with_advisor(rig)
    prom = rig.scan(advance=120)
    assert tokens(prom, role="implementer", model=SONNET, token_type="input") == 5
    assert tokens(prom, role="implementer", token_type="output") == 100
    assert tokens(prom, role="implementer", token_type="cache_read") == 2000
    assert tokens(prom, role="implementer", token_type="cache_write") == 300
    assert tokens(prom, role="nested_unattributed") == 0  # T_e == M, so N_e is 0 and publishes nothing
    assert tokens(prom, role="advisor", model=OPUS, token_type="input") == 40
    assert tokens(prom, role="advisor", model=OPUS, token_type="output") == 20
    assert tokens(prom) == (5 + 100 + 2000 + 300) + (40 + 20)  # sum over models of T, each once
    assert prom.sum("zeus_llm_advisor_consultations_total", executor_model=SONNET, advisor_model=OPUS) == 1
    assert prom.sum("zeus_llm_invocations_total", outcome="finished", role="implementer", source="routine") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert rig.invocation(TASK, 1)["predecessor_state"] == "none"
    assert prom.sum("zeus_llm_estimated_cost_usd_total", model=OPUS) == 0.6


def test_a02_active_stream_publishes_result_but_stays_open(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(), assistant(),
               claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5)}))
    prom = rig.scan(advance=30)
    assert tokens(prom, role="implementer", token_type="output") == 10
    assert prom.sum("zeus_llm_open_invocations", state="open") == 1
    assert prom.sum("zeus_llm_invocations_total") == 0 and prom.sum("zeus_llm_unknown_invocations_total") == 0
    rig.events(TASK, 1, claude_result("r2", usage(0, 5, 0, 0), {SONNET: entry(1, 15, 100, 5)}, index=1))
    prom = rig.scan(advance=30)  # a later result does not finalize; only the terminal row does
    assert tokens(prom, role="implementer", token_type="output") == 15
    assert prom.sum("zeus_llm_open_invocations", state="open") == 1
    assert prom.sum("zeus_llm_invocations_total") == 0
    rig.record(TASK, terminal_row("finished", 1, rig.now))
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total", outcome="finished") == 1
    assert prom.sum("zeus_llm_open_invocations", state="open") == 0


def test_a03_a39_seven_results_over_scans_then_terminal_then_replay(tmp_path):
    rig = Rig(tmp_path)
    outputs = [1000, 1100, 1200, 1300, 1400, 779, 1000]
    assert sum(outputs) == 7779  # the R2-shaped total
    rig.record(TASK, start_row(TASK, 1, T0))
    lines, cumulative = [], 0
    for index, out in enumerate(outputs):
        cumulative += out
        lines.append(claude_result(f"r{index}", usage(1, out, 10, 1), {SONNET: entry(index + 1, cumulative, 10 * (index + 1),
                                                                                      index + 1)}, index=index))
    rig.events(TASK, 1, claude_init(), lines[0])
    seen = [tokens(rig.scan(advance=30), token_type="output")]
    rig.events(TASK, 1, *lines[1:])
    prom = rig.scan(advance=30)
    seen.append(tokens(prom, token_type="output"))
    assert prom.sum("zeus_llm_invocations_total") == 0
    rig.record(TASK, terminal_row("finished", 1, rig.now))
    prom = rig.scan(advance=30)
    seen.append(tokens(prom, token_type="output"))
    assert prom.sum("zeus_llm_invocations_total") == 1
    prom = rig.scan(advance=30)  # replay: nothing changes
    seen.append(tokens(prom, token_type="output"))
    assert seen == [1000, 7779, 7779, 7779]
    assert prom.sum("zeus_llm_invocations_total") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert tokens(prom, role="nested_unattributed") == 0


def test_a04_resume_usage_per_process_modelusage_cumulative(tmp_path):
    rig = Rig(tmp_path)
    fresh_attempt_with_advisor(rig)
    rig.record(TASK, start_row(TASK, 2, T0 + 100, resumed=True))
    rig.events(TASK, 2, claude_init(), claude_result(
        "r2", usage(2, 9, 500, 20), {SONNET: entry(7, 109, 2500, 320, 2.5), OPUS: entry(40, 20, 0, 0, 0.6, carried=True)}))
    rig.record(TASK, terminal_row("finished", 2, T0 + 200))
    prom = rig.scan(advance=300)
    assert rig.invocation(TASK, 2)["predecessor_state"] == "proven"
    assert rig.invocation(TASK, 2)["unknown_reason"] is None
    # attempt 2 publishes M only: T_sonnet = cum(2) - cum(1) = (2,9,500,20) = M, T_opus = 0
    contributions = rig.sql("SELECT kind,model,role,token_type,value FROM contributions WHERE invocation_id=?",
                            "routine:synthetic-task:2")
    assert sorted(contributions) == sorted([("main_result", SONNET, "implementer", "input", 2),
                                            ("main_result", SONNET, "implementer", "output", 9),
                                            ("main_result", SONNET, "implementer", "cache_read", 500),
                                            ("main_result", SONNET, "implementer", "cache_write", 20)])
    assert prom.sum("zeus_llm_estimated_cost_usd_total", model=SONNET) == 2.5  # 2.0 (attempt 1) + 0.5 delta
    assert prom.sum("zeus_llm_estimated_cost_usd_total", model=OPUS) == 0.6  # the carried entry adds nothing


def test_a05_a45_resume_without_baseline_never_uses_an_older_attempt(tmp_path):
    rig = Rig(tmp_path)
    fresh_attempt_with_advisor(rig)  # attempt 1 has events
    rig.record(TASK, start_row(TASK, 2, T0 + 100, resumed=True), terminal_row("failed", 2, T0 + 200))  # no file
    rig.record(TASK, start_row(TASK, 3, T0 + 300, resumed=True))
    rig.events(TASK, 3, claude_init(), claude_result(
        "r3", usage(2, 9, 500, 20), {SONNET: entry(7, 109, 2500, 320), OPUS: entry(40, 20)}))
    rig.record(TASK, terminal_row("finished", 3, T0 + 400))
    prom = rig.scan(advance=500)
    third = rig.invocation(TASK, 3)
    assert third["predecessor_state"] == "missing" and third["unknown_reason"] == "no_baseline"
    assert rig.invocation(TASK, 2)["unknown_reason"] == "no_result"
    rows = rig.sql("SELECT kind,token_type,value FROM contributions WHERE invocation_id=? ORDER BY token_type",
                   "routine:synthetic-task:3")
    assert {r[0] for r in rows} == {"main_result"}  # M only; no cum(3) - cum(1) remainder
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="no_baseline") == 1
    assert prom.sum("zeus_llm_unknown_shares_total", reason="no_baseline") == 2  # sonnet and opus in cum(3)


def test_a06_zeroed_error_result_is_error_zeroed_not_zero_tokens(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("failed", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), claude_result("e1", usage(), {}, is_error=True, subtype="error_during_execution"))
    prom = rig.scan(advance=60)
    assert tokens(prom) == 0
    assert prom.sum("zeus_llm_invocations_total", outcome="failed") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="error_zeroed") == 1


def test_a07_success_then_zeroed_crash_keeps_earlier_contributions(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(),
               claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5)}),
               claude_result("r2", usage(1, 20, 100, 5), {SONNET: entry(2, 30, 200, 10)}, index=1))
    before = tokens(rig.scan(advance=30))
    assert before == 1 + 10 + 100 + 5 + 1 + 20 + 100 + 5
    rig.events(TASK, 1, claude_result("crash", usage(), {}, index=2, is_error=True, subtype="error_during_execution"))
    rig.record(TASK, terminal_row("failed", 1, rig.now))
    prom = rig.scan(advance=30)
    assert tokens(prom) == before  # no decrease, and no tokens from the crash
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="error_zeroed") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total") == 1


def test_a08_result_without_usage_publishes_nothing_one_unknown(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 30))
    rig.events(TASK, 1, claude_init(), claude_result("r1", None, None))
    prom = rig.scan(advance=60)
    assert tokens(prom) == 0
    assert rig.invocation(TASK, 1)["unknown_reason"] == "malformed"  # lowest precedence: an unusable result
    assert prom.sum("zeus_llm_unknown_invocations_total") == 1 == prom.sum("zeus_llm_invocations_total")


def test_a09_timeout_without_result_is_no_result(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("timed_out", 1, T0 + 3600))
    rig.events(TASK, 1, claude_init())
    prom = rig.scan(advance=4000)
    assert prom.sum("zeus_llm_invocations_total", outcome="timed_out") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="no_result") == 1


def test_a10_cancel_then_resume_task_attempts_and_first_pass(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("interrupted", 1, T0 + 100))
    rig.events(TASK, 1, claude_init())
    rig.record(TASK, start_row(TASK, 2, T0 + 200, resumed=True))
    rig.events(TASK, 2, claude_init(), claude_result("r2", usage(1, 8, 50, 2), {SONNET: entry(1, 8, 50, 2)}))
    rig.record(TASK, terminal_row("finished", 2, T0 + 300), completed_row("accepted", T0 + 400))
    prom = rig.scan(advance=500)
    first, second = rig.invocation(TASK, 1), rig.invocation(TASK, 2)
    assert first["outcome"] == "interrupted" and first["unknown_reason"] == "no_result"
    assert second["predecessor_id"] == "routine:synthetic-task:1" and second["unknown_reason"] == "no_baseline"
    assert prom.sum("zeus_task_attempts_total", outcome="accepted") == 2
    assert prom.sum("zeus_task_outcomes_total", outcome="accepted", first_pass="false") == 1
    assert prom.sum("zeus_task_outcomes_total", first_pass="true") == 0
    assert prom.sum("zeus_task_unknown_invocations_total", outcome="accepted") == 2


def test_a11_retry_task_tokens_include_failed_attempt_and_rework(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("failed", 1, T0 + 100))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(1, 30, 100, 5), {SONNET: entry(1, 30, 100, 5)}))
    rig.record(TASK, start_row(TASK, 2, T0 + 200, resumed=True))
    rig.events(TASK, 2, claude_init(), claude_result("r2", usage(1, 20, 50, 5), {SONNET: entry(2, 50, 150, 10)}))
    rig.record(TASK, terminal_row("finished", 2, T0 + 300), completed_row("accepted", T0 + 400))
    prom = rig.scan(advance=500)
    assert prom.sum("zeus_llm_invocations_total") == 2
    assert prom.sum("zeus_task_tokens_total", outcome="accepted", role="implementer", token_type="output") == 50
    assert prom.sum("zeus_task_elapsed_seconds_count", outcome="accepted") == 1
    assert prom.sum("zeus_task_elapsed_seconds_sum", outcome="accepted") == 400


def test_a19_advisor_state_comes_from_the_receipt(tmp_path):
    rig = Rig(tmp_path)
    rig.record("skipped-task", start_row("skipped-task", 1, T0), terminal_row("finished", 1, T0 + 30))
    rig.events("skipped-task", 1, claude_init(), claude_result("s1", usage(1, 5, 10, 1), {SONNET: entry(1, 5, 10, 1)}))
    rig.receipt("skipped-task", 1, advisor_enabled="skipped")
    fresh_attempt_with_advisor(rig, task="enabled-task")
    prom = rig.scan(advance=120)
    assert prom.sum("zeus_llm_advisor_state_total", state="skipped") == 1
    assert prom.sum("zeus_llm_advisor_state_total", state="enabled") == 1
    assert tokens(prom, role="advisor", task_class="unclassified") == 60  # only via the §3.4 rule, from enabled-task
    assert tokens(prom, role="implementer", model=OPUS) == 0


def test_a31_cli_version_semantics_for_resumed_attempts(tmp_path):
    for version, expect in (("2.1.270", "zero"), ("2.1.286", "delta"), (None, "unknown")):
        rig = Rig(tmp_path / str(version))
        fresh_attempt_with_advisor(rig)
        rig.record(TASK, start_row(TASK, 2, T0 + 100, resumed=True))
        # usage per process; modelUsage restarts at zero before 2.1.277, is cumulative after
        cum = (2, 9, 500, 20) if expect == "zero" else (7, 109, 2500, 320)
        rig.events(TASK, 2, claude_init(version=version), claude_result(
            "r2", usage(2, 9, 500, 20), {SONNET: entry(*cum), OPUS: entry(40, 20)}))
        rig.record(TASK, terminal_row("finished", 2, T0 + 200))
        prom = rig.scan(advance=300)
        second = rig.invocation(TASK, 2)
        if expect == "unknown":
            assert second["unknown_reason"] == "unknown_version_semantics"
            assert rig.sql("SELECT COUNT(*) FROM contributions WHERE invocation_id=? AND kind='tree_remainder'",
                           second["id"])[0][0] == 0
            assert tokens(prom, role="implementer", token_type="output") == 109  # M of both attempts still published
        else:
            assert second["unknown_reason"] is None
            # "zero": T = cum(P) = M and Opus T = (40,20) is published as advisor-less nested work
            opus_nested = tokens(prom, role="nested_unattributed", model=OPUS, token_type="output")
            assert opus_nested == (20 if expect == "zero" else 0)


def test_a40_blocked_worker_status_finalizes_as_blocked(tmp_path):
    rig = Rig(tmp_path)
    fresh_attempt_with_advisor(rig, terminal="blocked")
    prom = rig.scan(advance=120)
    assert prom.sum("zeus_llm_invocations_total", outcome="blocked") == 1
    assert prom.sum("zeus_llm_open_invocations") == 0
    assert rig.invocation(TASK, 1)["lifecycle_state"] == "finalized"


def test_a44_horizon_finalizes_terminal_unproven_then_late_terminal_is_a_correction(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0, timeout=100))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5)}))
    prom = rig.scan(advance=100 + 30 + 600)  # exactly at the horizon: still open
    assert prom.sum("zeus_llm_open_invocations", state="open") == 1
    before = tokens(prom)
    prom = rig.scan(advance=1)  # now - dispatched.at > timeout + 30 + 600
    assert prom.sum("zeus_llm_invocations_total", outcome="terminal_unproven") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="terminal_unproven") == 1
    assert tokens(prom) == before  # the measured result stays
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 0
    rig.record(TASK, terminal_row("finished", 1, rig.now))
    prom = rig.scan(advance=10)
    assert prom.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1
    assert prom.sum("zeus_llm_invocations_total", outcome="terminal_unproven") == 1
    assert prom.sum("zeus_llm_invocations_total", outcome="finished") == 0  # no re-publication, same outcome
    assert tokens(prom) == before
    assert rig.scan(advance=10).sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1


def test_a10_attempt_waits_for_an_unfinalized_predecessor(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), start_row(TASK, 2, T0 + 10, resumed=True),
               terminal_row("finished", 2, T0 + 20))  # a hand-edited record: attempt 1 has no terminal row
    rig.events(TASK, 2, claude_init(), claude_result("r2", usage(1, 5, 5, 1), {SONNET: entry(1, 5, 5, 1)}))
    prom = rig.scan(advance=60)
    assert prom.sum("zeus_llm_open_invocations", state="awaiting_predecessor") == 1
    assert prom.sum("zeus_llm_invocations_total") == 0
    prom = rig.scan(advance=3600 + 30 + 600)  # attempt 1 reaches its horizon, then attempt 2 follows
    assert prom.sum("zeus_llm_open_invocations", state="awaiting_predecessor") == 0
    assert prom.sum("zeus_llm_invocations_total") == 2


def remainder(rig, task, attempt=1):
    return sorted(rig.sql("SELECT model,role,token_type,value FROM contributions WHERE invocation_id=? "
                          "AND kind='tree_remainder'", f"routine:{task}:{attempt}"))


def test_c_w1_1_a07_crash_after_results_keeps_the_remainder_of_the_last_valid_result(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(), assistant(advisor_blocks=1),
               claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5), OPUS: entry(4, 7, 0, 0)}),
               claude_result("r2", usage(1, 20, 100, 5), {SONNET: entry(2, 30, 200, 10), OPUS: entry(4, 9, 0, 0)},
                             index=1))
    rig.events(TASK, 1, claude_result("crash", usage(), {}, index=2, is_error=True, subtype="error_during_execution"))
    rig.record(TASK, terminal_row("failed", 1, T0 + 50))
    prom = rig.scan(advance=100)
    assert remainder(rig, TASK) == [(OPUS, "advisor", "input", 4), (OPUS, "advisor", "output", 9)]
    assert prom.sum("zeus_llm_tokens_total", model=OPUS, role="advisor", token_type="output") == 9
    assert rig.invocation(TASK, 1)["unknown_reason"] == "error_zeroed"
    assert prom.sum("zeus_llm_unknown_invocations_total") == 1
    assert prom.sum("zeus_llm_unknown_shares_total") == 0


def test_c_w1_1_a41_horizon_publishes_remainder_of_second_result(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0, timeout=100))
    rig.events(TASK, 1, claude_init(),
               claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 12, 100, 5)}),
               claude_result("r2", usage(1, 20, 100, 5), {SONNET: entry(2, 40, 200, 10)}, index=1))
    prom = rig.scan(advance=100 + 30 + 600 + 1)
    assert rig.invocation(TASK, 1)["unknown_reason"] == "terminal_unproven"
    assert remainder(rig, TASK) == [(SONNET, "nested_unattributed", "output", 10)]  # T_e 40 - M 30
    assert tokens(prom, token_type="output") == 40


def test_c_w1_1_a58_torn_tail_settlement_publishes_remainder_of_last_complete_result(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 25, 100, 5)}),
               torn='{"type": "resu')
    rig.scan(advance=10)
    rig.record(TASK, terminal_row("finished", 1, T0 + 20))
    prom = rig.scan(advance=10)
    assert rig.invocation(TASK, 1)["unknown_reason"] == "incomplete_tail"
    assert remainder(rig, TASK) == [(SONNET, "nested_unattributed", "output", 15)]
    assert tokens(prom, token_type="output") == 25


def test_c_w1_1_a08_a13_invalid_result_and_malformed_line_use_the_last_valid_result(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 20))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 18, 100, 5)}),
               claude_result("bad", None, None, index=1))
    rig.raw_events(TASK, 1, "not json\n")
    prom = rig.scan(advance=60)
    assert rig.invocation(TASK, 1)["unknown_reason"] == "malformed"
    assert remainder(rig, TASK) == [(SONNET, "nested_unattributed", "output", 8)]
    assert tokens(prom, token_type="output") == 18


def test_c_w1_1_a09_no_result_publishes_nothing_beyond_m(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("timed_out", 1, T0 + 20))
    rig.events(TASK, 1, claude_init())
    prom = rig.scan(advance=60)
    assert tokens(prom) == 0 and remainder(rig, TASK) == []
    assert rig.invocation(TASK, 1)["unknown_reason"] == "no_result"
