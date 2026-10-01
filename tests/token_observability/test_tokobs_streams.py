"""ACCEPTANCE A12-A18, A47 (routine), A48, A58 (routine): reading, identity, restart, settlement."""

import hashlib
import json
import os
import shutil

import pytest
from fixtures import (
    ASSISTANT_TEXT_SENTINEL,
    SONNET,
    T0,
    Rig,
    claude_init,
    claude_result,
    entry,
    start_row,
    terminal_row,
    usage,
)
from tokobs.__main__ import main
from tokobs.collector import scan_once
from tokobs.ledger import CollectorBusy, collector_lock

TASK = "stream-task"


def result(uuid, out, cum, index=0):
    return claude_result(uuid, usage(1, out, 10, 1), {SONNET: entry(index + 1, cum, 10 * (index + 1), index + 1)},
                         index=index)


def tokens(prom, **labels):
    return prom.sum("zeus_llm_tokens_total", **labels)


def test_a12_partial_line_waits_while_open_then_parses_once(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    second = json.dumps(result("r2", 20, 30, 1), sort_keys=True)
    rig.events(TASK, 1, claude_init(), result("r1", 10, 10), torn=second[:50])
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="output") == 10  # the complete result is published, the tail waits
    assert prom.sum("zeus_llm_open_invocations", state="open") == 1
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 0
    rig.raw_events(TASK, 1, second[50:] + "\n")
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="output") == 30
    assert rig.sql("SELECT COUNT(*) FROM results")[0][0] == 2
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 0


def test_a13_malformed_lines_are_counted_and_the_file_continues(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 60))
    rig.raw_events(TASK, 1, "this is not json\n" + json.dumps(claude_init()) + "\n[1, 2, 3]\n"
                   + json.dumps(result("r1", 10, 10)) + "\n")
    prom = rig.scan(advance=120)
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 2
    assert tokens(prom, token_type="output") == 10  # the file continued past both
    assert rig.invocation(TASK, 1)["unknown_reason"] == "malformed"  # a bad line may hide a result
    rig.scan(advance=30)
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 2  # replay: not counted again


def test_a14_duplicate_read_and_redelivered_result_add_nothing(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(), result("r1", 10, 10))
    first = rig.scan(advance=30)
    again = rig.scan(advance=30)  # same file scanned twice
    assert tokens(again) == tokens(first)
    rig.events(TASK, 1, result("r1", 10, 10))  # the identical result line redelivered
    redelivered = rig.scan(advance=30)
    assert tokens(redelivered) == tokens(first)
    assert redelivered.sum("zeus_tokobs_ledger_corrections_total", kind="duplicate_after_publish") == 1
    assert rig.sql("SELECT COUNT(*) FROM results")[0][0] == 1


@pytest.mark.parametrize("mode", ["replace", "truncate"])
def test_a16_rotation_and_truncation_rewrite_adds_no_contributions(tmp_path, mode):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    lines = [claude_init(), result("r1", 10, 10), result("r2", 20, 30, 1)]
    path = rig.events(TASK, 1, *lines)
    before = tokens(rig.scan(advance=30), token_type="output")
    body = "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)
    if mode == "replace":
        replacement = path.with_name("events-1.new")
        replacement.write_text(body)
        os.replace(replacement, path)  # a new inode
    else:
        path.write_text(json.dumps(claude_init(), sort_keys=True) + "\n")  # shorter than the read offset
        rig.scan(advance=1)
        path.write_text(body)
    after = rig.scan(advance=30)
    assert tokens(after, token_type="output") == before == 30
    assert rig.sql("SELECT COUNT(*) FROM stream_aliases WHERE path=?", str(path))[0][0] >= 2  # a new read identity


