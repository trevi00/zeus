"""Deterministic scenarios behind the golden files (one per source) and the ledger snapshot they compare.

Every time is derived from the rig clock (`T0`), every id is synthetic, and the scan clock is fake, so two runs
produce identical bytes. The goldens are recorded once from these scenarios and reviewed by hand against the
numbers asserted in the scenario tests; they are never regenerated to make a failing test pass.
"""

from __future__ import annotations

import sqlite3

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
    rate_limit,
    start_row,
    terminal_row,
    usage,
    user_line,
)

THREAD = "01a0e11e-synthetic-thread"
FUTURE = T0 + 3 * 86400
SNAPSHOT_TABLES = {
    "invocations": "id,source,provider,session_or_thread,task_id,attempt,mode,predecessor_id,predecessor_state,"
                   "executor_model,advisor_model,cli_version,lifecycle_state,outcome,unknown_reason,"
                   "terminal_evidence,terminal_kind,started_at,finalized_at,backfill,task_class",
    "results": "session_id,uuid,invocation_id,seq,is_error,zeroed,input,output,cache_read,cache_write",
    "contributions": "id,invocation_id,kind,provider,model,role,source,task_class,token_type,value,published_at,"
                     "backfill",
    "cost_contributions": "id,invocation_id,model,source,task_class,usd,backfill",
    "reasoning_contributions": "id,invocation_id,model,role,source,task_class,value,backfill",
    "unbound_contributions": "id,model,role,source,task_class,token_type,value,backfill",
    "unknown_shares": "invocation_id,model,provider,reason",
    "corrections": "kind,invocation_id,detail_enum,recorded_at",
    "codex_points": "thread_id,input_tokens,cached,cache_write,output,reasoning,invocation_id,published",
    "rate_observations": "session_id,event_key,window,slot,marker,utilization,resets_at,observed_at,provenance,"
                         "line_index",
    "tasks": "task_id,task_class,outcome,attempts,first_pass,unknown_invocations,backfill",
    "advisor_consultations": "session_id,message_id,block_index,invocation_id",
}


def ledger_snapshot(rig: Rig) -> dict:
    """The accounting state without paths, inodes or file hashes."""
    conn = sqlite3.connect(rig.data / "ledger.sqlite3")
    try:
        return {table: [list(row) for row in conn.execute(f"SELECT {columns} FROM {table} ORDER BY 1,2,3,4")]  # noqa: S608
                for table, columns in sorted(SNAPSHOT_TABLES.items())}
    finally:
        conn.close()


def routine_scenario(tmp_path) -> Rig:
    """S1: a resumed pair with a Sonnet executor and an Opus advisor (ACCEPTANCE A01, A04)."""
    rig = Rig(tmp_path)
    task = "golden-routine"
    rig.record(task, start_row(task, 1, T0), terminal_row("failed", 1, T0 + 100),
               start_row(task, 2, T0 + 200, resumed=True), terminal_row("finished", 2, T0 + 300),
               {"event": "completed", "outcome": "accepted", "at": "2026-09-26T21:35:50Z"})
    rig.events(task, 1, claude_init(), assistant(advisor_blocks=1), claude_result(
        "g1", usage(2, 100, 1000, 10), {SONNET: entry(2, 100, 1000, 10, 0.5), OPUS: entry(5, 40, 200, 0, 0.25)}))
    rig.events(task, 2, claude_init(), claude_result(
        "g2", usage(1, 30, 500, 5), {SONNET: entry(3, 130, 1500, 15, 0.75), OPUS: entry(5, 40, 200, 0, 0.0, True)}))
    rig.receipt(task, 1)
    rig.receipt(task, 2)
    rig.scan(advance=400)
    return rig


def s2_scenario(tmp_path) -> Rig:
    """S2: a receipt-named coordinator stream (horizon), a finished lane, and rate-window markers."""
    rig = Rig(tmp_path)
    rig.credential_receipt("coordinator:fleet", "fleet-autonomy-cont-1-events.jsonl", "primary")
    rig.stream("fleet-autonomy-cont-1-events.jsonl", claude_init(model="opus"), user_line(T0 + 5), rate_limit(
        "g-rl-1", five_hour=(0.25, FUTURE), seven_day=(0.5, FUTURE)),
        claude_result("c1", usage(1, 10, 10, 1), {OPUS: entry(1, 10, 10, 1)}),
        claude_result("c2", usage(1, 20, 20, 1), {OPUS: entry(2, 37, 20, 2)}, index=1))
    rig.lane_meta("golden-lane", state="finished", exit_code=0)
    rig.stream("evidence/golden-lane/events.jsonl", claude_init(model="opus", session="lane-session"), claude_result(
        "l1", usage(1, 8, 4, 0), {OPUS: entry(1, 15, 4, 0)}, session="lane-session"))
    rig.scan(advance=60)
    rig.scan(advance=14_500)  # past the 14,400 s horizon
    return rig


def codex_scenario(tmp_path) -> Rig:
    """S3: a fresh run, a pre-start-proven resume, and an unproven resume (A20, A49)."""
    rig = Rig(tmp_path)
    points = {"gold0": codex_usage(1000, 800, 100, 30), "gold1": codex_usage(1500, 1200, 160, 40),
              "gold2": codex_usage(2100, 1700, 250, 55)}
    for index, (stem, point) in enumerate(points.items()):
        rig.codex_script(stem, resume=index > 0)
        if stem == "gold1":
            rig.codex_prestart(stem, THREAD, points["gold0"])
        rig.codex_events(stem, codex_thread_started(THREAD), codex_turn_completed(point))
    rig.scan(advance=60)
    return rig


SCENARIOS = {"routine": routine_scenario, "s2_windows": s2_scenario, "codex": codex_scenario}
