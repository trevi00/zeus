"""Prometheus exposition rendering: `data.prom` (last good) and `health.prom` (always current).

Purpose: turn the ledger into bounded exposition text and write it atomically. Layer: tooling.
Owns: DESIGN §5 metric contract for the S1/core subset, label allowlists and regex, the 5,000-series refusal with
render-refusal health, atomic replace with 0600 files (K10). Does-not-own: scanning, HTTP serving (W1b), the
provider-window and S9 metrics (W1b).
Implements: ACCEPTANCE A24 (bounded labels, no ids), A43 (render refusal), the counter-monotonicity universal
assertion (every counter is a Σ over append-only rows, never a stored mutable number), A15 (deterministic text).
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import windows
from .ledger import Ledger
from .vocab import (
    EXECUTOR_ROLE,
    FIXED_TASK_CLASSES,
    LABEL_ALLOWLISTS,
    LABEL_RE,
    MAX_TASK_CLASSES,
    MODEL_ALLOWLIST,
    OPEN_STATES,
    OTHER,
    SOURCES,
)

MAX_SERIES = 5000
ELAPSED_BUCKETS = (300, 900, 1800, 3600, 7200, 14400, 28800, 86400)
OPEN_STATE_OF = {"open": "open", "terminal_observed": "terminal_observed_pending_eof",
                 "terminal_unavailable": "terminal_observed_pending_eof",
                 "awaiting_predecessor": "awaiting_predecessor"}
MODEL_LABELS = frozenset(MODEL_ALLOWLIST) | {OTHER}
DATA_NAME = "data.prom"
HEALTH_NAME = "health.prom"


class LabelViolation(ValueError):
    pass


@dataclass
class Metric:
    name: str
    mtype: str
    help: str
    values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = field(default_factory=lambda: defaultdict(float))

    def add(self, labels: dict[str, str], value: float, suffix: str = "") -> None:
        self.values[(self.name + suffix, tuple(sorted(labels.items())))] += value


class Labeler:
    """Maps raw label values into their bounded vocabularies (out-of-list -> `other`)."""

    def __init__(self, task_classes: set[str]):
        extra = sorted(c for c in task_classes if LABEL_RE.match(c) and c not in FIXED_TASK_CLASSES)
        self.classes = frozenset(FIXED_TASK_CLASSES) | frozenset(extra[:MAX_TASK_CLASSES - len(FIXED_TASK_CLASSES)])

    def __call__(self, **raw: object) -> dict[str, str]:
        out = {}
        for key, value in raw.items():
            text = str(value)
            if key in ("model", "executor_model", "advisor_model"):
                allowed = MODEL_LABELS
            elif key == "task_class":
                allowed = self.classes
            else:
                allowed = LABEL_ALLOWLISTS.get(key)
            out[key] = text if allowed is None or text in allowed else OTHER
            if not LABEL_RE.match(out[key]):
                raise LabelViolation(f"label {key} fails the bounded-value regex")
        return out


def _fmt(value: float) -> str:
    if isinstance(value, int) or float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(round(float(value), 9))


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _text(metrics: list[Metric]) -> tuple[str, int]:
    lines, series = [], 0
    for metric in sorted(metrics, key=lambda m: m.name):
        lines += [f"# HELP {metric.name} {metric.help}", f"# TYPE {metric.name} {metric.mtype}"]
        for (name, labels), value in sorted(metric.values.items()):
            rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
            lines.append(f"{name}{{{rendered}}} {_fmt(value)}" if labels else f"{name} {_fmt(value)}")
            series += 1
    return "\n".join(lines) + "\n", series


def _task_classes(conn) -> set[str]:
    found: set[str] = set()
    for table in ("invocations", "contributions", "tasks", "cost_contributions"):
        found |= {r[0] for r in conn.execute(f"SELECT DISTINCT task_class FROM {table}")}  # noqa: S608 (fixed names)
    return found


def build_data(ledger: Ledger, now: int = 0) -> tuple[str, int]:
    conn = ledger.conn
    label = Labeler(_task_classes(conn))
    m = {name: Metric(name, mtype, text) for name, mtype, text in (
        ("zeus_llm_tokens_total", "counter", "Measured tokens by provider, model, role, type, source, task class"),
        ("zeus_llm_invocations_total", "counter", "Finalized invocations, once each"),
        ("zeus_llm_unknown_invocations_total", "counter", "Finalized invocations with unknown coverage, at most one each"),
        ("zeus_llm_unknown_shares_total", "counter", "Per-model unknown share detail; not part of the ratio"),
        ("zeus_llm_open_invocations", "gauge", "Invocations not yet finalized"),
        ("zeus_llm_estimated_cost_usd_total", "counter", "Client cost estimate from modelUsage; not a charge"),
        ("zeus_llm_advisor_consultations_total", "counter", "Observed advisor blocks"),
        ("zeus_llm_advisor_state_total", "counter", "Advisor state from the receipt"),
        ("zeus_llm_model_mismatch_total", "counter", "Requested model differs from the observed model"),
        ("zeus_llm_model_unrecognized_total", "counter", "Model names outside the allowlist"),
        ("zeus_task_outcomes_total", "counter", "Closed tasks"),
        ("zeus_task_tokens_total", "counter", "Task contributions, added once at close"),
        ("zeus_task_unknown_invocations_total", "counter", "Unknown invocations of closed tasks"),
        ("zeus_task_attempts_total", "counter", "Attempts of closed tasks"),
        ("zeus_task_review_rounds_total", "counter", "Review rounds of closed tasks; no source exists today (C-W1-5)"),
        ("zeus_llm_reasoning_output_tokens_total", "counter", "Codex reasoning tokens, a subset of output"),
        ("zeus_llm_provider_window_state", "gauge", "Provider window state, one-hot (DESIGN §3.8)"),
        ("zeus_llm_provider_utilization_ratio", "gauge", "Provider-reported utilization; not derived from tokens"),
        ("zeus_llm_provider_window_observed_timestamp_seconds", "gauge", "Bracketed observation time of the window"),
        ("zeus_llm_provider_window_resets_timestamp_seconds", "gauge", "Provider-reported window reset time"),
        ("zeus_task_elapsed_seconds", "histogram", "First dispatch to close"),
        ("zeus_tokobs_ledger_corrections_total", "counter", "Late facts recorded as corrections"))}
    for provider, model, role, tau, source, task_class, value in conn.execute(
            "SELECT provider,model,role,token_type,source,task_class,SUM(value) FROM contributions "
            "WHERE backfill=0 GROUP BY 1,2,3,4,5,6"):
        m["zeus_llm_tokens_total"].add(label(provider=provider, model=model, role=role, token_type=tau,
                                             source=source, task_class=task_class), value)
    for provider, model, role, tau, source, task_class, value in conn.execute(
            "SELECT provider,model,role,token_type,source,task_class,SUM(value) FROM unbound_contributions "
            "WHERE backfill=0 GROUP BY 1,2,3,4,5,6"):  # C-W1-2: identity_unavailable, no invocation behind it
        m["zeus_llm_tokens_total"].add(label(provider=provider, model=model, role=role, token_type=tau,
                                             source=source, task_class=task_class), value)
    for provider, model, role, source, task_class, value in conn.execute(
            "SELECT provider,model,role,source,task_class,SUM(value) FROM reasoning_contributions "
            "WHERE backfill=0 GROUP BY 1,2,3,4,5"):
        m["zeus_llm_reasoning_output_tokens_total"].add(
            label(provider=provider, model=model, role=role, source=source, task_class=task_class), value)
    for provider, model, source, outcome, count in conn.execute(
            "SELECT provider,COALESCE(executor_model,'other'),source,outcome,COUNT(*) FROM invocations "
            "WHERE lifecycle_state='finalized' AND backfill=0 GROUP BY 1,2,3,4"):
        m["zeus_llm_invocations_total"].add(label(provider=provider, model=model, role=EXECUTOR_ROLE.get(source, ""),
                                                  source=source, outcome=outcome), count)
    for provider, source, reason, count in conn.execute(
            "SELECT provider,source,unknown_reason,COUNT(*) FROM invocations WHERE lifecycle_state='finalized' "
            "AND backfill=0 AND unknown_reason IS NOT NULL GROUP BY 1,2,3"):
        m["zeus_llm_unknown_invocations_total"].add(label(provider=provider, source=source, reason=reason), count)
    for provider, reason, count in conn.execute(
            "SELECT s.provider,s.reason,COUNT(*) FROM unknown_shares s JOIN invocations i ON i.id=s.invocation_id "
            "WHERE i.backfill=0 GROUP BY 1,2"):
        m["zeus_llm_unknown_shares_total"].add(label(provider=provider, reason=reason), count)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for provider, source, state, count in conn.execute(
            "SELECT provider,source,lifecycle_state,COUNT(*) FROM invocations WHERE lifecycle_state!='finalized' "
            "AND backfill=0 GROUP BY 1,2,3"):
        counts[(provider, source, OPEN_STATE_OF[state])] += count
    pairs = {(p, s) for p, s, _ in counts} | {("anthropic", "routine")}  # S1 is collected: 0 is a true count
    for provider, source in pairs:
        for state in OPEN_STATES:
            m["zeus_llm_open_invocations"].add(label(provider=provider, source=source, state=state),
                                               counts.get((provider, source, state), 0))
    for provider, model, source, task_class, usd in conn.execute(
            "SELECT provider,model,source,task_class,SUM(usd) FROM cost_contributions WHERE backfill=0 GROUP BY 1,2,3,4"):
        m["zeus_llm_estimated_cost_usd_total"].add(label(provider=provider, model=model, source=source,
                                                         task_class=task_class), usd)
    for executor, advisor, task_class, count in conn.execute(
            "SELECT COALESCE(i.executor_model,'other'),i.advisor_model,i.task_class,COUNT(*) FROM "
            "advisor_consultations c JOIN invocations i ON i.id=c.invocation_id WHERE i.backfill=0 "
            "AND i.advisor_model IS NOT NULL GROUP BY 1,2,3"):
        m["zeus_llm_advisor_consultations_total"].add(
            label(executor_model=executor, advisor_model=advisor, task_class=task_class), count)
    for state, count in conn.execute(
            "SELECT advisor_state,COUNT(*) FROM invocations WHERE lifecycle_state='finalized' AND backfill=0 "
            "AND advisor_state IS NOT NULL GROUP BY 1"):
        m["zeus_llm_advisor_state_total"].add(label(state=state), count)
    for kind, provider, source, count in conn.execute(
            "SELECT f.kind,i.provider,i.source,COUNT(*) FROM model_flags f JOIN invocations i ON i.id=f.invocation_id "
            "WHERE i.backfill=0 GROUP BY 1,2,3"):
        name = "zeus_llm_model_mismatch_total" if kind == "mismatch" else "zeus_llm_model_unrecognized_total"
        m[name].add(label(provider=provider, source=source), count)
    for task_class, outcome, first_pass, attempts, unknown, elapsed, review_rounds in conn.execute(
            "SELECT task_class,outcome,first_pass,attempts,unknown_invocations,closed_at-first_dispatch_at,"
            "review_rounds FROM tasks "
            "WHERE closed_at IS NOT NULL"):
        base = label(task_class=task_class, outcome=outcome)
        m["zeus_task_outcomes_total"].add({**base, **label(first_pass="true" if first_pass else "false")}, 1)
        m["zeus_task_unknown_invocations_total"].add(base, unknown)
        m["zeus_task_attempts_total"].add(base, attempts)
        if review_rounds is not None:  # never inferred (C-W1-5): absent means no series
            m["zeus_task_review_rounds_total"].add(base, review_rounds)
        hist = m["zeus_task_elapsed_seconds"]
        for bound in ELAPSED_BUCKETS:
            hist.add({**base, "le": str(bound)}, 1 if elapsed <= bound else 0, "_bucket")
        hist.add({**base, "le": "+Inf"}, 1, "_bucket")
        hist.add(base, max(elapsed, 0), "_sum")
        hist.add(base, 1, "_count")
    for task_class, outcome, role, tau, value in conn.execute(
            "SELECT t.task_class,t.outcome,s.role,s.token_type,s.value FROM task_token_snapshots s "
            "JOIN tasks t USING(task_id) WHERE t.closed_at IS NOT NULL"):
        m["zeus_task_tokens_total"].add(label(task_class=task_class, outcome=outcome, token_type=tau, role=role), value)
    known = dict(conn.execute("SELECT kind,COUNT(*) FROM corrections GROUP BY 1").fetchall())
    for kind in LABEL_ALLOWLISTS["kind"]:
        m["zeus_tokobs_ledger_corrections_total"].add(label(kind=kind), known.get(kind, 0))
    _window_metrics(conn, label, m, now)
    return _text(list(m.values()))


def _window_metrics(conn, label, m, now: int) -> None:
    """§3.8: one-hot state per (slot, window); utilization only for current/stale; never 0 for unknown."""
    for (slot, window), row in windows.selected(conn).items():
        state = windows.state_of(row, now)
        base = label(provider=windows.PROVIDER, slot=slot, window=window)
        for name in windows.STATES:
            m["zeus_llm_provider_window_state"].add({**base, **label(state=name)}, 1 if name == state else 0)
        if row is not None and row[0] == "value":
            _marker, utilization, resets, observed = row
            if state in ("current", "stale"):
                m["zeus_llm_provider_utilization_ratio"].add({**base, **label(freshness=state)}, utilization)
            m["zeus_llm_provider_window_observed_timestamp_seconds"].add(
                {**base, **label(provenance=windows.PROVENANCE)}, observed)
            m["zeus_llm_provider_window_resets_timestamp_seconds"].add(base, resets)


def build_health(ledger: Ledger, *, refused: bool, series_count: int, now: int) -> str:
    conn = ledger.conn
    rows: list[Metric] = []

    def gauge(name: str, text: str, samples: list[tuple[dict[str, str], float]], mtype: str = "gauge") -> None:
        metric = Metric(name, mtype, text)
        for labels, value in samples:
            metric.add(labels, value)
        rows.append(metric)

    for key, name, text in (("last_scan_success", "zeus_tokobs_last_scan_success_timestamp_seconds",
                             "Unix time of the last successful scan"),
                            ("last_render_success", "zeus_tokobs_last_render_success_timestamp_seconds",
                             "Unix time of the last successful render")):
        value = ledger.meta(key)
        if value is not None:  # an unknown time is absent, never 0
            gauge(name, text, [({}, int(value))])
    gauge("zeus_tokobs_render_refused", "1 when the last render was refused", [({}, 1 if refused else 0)])
    gauge("zeus_tokobs_series_count", "Series in the last attempted render", [({}, series_count)])
    duration = ledger.meta("scan_duration_seconds")
    if duration is not None:
        gauge("zeus_tokobs_scan_duration_seconds", "Duration of the last scan", [({}, float(duration))])
    malformed = dict(conn.execute("SELECT source,COUNT(*) FROM malformed_lines GROUP BY 1").fetchall())
    unbound = dict(conn.execute(
        "SELECT a.source,COUNT(*) FROM read_state rs JOIN stream_aliases a USING(alias_id) "
        "WHERE a.binding IN ('alias_pending','unbound') GROUP BY 1").fetchall())
    files: dict[tuple[str, str], int] = defaultdict(int)
    for source, binding, lifecycle in conn.execute(
            "SELECT a.source,a.binding,i.lifecycle_state FROM read_state rs JOIN stream_aliases a USING(alias_id) "
            "LEFT JOIN invocations i ON i.id=a.invocation_id"):
        state = "finalized" if lifecycle == "finalized" else "open" if binding == "canonical" else binding
        files[(source, state)] += 1
    up = {k.split(".", 1)[1]: int(v) for k, v in conn.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'source_up.%'").fetchall()}
    up_names = {"s2": ("coordinator", "lane"), "routine": ("routine",), "codex_exec": ("codex_exec",)}
    sources = sorted({"routine"} | set(malformed) | set(unbound) | {s for s, _ in files})
    sources = [s for s in sources if s in SOURCES]
    gauge("zeus_tokobs_malformed_lines_total", "Complete malformed lines and settled torn tails",
          [({"source": s}, malformed.get(s, 0)) for s in sources], "counter")
    gauge("zeus_tokobs_unbound_streams", "Read aliases with no canonical invocation",
          [({"source": s}, unbound.get(s, 0)) for s in sources])
    gauge("zeus_tokobs_source_files", "Stream files by state",
          [({"source": s, "state": st}, files.get((s, st), 0)) for s in sources for st in ("open", "finalized", "alias_pending", "bound")])
    samples = [({"source": name}, flag) for key, flag in sorted(up.items()) for name in up_names.get(key, ())]
    if samples:
        gauge("zeus_tokobs_source_up", "1 when the source directory is readable", samples)
    lag = ledger.meta("ingest_lag_seconds")
    if lag is not None:
        gauge("zeus_tokobs_ingest_lag_seconds", "Unobserved window at the start of the last scan", [({}, int(lag))])
    gauge("zeus_tokobs_backfill_invocations", "Invocations classified as history (excluded from counters)",
          [({}, conn.execute("SELECT COUNT(*) FROM invocations WHERE backfill=1").fetchone()[0])])
    deferred = ledger.meta("deferred_source_rows")
    if deferred is not None:
        gauge("zeus_tokobs_deferred_source_rows", "Rows of a configured deferred source; never ingested (§3.10)",
              [({}, int(deferred))])
    collected = ledger.meta("s9.collected_at")
    if collected is not None:
        gauge("zeus_s9_snapshot_collected_timestamp_seconds", "S9 monitoring.json collected_at", [({}, float(collected))])
    s9 = conn.execute("SELECT name,ok FROM s9_sources ORDER BY name").fetchall()
    if s9:
        gauge("zeus_s9_source_ok", "1 when the S9 source status is ok", [({"s9_source": n}, ok) for n, ok in s9])
    return _text(rows)[0]


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


@dataclass(frozen=True)
class RenderResult:
    refused: bool
    series_count: int


def render(ledger: Ledger, data_dir: Path, now: int, *, max_series: int = MAX_SERIES) -> RenderResult:
    """Write `data.prom` atomically unless the render would exceed `max_series` or a label check fails; in both
    cases `health.prom` is rewritten (render-refusal health, DESIGN §5), keeping the last good `data.prom`."""
    data_dir = Path(data_dir)
    refused = False
    try:
        text, series = build_data(ledger, now)
        refused = series > max_series
    except LabelViolation:
        text, series, refused = "", 0, True
    if not refused:
        _write_atomic(data_dir / DATA_NAME, text)
        ledger.set_meta("last_render_success", now)
    _write_atomic(data_dir / HEALTH_NAME, build_health(ledger, refused=refused, series_count=series, now=now))
    return RenderResult(refused, series)
