"""Shared S9 scenario steps (`observation.local_facts`): M7 `adapters/monitoring_observations.py` (the read-only observation projection for the monitor).

Layer: harness (never shipped)

`api.module` is the side's projection module (`text`, `parse_time`, `scan_bounded`, `project_event`, `sort_key`, `merge_events`, `collection_facts`,
`project_operation`, `local_facts`, `observation_facts` and the constants), `api.SpoolDirectory` and `api.spool_module` the side's real spool directory class and
the module that `local_facts` imports it from, `api.MemoryStore` the side's store. Mirrors `tests/test_monitoring_observations.py` (the projection half): every
helper over its shapes, `local_facts` over a REAL spool directory in a per-case temporary directory (read-only: the tree is listed before and after), and
`observation_facts` over a MemoryStore with and without a runtime, always with a fixed `now`.

Declared nondeterministic fields, normalized HERE and never by the mask list: the temporary root (`<root>`) and, when `now` is not given, `observed_at` (proven
an ISO-8601 UTC instant and reported as `<utc-iso>`; the call then uses a store without collection receipts, whose lag would otherwise read the wall clock).
No clock, process, network or database.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
CANARY = "CANARY-5f1e2d3c4b5a69788796a5b4c3d2e1f0"


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def event(event_id, category="development", severity="info", minutes=0, **extra):
    """A synthetic stored observation row (the fixture shape of the M7 tests)."""
    row = {"event_id": event_id, "event_type": f"{category}.fixture", "category": category, "severity": severity, "outcome": "observed",
           "observed_at": (NOW - timedelta(minutes=minutes)).isoformat(), "occurred_at": None, "source": {"component": "unit", "host": "h", "pid": 1},
           "execution": {"kind": "system", "process_run_id": "a" * 32, "task_id": None, "attempt": None},
           "evidence_refs": ["sha256:" + "b" * 64], "attributes": {"secret_prompt": "password=" + CANARY}, "payload_hash": "x"}
    row.update(extra)
    return row


def summarize(value, keep=3):
    """Long row lists are reported by length, digest and their first and last rows; nothing else is trimmed."""
    if isinstance(value, dict):
        return {k: summarize(v, keep) for k, v in value.items()}
    if isinstance(value, list) and len(value) > 2 * keep:
        return {"len": len(value), "digest": canonical_digest(value), "first": value[:keep], "last": value[-keep:]}
    return value


class Case:
    def __init__(self, api):
        self.api = api
        self.root = Path(tempfile.mkdtemp(prefix="s9-local-facts-")).resolve()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def text(self, value):
        return json.loads(json.dumps(value, default=str).replace(str(self.root), "<root>"))

    def tree(self):
        return sorted((p.relative_to(self.root).as_posix(), p.stat().st_size if p.is_file() else None) for p in self.root.rglob("*"))

    def spool_dir(self):
        return self.api.SpoolDirectory(self.root / "observations")


def helper_text(api):
    m = api.module
    values = [None, 5, 5.5, True, [], {}, b"bytes", "", "plain", "x" * 500, "token=" + CANARY, "password=" + CANARY + " tail", "ghp_" + "A" * 30,
              "한글 라벨 " + "가" * 300, "line1\nline2", "<script>alert(1)</script>"]
    return {"default_limit": [call(m.text, v) for v in values], "limit_20": [call(m.text, v, 20) for v in values[8:12]],
            "limit_zero": call(m.text, "abc", 0), "limit_negative": call(m.text, "abcdef", -2), "limit_none": call(m.text, "abc", None),
            "redaction_before_truncation": call(m.text, "a" * 190 + "password=" + CANARY, 200),
            "constants": {k: getattr(m, k) for k in ("SCHEMA", "BUCKET_LIMIT", "PAGE", "ROW_LIMIT", "HIGH_LIMIT", "OPERATION_LIMIT", "TEXT_LIMIT", "REFS_LIMIT",
                                                      "SEVERITY_RANK", "CATEGORY_RANK", "CATEGORY_LABELS", "PENDING_TERMINATION", "OPERATION_BUCKET")}}


def helper_parse_time(api):
    m = api.module
    values = ["2026-09-18T12:00:00+00:00", "2026-09-18T12:00:00Z", "2026-09-18T21:00:00+09:00", "2026-09-18T12:00:00.123456+00:00", "2026-09-18T12:00:00",
              "2026-09-18", "20260918T120000+0000", "not-a-time", "", None, 5, 5.5, ["x"], {}, True, b"2026-09-18T12:00:00+00:00", " 2026-09-18T12:00:00+00:00"]
    out = []
    for v in values:
        r = call(m.parse_time, v)
        out.append({"input": repr(v), "result": iso(r["value"]) if "value" in r else r, "utcoffset": (r["value"].utcoffset().total_seconds()
                                                                                                    if r.get("value") is not None else None)})
    return out


def helper_scan_bounded(api):
    m = api.module
    store = api.MemoryStore()
    with store.transaction() as tx:
        for index in range(7):
            tx.put("b7", f"r{index:03d}", {"n": index})
        for index in range(5):
            tx.put("b5", f"r{index:03d}", {"n": index})
        for index in range(m.BUCKET_LIMIT + 3):
            tx.put("big", f"r{index:05d}", {"n": index})
    out = {}
    with store.transaction() as tx:
        def scan(bucket, **kwargs):
            rows, meta = m.scan_bounded(tx, bucket, **kwargs)
            return {"n": [r["n"] for r in rows], "meta": meta}
        out["empty"] = scan("none", limit=5, page=2)
        out["fewer_than_limit"] = scan("b5", limit=10, page=2)
        out["exactly_limit"] = scan("b5", limit=5, page=2)
        out["limit_plus_one"] = scan("b7", limit=6, page=2)
        out["limit_plus_one_big_page"] = scan("b7", limit=6, page=100)
        out["page_equals_limit"] = scan("b7", limit=4, page=4)
        out["page_one"] = scan("b5", limit=3, page=1)
        out["limit_zero"] = scan("b5", limit=0, page=2)
        out["limit_one"] = scan("b7", limit=1, page=2)
        rows, meta = m.scan_bounded(tx, "big")
        out["default_big"] = {"len": len(rows), "first": rows[0], "last": rows[-1], "meta": meta, "digest": canonical_digest(rows)}
        out["page_zero"] = call(m.scan_bounded, tx, "b7", 4, 0)
    return out


def helper_project_event(api):
    m = api.module
    full = event("e1", "operations", "error", record_kind="event", collected_at=NOW.isoformat(), occurred_at=NOW.isoformat(), audit_confirmed=True,
                 correlation_id="corr-1", reason_code="r", execution={"kind": "lease", "role": "worker", "task_id": "t1", "bucket": "tasks", "attempt": 2,
                                                                      "generation": 3, "process_run_id": "a" * 32, "invocation_id": "inv"})
    refs = ["sha256:" + "c" * 64, "ok-ref", "has space", 5, None, "", "a" * 201, "a" * 200, "x/y"] + [f"ref{i}" for i in range(12)]
    rows = {"full": full, "empty": {}, "nothing_known": {"event_id": 5, "event_type": None},
            "bad_severity_category": event("bad", "weird", "loud"), "unhashable_severity": event("u", "general", ["x"]),
            "naive_observed": event("n", observed_at="2026-09-18T11:00:00"), "bad_observed": event("b", observed_at="nope"), "missing_observed": event("m", observed_at=None),
            "occurred_collected_bad": event("o", occurred_at="x", collected_at="2026-09-18"), "non_dict_execution": event("e", execution="x", source=[1]),
            "bool_attempt": event("t", execution={"attempt": True, "generation": 1.0, "kind": "k" * 50, "bucket": "b" * 80}),
            "refs_filtered": event("r", evidence_refs=refs), "refs_none": event("r2", evidence_refs=None), "refs_string": event("r3", evidence_refs="abc"),
            "refs_dict": event("r4", evidence_refs={"a": 1}), "refs_empty": event("r5", evidence_refs=[]),
            "long_text": event("l" * 400, correlation_id="c" * 400, reason_code="z" * 200, outcome="o" * 100),
            "credentials": event("c", reason_code="password=" + CANARY, correlation_id="token=" + CANARY, source={"component": "api_key=" + CANARY}),
            "audit_unconfirmed": event("a", audit_confirmed=False), "extra_keys_dropped": event("x", attributes={"deep": {"x": CANARY}}, payload_hash="h", spool={"file": "f"})}
    out = {name: call(m.project_event, copy.deepcopy(row), "audit") for name, row in rows.items()}
    out["kinds"] = {repr(kind): call(m.project_event, copy.deepcopy(full), kind)["value"]["record_kind"] for kind in ("audit", "event", "collected", "both", None)}
    out["non_dict_row"] = [call(m.project_event, v, "audit") for v in (None, [], "x", 5)]
    out["canary_leaked"] = any(CANARY in json.dumps(v) for v in out.values() if isinstance(v, dict))
    return out


def helper_merge_events(api):
    m = api.module
    audits = [event("e1", "operations", "info"), event("a1", "general", "debug", minutes=9), event("bad", "weird", "loud", observed_at="not-a-time"),
              event("naive", "general", "warning", observed_at="2026-09-18T11:00:00"), {"event_id": 5}, {"event_id": None}, {"no_id": 1},
              event("dup", "general", "info", minutes=1), event("dup", "operations", "error", minutes=2)]
    collected = [event("e1", "operations", "info", record_kind="event"), event("e2", "development", "critical", record_kind="event"),
                 event("e3", "general", "error", minutes=5, record_kind="event"), event("e4", "operations", "error", minutes=1, record_kind="event"),
                 event("e5", "operations", "error", minutes=0, record_kind="event"), {"event_id": 7}, event("dup", "general", "debug", minutes=3), {}]
    merged, kinds = m.merge_events(copy.deepcopy(audits), copy.deepcopy(collected))
    only_audit, kinds_audit = m.merge_events(copy.deepcopy(audits), [])
    only_collected, kinds_collected = m.merge_events([], copy.deepcopy(collected))
    ties = [event("b", "general", "info"), event("a", "general", "info"), event("c", "general", "info")]
    return {"order": [e["event_id"] for e in merged], "kinds": kinds, "dup": next(e for e in merged if e["event_id"] == "dup"),
            "only_audit": {"order": [e["event_id"] for e in only_audit], "kinds": kinds_audit},
            "only_collected": {"order": [e["event_id"] for e in only_collected], "kinds": kinds_collected},
            "empty": list(m.merge_events([], [])), "ties_by_event_id": [e["event_id"] for e in m.merge_events(ties, [])[0]],
            "sort_key_unknowns": [m.sort_key(e) for e in m.merge_events([event("x", "weird", "loud", observed_at="nope")], [])[0]],
            "non_dict_row": call(m.merge_events, ["x"], []), "full_first": merged[0]}


def helper_collection_facts(api):
    m = api.module
    at = lambda **d: (NOW - timedelta(**d)).isoformat()  # noqa: E731
    receipts = {"empty": [], "no_valid_time": [{"id": "x", "at": "garbage"}, {"id": "y"}, {"at": None}, {"at": "2026-09-18T11:00:00"}],
                "latest_of_three": [{"id": "c1", "file": "a.jsonl", "records": 3, "inserted": 2, "duplicates": 1, "at": at(seconds=90)},
                                    {"id": "c0", "records": 1, "at": at(hours=1)}, {"id": "cx", "at": "garbage"}],
                "tie_keeps_first": [{"id": "first", "at": at(seconds=5), "records": 1}, {"id": "second", "at": at(seconds=5), "records": 2}],
                "future_clamped": [{"id": "f", "at": (NOW + timedelta(seconds=30)).isoformat(), "records": 9}],
                "long_file_bounded": [{"id": "l", "at": at(seconds=1), "file": "f" * 400 + ".jsonl", "records": 1}],
                "credential_file": [{"id": "k", "at": at(seconds=1), "file": "password=" + CANARY}],
                "all_keys": [{"id": "k", "at": at(seconds=1), "file": "a", "records": 1, "inserted": 2, "duplicates": 3, "conflicts": 4, "corrupt": 5, "refused": 6,
                              "truncated_tail": 7, "unconfirmed_audits": 8, "confirmed_audits": 9, "extra": "dropped"}],
                "non_string_file": [{"id": "n", "at": at(seconds=1), "file": 5}], "aware_other_zone": [{"id": "z", "at": "2026-09-18T20:59:00+09:00"}]}
    out = {name: call(m.collection_facts, copy.deepcopy(rows), NOW) for name, rows in receipts.items()}
    out["naive_now"] = call(m.collection_facts, receipts["latest_of_three"], datetime(2026, 9, 18, 12))
    out["naive_now_no_receipts"] = call(m.collection_facts, [], datetime(2026, 9, 18, 12))
    out["non_dict_receipt"] = call(m.collection_facts, ["x"], NOW)
    out["canary_leaked"] = CANARY in json.dumps(out["credential_file"])
    return out


def helper_project_operation(api):
    m = api.module
    rows = {"full": {"id": "op", "status": "failed", "reason_code": "evidence_gate_refused", "task_id": "task", "decision_id": "d", "lead_accepted": True,
                     "goal": {"criterion": "c"}, "correlation_id": "corr"},
            "empty": {}, "non_dict_goal": {"id": "o", "goal": "x"}, "none_goal": {"id": "o", "goal": None}, "credential": {"id": "o", "goal": {"criterion": "token=" + CANARY + " <img onerror=x>"}},
            "long": {"id": "i" * 400, "status": "s" * 100, "reason_code": "r" * 200, "goal": {"criterion": "g" * 500}},
            "non_string": {"id": 5, "status": None, "reason_code": ["x"], "task_id": {}, "goal": {"criterion": 7}}, "lead_accepted_false": {"id": "o", "lead_accepted": False}}
    out = {name: call(m.project_operation, row) for name, row in rows.items()}
    out["non_dict_row"] = [call(m.project_operation, v) for v in (None, "x", [])]
    out["canary_leaked"] = CANARY in json.dumps(out["credential"])
    return out


def populate_runtime(case, many=False):
    """A real runtime directory: `observations/{spool,health,...}` written through the spool directory's own write methods."""
    d = case.spool_dir()
    runs = ["a" * 32, "b" * 32]
    d.write_health(runs[0], {"process_run_id": runs[0], "component": "exec", "role": "worker", "updated_at": NOW.isoformat(), "sink": "unavailable",
                             "counters": {"dropped_spool_full": 2, "spool_failures": 1, "refused": 0, "dropped_run_refused": 3, "alerts_pending_dropped": 4, "other": 9},
                             "spool": {"unacknowledged_bytes": 10, "limit_bytes": 20}, "pending_alerts": [{"event_type": "x"}, {"event_type": "y"}],
                             "last_defect": "password=" + CANARY})
    d.write_health(runs[1], {"process_run_id": runs[1], "component": "c" * 200, "role": 5, "updated_at": "nope", "sink": "available", "counters": "x", "spool": [1],
                             "pending_alerts": None, "last_defect": None})
    (case.root / "observations" / "health" / ("c" * 32 + ".json")).write_text("{broken", "utf-8")
    d.write_pending_alerts(runs[0], [{"event_id": "p1"}, {"event_id": "p2"}])
    d.write_pending_alerts(runs[1], [{"event_id": "p3"}])
    d.record_termination("term", {"record_id": "term", "task_id": "t", "status": "pending_reconciliation"})
    (case.root / "observations" / "terminations" / "half.json").write_bytes(b'{"record_id": "half')
    (case.root / "observations" / "spool").mkdir(exist_ok=True)
    (case.root / "observations" / "spool" / (runs[0] + ".0000.jsonl")).write_bytes(b"x" * 1024)
    (case.root / "observations" / "spool" / (runs[0] + ".0001.jsonl")).write_bytes(b"y" * 100)
    if many:
        for index in range(60):
            d.write_health(f"{index:032x}", {"process_run_id": f"{index:032x}", "component": "many", "updated_at": NOW.isoformat(), "sink": "available",
                                              "counters": {}, "spool": {}, "pending_alerts": []})
            d.write_pending_alerts(f"{0x100 + index:032x}", [{"event_id": f"p{index}"}])
    return d


