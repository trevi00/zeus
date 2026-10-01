"""ACCEPTANCE A20, A21, A46, A47 (Codex), A49, A59 and C-W1-3, C-W1-4: S3 Codex exec streams."""

import shutil
from pathlib import Path

import tokobs.vocab as vocab
from fixtures import Rig, codex_thread_started, codex_turn_completed, codex_usage

THREAD = "01a0e11e-synthetic-thread"
P0 = codex_usage(1000, 800, 100, 30)  # fresh exec: delta from 0
P1 = codex_usage(1500, 1200, 160, 40)
P2 = codex_usage(2100, 1700, 250, 55)
IDLE = 2 * 900 + 60


def tokens(prom, **labels):
    return prom.sum("zeus_llm_tokens_total", **labels)


def run(rig, stem, point, *, resume=True, thread=THREAD, prestart=None, model="gpt-6-astra", lines=()):
    rig.codex_script(stem, resume=resume, model=model)
    if prestart is not None:
        rig.codex_prestart(stem, thread, prestart)
    return rig.codex_events(stem, codex_thread_started(thread), {"type": "turn.started"},
                            *( [codex_turn_completed(point)] if point is not None else [] ), *lines)


def by_run(rig):
    return dict(rig.sql("SELECT invocation_id || '/' || token_type, SUM(value) FROM contributions GROUP BY 1"))


def test_the_idle_horizon_is_read_from_the_single_policy_definition():
    from codex_harness.domain.policy import (
        POLICY,  # AGENTS.md: the single definition, never restated (C-W1-8)
    )

    assert vocab.codex_idle_seconds() == 2 * POLICY.decision_seconds  # DESIGN §3.2
    assert "900" not in (Path(vocab.__file__).read_text())  # the number itself is not restated