def test_a48_path_reused_with_different_results_publishes_the_new_ones(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    path = rig.events(TASK, 1, claude_init(), result("r1", 10, 10))
    assert tokens(rig.scan(advance=30), token_type="output") == 10
    replacement = path.with_name("events-1.new")
    replacement.write_text("".join(json.dumps(line, sort_keys=True) + "\n"
                                   for line in (claude_init(), result("r2", 20, 30, 1))))
    os.replace(replacement, path)
    rig.record(TASK, terminal_row("finished", 1, rig.now))
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="output") == 30  # r1 stays, r2 is new
    assert rig.invocation(TASK, 1)["unknown_reason"] is None  # cum(r2)=30 = M(10+20)


def test_a17_concurrent_streams_attribute_each_result_to_its_own_invocation(tmp_path):
    rig = Rig(tmp_path)
    for task, session in (("task-one", "sess-1"), ("task-two", "sess-2")):
        rig.record(task, start_row(task, 1, T0, session=session))
    rig.events("task-one", 1, claude_init(session="sess-1"), claude_result(
        "a1", usage(0, 10, 0, 0), {SONNET: entry(0, 10, 0, 0)}, session="sess-1"))
    rig.events("task-two", 1, claude_init(session="sess-2"), claude_result(
        "b1", usage(0, 70, 0, 0), {SONNET: entry(0, 70, 0, 0)}, session="sess-2"))
    rig.scan(advance=30)
    rig.events("task-one", 1, claude_result("a2", usage(0, 5, 0, 0), {SONNET: entry(0, 15, 0, 0)}, session="sess-1", index=1))
    rig.scan(advance=30)
    rows = dict(rig.sql("SELECT invocation_id, SUM(value) FROM contributions GROUP BY 1"))
    assert rows == {"routine:task-one:1": 15, "routine:task-two:1": 70}


def test_a18_second_collector_exits_75_and_leaves_the_ledger_untouched(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init(), result("r1", 10, 10))
    rig.scan(advance=30)
    ledger = rig.data / "ledger.sqlite3"
    digest = hashlib.sha256(ledger.read_bytes()).hexdigest()
    with collector_lock(rig.data):
        with pytest.raises(CollectorBusy):
            scan_once(rig.data, rig.root, now=T0 + 99)
        assert main(["scan", "--data", str(rig.data), "--source-root", str(rig.root), "--now", str(T0 + 99)]) == 75
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == digest
    fresh = tmp_path / "never-created"
    with collector_lock(fresh):
        assert main(["scan", "--data", str(fresh), "--source-root", str(rig.root)]) == 75
        assert not (fresh / "ledger.sqlite3").exists()


def snapshot(rig):
    return rig.dump(), (rig.data / "data.prom").read_bytes(), (rig.data / "health.prom").read_bytes()


def test_a15_restart_after_a_crash_before_commit_equals_an_uninterrupted_run(tmp_path):
    reference = Rig(tmp_path, "reference")
    reference.record(TASK, start_row(TASK, 1, T0), start_row(TASK, 2, T0 + 100, resumed=True))
    reference.record(TASK, terminal_row("finished", 1, T0 + 50), terminal_row("finished", 2, T0 + 150))
    reference.events(TASK, 1, claude_init(), result("r1", 10, 10))
    reference.events(TASK, 2, claude_init(), result("r2", 20, 30, 1))
    calls = []
    reference.before_commit = lambda: calls.append(1)
    reference.scan(advance=300)
    assert len(calls) >= 4
    for crash_at in range(1, len(calls) + 1):
        crashed = Rig(tmp_path, f"crash-{crash_at}")
        crashed.now = reference.now - 300
        count = []

        def fault(count=count, crash_at=crash_at):
            count.append(1)
            if len(count) == crash_at:
                raise RuntimeError("injected crash before COMMIT")

        crashed.before_commit = fault
        with pytest.raises(RuntimeError):
            crashed.scan(advance=300)
        crashed.before_commit = None
        crashed.now = reference.now - 300
        crashed.history.clear()
        crashed.scan(advance=300)
        assert snapshot(crashed) == snapshot(reference), f"crash at commit {crash_at}"


