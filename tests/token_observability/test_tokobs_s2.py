"""ACCEPTANCE A17, A41, A58 (coordinator), A44 (lane metadata) and C-W1-2, C-W1-6: S2 streams and read aliases."""

import hashlib
import json
import shutil

from fixtures import (
    OPUS,
    SESSION,
    T0,
    Rig,
    claude_init,
    claude_result,
    entry,
    start_row,
    terminal_row,
    usage,
)

HORIZON = 14_400
COORD = "fleet-autonomy-cont-1-events.jsonl"
LANE = "evidence/lane-one"


def result(uuid, out, cum, index=0, session=SESSION):
    return claude_result(uuid, usage(1, out, 10, 1), {OPUS: entry(index + 1, cum, 10 * (index + 1), index + 1)},
                         index=index, session=session)


def tokens(prom, **labels):
    return prom.sum("zeus_llm_tokens_total", **labels)


def coordinator(rig, *lines, **kwargs):
    rig.credential_receipt("coordinator:fleet", COORD)
    return rig.stream(COORD, *lines, **kwargs)


def test_receipt_named_coordinator_stream_publishes_per_result_and_stays_open(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, claude_init(model="opus"), result("c1", 10, 10))
    prom = rig.scan(advance=30)
    assert tokens(prom, role="coordinator", source="coordinator", task_class="coordination") == 22
    assert tokens(prom, role="coordinator", token_type="output") == 10
    assert prom.sum("zeus_llm_open_invocations", source="coordinator", state="open") == 1
    assert prom.sum("zeus_llm_invocations_total") == 0
    inv = rig.inv("stream:fleet-autonomy-cont-1-events")
    assert inv["source"] == "coordinator" and inv["mode"] is None and inv["lifecycle_state"] == "open"
    assert inv["executor_model"] == OPUS  # `--model opus` alias resolved from the init line
    rig.stream(COORD, result("c2", 20, 30, 1))
    assert tokens(rig.scan(advance=30), role="coordinator", token_type="output") == 30


def test_a41_coordinator_without_metadata_is_terminal_unproven_after_the_horizon(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, claude_init(model="opus"), result("c1", 10, 10), result("c2", 20, 37, 1))
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total") == 0
    prom = rig.scan(advance=HORIZON - 30)  # idle exactly at the horizon: not past it
    assert prom.sum("zeus_llm_invocations_total") == 0
    prom = rig.scan(advance=31)
    assert prom.sum("zeus_llm_invocations_total", source="coordinator", outcome="terminal_unproven") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", source="coordinator", reason="terminal_unproven") == 1
    assert tokens(prom, role="coordinator", token_type="output") == 30  # the two results stay
    # C-W1-6: continuity is unproven, so M only; the 7-token whole-tree remainder is withheld, never guessed
    assert tokens(prom, role="nested_unattributed") == 0
    inv = rig.inv("stream:fleet-autonomy-cont-1-events")
    assert (inv["predecessor_state"], inv["terminal_kind"], inv["terminal_evidence"]) == ("unproven", "horizon",
                                                                                             "horizon")
    assert rig.sql("SELECT reason FROM unknown_shares") == [("terminal_unproven",)]
    again = rig.scan(advance=60)
    assert again.sum("zeus_llm_invocations_total") == 1  # finalized once
    assert again.sum("zeus_llm_unknown_invocations_total") == 1


def test_a41_lane_with_metadata_still_started_is_terminal_unproven_and_a_fresh_lane_has_baseline_zero(tmp_path):
    rig = Rig(tmp_path)
    rig.lane_meta("lane-one", state="started")
    rig.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("l1", 10, 10), result("l2", 20, 37, 1))
    assert rig.scan(advance=30).sum("zeus_llm_invocations_total") == 0
    prom = rig.scan(advance=HORIZON + 1)
    assert prom.sum("zeus_llm_invocations_total", source="lane", outcome="terminal_unproven") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", source="lane", reason="terminal_unproven") == 1
    assert tokens(prom, role="lane_worker", token_type="output") == 30
    # a lane created by `--session-id` is fresh: baseline 0, so C-W1-1's remainder (37 - 30) is published
    assert tokens(prom, role="nested_unattributed", token_type="output") == 7
    assert rig.inv("lane:lane-one:run.json")["predecessor_state"] == "none"