def helper_local_facts(api, case_factory):
    m = api.module
    out = {}
    case = case_factory()
    try:
        out["runtime_none"] = m.local_facts(None)
        out["root_missing"] = case.text(m.local_facts(case.root))
        (case.root / "observations").write_text("a file, not a directory", "utf-8")
        out["observations_is_a_file"] = case.text(m.local_facts(case.root))
        (case.root / "observations").unlink()
        (case.root / "observations").mkdir()
        out["empty_directory"] = case.text(m.local_facts(case.root))
        out["runtime_as_string"] = case.text(m.local_facts(str(case.root)))
        populate_runtime(case)
        before = case.tree()
        facts = m.local_facts(case.root)
        out["populated"] = case.text(facts)
        out["populated_read_only"] = case.tree() == before
        out["as_string_equal"] = m.local_facts(str(case.root)) == facts
        out["canary_leaked"] = CANARY in json.dumps(facts)
    finally:
        case.close()
    case = case_factory()
    try:
        (case.root / "observations").mkdir()
        populate_runtime(case, many=True)
        facts = m.local_facts(case.root)
        out["many"] = {"status": facts["status"], "health_len": len(facts["health"]), "health_total": facts["health_total"], "health_first": facts["health"][0],
                       "pending_alert_files_len": len(facts["pending_alert_files"]), "pending_alerts": facts["pending_alerts"],
                       "pending_terminations": facts["pending_terminations"], "unreadable_terminations": facts["unreadable_terminations"],
                       "segments": facts["segments"], "unacknowledged_bytes": facts["unacknowledged_bytes"]}
    finally:
        case.close()
    case = case_factory()
    try:
        (case.root / "observations").mkdir()
        original = api.spool_module.SpoolDirectory
        out["directory_failures"] = {}
        for name, exc in (("OSError", OSError("disk")), ("FileNotFoundError", FileNotFoundError("gone")), ("ValueError", ValueError("bad")),
                          ("RuntimeError", RuntimeError("other"))):
            class Failing(original):
                _exc = exc

                def spool_files(self):
                    raise self._exc
            api.spool_module.SpoolDirectory = Failing
            try:
                out["directory_failures"][name] = call(m.local_facts, case.root)
            finally:
                api.spool_module.SpoolDirectory = original
        for method in ("read_health", "pending_terminations", "read_pending_alerts", "unacknowledged_bytes"):
            class FailingLater(original):
                _method = method

                def __getattribute__(self, attr):
                    if attr == type(self)._method:
                        raise OSError("late " + attr)
                    return super().__getattribute__(attr)
            api.spool_module.SpoolDirectory = FailingLater
            try:
                out["directory_failures"]["late_" + method] = call(m.local_facts, case.root)
            finally:
                api.spool_module.SpoolDirectory = original
    finally:
        case.close()
    return out