def test_a47_copied_stream_is_a_read_alias_never_a_second_invocation(tmp_path):
    def build(rig):
        rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 50))
        return rig.events(TASK, 1, claude_init(), result("r1", 10, 10), result("r2", 20, 30, 1))

    def core(prom):
        return {k: v for k, v in prom.series.items() if k[0].startswith(("zeus_llm_", "zeus_task_"))}

    original = Rig(tmp_path / "original")
    build(original)
    expected = core(original.scan(advance=100))

    after = Rig(tmp_path / "after")  # (a) the copy is read after the original's finalization
    source = build(after)
    after.scan(advance=100)
    shutil.copyfile(source, source.with_name("events-9.jsonl"))
    prom = after.scan(advance=30)
    assert core(prom) == expected
    assert after.sql("SELECT binding, invocation_id FROM stream_aliases WHERE path LIKE '%events-9.jsonl'") == [
        ("bound", "routine:stream-task:1")]
    assert after.health().sum("zeus_tokobs_unbound_streams", source="routine") == 0

    before = Rig(tmp_path / "before")  # (b) the copy is read before the original arrives
    before.record(TASK, start_row(TASK, 1, T0))
    scratch = tmp_path / "scratch.jsonl"
    scratch.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in
                               (claude_init(), result("r1", 10, 10), result("r2", 20, 30, 1))))
    shutil.copyfile(scratch, before.task_dir(TASK) / "events-9.jsonl")
    prom = before.scan(advance=30)
    assert tokens(prom) == 0 and prom.sum("zeus_llm_invocations_total") == 0  # a pending alias publishes nothing
    assert before.health().sum("zeus_tokobs_unbound_streams", source="routine") == 1
    shutil.copyfile(scratch, before.task_dir(TASK) / "events-1.jsonl")
    before.record(TASK, terminal_row("finished", 1, T0 + 50))
    prom = before.scan(advance=70)
    assert core(prom) == expected
    assert before.sql("SELECT binding FROM stream_aliases WHERE path LIKE '%events-9.jsonl'") == [("bound",)]
    assert before.sql("SELECT COUNT(*) FROM invocations")[0][0] == 1
    assert before.health().sum("zeus_tokobs_unbound_streams", source="routine") == 0


def test_an_unbound_alias_creates_no_invocation_outcome_attempt_or_unknown(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0))
    rig.events(TASK, 1, claude_init())
    rig.events(TASK, 7, claude_init(), result("x1", 99, 99), name="events-7.jsonl")  # no attempt 7 in the record
    prom = rig.scan(advance=30)
    assert rig.sql("SELECT COUNT(*) FROM invocations")[0][0] == 1
    assert tokens(prom) == 0 and rig.health().sum("zeus_tokobs_unbound_streams", source="routine") == 1


def tail_scenario(rig, terminal):
    rig.record(TASK, start_row(TASK, 1, T0, timeout=100))
    second = json.dumps(result("r2", 20, 30, 1), sort_keys=True)
    partial = ASSISTANT_TEXT_SENTINEL + second[:40]
    rig.events(TASK, 1, claude_init(), result("r1", 10, 10), torn=partial)
    prom = rig.scan(advance=30)  # while open the tail waits
    assert tokens(prom, token_type="output") == 10
    assert prom.sum("zeus_llm_open_invocations", state="open") == 1
    assert prom.sum("zeus_llm_invocations_total") == 0 and prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert rig.health().sum("zeus_tokobs_malformed_lines_total") == 0
    if terminal:
        rig.record(TASK, terminal_row("finished", 1, rig.now))
        prom = rig.scan(advance=30)
    else:
        prom = rig.scan(advance=100 + 30 + 600)
    return prom, partial, second