def test_lane_metadata_finished_is_terminal_evidence_and_a_late_one_is_a_correction(tmp_path):
    rig = Rig(tmp_path)
    meta = rig.lane_meta("lane-one", state="started")
    rig.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("l1", 10, 10))
    rig.scan(advance=30)
    rig.lane_meta("lane-one", state="finished", exit_code=0, timed_out=False)
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total", source="lane", outcome="finished") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
    assert rig.inv("lane:lane-one:run.json")["terminal_kind"] == "run_metadata"
    # horizon-finalized, then the metadata appears: a late terminal correction, no second finalization
    horizon = Rig(tmp_path, "horizon")
    horizon.lane_meta("lane-one", state="started")
    horizon.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("l1", 10, 10))
    horizon.scan(advance=HORIZON + 60)
    horizon.lane_meta("lane-one", state="finished", exit_code=1, timed_out=False)
    late = horizon.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_terminal") == 1
    assert late.sum("zeus_llm_invocations_total") == 1 and meta.exists()
    assert horizon.inv("lane:lane-one:run.json")["outcome"] == "terminal_unproven"


def test_lane_outcomes_follow_exit_code_and_timeout(tmp_path):
    rig = Rig(tmp_path)
    for lane, fields in (("lane-a", {"exit_code": 1}), ("lane-b", {"exit_code": 143, "timed_out": True})):
        rig.lane_meta(lane, state="finished", **fields)
        rig.stream(f"evidence/{lane}/events.jsonl", claude_init(model="opus"))
    prom = rig.scan(advance=30)
    assert prom.sum("zeus_llm_invocations_total", source="lane", outcome="failed") == 1
    assert prom.sum("zeus_llm_invocations_total", source="lane", outcome="timed_out") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="no_result") == 2


def test_lane_resume_uses_the_named_predecessor_baseline(tmp_path):
    rig = Rig(tmp_path)
    rig.lane_meta("lane-one", "run.json", state="finished", exit_code=0)
    rig.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("a1", 10, 10))
    rig.lane_meta("lane-one", "run-r2.json", state="finished", exit_code=0, mode="resume",
                  predecessor_run="run.json")
    rig.stream(f"{LANE}/events-r2.jsonl", claude_init(model="opus"), result("a2", 5, 19, 1))
    prom = rig.scan(advance=30)
    second = rig.inv("lane:lane-one:run-r2.json")
    assert second["predecessor_id"] == "lane:lane-one:run.json" and second["predecessor_state"] == "proven"
    # T = cum(2) - cum(1) = 19 - 10 = 9 output; M = 5; remainder 4
    assert tokens(prom, role="nested_unattributed", token_type="output") == 4
    assert prom.sum("zeus_llm_invocations_total", source="lane") == 2


def test_lane_resume_without_a_named_predecessor_is_unproven_continuity(tmp_path):
    rig = Rig(tmp_path)
    rig.lane_meta("lane-one", state="finished", exit_code=0, mode="resume")
    rig.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("a1", 10, 40))
    prom = rig.scan(advance=30)
    assert tokens(prom, role="lane_worker", token_type="output") == 10
    assert tokens(prom, role="nested_unattributed") == 0
    assert prom.sum("zeus_llm_unknown_invocations_total", reason="no_baseline") == 1


def test_discovery_maps_host_paths_by_trailing_components_and_ignores_foreign_files(tmp_path):
    rig = Rig(tmp_path)
    rig.credential_receipt("coordinator:fleet", COORD)  # host prefix differs from the scan root
    rig.credential_receipt("routine:some-task:1", "routine-runs/some-task/events-1.jsonl")  # S1's, never S2's
    rig.credential_receipt("design:x", "x-codex-events.jsonl")  # a Codex stream is never an S2 stream
    rig.credential_receipt("coordinator:y", "../../etc/passwd")
    rig.stream(COORD, claude_init(model="opus"), result("c1", 10, 10))
    rig.stream("x-codex-events.jsonl", {"type": "thread.started", "thread_id": "t"})
    for decoy in ("run-start.json", "run-exit.json", "run-child.json", "run-stdout.json"):  # other launchers' files
        (rig.root / "evidence" / "decoy").mkdir(parents=True, exist_ok=True)
        (rig.root / "evidence" / "decoy" / decoy).write_text(json.dumps({"pid": 1, "exit": 0}))
    rig.stream("evidence/decoy/events.jsonl", claude_init(model="opus"))
    rig.scan(advance=30)
    ids = [r[0] for r in rig.sql("SELECT id FROM invocations ORDER BY id")]
    assert ids == ["stream:fleet-autonomy-cont-1-events"]