def test_a20_codex_cumulative_points_attributed_with_recorded_prestart_tuples(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", P0, resume=False)
    run(rig, "r1", P1, prestart=P0)
    run(rig, "r2", P2, prestart=P1)
    prom = rig.scan(advance=30)
    assert by_run(rig) == {
        "codex:r0/input": 200, "codex:r0/cache_read": 800, "codex:r0/output": 100,  # delta from 0
        "codex:r1/input": 100, "codex:r1/cache_read": 400, "codex:r1/output": 60,  # input = input - cached
        "codex:r2/input": 100, "codex:r2/cache_read": 500, "codex:r2/output": 90}
    assert tokens(prom, provider="openai", source="codex_exec", role="reviewer", task_class="unclassified") == 2350
    assert tokens(prom, task_class="unattributed_interval") == 0  # every predecessor is proven
    assert prom.sum("zeus_llm_reasoning_output_tokens_total", provider="openai") == 55  # a separate subset counter
    assert tokens(prom, token_type="reasoning_output") == 0
    assert prom.sum("zeus_llm_invocations_total", source="codex_exec", outcome="codex_completed") == 3
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert [r[0] for r in rig.sql("SELECT predecessor_state FROM invocations ORDER BY id")] == ["proven"] * 3


def test_c_w1_4_a_mismatching_or_foreign_sidecar_does_not_prove_the_predecessor(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", P0, resume=False)
    run(rig, "r1", P1, prestart=codex_usage(1, 1, 1))  # a recorded tuple that is not the previous point
    run(rig, "r2", P2, thread="another-thread", prestart=P1)  # right tuple, wrong thread
    (rig.root / "r3-codex-prestart.json").write_text("{not json")
    run(rig, "r3", codex_usage(2200, 1800, 260, 56))
    prom = rig.scan(advance=30)
    assert tokens(prom, task_class="unattributed_interval", token_type="output") == 60 + 100
    assert rig.inv("codex:r2")["unknown_reason"] == "no_baseline"  # another thread: its first point is an anchor
    assert rig.sql("SELECT predecessor_state FROM invocations WHERE id='codex:r1'") == [("unproven",)]


def test_a49_unproven_continuity_publishes_unattributed_intervals_and_no_task_tokens(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", P0, resume=False)
    run(rig, "r1", P1)  # resumed, no pre-start tuple recorded (today's launchers)
    run(rig, "r2", P2)
    prom = rig.scan(advance=30)
    assert tokens(prom, task_class="unattributed_interval", role="reviewer", token_type="output") == 60 + 90
    assert tokens(prom, task_class="unclassified", token_type="output") == 100  # only the fresh run's own delta
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0  # measured, with the allocation explicitly unknown
    assert rig.inv("codex:r1")["task_class"] == "unattributed_interval"
    assert rig.inv("codex:r1")["predecessor_state"] == "unproven"


def test_a21_anchor_then_non_monotonic_never_a_negative_contribution(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r1", P1)  # the first known point of a resumed thread
    prom = rig.scan(advance=30)
    assert tokens(prom) == 0 and rig.inv("codex:r1")["unknown_reason"] == "no_baseline"
    assert prom.sum("zeus_llm_unknown_invocations_total", provider="openai", reason="no_baseline") == 1
    run(rig, "r2", codex_usage(1600, 1250, 120, 40))  # output went down: one field smaller
    prom = rig.scan(advance=30)
    assert rig.inv("codex:r2")["unknown_reason"] == "non_monotonic"
    assert prom.sum("zeus_llm_unknown_invocations_total", provider="openai", reason="non_monotonic") == 1
    assert tokens(prom) == 0
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE value<=0")[0][0] == 0
    run(rig, "r3", P2)  # the outlier is not a neighbour: r3 is compared with the anchor
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="output") == 90 and rig.inv("codex:r3")["task_class"] == "unattributed_interval"


def test_a46_a_point_arriving_between_published_points_is_a_late_point_correction(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", P0, resume=False)
    run(rig, "r2", P2)
    first = rig.scan(advance=30)
    assert tokens(first, task_class="unattributed_interval", token_type="output") == 150  # p2 - p0
    run(rig, "r1", P1)
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_point") == 1
    assert tokens(late) == tokens(first)  # counters unchanged; model total = p0 + (p2 - p0)
    assert tokens(late, token_type="output") == 250
    assert by_run(rig).get("codex:r1/output") is None
    assert late.sum("zeus_llm_invocations_total", source="codex_exec") == 3
    assert rig.scan(advance=30).sum("zeus_tokobs_ledger_corrections_total", kind="late_point") == 1


def test_file_order_in_one_scan_does_not_change_intervals(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "z0", P0, resume=False)  # sorts last by name, first by tuple
    run(rig, "a1", P1, prestart=P0)
    run(rig, "m2", P2, prestart=P1)
    rig.scan(advance=30)
    assert by_run(rig)["codex:a1/output"] == 60 and by_run(rig)["codex:m2/output"] == 90
    assert rig.sql("SELECT COUNT(*) FROM corrections WHERE kind='late_point'")[0][0] == 0


def core(prom):
    return {k: v for k, v in prom.series.items() if k[0].startswith(("zeus_llm_", "zeus_task_"))}


def test_a47_codex_copy_is_a_read_alias_never_a_second_invocation(tmp_path):
    original = Rig(tmp_path / "original")
    run(original, "r0", P0, resume=False)
    expected = core(original.scan(advance=30))

    after = Rig(tmp_path / "after")  # (a) the copy is read after the original's finalization
    source = run(after, "r0", P0, resume=False)
    after.scan(advance=30)
    shutil.copyfile(source, after.root / "renamed-codex-events.jsonl")
    after.touch(after.root / "renamed-codex-events.jsonl")
    prom = after.scan(advance=30)
    assert core(prom) == expected
    assert after.sql("SELECT binding, invocation_id FROM stream_aliases WHERE path LIKE '%renamed%'") == [
        ("bound", "codex:r0")]
    assert after.health().sum("zeus_tokobs_unbound_streams", source="codex_exec") == 0

    before = Rig(tmp_path / "before")  # (b) the copy is read before the original arrives
    scratch = tmp_path / "scratch.jsonl"
    scratch.write_text(source.read_text())
    shutil.copyfile(scratch, before.root / "renamed-codex-events.jsonl")
    before.touch(before.root / "renamed-codex-events.jsonl")
    prom = before.scan(advance=30)
    assert tokens(prom) == 0 and prom.sum("zeus_llm_invocations_total") == 0
    assert before.health().sum("zeus_tokobs_unbound_streams", source="codex_exec") == 1
    run(before, "r0", P0, resume=False)
    prom = before.scan(advance=30)
    assert core(prom) == expected
    assert before.sql("SELECT binding FROM stream_aliases WHERE path LIKE '%renamed%'") == [("bound",)]
    assert before.sql("SELECT COUNT(*) FROM invocations")[0][0] == 1
    assert before.health().sum("zeus_tokobs_unbound_streams", source="codex_exec") == 0


def test_a59a_two_canonical_runs_sharing_a_tuple_survive_and_the_point_counts_once(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "y", P0)  # a resumed run with the same point; its name sorts AFTER x but is read first below
    run(rig, "x", P0, resume=False)
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total", source="codex_exec") == 2
    assert tokens(prom, token_type="output") == 100  # the shared point once
    assert by_run(rig).get("codex:y/output") is None  # Y's delta is 0
    assert rig.inv("codex:x")["unknown_reason"] is None and rig.inv("codex:y")["unknown_reason"] is None


def test_a59b_unbound_codex_stream_publishes_identity_unavailable_without_an_invocation(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "x", P0, resume=False)
    rig.codex_events("unnamed", codex_thread_started(THREAD), codex_turn_completed(P1))  # no launcher names it
    prom = rig.scan(advance=30)
    assert tokens(prom, task_class="identity_unavailable") == 0  # within the horizon: pending
    prom = rig.scan(advance=IDLE)
    assert tokens(prom, task_class="identity_unavailable", token_type="output", model="other") == 60
    assert prom.sum("zeus_llm_invocations_total", source="codex_exec") == 1  # only the named run
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert rig.sql("SELECT COUNT(*) FROM invocations")[0][0] == 1
    assert rig.health().sum("zeus_tokobs_unbound_streams", source="codex_exec") == 1
    assert tokens(rig.scan(advance=60), task_class="identity_unavailable") == tokens(prom, task_class="identity_unavailable")


def test_c_w1_3_a_point_without_cache_write_leaves_cache_write_unknown_not_zero(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", codex_usage(1000, 800, 100, 30, cw=None), resume=False)
    run(rig, "r1", codex_usage(1500, 1200, 160, 40, cw=0), prestart=codex_usage(1000, 800, 100, 30, cw=None))
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="cache_write") == 0 and prom.count("zeus_llm_tokens_total", token_type="cache_write") == 0
    assert tokens(prom, token_type="output") == 160  # the other types are unaffected
    assert prom.sum("zeus_llm_unknown_shares_total", provider="openai", reason="unknown_version_semantics") == 2
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0  # share detail only (§3.6)


def test_c_w1_3_cache_write_is_published_when_present_and_nonzero(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", codex_usage(1000, 800, 100, 30, cw=7), resume=False)
    run(rig, "r1", codex_usage(1500, 1200, 160, 40, cw=12), prestart=codex_usage(1000, 800, 100, 30, cw=7))
    prom = rig.scan(advance=30)
    assert by_run(rig)["codex:r0/cache_write"] == 7 and by_run(rig)["codex:r1/cache_write"] == 5
    assert prom.sum("zeus_llm_unknown_shares_total") == 0


def test_codex_failed_turn_and_horizon_and_bad_usage_are_unknown_not_zero(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "bad", None, resume=False, lines=({"type": "turn.failed", "error": {"message": "x"}},))
    run(rig, "open", None, resume=False)
    run(rig, "shape", codex_usage(5, 9, 1))  # cached > input is not a usable shape
    prom = rig.scan(advance=30)
    assert rig.inv("codex:bad")["outcome"] == "codex_failed" and rig.inv("codex:bad")["unknown_reason"] == "no_result"
    assert rig.inv("codex:open")["lifecycle_state"] == "open"
    assert rig.inv("codex:shape")["unknown_reason"] == "malformed"
    assert tokens(prom) == 0
    prom = rig.scan(advance=IDLE)
    assert rig.inv("codex:open")["outcome"] == "terminal_unproven"
    assert rig.inv("codex:open")["terminal_evidence"] == "horizon"
    assert prom.sum("zeus_llm_invocations_total", source="codex_exec") == 3


def test_a58_codex_torn_tail_settles_once_with_the_turn_line_as_terminal_evidence(tmp_path):
    rig = Rig(tmp_path)
    run(rig, "r0", P0, resume=False)
    rig.codex_events("r0", torn='{"type":"item.comp')
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total", outcome="codex_completed") == 1
    assert rig.inv("codex:r0")["unknown_reason"] == "incomplete_tail"
    assert tokens(prom, token_type="output") == 100
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="codex_exec") == 1
    rig.codex_events("r0", {"type": "item.completed"})
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1
    assert late.sum("zeus_llm_invocations_total") == 1