def test_a58_routine_terminal_row_settles_the_torn_tail_once(tmp_path):
    rig = Rig(tmp_path)
    prom, partial, second = tail_scenario(rig, terminal=True)
    assert prom.sum("zeus_llm_invocations_total", outcome="finished") == 1
    assert tokens(prom, token_type="output") == 10  # measured tokens preserved
    assert rig.invocation(TASK, 1)["unknown_reason"] == "incomplete_tail"
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="incomplete_tail") == 1
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 1
    (settlement,) = rig.sql("SELECT prefix_end_offset, tail_bytes, tail_sha256 FROM stream_settlements")
    assert settlement[1] == len(partial.encode())
    assert settlement[2] == hashlib.sha256(partial.encode()).hexdigest()
    settled = snapshot(rig)
    rig.scan(advance=30)  # replay: nothing is re-parsed, re-published or re-finalized
    after_replay = snapshot(rig)
    assert after_replay[0]["contributions"] == settled[0]["contributions"]
    assert after_replay[0]["corrections"] == settled[0]["corrections"]
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 1
    # the tail completes and one more complete result line appears: a correction, nothing else
    rig.raw_events(TASK, 1, second[40:] + "\n")
    rig.events(TASK, 1, result("r3", 5, 35, 2))
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1
    assert tokens(late, token_type="output") == 10
    assert late.sum("zeus_llm_invocations_total") == 1
    assert rig.invocation(TASK, 1)["outcome"] == "finished"
    assert rig.sql("SELECT COUNT(*) FROM results")[0][0] == 1  # the late bytes are never parsed into facts
    assert rig.scan(advance=30).sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1


def test_a58_horizon_settlement_keeps_the_higher_precedence_reason(tmp_path):
    rig = Rig(tmp_path)
    prom, _partial, second = tail_scenario(rig, terminal=False)
    assert prom.sum("zeus_llm_invocations_total", outcome="terminal_unproven") == 1
    assert rig.invocation(TASK, 1)["unknown_reason"] == "terminal_unproven"  # > incomplete_tail
    assert prom.sum("zeus_llm_unknown_invocations_total") == 1  # at most one unknown
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="routine") == 1
    assert tokens(prom, token_type="output") == 10
    rig.raw_events(TASK, 1, second[40:] + "\n")
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1
    assert late.sum("zeus_llm_invocations_total") == 1


def test_bounded_reads_defer_finalization_until_the_stream_is_consumed(tmp_path):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 10))
    rig.events(TASK, 1, claude_init(), *[result(f"r{n}", 10, 10 * (n + 1), n) for n in range(6)])
    states = []
    for _ in range(40):
        prom = rig.scan(advance=1, max_read_bytes=64)
        states.append(prom.sum("zeus_llm_invocations_total"))
        if states[-1]:
            break
    assert states[0] == 0 and states[-1] == 1
    assert tokens(prom, token_type="output") == 60
    assert rig.invocation(TASK, 1)["unknown_reason"] is None


def test_symlinks_inside_the_tree_are_never_followed(tmp_path):
    rig = Rig(tmp_path)
    decoy = tmp_path / "decoy.jsonl"
    decoy.write_text("SECRET-SHAPED-decoy-line-not-json\n" + json.dumps(result("d1", 99, 99)) + "\n")
    rig.record(TASK, start_row(TASK, 1, T0), terminal_row("finished", 1, T0 + 10))
    (rig.task_dir(TASK) / "events-1.jsonl").symlink_to(decoy)  # a canonical name that is a link
    (rig.task_dir(TASK) / "events-5.jsonl").symlink_to(decoy)  # an alias name that is a link
    (rig.runs / "linked-task").symlink_to(rig.task_dir(TASK), target_is_directory=True)
    prom = rig.scan(advance=30)
    assert tokens(prom) == 0
    assert rig.sql("SELECT COUNT(*) FROM malformed_lines")[0][0] == 0
    assert rig.sql("SELECT COUNT(*) FROM stream_aliases")[0][0] == 0
    assert rig.invocation(TASK, 1)["unknown_reason"] == "no_result"
    assert rig.sql("SELECT COUNT(*) FROM tasks WHERE task_id='linked-task'")[0][0] == 0
