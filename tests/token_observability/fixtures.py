"""Synthetic builders in the shapes of SOURCE-MAP R1-R5/R10. Every number and string here is SYNTHETIC.

No file under `A/`, `/srv`, `~/.claude` or `~/.codex` is read; roots are always pytest `tmp_path`.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from tokobs.collector import scan_once
from tokobs.config import TaskClassRegistry
from tokobs.ledger import open_ledger
from tokobs.render import render

T0 = 1_790_000_000  # synthetic epoch
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
SESSION = "11111111-aaaa-bbbb-cccc-000000000001"
RESULT_TEXT_SENTINEL = "SYNTHETIC-RESULT-TEXT-sentinel-7f3a"
ASSISTANT_TEXT_SENTINEL = "SYNTHETIC-ASSISTANT-TEXT-sentinel-91c2"
SECRET_SHAPED = "sk-ant-oat01-" + "Z" * 40  # a credential-shaped string that must never be stored
RECORD_NOTE_SENTINEL = "SYNTHETIC-RECORD-NOTE-sentinel-5d10"
RECEIPT_TEXT_SENTINEL = "SYNTHETIC-RECEIPT-FINAL-TEXT-sentinel-2b8e"
SENTINELS = (RESULT_TEXT_SENTINEL, ASSISTANT_TEXT_SENTINEL, SECRET_SHAPED, RECORD_NOTE_SENTINEL,
             RECEIPT_TEXT_SENTINEL)


def iso(epoch: int) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def usage(i: int = 0, o: int = 0, cr: int = 0, cw: int = 0) -> dict:
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": cw, "iterations": [{"type": "message"}], "service_tier": "standard"}


def entry(i: int = 0, o: int = 0, cr: int = 0, cw: int = 0, cost: float = 0.0, carried: bool = False) -> dict:
    """One `modelUsage` value. `carried=True` mimics a carried-forward entry without costBasis keys (R3)."""
    base = {"inputTokens": i, "outputTokens": o, "cacheReadInputTokens": cr, "cacheCreationInputTokens": cw,
            "costUSD": cost, "thinkingTokens": 0, "webSearchRequests": 0, "contextWindow": 1_000_000}
    if not carried:
        base["costBasis"] = "list"
    return base


def claude_init(version: str | None = "2.1.286", model: str = SONNET, session: str = SESSION) -> dict:
    line = {"type": "system", "subtype": "init", "session_id": session, "model": model, "cwd": "/synthetic",
            "tools": ["Read"], "uuid": "init-" + session[-4:]}
    if version is not None:
        line["claude_code_version"] = version
    return line


def claude_result(uuid: str, usage_value: dict | None, model_usage: dict | None, *, index: int = 0,
                  is_error: bool = False, subtype: str = "success", session: str = SESSION, spawned: int = 0,
                  spawned_by_subagents: int = 0) -> dict:
    line = {"type": "result", "subtype": subtype, "is_error": is_error, "result": RESULT_TEXT_SENTINEL,
            "session_id": session, "uuid": uuid, "result_index": index, "total_cost_usd": 0.5,
            "terminal_reason": "completed",
            "subagent_stats": {"spawned": spawned, "spawned_by_subagents": spawned_by_subagents, "max_depth": 0}}
    if usage_value is not None:
        line["usage"] = usage_value
    if model_usage is not None:
        line["modelUsage"] = model_usage
    return line


def assistant(text: str = ASSISTANT_TEXT_SENTINEL, *, message_id: str = "msg-1", advisor_blocks: int = 0,
              session: str = SESSION, ts: str | None = None) -> dict:
    content: list[dict] = [{"type": "text", "text": text}]
    for n in range(advisor_blocks):
        content.append({"type": "server_tool_use", "id": f"srvtoolu_{n}", "name": "advisor", "input": {}})
    line = {"type": "assistant", "session_id": session, "uuid": "a-" + message_id,
            "message": {"id": message_id, "role": "assistant", "content": content}}
    if ts:
        line["timestamp"] = ts
    return line


def start_row(task: str, attempt: int, at: int, *, resumed: bool = False, timeout: int = 3600,
              advisor: str | None = OPUS, session: str = SESSION, model: str = SONNET) -> dict:
    row = {"event": "resumed" if resumed else "dispatched", "task_id": task, "attempt": attempt, "at": iso(at),
           "worker_session": session, "model": model, "timeout_seconds": timeout, "spec_sha256": "0" * 64,
           "coordinator_session": "coord-synthetic"}
    if advisor is not None:
        row["advisor"] = advisor
    return row


def terminal_row(event: str, attempt: int, at: int) -> dict:
    return {"event": event, "attempt": attempt, "at": iso(at), "exit": 0 if event == "finished" else 1,
            "receipt": {"final_text": RECEIPT_TEXT_SENTINEL}}


def completed_row(outcome: str, at: int) -> dict:
    return {"event": "completed", "outcome": outcome, "at": iso(at), "note": RECORD_NOTE_SENTINEL}


def iso_ms(epoch: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(epoch))) + f".{int(round((epoch % 1) * 1000)):03d}Z"


def user_line(ts: float, session: str = SESSION) -> dict:
    """A timestamped non-event line: the bracket for a following `rate_limit_event` (SOURCE-MAP R6)."""
    return {"type": "user", "session_id": session, "timestamp": iso_ms(ts), "uuid": f"u-{int(ts * 1000)}",
            "message": {"role": "user", "content": [{"type": "text", "text": ASSISTANT_TEXT_SENTINEL}]}}


def rate_limit(uuid: str, five_hour=None, seven_day=None, *, session: str = SESSION, status: str = "allowed") -> dict:
    """`windows` values are (utilization, resetsAt) pairs, a raw dict, or None for an absent window."""
    def window(value):
        return {"utilization": value[0], "resetsAt": value[1]} if isinstance(value, tuple) else value

    unified = {name: window(value) for name, value in (("five_hour", five_hour), ("seven_day", seven_day))
               if value is not None}
    return {"type": "rate_limit_event", "session_id": session, "uuid": uuid,
            "rate_limit_info": {"status": status, "unifiedWindows": unified}}


def codex_usage(inp: int, cached: int, out: int, reasoning: int = 0, cw: int | None = 0) -> dict:
    usage = {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
             "reasoning_output_tokens": reasoning}
    if cw is not None:
        usage["cache_write_input_tokens"] = cw
    return usage


def codex_thread_started(thread: str) -> dict:
    return {"type": "thread.started", "thread_id": thread}


def codex_turn_completed(usage_value: dict) -> dict:
    return {"type": "turn.completed", "usage": usage_value}


def parse_prom(text: str) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})? (\S+)$", line)
        assert match, line
        labels = tuple(sorted(re.findall(r'([a-z0-9_]+)="((?:[^"\\]|\\.)*)"', match.group(2) or "")))
        out[(match.group(1), labels)] = float(match.group(3))
    return out


class Prom:
    def __init__(self, series: dict):
        self.series = series

    def sum(self, name: str, **labels: str) -> float:
        wanted = set(labels.items())
        return sum(v for (n, ls), v in self.series.items() if n == name and wanted <= set(ls))

    def count(self, name: str, **labels: str) -> int:
        wanted = set(labels.items())
        return sum(1 for (n, ls) in self.series if n == name and wanted <= set(ls))


COUNTER_SUFFIXES = ("_total", "_bucket", "_sum", "_count")


class Rig:
    """A synthetic source tree plus a data dir, with the universal per-scan assertions of ACCEPTANCE:
    every counter series is >= its previous value and never disappears; unknown <= invocations;
    no sentinel text and no id in the ledger bytes or the exposition."""

    def __init__(self, tmp_path: Path, name: str = "run"):
        self.root = tmp_path / "A"
        self.data = tmp_path / name
        self.runs = self.root / "routine-runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        self.now = T0
        self.registry = TaskClassRegistry()
        self.history: list[dict] = []
        self.before_commit = None

    # -- source files ---------------------------------------------------------
    def task_dir(self, task: str) -> Path:
        path = self.runs / task
        path.mkdir(parents=True, exist_ok=True)
        return path

    def record(self, task: str, *rows: dict) -> None:
        with (self.task_dir(task) / "record.jsonl").open("a") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def events(self, task: str, attempt: int, *lines: dict, torn: str = "", name: str | None = None) -> Path:
        path = self.task_dir(task) / (name or f"events-{attempt}.jsonl")
        with path.open("a") as handle:
            for line in lines:
                handle.write(json.dumps(line, sort_keys=True) + "\n")
            handle.write(torn)
        return path

    def raw_events(self, task: str, attempt: int, raw: str) -> Path:
        path = self.task_dir(task) / f"events-{attempt}.jsonl"
        with path.open("a") as handle:
            handle.write(raw)
        return path

    def receipt(self, task: str, attempt: int, advisor_enabled: str = "enabled", ok: bool = True) -> None:
        body = {"receipt_ok": ok, "worker_status": "done", "advisor_enabled": advisor_enabled,
                "final_text": RECEIPT_TEXT_SENTINEL}
        (self.task_dir(task) / f"receipt-{attempt}.json").write_text(json.dumps(body))

    # -- S2 / S3 sources ------------------------------------------------------
    def stream(self, rel: str, *lines: dict, torn: str = "", touch: bool = True) -> Path:
        """Append complete lines to a root-relative file; the mtime follows the rig clock (idle horizons)."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            for line in lines:
                handle.write(json.dumps(line, sort_keys=True) + "\n")
            handle.write(torn)
        if touch:
            self.touch(path)
        return path

    def touch(self, path: Path, epoch: float | None = None) -> None:
        stamp = self.now if epoch is None else epoch
        os.utime(path, (stamp, stamp))

    def credential_receipt(self, consumer: str, rel: str, selection: str = "primary", name: str | None = None) -> None:
        """A credential-selection receipt; its `events` path carries a HOST prefix unlike the scan root."""
        directory = self.root / "credential-selection"
        directory.mkdir(parents=True, exist_ok=True)
        body = {"consumer": consumer, "events": f"/host/zeus/artifacts/aibox/{rel}", "selection": selection,
                "has_token": True, "reasons": [], "schema": "synthetic"}
        (directory / (name or f"{len(list(directory.iterdir())):03d}.json")).write_text(json.dumps(body))

    def lane_meta(self, lane: str, run_name: str = "run.json", **fields) -> Path:
        body = {"session": SESSION, "selection": "primary", "model": "opus", "state": "started",
                "started_at": "2026-10-01T05:12:33.123456+00:00", **fields}
        path = self.root / "evidence" / lane / run_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
        return path

    def codex_script(self, stem: str, *, resume: bool = True, model: str = "gpt-6-astra") -> None:
        verb = "exec -s danger-full-access resume --json" if resume else "exec -s danger-full-access --json"
        thread = " 01a0e11e-synthetic-thread" if resume else ""
        text = ("set -euo pipefail\nM=/host/zeus/artifacts/aibox\nset -o noclobber\n"
                f'codex -a never {verb} -m {model} -o "$M/{stem}-codex-final.md"{thread} - < "$M/{stem}-codex-task.md" '
                f'> "$M/{stem}-codex-events.jsonl" 2> "$M/{stem}-codex-stderr.log"\n')
        (self.root / f"{stem}-codex-run.sh").write_text(text)

    def codex_events(self, stem: str, *lines: dict, torn: str = "") -> Path:
        return self.stream(f"{stem}-codex-events.jsonl", *lines, torn=torn)

    def codex_prestart(self, stem: str, thread: str, usage_value: dict) -> None:
        (self.root / f"{stem}-codex-prestart.json").write_text(json.dumps({"thread_id": thread, "usage": usage_value}))

    def inv(self, inv_id: str) -> dict:
        conn = sqlite3.connect(self.data / "ledger.sqlite3")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM invocations WHERE id=?", (inv_id,)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    # -- scanning -------------------------------------------------------------
    def scan(self, advance: int = 0, **kwargs) -> Prom:
        self.now += advance
        scan_once(self.data, self.root, now=self.now, registry=self.registry, monotonic=lambda: 0.0,
                  before_commit=self.before_commit, **kwargs)
        ledger = open_ledger(self.data)
        try:
            render(ledger, self.data, self.now)
        finally:
            ledger.close()
        prom = Prom(parse_prom((self.data / "data.prom").read_text()))
        self.check_universal(prom)
        return prom

    def health(self) -> Prom:
        return Prom(parse_prom((self.data / "health.prom").read_text()))

    def check_universal(self, prom: Prom) -> None:
        if self.history:
            previous = self.history[-1]
            for (name, labels), value in previous.items():
                if name.endswith(COUNTER_SUFFIXES):
                    assert (name, labels) in prom.series, f"series disappeared: {name}{labels}"
                    assert prom.series[(name, labels)] >= value, f"counter decreased: {name}{labels}"
        self.history.append(dict(prom.series))
        invocations = prom.sum("zeus_llm_invocations_total")
        assert prom.sum("zeus_llm_unknown_invocations_total") <= invocations
        self.assert_no_text()

    def assert_no_text(self) -> None:
        blobs = [p.read_bytes() for p in self.data.iterdir() if p.is_file()]
        for needle in SENTINELS:
            for blob in blobs:
                assert needle.encode() not in blob, f"text leaked into the data dir: {needle[:24]}"

    # -- ledger inspection ----------------------------------------------------
    def sql(self, query: str, *params) -> list[tuple]:
        conn = sqlite3.connect(self.data / "ledger.sqlite3")
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()

    def invocation(self, task: str, attempt: int) -> dict:
        conn = sqlite3.connect(self.data / "ledger.sqlite3")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM invocations WHERE id=?", (f"routine:{task}:{attempt}",)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def corrections(self, kind: str) -> int:
        return self.sql("SELECT COUNT(*) FROM corrections WHERE kind=?", kind)[0][0]

    def dump(self) -> dict[str, list[tuple]]:
        conn = sqlite3.connect(self.data / "ledger.sqlite3")
        try:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                 "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables}
        finally:
            conn.close()