def observed_at_normalized(facts):
    facts = dict(facts)
    moment = datetime.fromisoformat(facts["observed_at"])
    facts["observed_at"] = "<utc-iso>" if moment.utcoffset() == timedelta(0) else "<not-utc>"
    return facts


def facts_cases(api, case_factory):
    m = api.module
    out = {}
    store = api.MemoryStore()
    with store.transaction() as tx:
        tx.put("observations", "e1", event("e1", "operations", "info", record_kind="event", collected_at=NOW.isoformat()))
        tx.put("observations", "e2", event("e2", "development", "critical", record_kind="event", collected_at=NOW.isoformat()))
        tx.put("observations", "e3", event("e3", "general", "error", minutes=5, record_kind="event", collected_at=NOW.isoformat()))
        tx.put("observations", "e4", event("e4", "operations", "error", minutes=1, record_kind="event", collected_at=NOW.isoformat()))
        tx.put("observations", "e5", event("e5", "operations", "error", minutes=0, record_kind="event", collected_at=NOW.isoformat()))
        tx.put("observation_audit", "e1", event("e1", "operations", "info"))
        tx.put("observation_audit", "a1", event("a1", "general", "debug", minutes=9))
        tx.put("observation_audit", "bad", event("bad", "weird", "loud", observed_at="not-a-time"))
        tx.put("observation_audit", "naive", event("naive", "general", "warning", observed_at="2026-09-18T11:00:00"))
    before = copy.deepcopy(store.data)
    facts = m.observation_facts(store, None, NOW)
    out["priority_order"] = {"facts": facts, "store_unchanged": store.data == before, "canary_leaked": CANARY in json.dumps(facts)}
    out["positional_runtime_none"] = m.observation_facts(store, None, NOW) == m.observation_facts(store, now=NOW)

    store = api.MemoryStore()
    with store.transaction() as tx:
        tx.put("observation_collections", "c1", {"id": "c1", "file": "a.jsonl", "records": 3, "inserted": 2, "duplicates": 1, "at": (NOW - timedelta(seconds=90)).isoformat()})
        tx.put("observation_collections", "c0", {"id": "c0", "records": 1, "at": (NOW - timedelta(hours=1)).isoformat()})
        tx.put("observation_collections", "cx", {"id": "cx", "at": "garbage"})
        tx.put("observation_alerts", "al", {"event_id": "al", "notification": {"status": "pending"}})
        tx.put("observation_alerts", "al2", {"event_id": "al2", "notification": {"status": "recorded"}})
        tx.put("observation_alerts", "al3", {"event_id": "al3"})
        tx.put("observation_alerts", "al4", {"event_id": "al4", "notification": None})
        tx.put("observation_quarantine", "q", {"id": "q", "reason": "corrupt_record"})
        tx.put("observation_quarantine", "q2", {"id": "q2"})
        tx.put("observation_terminations", "t1", {"record_id": "t1", "status": "pending_reconciliation"})
        tx.put("observation_terminations", "t2", {"record_id": "t2", "status": "unconfirmed"})
        tx.put("observation_terminations", "t3", {"record_id": "t3", "status": "closed"})
        tx.put("observation_terminations", "t4", {"record_id": "t4"})
        tx.put("operations", "op", {"id": "op", "status": "failed", "reason_code": "evidence_gate_refused", "task_id": "task", "lead_accepted": None, "goal": {"criterion": "c"}})
        tx.put("operations", "op2", {"id": "op2", "goal": {"criterion": "token=" + CANARY + " <img onerror=x>"}})
        tx.put("tasks", "task", {"id": "task", "status": "succeeded"})
    facts = m.observation_facts(store, None, NOW)
    out["separate_buckets"] = {"facts": facts, "canary_leaked": CANARY in json.dumps(facts)}
    out["naive_now_with_receipts"] = call(m.observation_facts, store, None, datetime(2026, 9, 18, 12))
    out["empty_store"] = m.observation_facts(api.MemoryStore(), None, NOW)

    big = api.MemoryStore()
    with big.transaction() as tx:
        for index in range(m.BUCKET_LIMIT + 3):
            tx.put("observations", f"r{index:05d}", event(f"r{index:05d}", "general", "debug" if index % 7 else "error", record_kind="event"))
        for index in range(m.OPERATION_LIMIT + 5):
            tx.put("operations", f"op{index:04d}", {"id": f"op{index:04d}", "status": "running" if index % 2 else "failed", "goal": {"criterion": "c"}})
        for index in range(m.HIGH_LIMIT + 5):
            tx.put("observation_audit", f"h{index:04d}", event(f"h{index:04d}", "operations", "critical", minutes=index))
    facts = m.observation_facts(big, None, NOW)
    out["bounded_sample"] = {"sample": facts["sample"], "events": summarize({k: v for k, v in facts["events"].items()}), "operations": summarize(facts["operations"]),
                             "digest": canonical_digest(facts)}

    case = case_factory()
    try:
        (case.root / "observations").mkdir()
        populate_runtime(case)
        runtime = {"none": m.observation_facts(api.MemoryStore(), None, NOW)["local"], "missing_dir": m.observation_facts(api.MemoryStore(), case.root / "nowhere", NOW)["local"],
                   "populated": case.text(m.observation_facts(api.MemoryStore(), case.root, NOW)["local"]),
                   "populated_str": case.text(m.observation_facts(api.MemoryStore(), str(case.root), NOW)["local"])}
        out["runtime"] = runtime
    finally:
        case.close()

    default = m.observation_facts(api.MemoryStore())
    out["default_now"] = observed_at_normalized(default)

    class Broken:
        def transaction(self):
            raise RuntimeError("injected observation outage")
    out["store_failure"] = call(m.observation_facts, Broken(), None, NOW)

    class ReadsOnly:
        def __init__(self, inner):
            self.inner, self.writes = inner, 0

        def transaction(self):
            import contextlib

            @contextlib.contextmanager
            def guarded():
                with self.inner.transaction() as tx:
                    owner = self

                    class Tx:
                        def __getattr__(self, name):
                            if name in ("put", "put_node", "put_edge"):
                                owner.writes += 1
                            return getattr(tx, name)
                    yield Tx()
            return guarded()
    watched = ReadsOnly(store)
    m.observation_facts(watched, None, NOW)
    out["reads_only"] = watched.writes == 0
    return out


def run(api) -> dict:
    def factory():
        return Case(api)
    return {"text": helper_text(api), "parse_time": helper_parse_time(api), "scan_bounded": helper_scan_bounded(api), "project_event": helper_project_event(api),
            "merge_events": helper_merge_events(api), "collection_facts": helper_collection_facts(api), "project_operation": helper_project_operation(api),
            "local_facts": helper_local_facts(api, factory), "observation_facts": facts_cases(api, factory)}