def test_run_metadata_wins_over_a_receipt_for_the_same_stream(tmp_path):
    rig = Rig(tmp_path)
    rig.credential_receipt("design:lane", f"{LANE}/events.jsonl", selection="secondary")
    rig.lane_meta("lane-one", state="finished", exit_code=0)
    rig.stream(f"{LANE}/events.jsonl", claude_init(model="opus"), result("a1", 10, 10))
    rig.scan(advance=30)
    assert [r[0] for r in rig.sql("SELECT id FROM invocations")] == ["lane:lane-one:run.json"]
    assert rig.sql("SELECT DISTINCT provenance FROM stream_aliases") == [("run_metadata",)]


def test_a17_two_routine_attempts_and_a_coordinator_stream_grow_together(tmp_path):
    rig = Rig(tmp_path)
    for task, session in (("task-one", "sess-1"), ("task-two", "sess-2")):
        rig.record(task, start_row(task, 1, T0, session=session))
    rig.credential_receipt("coordinator:fleet", COORD)
    for round_number in range(3):
        rig.events("task-one", 1, *([claude_init(session="sess-1")] if round_number == 0 else []), claude_result(
            f"a{round_number}", usage(0, 10, 0, 0), {"claude-sonnet-5-5": entry(0, 10 * (round_number + 1), 0, 0)},
            session="sess-1", index=round_number))
        rig.events("task-two", 1, *([claude_init(session="sess-2")] if round_number == 0 else []), claude_result(
            f"b{round_number}", usage(0, 70, 0, 0), {"claude-sonnet-5-5": entry(0, 70 * (round_number + 1), 0, 0)},
            session="sess-2", index=round_number))
        rig.stream(COORD, *([claude_init(model="opus", session="sess-3")] if round_number == 0 else []),
                   claude_result(f"c{round_number}", usage(0, 500, 0, 0), {OPUS: entry(0, 500 * (round_number + 1), 0, 0)},
                                 session="sess-3", index=round_number))
        rig.scan(advance=30)
    rows = dict(rig.sql("SELECT invocation_id, SUM(value) FROM contributions GROUP BY 1"))
    assert rows == {"routine:task-one:1": 30, "routine:task-two:1": 210, "stream:fleet-autonomy-cont-1-events": 1500}
    roles = dict(rig.sql("SELECT invocation_id, role FROM contributions GROUP BY 1"))
    assert roles["stream:fleet-autonomy-cont-1-events"] == "coordinator"


def tail_stream(rig):
    partial = json.dumps(result("c2", 20, 30, 1), sort_keys=True)
    coordinator(rig, claude_init(model="opus"), result("c1", 10, 10), torn=partial[:40])
    return partial


def test_a58_coordinator_torn_tail_waits_then_settles_at_the_horizon_and_late_completion_is_a_correction(tmp_path):
    rig = Rig(tmp_path)
    partial = tail_stream(rig)
    prom = rig.scan(advance=30)
    assert tokens(prom, token_type="output") == 10 and prom.sum("zeus_llm_invocations_total") == 0
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="coordinator") == 0
    prom = rig.scan(advance=HORIZON + 60)
    assert prom.sum("zeus_llm_invocations_total", outcome="terminal_unproven") == 1
    assert rig.inv("stream:fleet-autonomy-cont-1-events")["unknown_reason"] == "terminal_unproven"  # > incomplete_tail
    assert rig.health().sum("zeus_tokobs_malformed_lines_total", source="coordinator") == 1
    (settlement,) = rig.sql("SELECT tail_bytes, tail_sha256 FROM stream_settlements")
    assert settlement == (40, hashlib.sha256(partial[:40].encode()).hexdigest())
    settled = rig.dump()["contributions"]
    assert rig.scan(advance=30).sum("zeus_llm_invocations_total") == 1  # replay
    path = rig.root / COORD
    with path.open("a") as handle:
        handle.write(partial[40:] + "\n")
    rig.touch(path)
    late = rig.scan(advance=30)
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="late_tail") == 1
    assert rig.dump()["contributions"] == settled and late.sum("zeus_llm_invocations_total") == 1
    assert rig.sql("SELECT COUNT(*) FROM results")[0][0] == 1


