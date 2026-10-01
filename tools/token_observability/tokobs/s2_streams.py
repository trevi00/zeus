"""S2 sources: lane workers with run metadata, and coordinator/design streams named by credential receipts.

Purpose: read `evidence/*/run*.json` + `events*.jsonl` (lanes) and receipt-named `*-events.jsonl` streams
(coordinator/design) into the ledger. Layer: tooling.
Owns: DESIGN §3.2 (S2 lifecycle rows, 14,400 s horizon, no terminal evidence for streams without metadata),
§3.3 (canonical IDs `lane:<dir>:<run_file>` and `stream:<root-relative stem>`; precedence run metadata > receipt;
routine receipts belong to S1; unnamed paths are read aliases), C-W1-6 (continuity), C-W1-2 (alias horizon).
Does-not-own: reading primitives, the partition and finalization (s1_routine, reused), aliases (aliases.py).
Implements: ACCEPTANCE A17, A41, A44 (lane metadata), A58 (coordinator).

Receipt `events` paths are host paths (`/home/...`); the collector may see the tree under another mount, so a path
is mapped by its trailing components only (`<name>-events.jsonl` or `evidence/<dir>/events*.jsonl`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .backfill import stream_is_history
from .publication import record_correction
from .s1_routine import (
    TASK_ID,
    Scan,
    _inv,
    finalize_claude,
    ingest_claude_events,
    late_tail_check,
    read_json,
    safe_token,
)
from .vocab import LANE_HORIZON_SECONDS
from .windows import parse_ts

PROVIDER = "anthropic"
TOP_EVENTS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-events\.jsonl$")
EVIDENCE_EVENTS = re.compile(r"^events[A-Za-z0-9._-]*\.jsonl$")
RUN_NAME = re.compile(r"^run(?P<suffix>(?:-[A-Za-z0-9._-]+)?)\.json$")
SLOTS = ("primary", "secondary")


def is_codex_stream(name: str) -> bool:
    return name.endswith("-codex-events.jsonl")


def rel_events(text: object) -> str | None:
    """Map a receipt's recorded events path onto a root-relative allowlisted path, or None."""
    if not isinstance(text, str) or len(text) > 1024 or "\x00" in text:
        return None
    parts = PurePosixPath(text.replace("\\", "/")).parts
    if len(parts) >= 3 and parts[-3] == "evidence" and EVIDENCE_EVENTS.match(parts[-1]) \
            and TASK_ID.match(parts[-2]):
        return f"evidence/{parts[-2]}/{parts[-1]}"
    if parts and TOP_EVENTS.match(parts[-1]) and not is_codex_stream(parts[-1]) and "routine-runs" not in parts:
        return parts[-1]
    return None


@dataclass
class StreamSpec:
    inv_id: str
    path: Path
    rel: str
    source: str  # coordinator | lane
    provenance: str  # run_metadata | credential_receipt
    task_class: str
    slot: str = "unknown"
    meta: dict | None = None
    lane_dir: str | None = None
    run_file: str | None = None


def receipt_streams(root: Path) -> dict[str, str]:
    """rel path -> slot, from `credential-selection/*.json` of non-routine consumers (SOURCE-MAP R10)."""
    found: dict[str, str] = {}
    directory = root / "credential-selection"
    if not directory.is_dir() or directory.is_symlink():
        return found
    for path in sorted(directory.glob("*.json")):
        data = read_json(path)
        if data is None:
            continue
        consumer = data.get("consumer")
        if not isinstance(consumer, str) or consumer.startswith("routine:"):
            continue
        rel = rel_events(data.get("events"))
        if rel is not None:
            selection = data.get("selection")
            found[rel] = selection if selection in SLOTS else "unknown"
    return found


def lane_specs(scan: Scan, receipts: dict[str, str]) -> list[StreamSpec]:
    specs: list[StreamSpec] = []
    evidence = scan.source_root / "evidence"
    if not evidence.is_dir() or evidence.is_symlink():
        return specs
    for lane in sorted(p for p in evidence.iterdir() if p.is_dir() and not p.is_symlink() and TASK_ID.match(p.name)):
        for run_path in sorted(lane.glob("run*.json")):
            match = RUN_NAME.match(run_path.name)
            meta = read_json(run_path) if match else None
            if meta is None or not isinstance(meta.get("session"), str) or meta.get("state") not in ("started", "finished"):
                continue  # not the lane shape: `run-start.json`, `run-exit.json`, ... are other launchers' files
            events = lane / f"events{match.group('suffix')}.jsonl"
            if not events.is_file() or events.is_symlink():
                continue
            rel = f"evidence/{lane.name}/{events.name}"
            slot = receipts.get(rel) or (meta.get("selection") if meta.get("selection") in SLOTS else "unknown")
            specs.append(StreamSpec(f"lane:{lane.name}:{run_path.name}", events, rel, "lane", "run_metadata",
                                    scan.registry.classify(lane.name), slot, meta, lane.name, run_path.name))
    return specs


def coordinator_specs(scan: Scan, receipts: dict[str, str], claimed: set[str]) -> list[StreamSpec]:
    specs = []
    for rel in sorted(receipts):
        path = scan.source_root.joinpath(*rel.split("/"))
        if rel in claimed or not path.is_file() or path.is_symlink():
            continue
        stem = rel[:-len(".jsonl")]
        specs.append(StreamSpec(f"stream:{stem}", path, rel, "coordinator", "credential_receipt", "coordination",
                                receipts[rel]))
    return specs


