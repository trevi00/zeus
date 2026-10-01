"""ACCEPTANCE A32, A33 and C-W1-5, C-W1-7: backfill versus live, ingest lag, deferred sources, S9 freshness."""

import calendar
import json
import os
import sqlite3

from fixtures import (
    OPUS,
    SONNET,
    T0,
    Rig,
    claude_init,
    claude_result,
    entry,
    iso,
    start_row,
    terminal_row,
    usage,
)
from tokobs.__main__ import main

LIVE = T0 + 10_000


def finished_task(rig, task, at, out=10):
    rig.record(task, start_row(task, 1, at, advisor=None), terminal_row("finished", 1, at + 30),
               {"event": "completed", "outcome": "accepted", "at": iso(at + 40)})
    rig.events(task, 1, claude_init(), claude_result(f"{task}-r", usage(0, out, 0, 0), {SONNET: entry(0, out, 0, 0)}))


def test_a32_evidence_older_than_live_since_is_backfill_and_excluded_from_counters(tmp_path):
    rig = Rig(tmp_path)
    for n in range(40):
        finished_task(rig, f"old-{n:02d}", T0 + 100 + n)
    finished_task(rig, "new-task", LIVE + 50, out=7)
    rig.now = LIVE + 200
    prom = rig.scan(live_since=LIVE)
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 7  # only the post-T contribution
    assert prom.sum("zeus_llm_invocations_total") == 1
    assert prom.sum("zeus_task_outcomes_total") == 1 and prom.sum("zeus_task_tokens_total", token_type="output") == 7
    assert rig.health().sum("zeus_tokobs_backfill_invocations") == 40
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE backfill=1")[0][0] == 40  # kept for reports
    assert rig.sql("SELECT value FROM meta WHERE key='live_since'") == [(str(LIVE),)]


def test_a32_an_attempt_still_in_flight_at_live_since_is_live(tmp_path):
    rig = Rig(tmp_path)
    rig.record("flight", start_row("flight", 1, LIVE - 600, advisor=None))  # started 10 min before, no terminal row
    rig.events("flight", 1, claude_init(), claude_result("f1", usage(0, 9, 0, 0), {SONNET: entry(0, 9, 0, 0)}))
    rig.now = LIVE
    prom = rig.scan(live_since=LIVE)
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 9
    assert rig.health().sum("zeus_tokobs_backfill_invocations") == 0


def test_a32_streams_last_written_before_live_since_are_history(tmp_path):
    rig = Rig(tmp_path)
    rig.credential_receipt("coordinator:fleet", "fleet-old-events.jsonl")
    rig.stream("fleet-old-events.jsonl", claude_init(model="opus"), claude_result(
        "o1", usage(0, 5, 0, 0), {OPUS: entry(0, 5, 0, 0)}))
    rig.codex_script("old", resume=False)
    rig.codex_events("old", {"type": "thread.started", "thread_id": "t"}, {"type": "turn.completed", "usage": {
        "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 4, "reasoning_output_tokens": 1,
        "cache_write_input_tokens": 0}})
    rig.now = LIVE
    prom = rig.scan(live_since=LIVE)
    assert prom.sum("zeus_llm_tokens_total") == 0 and prom.sum("zeus_llm_reasoning_output_tokens_total") == 0
    assert prom.sum("zeus_llm_invocations_total") == 0
    assert rig.health().sum("zeus_tokobs_backfill_invocations") == 2


def test_a32_outage_catch_up_is_counted_at_ingest_time_and_lag_is_exported(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig, "before", LIVE)
    rig.now = LIVE + 60
    rig.scan(live_since=LIVE)
    assert rig.health().sum("zeus_tokobs_ingest_lag_seconds") == 0  # the first scan has no earlier one
    rig.now = LIVE + 120
    rig.scan()
    assert rig.health().sum("zeus_tokobs_ingest_lag_seconds") == 60
    finished_task(rig, "during-outage", LIVE + 200, out=11)  # written while the collector was down
    prom = rig.scan(advance=7200)  # two hours later
    assert rig.health().sum("zeus_tokobs_ingest_lag_seconds") >= 7200
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 21  # counted when ingested, not back-dated
    assert rig.sql("SELECT published_at FROM contributions WHERE invocation_id='routine:during-outage:1' LIMIT 1") == [
        (LIVE + 120 + 7200,)]


def test_c_w1_7_live_since_is_stored_once_and_a_plain_scan_classifies_no_backfill(tmp_path):
    plain = Rig(tmp_path / "plain")
    finished_task(plain, "old", T0 + 10)
    plain.now = LIVE
    prom = plain.scan()
    assert prom.sum("zeus_llm_tokens_total", token_type="output") == 10  # nothing is history without live_since
    assert plain.sql("SELECT COUNT(*) FROM meta WHERE key='live_since'")[0][0] == 0
    assert plain.health().sum("zeus_tokobs_backfill_invocations") == 0
    pinned = Rig(tmp_path / "pinned")
    finished_task(pinned, "old", T0 + 10)
    pinned.now = LIVE
    pinned.scan(live_since=LIVE)
    pinned.scan(advance=60, live_since=LIVE + 5000)  # never reset by a later value
    assert pinned.sql("SELECT value FROM meta WHERE key='live_since'") == [(str(LIVE),)]