def routine_copy(rig, name="events-9.jsonl"):
    rig.record("stream-task", start_row("stream-task", 1, T0), terminal_row("finished", 1, T0 + 50))
    source = rig.events("stream-task", 1, claude_init(), result("r1", 10, 10))
    target = source.with_name(name)
    shutil.copyfile(source, target)
    return source, target


def test_c_w1_2_unnamed_routine_copy_stays_pending_then_publishes_identity_unavailable(tmp_path):
    rig = Rig(tmp_path)
    lines = [claude_init(model="claude-sonnet-5-5"), claude_result(
        "x1", usage(1, 99, 5, 1), {"claude-sonnet-5-5": entry(1, 99, 5, 1)}), claude_result(
        "x2", usage(0, 1, 0, 0), {"claude-sonnet-5-5": entry(1, 100, 5, 1)}, index=1)]
    path = rig.events("stream-task", 7, *lines, name="events-7.jsonl")
    rig.touch(path)
    prom = rig.scan(advance=30)
    assert tokens(prom) == 0 and rig.sql("SELECT binding FROM stream_aliases WHERE path LIKE '%events-7.jsonl'") == [
        ("alias_pending",)]
    prom = rig.scan(advance=HORIZON - 30)  # not yet past the horizon
    assert tokens(prom, task_class="identity_unavailable") == 0
    prom = rig.scan(advance=40)  # past 14,400 s of idle
    assert tokens(prom, task_class="identity_unavailable", token_type="output") == 100
    assert tokens(prom, task_class="identity_unavailable", model="claude-sonnet-5-5") == 99 + 1 + 5 + 1 + 1
    assert prom.sum("zeus_llm_invocations_total") == 0  # no invocation, outcome or unknown
    assert rig.sql("SELECT COUNT(*) FROM invocations WHERE id LIKE '%:7'")[0][0] == 0
    assert rig.health().sum("zeus_tokobs_unbound_streams", source="routine") == 1
    again = rig.scan(advance=60)  # published once
    assert tokens(again, task_class="identity_unavailable", token_type="output") == 100
    # the canonical stream arrives later: the same facts add nothing a second time
    rig.record("stream-task", start_row("stream-task", 1, rig.now - 100), terminal_row("finished", 1, rig.now))
    rig.events("stream-task", 1, *lines)
    late = rig.scan(advance=30)
    assert tokens(late, token_type="output") == 100
    assert late.sum("zeus_tokobs_ledger_corrections_total", kind="duplicate_after_publish") >= 1


def test_c_w1_2_shared_facts_deduplicate_before_and_after_the_horizon(tmp_path):
    rig = Rig(tmp_path)
    source, target = routine_copy(rig)
    rig.touch(target)
    rig.touch(source)
    prom = rig.scan(advance=HORIZON + 100)
    assert tokens(prom, task_class="identity_unavailable") == 0  # bound to the canonical attempt
    assert tokens(prom, token_type="output") == 10 and prom.sum("zeus_llm_invocations_total") == 1
    assert rig.sql("SELECT binding FROM stream_aliases WHERE path LIKE '%events-9.jsonl'") == [("bound",)]


def test_unnamed_coordinator_stream_is_an_alias_and_publishes_identity_unavailable(tmp_path):
    rig = Rig(tmp_path)
    rig.stream("fleet-old-events.jsonl", claude_init(model="opus"), result("o1", 10, 10))
    prom = rig.scan(advance=30)
    assert tokens(prom) == 0 and prom.sum("zeus_llm_invocations_total") == 0
    prom = rig.scan(advance=HORIZON + 60)
    assert tokens(prom, task_class="identity_unavailable", role="coordinator", model=OPUS) == 22
    assert rig.health().sum("zeus_tokobs_unbound_streams", source="coordinator") == 1
    assert prom.sum("zeus_llm_unknown_invocations_total") == 0