def _mtime(path: Path) -> float | None:
    try:
        return path.lstat().st_mtime
    except OSError:
        return None


def _ensure(scan: Scan, spec: StreamSpec) -> dict:
    existing = _inv(scan.conn, spec.inv_id)
    if existing:
        return existing
    meta = spec.meta or {}
    mode, predecessor = None, None
    if spec.source == "lane":
        resumed = meta.get("mode") == "resume"
        mode = "resumed" if resumed else "fresh"  # C-W1-6: a fresh `--session-id` lane has baseline 0
        run = meta.get("predecessor_run")
        if resumed and isinstance(run, str) and RUN_NAME.match(run):
            predecessor = f"lane:{spec.lane_dir}:{run}"
    started = parse_ts(meta.get("started_at"))
    history = stream_is_history(scan.live_since, _mtime(spec.path), terminal=meta.get("state") == "finished",
                                horizon_seconds=LANE_HORIZON_SECONDS)
    scan.conn.execute(
        "INSERT INTO invocations(id,source,provider,session_or_thread,mode,predecessor_id,requested_model_raw,"
        "lifecycle_state,started_at,task_class,backfill) VALUES(?,?,?,?,?,?,?,'open',?,?,?)",
        (spec.inv_id, spec.source, PROVIDER, safe_token(meta.get("session")), mode, predecessor,
         safe_token(meta.get("model")), int(started) if started else scan.now, spec.task_class, int(history)))
    return _inv(scan.conn, spec.inv_id)  # type: ignore[return-value]


def _terminal(spec: StreamSpec, scan: Scan) -> tuple[str, str, str] | None:
    """(evidence, outcome, kind) or None. Run metadata is terminal evidence; a stream without metadata has none."""
    meta = spec.meta or {}
    if meta.get("state") == "finished":
        if meta.get("timed_out") is True:
            outcome = "timed_out"
        else:
            outcome = "finished" if meta.get("exit_code") == 0 else "failed"
        return "record_row", outcome, "run_metadata"
    modified = _mtime(spec.path)
    if modified is not None and scan.now - modified > LANE_HORIZON_SECONDS:
        return "horizon", "terminal_unproven", "horizon"
    return None


def process_stream(scan: Scan, spec: StreamSpec) -> None:
    with scan.ledger.transaction() as conn:
        inv = _ensure(scan, spec)
        if inv["lifecycle_state"] == "finalized":
            terminal = _terminal(spec, scan)
            if inv["terminal_evidence"] == "horizon" and terminal and terminal[0] == "record_row":
                record_correction(conn, kind="late_terminal", invocation_id=inv["id"], detail=terminal[1],
                                  dedupe_key=f"late_terminal:{inv['id']}", now=scan.now)
            late_tail_check(scan, inv, spec.path)
            return
        state = ingest_claude_events(scan, inv, spec.path, spec.task_class, provenance=spec.provenance,
                                     slot=spec.slot)
        terminal = _terminal(spec, scan)
        if terminal is None:
            return
        if not state.at_eof:
            conn.execute("UPDATE invocations SET lifecycle_state='terminal_observed' WHERE id=?", (inv["id"],))
            return
        evidence, outcome, kind = terminal
        finalize_claude(scan, inv, spec.path, state, spec.task_class, evidence=evidence, outcome=outcome,
                        terminal_kind=kind)


def _predecessors_first(specs: list[StreamSpec]) -> list[StreamSpec]:
    """A resumed lane is processed after the run it names, whatever the file names sort like."""
    by_id = {spec.inv_id: spec for spec in specs}
    ordered: list[StreamSpec] = []
    done: set[str] = set()

    def visit(spec: StreamSpec, depth: int = 0) -> None:
        if spec.inv_id in done or depth > len(specs):
            return
        run = (spec.meta or {}).get("predecessor_run")
        before = by_id.get(f"lane:{spec.lane_dir}:{run}") if isinstance(run, str) else None
        if before is not None:
            visit(before, depth + 1)
        done.add(spec.inv_id)
        ordered.append(spec)

    for spec in specs:
        visit(spec)
    return ordered


def scan_s2(scan: Scan) -> list[tuple[Path, str]]:
    """Process canonical S2 streams; return the (path, source) read-alias candidates for aliases.py."""
    root = scan.source_root
    receipts = receipt_streams(root)
    lanes = lane_specs(scan, receipts)
    claimed = {spec.rel for spec in lanes}
    specs = _predecessors_first(lanes) + coordinator_specs(scan, receipts, claimed)
    scan.ledger.set_meta("source_up.s2", 1 if root.is_dir() else 0)
    canonical = {spec.path for spec in specs}
    for spec in specs:
        process_stream(scan, spec)
    found: list[tuple[Path, str]] = []
    try:
        found += [(p, "coordinator") for p in sorted(root.glob("*-events.jsonl"))
                  if TOP_EVENTS.match(p.name) and not is_codex_stream(p.name)]
        found += [(p, "lane") for p in sorted(root.glob("evidence/*/events*.jsonl"))
                  if EVIDENCE_EVENTS.match(p.name) and TASK_ID.match(p.parent.name)]
    except OSError:
        return []
    return [(path, source) for path, source in found
            if path not in canonical and path.is_file() and not path.is_symlink() and not path.parent.is_symlink()]