def test_cli_scan_accepts_an_explicit_live_since(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig, "old", T0 + 10)
    code = main(["scan", "--data", str(rig.data), "--source-root", str(rig.root), "--now", str(LIVE),
                 "--live-since", str(LIVE)])
    assert code == 0
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE backfill=1")[0][0] > 0


def test_a33_deferred_rows_are_counted_but_never_ingested(tmp_path):
    receipt_only = Rig(tmp_path / "receipt")
    finished_task(receipt_only, "task", T0)
    expected = {k: v for k, v in receipt_only.scan(advance=100).series.items() if k[0].startswith("zeus_llm_")}
    rig = Rig(tmp_path / "with-rows")
    finished_task(rig, "task", T0)
    deferred = tmp_path / "harness-projection.jsonl"
    rows = [{"provider_session_id": "11111111-aaaa-bbbb-cccc-000000000001", "outcome": "finished",
             "usage_source": "harness", "parts": {"output": 99999}}, {"provider_session_id": "other", "parts": None}]
    deferred.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    prom = rig.scan(advance=100, deferred_file=deferred)
    assert rig.health().sum("zeus_tokobs_deferred_source_rows") == 2
    assert {k: v for k, v in prom.series.items() if k[0].startswith("zeus_llm_")} == expected
    assert rig.sql("SELECT COUNT(*) FROM contributions WHERE value=99999")[0][0] == 0
    unconfigured = receipt_only.health()
    assert unconfigured.count("zeus_tokobs_deferred_source_rows") == 0  # absent when no such file is configured


def s9_dir(tmp_path, body=None):
    directory = tmp_path / "control"
    directory.mkdir(exist_ok=True)
    body = body or {"schema": "harness-monitor.v1", "collected_at": "2026-10-01T06:44:28.104979+00:00",
                    "scope": "x", "sources": {"database": {"status": "ok", "observed_at": "x", "data": {"big": 1}},
                                              "docker": {"status": "degraded", "observed_at": "x", "data": {}},
                                              "Bad Name!": {"status": "ok"}}}
    (directory / "monitoring.json").write_text(json.dumps(body))
    return directory


def test_s9_freshness_is_read_only_and_exported(tmp_path):
    rig = Rig(tmp_path)
    directory = s9_dir(tmp_path)
    before = (sorted(os.listdir(directory)), (directory / "monitoring.json").read_bytes())
    rig.scan(advance=30, s9_dir=directory)
    health = rig.health()
    assert health.sum("zeus_s9_snapshot_collected_timestamp_seconds") == calendar.timegm((2026, 10, 1, 6, 44, 28)) + 0.104979
    assert health.sum("zeus_s9_source_ok", s9_source="database") == 1
    assert health.sum("zeus_s9_source_ok", s9_source="docker") == 0
    assert health.sum("zeus_s9_source_ok", s9_source="other") == 1  # an unbounded name is never a label
    assert (sorted(os.listdir(directory)), (directory / "monitoring.json").read_bytes()) == before  # nothing written


def test_s9_unreadable_or_missing_snapshot_is_absent_never_zero(tmp_path):
    rig = Rig(tmp_path)
    directory = tmp_path / "control"
    directory.mkdir()
    rig.scan(advance=30, s9_dir=directory)  # no monitoring.json
    assert rig.health().count("zeus_s9_snapshot_collected_timestamp_seconds") == 0
    assert rig.health().count("zeus_s9_source_ok") == 0
    (directory / "monitoring.json").write_text("{broken")
    rig.scan(advance=30, s9_dir=directory)
    assert rig.health().count("zeus_s9_source_ok") == 0
    s9_dir(tmp_path)
    rig.scan(advance=30, s9_dir=directory)
    assert rig.health().count("zeus_s9_source_ok") == 3
    (directory / "monitoring.json").unlink()
    (directory / "monitoring.json").symlink_to(tmp_path / "control" / "elsewhere")
    rig.scan(advance=30, s9_dir=directory)
    assert rig.health().count("zeus_s9_source_ok") == 0  # a link is never followed


def test_c_w1_5_review_rounds_are_never_inferred(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig, "task", T0)
    prom = rig.scan(advance=100)
    assert prom.count("zeus_task_review_rounds_total") == 0  # no source exists today: no series, not 0
    text = (rig.data / "data.prom").read_text()
    assert "# TYPE zeus_task_review_rounds_total counter" in text
    conn = sqlite3.connect(rig.data / "ledger.sqlite3")
    conn.execute("UPDATE tasks SET review_rounds=2 WHERE task_id='task'")  # a future source would fill this column
    conn.commit()
    conn.close()
    assert rig.scan(advance=10).sum("zeus_task_review_rounds_total", outcome="accepted") == 2
