"""Shared S9 scenario steps (`observation.collectors_core`): M7 `adapters/monitoring.py` U6, the core collectors (the read-only wrappers, the database facts, the activity projection and `lane_view`).

Layer: harness (never shipped)

`api.module` is the side's collectors module (`CONTAINER_NAME`, `MAX_CONTAINERS`, `safe_text`, `ReadOnlyTransaction`, `ReadOnlyStore`, `ReadOnlyArtifacts`, `ReadOnlyService`,
`read_only`, `container_scope`, `parse_observed`, `persisted_measurements`, `DatabaseFacts`, `audit_progress`, the lane constants, the activity constants, `ArtifactReader`,
`project_receipt`, `execution_activity`, `lane_artifact_resolver`, `lane_view`, `scope_label`), `api.MemoryStore` and `api.FileArtifacts` the side's store and artifact classes,
`api.build_receipt`/`api.canonical` the side's compact-receipt builder and canonical JSON. Mirrors `tests/test_monitoring_activity.py`, the monitoring parts of
`tests/test_progress_activity.py` and the read-only wrapper, `persisted_measurements`, `container_scope`, `DatabaseFacts` and `audit_progress` tests of `tests/test_monitoring.py`:
MemoryStores and REAL temporary lane artifact files (`<runtime>/artifacts/<sha256>.txt`, including a symlink, a FIFO, a directory, a tampered and an oversized file), always with
a fixed `now` (the default-`now` calls are normalized, never masked).

Declared nondeterministic fields, normalized HERE and never by the mask list: the temporary root (`<root>`) and, for the two default-`now` calls, `age_seconds` (proven > 20 and
reported as a boolean). No clock, process, network, container or database.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
NOW_ISO = NOW.isoformat()
CANARY = "CANARY-collectors-core-9d8c7b6a5f4e3d2c1b0a"
ZERO = "sha256:" + "0" * 64
SEP = ":" + "//"  # built, never written as a literal URL: the tree check refuses credential-shaped strings


def norm(value):
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


def call(fn, *args, **kwargs):
    try:
        return {"value": norm(fn(*args, **kwargs))}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def summarize(value, keep=3):
    if isinstance(value, dict):
        return {k: summarize(v, keep) for k, v in value.items()}
    if isinstance(value, list) and len(value) > 2 * keep:
        return {"len": len(value), "digest": digest(value), "first": value[:keep], "last": value[-keep:]}
    return value


class Case:
    def __init__(self, prefix="s9-collectors-core-"):
        self.root = Path(tempfile.mkdtemp(prefix=prefix)).resolve()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def text(self, value):
        return json.loads(json.dumps(value, default=str).replace(str(self.root), "<root>"))

    def tree(self):
        return sorted((p.relative_to(self.root).as_posix(), p.stat().st_size if p.is_file() else None) for p in self.root.rglob("*"))


def store_text(root, body) -> str:
    """One artifact exactly as FileArtifacts names it (sha256 of the bytes); returns its reference."""
    data = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(data).hexdigest()
    (root / (key + ".txt")).write_bytes(data)
    return "sha256:" + key


def envelope(event, malformed=False, defect=None, previous=None):
    return {"event": event, "malformed": malformed, "defect": defect, "previous": previous}


def claude(kind, status=None, tool=None, **extra):
    return {"provider": "claude-code-cli", "stream": "stdout", "type": kind, "raw_type": "assistant", "subtype": CANARY, "id": "toolu_" + CANARY, "status": status,
            "sequence": 41, "tool": tool, "text": CANARY, "defect": CANARY,
            "raw": {"message": {"content": [{"type": "tool_use", "input": {"command": "cat " + CANARY}, "thinking": CANARY}]}}, **extra}


def codex(method, item=None, **extra):
    return {"jsonrpc": "2.0", "method": method, "id": CANARY,
            "params": {"threadId": CANARY, "turnId": CANARY, "item": item, "completedAtMs": 1790550000000, "tokenUsage": {"secret": CANARY}}, **extra}


class Spy:
    """Records every requested ref; reads go to a real ArtifactReader."""

    def __init__(self, api, root):
        self.inner, self.calls = api.module.ArtifactReader(root), []

    def read(self, reference):
        self.calls.append(reference)
        return self.inner.read(reference)


def row(status="running", generation=2, attempt=1, completed_at=None):
    return {"id": "task-1", "status": status, "generation": generation, "attempt": attempt, "completed_at": completed_at}


def progress(recent, last=None, generation=2, attempt=1, sequence=7, collected="2026-09-28T00:59:30+00:00", **extra):
    return {"id": "task-1", "recent": recent, "last_record": last if last is not None else (recent[-1] if recent else None), "generation": generation, "attempt": attempt,
            "sequence": sequence, "collected_at": collected, **extra}


def compact_progress(ring, sequence=3, watermark=3, **extra):
    return {"id": "task-1", "recent": [ZERO[:7] + "e" * 64], "last_record": ZERO[:7] + "e" * 64, "generation": 2, "attempt": 1, "sequence": sequence, "collected_at": NOW_ISO,
            "activity_recent": ring, "activity_sequence": len(ring), "activity_progress_sequence": watermark, **extra}


# ----- read-only wrappers, safe_text, container_scope, parse_observed ---------------------------------------------------------------------
class RecordingTransaction:
    def __init__(self):
        self.calls = []

    def get(self, bucket, key):
        self.calls.append(("get", bucket, key))
        return {"got": [bucket, key]}

    def scan(self, bucket):
        self.calls.append(("scan", bucket))
        return [{"scanned": bucket}]

    def entries(self, bucket, after="", limit=100):
        self.calls.append(("entries", bucket, after, limit))
        return [{"entries": [bucket, after, limit]}]

    def records(self):
        self.calls.append(("records",))
        return [{"records": True}]

    def put(self, *args, **kwargs):
        self.calls.append(("put", args))

    def graph(self):
        self.calls.append(("graph",))


class RecordingArtifacts:
    def __init__(self):
        self.calls = []

    def put(self, *args, **kwargs):
        self.calls.append(("put", args))

    def _body(self, reference, max_bytes=None):
        self.calls.append(("_body", reference, max_bytes))
        return "body"

    def document(self, reference):
        self.calls.append(("document", reference))
        return {"document": reference}

    def text(self, reference, max_bytes):
        self.calls.append(("text", reference, max_bytes))
        return "text"

    def read(self, reference, start=0, length=8000):
        self.calls.append(("read", reference, start, length))
        return "read"

    def inspect(self, reference):
        self.calls.append(("inspect", reference))
        return {"inspect": reference}

    def search(self, reference, needle, limit=20):
        self.calls.append(("search", reference, needle, limit))
        return [{"search": [reference, needle, limit]}]


def refused_in_transaction(store, action):
    try:
        with store.transaction() as tx:
            action(tx)
    except Exception as exc:
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}
    return {"value": "not refused"}


def read_only_cases(api):
    m = api.module
    out = {}
    store = api.MemoryStore()
    with store.transaction() as tx:
        tx.put("tasks", "one", {"id": "one", "status": "queued"})
        tx.put("tasks", "two", {"id": "two", "status": "running"})
        tx.put("other", "k", {"id": "k"})
    before = copy.deepcopy(store.data)
    ro = m.ReadOnlyStore(store)
    reads = {}
    with ro.transaction() as tx:
        reads["type"] = type(tx).__name__
        reads["get"] = tx.get("tasks", "one")
        reads["get_missing"] = tx.get("tasks", "none")
        reads["scan"] = tx.scan("tasks")
        reads["scan_missing"] = tx.scan("none")
        reads["entries"] = tx.entries("tasks")
        reads["entries_after"] = tx.entries("tasks", "one", 5)
        reads["entries_keywords"] = tx.entries("tasks", after="", limit=1)
        reads["records"] = tx.records()
        reads["put_refused"] = call(tx.put, "tasks", "x", {"id": "x"})
        reads["put_keywords_refused"] = call(tx.put, bucket="tasks", key="x", body={})
        reads["put_no_args_refused"] = call(tx.put)
        reads["graph_refused"] = call(tx.graph)
        reads["put_node_unreachable"] = call(lambda: tx.put_node)
        reads["put_edge_unreachable"] = call(lambda: tx.put_edge)
        reads["underlying_unreachable"] = [call(lambda name=name: getattr(tx, name)) for name in ("delete", "commit", "execute", "conn")]
        reads["private_view"] = call(lambda: type(tx._transaction).__name__)
    out["transaction_reads"] = reads
    out["write_inside_with"] = refused_in_transaction(ro, lambda tx: tx.put("tasks", "x", {"id": "x"}))
    out["graph_inside_with"] = refused_in_transaction(ro, lambda tx: tx.graph())
    out["put_after_reads"] = refused_in_transaction(ro, lambda tx: (tx.scan("tasks"), tx.put("tasks", "y", {"id": "y"})))
    out["store_unchanged"] = store.data == before
    with store.transaction() as tx:
        tx.put("tasks", "three", {"id": "three"})
    with store.transaction() as tx:
        out["store_still_writable_directly"] = any(r["id"] == "three" for r in tx.scan("tasks"))

    recorded = RecordingTransaction()

    class Wrapped:
        def __init__(self, inner):
            self.inner = inner

        def transaction(self):
            import contextlib

            @contextlib.contextmanager
            def cm():
                yield self.inner
            return cm()
    with m.ReadOnlyStore(Wrapped(recorded)).transaction() as tx:
        tx.get("b", "k")
        tx.scan("b")
        tx.entries("b")
        tx.entries("b", "a", 7)
        tx.records()
        call(tx.put, 1, 2, three=3)
        call(tx.graph)
    out["delegation_calls"] = recorded.calls

    artifacts = RecordingArtifacts()
    ra = m.ReadOnlyArtifacts(artifacts)
    shapes = {"put": call(ra.put, "body", "monitor"), "put_keywords": call(ra.put, body="b", source="s"), "_body": call(ra._body, "ref"), "_body_max": call(ra._body, "ref", 5),
              "document": call(ra.document, "ref"), "text": call(ra.text, "ref", 10), "read": call(ra.read, "ref"), "read_args": call(ra.read, "ref", 3, 4),
              "inspect": call(ra.inspect, "ref"), "search": call(ra.search, "ref", "needle"), "search_limit": call(ra.search, "ref", "needle", 2),
              "unreachable": [call(lambda name=name: getattr(ra, name)) for name in ("delete", "write", "remove", "root")]}
    out["artifact_reader"] = {"results": shapes, "calls": artifacts.calls}

    case = Case()
    try:
        files = api.FileArtifacts(str(case.root / "artifacts"))
        reader = m.ReadOnlyArtifacts(files)
        before_tree = case.tree()
        out["real_artifacts_put_refused"] = {"put": call(reader.put, "body", "monitor"), "tree_unchanged": case.tree() == before_tree,
                                             "root_entries": sorted(p.name for p in (case.root / "artifacts").iterdir()) if (case.root / "artifacts").exists() else None}
    finally:
        case.close()

    service = SimpleNamespace(store=store, org="ORG", extra="dropped")
    ros = m.ReadOnlyService(service)
    with ros.store.transaction() as tx:
        scanned = [r["id"] for r in tx.scan("tasks")]
    out["service"] = {"org": ros.org, "store_type": type(ros.store).__name__, "extra_dropped": call(lambda: ros.extra), "scan": scanned}
    pair = m.read_only(service, artifacts)
    out["read_only"] = {"types": [type(p).__name__ for p in pair], "len": len(pair), "org": pair[0].org,
                        "artifact_put_refused": call(pair[1].put, "x"),
                        "store_put_refused": refused_in_transaction(pair[0].store, lambda tx: tx.put("a", "b", {}))}
    out["no_service_attrs"] = call(m.ReadOnlyService, SimpleNamespace(store=store))
    return out


def helper_safe_text(api):
    m = api.module
    values = [None, 0, False, "", "plain", 5, 5.5, [1], {"a": 1}, b"bytes", "x" * 1300, "한글 라벨 " + "가" * 50,
              "postgresql" + SEP + "admin:secret@localhost/db", "https" + SEP + "user:pw@host.example/path", "redis" + SEP + ":pw@h", "scheme" + SEP + "onlyuser@host",
              "a" + SEP + "b:c@d e" + SEP + "f:g@h",
              "Bearer abc.def", "bearer lower", "Authorization: Bearer " + CANARY, "token=" + CANARY, "TOKEN: " + CANARY, "api_key = " + CANARY, "API-KEY:" + CANARY,
              "apikey=" + CANARY, "password: hunter2 trailing", "PASSWORD=x token=y", "mixed postgresql" + SEP + "a:b@c Bearer d token=e", "token=", "password", "no secret here"]
    out = {"default_limit": [call(m.safe_text, v) for v in values], "limit_20": [call(m.safe_text, v, 20) for v in values[10:16] + values[17:22]],
           "limit_zero": call(m.safe_text, "abc", 0), "limit_negative": call(m.safe_text, "abcdef", -2), "limit_none": call(m.safe_text, "abc", None),
           "limit_float": call(m.safe_text, "abc", 2.0), "redaction_before_truncation": call(m.safe_text, "a" * 1195 + "token=" + CANARY),
           "redaction_before_truncation_20": call(m.safe_text, "x" * 10 + "password=" + CANARY, 20), "multiline": call(m.safe_text, "a\ntoken=" + CANARY + "\nb")}
    out["canary_leaked"] = any(CANARY in json.dumps(v) for v in out.values() if isinstance(v, (dict, list)))
    out["constants"] = {"CONTAINER_NAME": m.CONTAINER_NAME.pattern, "MAX_CONTAINERS": m.MAX_CONTAINERS}
    return out


def helper_container_scope(api):
    m = api.module
    values = [None, "", "  ", "\n", "[", "{}", "[]", "null", "5", '"abc"', "true", '["a", "a"]', '["-x"]', '["_x"]', '["x-"]', "[1]", '["a b"]', '["a/b"]', '["a"] ', '["a"]\n',
              '["zeus-local-ops-redis", "zeus_pg.1"]', json.dumps(["c%d" % i for i in range(32)]), json.dumps(["c%d" % i for i in range(33)]), '["' + "a" * 128 + '"]',
              '["' + "a" * 129 + '"]', '[null]', '[["a"]]', '["a", 1]', '["A", "a"]', '["한글"]', 5, [], b'["bytes"]', ["a"]]
    return {"values": [{"input": repr(v)[:60], "result": call(m.container_scope, v)} for v in values],
            "returns_a_new_list": call(lambda: (lambda r: r is not json.loads('["a"]') and r == ["a"])(m.container_scope('["a"]'))),
            "fullmatch_samples": [bool(m.CONTAINER_NAME.fullmatch(s)) for s in ("a", "a-b", "a.b_c", "-a", "a b", "", "a" * 128, "a" * 129, "a\n")]}


def helper_parse_observed(api):
    m = api.module
    values = ["2026-09-18T12:00:00+00:00", "2026-09-18T12:00:00Z", "2026-09-18T21:00:00+09:00", "2026-09-18T12:00:00.123456+00:00", "2026-09-18T12:00:00", "2026-09-18",
              "20260918T120000+0000", "not-a-time", "", None, 5, 5.5, ["x"], {}, True, b"2026-09-18T12:00:00+00:00", " 2026-09-18T12:00:00+00:00"]
    out = []
    for v in values:
        r = call(m.parse_observed, v)
        out.append({"input": repr(v), "result": r["value"] if "value" in r else r,
                    "utcoffset": (datetime.fromisoformat(r["value"]).utcoffset().total_seconds() if r.get("value") else None)})
    return out


# ----- persisted_measurements, audit_progress, DatabaseFacts ---------------------------------------------------------------------------------
def observation(metric_id, observed_at, value=1, **extra):
    return {"id": f"{metric_id}-{observed_at}", "metric_id": metric_id, "value": value, "status": "pass", "reason": "fixture", "observed_at": observed_at,
            "window_start": observed_at, "window_end": observed_at, "evidence_refs": ["sha256:" + "a" * 64], "definition": {"metric_id": metric_id}, **extra}


def persisted_cases(api):
    m = api.module
    now = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
    out = {}
    store = api.MemoryStore()
    out["empty"] = call(m.persisted_measurements, store, now)
    with store.transaction() as tx:
        tx.put("metric_observations", "a", observation("m", (now - timedelta(hours=2)).isoformat(), 1))
        tx.put("metric_observations", "b", observation("m", (now - timedelta(hours=1)).isoformat(), 2))
        tx.put("metric_observations", "c", observation("m", "2026-09-18T11:59:00", 3))  # naive: ignored
        tx.put("metric_observations", "d", observation("m", "not-a-time", 4))
        tx.put("metric_observations", "e", observation("", now.isoformat(), 5))
        tx.put("metric_observations", "f", observation("n", (now - timedelta(seconds=30)).isoformat(), 6))
        tx.put("metric_observations", "g", observation(7, now.isoformat(), 7))
        tx.put("metric_observations", "h", observation("tz", "2026-09-18T20:00:00+09:00", 8, source="forged"))
        tx.put("metric_observations", "i", observation("tie", (now - timedelta(minutes=5)).isoformat(), "first"))
        tx.put("metric_observations", "j", observation("tie", (now - timedelta(minutes=5)).isoformat(), "second"))
        tx.put("metric_observations", "k", {"metric_id": "bare", "observed_at": now.isoformat()})
        tx.put("metric_observations", "l", {"observed_at": now.isoformat()})
        tx.put("metric_observations", "m", observation("future", (now + timedelta(minutes=1)).isoformat(), 9))
    before = copy.deepcopy(store.data)
    out["latest_per_metric"] = call(m.persisted_measurements, store, now)
    out["store_unchanged"] = store.data == before
    out["positional_now_equals_keyword"] = m.persisted_measurements(store, now) == m.persisted_measurements(store, now=now)
    out["naive_now"] = call(m.persisted_measurements, store, datetime(2026, 9, 18, 12))
    out["read_only_store"] = call(m.persisted_measurements, m.ReadOnlyStore(store), now)
    default = m.persisted_measurements(store)
    out["default_now"] = {"metric_ids": [r["metric_id"] for r in default], "ages_over_20": [r["age_seconds"] > 20 for r in default if r["metric_id"] != "future"],
                          "future_age_negative": [r["age_seconds"] < 0 for r in default if r["metric_id"] == "future"]}

    class Broken:
        def transaction(self):
            raise RuntimeError("injected store outage")
    out["store_failure"] = call(m.persisted_measurements, Broken(), now)
    return out


def audit_cases(api):
    m = api.module
    out = {}
    data = {"reference_audits": [{"id": "legacy", "repository": "repo", "revision": "rev", "files": 2, "status": "inventoried_not_reviewed"}],
            "research_audits": [{"id": "audit", "source": {"repository": "repo", "commit": "rev", "manifest_ref": "manifest"}, "inventory": ["a", "b"],
                                 "status": "source_verified_not_reviewed"}]}
    out["no_partitions"] = call(m.audit_progress, copy.deepcopy(data), {})
    data["research_partitions"] = [{"audit_id": "audit", "remaining_paths": ["a"], "remaining_subsystems": ["storage"], "open_questions": ["test not run"]}]
    out["paused"] = call(m.audit_progress, copy.deepcopy(data), {"status": "paused"})
    out["inactive_default"] = call(m.audit_progress, copy.deepcopy(data), {})
    out["control_none_status"] = call(m.audit_progress, copy.deepcopy(data), {"status": None})
    out["control_none"] = call(m.audit_progress, copy.deepcopy(data), None)
    out["empty_data"] = call(m.audit_progress, {}, {})
    out["only_reference"] = call(m.audit_progress, {"reference_audits": [{"repository": "r", "revision": "v", "id": "x", "extra": "dropped", "review_ref": "rr",
                                                                         "independent_review": True, "semantically_reviewed_files": 3}]}, {})
    multi = {"reference_audits": [], "research_audits": [
        {"id": "a1", "source": {"repository": "r1", "commit": "c1", "manifest_ref": "m1"}, "inventory": ["x"] * 3, "status": "s1"},
        {"id": "a2", "source": {"repository": "r2", "commit": "c2", "manifest_ref": "m2"}, "inventory": [], "status": "s2"},
        {"id": "a3", "source": {"repository": "r1", "commit": "c1", "manifest_ref": "m3"}, "inventory": ["y"], "status": "s3"}],
        "research_partitions": [
            {"audit_id": "a1", "remaining_paths": ["p1", "p2"], "remaining_subsystems": ["s1"], "open_questions": ["q1", "q2"]},
            {"audit_id": "a1", "remaining_paths": ["p2", "p3"], "remaining_subsystems": ["s1", "s2"], "open_questions": ["q3"]},
            {"audit_id": "a2", "remaining_paths": [], "remaining_subsystems": [], "open_questions": []},
            {"audit_id": "other", "remaining_paths": ["z"], "remaining_subsystems": ["z"], "open_questions": ["z"]}]}
    out["multi"] = call(m.audit_progress, copy.deepcopy(multi), {"status": "active"})
    out["same_key_merge"] = call(m.audit_progress, {"reference_audits": [{"id": "legacy", "repository": "r1", "revision": "c1", "status": "legacy-status", "files": 9}],
                                                    "research_audits": multi["research_audits"][:1] + multi["research_audits"][2:]}, {})
    out["missing_repository"] = call(m.audit_progress, {"reference_audits": [{"revision": "v"}]}, {})
    out["missing_source"] = call(m.audit_progress, {"research_audits": [{"id": "x", "inventory": []}]}, {})
    out["missing_partition_field"] = call(m.audit_progress, {"research_audits": multi["research_audits"][:1], "research_partitions": [{"audit_id": "a1"}]}, {})
    out["control_not_a_mapping"] = call(m.audit_progress, copy.deepcopy(data), "paused")
    out["input_unchanged"] = (lambda d: (m.audit_progress(d, {}), d == data)[1])(copy.deepcopy(data))
    return out


@dataclass
class Agent:
    id: str
    role: str
    capabilities: tuple = ()


def facts_store(api, many_events=True):
    store = api.MemoryStore()
    plan = {"objective": "Improve the monitor token=" + CANARY + " " + "x" * 1300}
    with store.transaction() as tx:
        tx.put("tasks", "t1", {"id": "t1", "agent": "implementer", "status": "running", "attempt": 2, "lease_until": "2026-09-28T01:00:00+00:00",
                               "created_at": "2026-09-28T00:00:00+00:00", "completed_at": None, "error": "password=" + CANARY + " boom",
                               "message": {"correlation_id": "corr-1", "causation_id": "parent-1", "when": {"created_at": "2026-09-27T23:00:00+00:00"},
                                           "what": {"action": "implement", "details": {"plan": plan}}},
                               "result": {"summary": "ignored summary", "release_id": "rel-1", "reason": "token=" + CANARY, "accepted": True, "execution_ref": "sha256:" + "d" * 64,
                                          "candidate": {"revision": "abc123"}}})
        tx.put("tasks", "t2", {"id": "t2", "status": "queued", "agent": "reviewer"})
        tx.put("tasks", "t3", {"id": "t3", "status": "failed", "message": {"what": {"details": {"objective": "details only"}}}, "result": {"summary": "from result"},
                               "phase": "explicit-phase", "created_at": "2026-09-28T00:10:00+00:00"})
        tx.put("decisions_pending", "d1", {"id": "d1", "actor": "review_lead", "status": "blocked", "result": {"reason": "Cannot inspect candidate", "accepted": False},
                                           "message": {"what": {"action": "review"}}})
        tx.put("sessions", "s1", {"agent_id": "implementer", "session_id": "sess-1", "generation": 3,
                                  "checkpoint": {"thread_id": "th", "next_action": "continue with token=" + CANARY, "handoff_reason": "context", "evidence_ref": "sha256:" + "c" * 64,
                                                 "usage": {"modelContextWindow": 1000, "last": {"totalTokens": 250}}}})
        tx.put("sessions", "s2", {"agent_id": "reviewer", "session_id": "sess-2", "checkpoint": {"usage": {"last": {"totalTokens": 5}}}})
        tx.put("execution_progress", "t1", {"id": "t1", "agent": "implementer", "at": "2026-09-28T00:30:00+00:00", "context_ref": "sha256:" + "1" * 64,
                                            "recent": ["sha256:" + "2" * 64, "sha256:" + "3" * 64, "sha256:" + "4" * 64, "sha256:" + "5" * 64]})
        tx.put("execution_progress", "t0", {"id": "t0", "agent": "implementer", "at": "2026-09-28T00:10:00+00:00", "recent": ["sha256:" + "6" * 64]})
        tx.put("execution_progress", "t9", {"id": "t9", "agent": "reviewer", "at": "2026-09-28T00:40:00+00:00", "recent": ["sha256:" + "7" * 64]})
        tx.put("hooks", "h1", {"id": "h1", "status": "open", "root_cause": "fixture-cause", "scope": "repo", "revision": "r", "version": 2, "occurrences": [1, 2, 3], "secret": CANARY})
        tx.put("hooks", "h2", {"id": "h2", "status": "closed", "root_cause": "real"})
        tx.put("releases", "rel-1", {"id": "rel-1", "status": "accepted", "candidate": {"revision": "abc123", "branch": "b"}, "created_at": "2026-09-28T00:20:00+00:00",
                                     "reviews": [{"actor": "lead", "accepted": True, "evidence": "e", "note": CANARY}], "checks": {"cli": {"passed": True, "evidence": "ev", "out": CANARY}}})
        tx.put("releases", "rel-2", {"id": "rel-2", "status": "rejected"})
        if many_events:
            for index in range(70):
                tx.put("events", f"e{index:03d}", {"type": "tick", "at": f"2026-09-28T00:{index // 2:02d}:{(index % 2) * 30:02d}+00:00", "task_id": f"t{index}", "hook_id": None,
                                                   "release_id": None, "payload": CANARY})
        else:
            tx.put("events", "e1", {"type": "tick", "at": "2026-09-28T00:00:00+00:00"})
        tx.put("reference_audits", "ra", {"id": "ra", "repository": "repo", "revision": "rev", "status": "inventoried_not_reviewed", "files": 2})
        tx.put("research_audits", "ar", {"id": "ar", "source": {"repository": "repo2", "commit": "c2", "manifest_ref": "m"}, "inventory": ["a"], "status": "source_verified_not_reviewed"})
        tx.put("research_partitions", "rp", {"audit_id": "ar", "remaining_paths": ["a"], "remaining_subsystems": ["s"], "open_questions": ["q"]})
        tx.put("deployment", "active", {"release_id": "rel-1", "revision": "abc123", "at": "2026-09-28T00:25:00+00:00", "extra": CANARY})
        tx.put("health", "latest", {"status": "healthy", "checked_at": "2026-09-28T00:59:00+00:00", "extra": CANARY})
        tx.put("research_control", "activation", {"status": "paused"})
        tx.put("health", "outbox", {"last": "batch", "count": 3})
        for index, status in enumerate(("pending", "delivered", "pending", "failed")):
            tx.put("outbox_delivery", f"o{index}", {"id": f"o{index}", "status": status})
    return store


class FakeArtifacts:
    """`_body(reference)` answers from a mapping; a missing reference is an OSError, like the real reader."""

    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def _body(self, reference, max_bytes=None):
        self.calls.append(reference)
        value = self.bodies.get(reference, OSError("missing artifact"))
        if isinstance(value, Exception):
            raise value
        return value


def usage_body(window, total, wrapped=True):
    event = {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"modelContextWindow": window, "last": {"totalTokens": total}}}}
    return json.dumps({"event": event} if wrapped else event)


def database_cases(api):
    m = api.module
    out = {}
    org = SimpleNamespace(agents={"implementer": Agent("implementer", "worker", ("code", "test")), "reviewer": Agent("reviewer", "review"), "idle": Agent("idle", "none")})

    def facts(store, bodies, organization=org, wrap=True):
        artifacts = FakeArtifacts(bodies)
        service = SimpleNamespace(store=store, org=organization)
        if wrap:
            service, reader = m.read_only(service, artifacts)
        else:
            reader = artifacts
        return m.DatabaseFacts(service, reader).read(), artifacts

    store = facts_store(api)
    before = copy.deepcopy(store.data)
    bodies = {"sha256:" + "1" * 64: json.dumps({"estimated_tokens": 4321, "secret": CANARY}),
              "sha256:" + "2" * 64: usage_body(2000, 500),
              "sha256:" + "3" * 64: "not json",
              "sha256:" + "4" * 64: json.dumps({"method": "other", "params": {}}),
              "sha256:" + "5" * 64: usage_body(1000, 100, wrapped=False),
              "sha256:" + "7" * 64: json.dumps({"event": {"method": "thread/tokenUsage/updated"}})}
    result, artifacts = facts(store, bodies)
    out["full"] = {"facts": summarize({k: v for k, v in result.items()}), "digest": digest(result), "events_len": len(result["events"]), "artifact_calls": artifacts.calls,
                   "canary_leaked": CANARY in json.dumps(result), "store_unchanged": store.data == before}
    out["full_events"] = {"first": result["events"][0], "last": result["events"][-1], "sorted_descending": [e["at"] for e in result["events"]] == sorted([e["at"] for e in result["events"]],
                                                                                                                                                   reverse=True)}
    result_unwrapped, _ = facts(store, bodies, wrap=False)
    out["unwrapped_equals_wrapped"] = result_unwrapped == result
    out["agents_sessions"] = {a["id"]: a["session"] for a in result["agents"]}
    out["tasks"] = result["tasks"]
    out["decisions"] = result["decisions"]
    out["wrapper_blocks_writes"] = refused_in_transaction(m.ReadOnlyStore(store), lambda tx: tx.put("tasks", "x", {"id": "x"}))

    empty, _ = facts(api.MemoryStore(), {}, organization=SimpleNamespace(agents={}))
    out["empty_store_no_agents"] = empty
    empty_agents, _ = facts(api.MemoryStore(), {}, organization=org)
    out["empty_store_with_agents"] = empty_agents

    only_recent = api.MemoryStore()
    with only_recent.transaction() as tx:
        tx.put("sessions", "s1", {"agent_id": "implementer", "session_id": "x", "checkpoint": {"usage": {"modelContextWindow": 10, "last": {"totalTokens": 5}}}})
        tx.put("execution_progress", "p", {"id": "p", "agent": "implementer", "at": "2026-09-28T00:00:00+00:00",
                                           "recent": ["sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64]})
    cases = {"newest_wins": {"sha256:" + "a" * 64: usage_body(1, 1), "sha256:" + "b" * 64: usage_body(20, 10), "sha256:" + "c" * 64: json.dumps({"x": 1})},
             "checkpoint_when_no_recent_usage": {"sha256:" + "a" * 64: "bad", "sha256:" + "b" * 64: "bad", "sha256:" + "c" * 64: "bad"},
             "key_error_skipped": {"sha256:" + "a" * 64: usage_body(1, 1), "sha256:" + "b" * 64: json.dumps({"method": "thread/tokenUsage/updated", "params": {}}),
                                   "sha256:" + "c" * 64: json.dumps({"x": 1})},
             "all_missing": {}, "zero_capacity": {"sha256:" + "c" * 64: usage_body(0, 5)}, "null_total": {"sha256:" + "c" * 64: usage_body(100, None)}}
    out["usage_sources"] = {name: facts(only_recent, bodies_, organization=SimpleNamespace(agents={"implementer": Agent("implementer", "w")}))[0]["agents"][0]["session"]
                            for name, bodies_ in cases.items()}

    def refusal(label, mutate, bodies_=None):
        s = api.MemoryStore()
        with s.transaction() as tx:
            mutate(tx)
        return call(lambda: facts(s, bodies_ or {}, organization=SimpleNamespace(agents={"implementer": Agent("implementer", "w")}))[0])
    out["refusals"] = {
        "task_without_id": refusal("t", lambda tx: tx.put("tasks", "x", {"status": "queued"})),
        "task_without_status": refusal("t", lambda tx: tx.put("tasks", "x", {"id": "x"})),
        "release_without_status": refusal("r", lambda tx: tx.put("releases", "x", {"id": "x"})),
        "outbox_without_status": refusal("o", lambda tx: tx.put("outbox_delivery", "x", {"id": "x"})),
        "audit_without_repository": refusal("a", lambda tx: tx.put("reference_audits", "x", {"revision": "v"})),
        "progress_without_id": refusal("p", lambda tx: tx.put("execution_progress", "x", {"agent": "implementer"})),
        "session_without_agent": refusal("s", lambda tx: tx.put("sessions", "x", {"session_id": "s"})),
        "recent_body_a_list": refusal("p", lambda tx: tx.put("execution_progress", "x", {"id": "x", "agent": "implementer", "recent": ["sha256:" + "a" * 64]}),
                                      {"sha256:" + "a" * 64: "[1]"}),
        "context_body_a_list": refusal("p", lambda tx: tx.put("execution_progress", "x", {"id": "x", "agent": "implementer", "context_ref": "sha256:" + "a" * 64}),
                                       {"sha256:" + "a" * 64: "[1]"}),
        "event_without_at": refusal("e", lambda tx: tx.put("events", "x", {"type": "t"})),
        "artifact_runtime_error": refusal("p", lambda tx: tx.put("execution_progress", "x", {"id": "x", "agent": "implementer", "recent": ["sha256:" + "a" * 64]}),
                                          {"sha256:" + "a" * 64: RuntimeError("boom")}),
    }

    class Broken:
        def transaction(self):
            raise RuntimeError("injected store outage")
    out["store_failure"] = call(lambda: m.DatabaseFacts(SimpleNamespace(store=Broken(), org=org), FakeArtifacts({})).read())
    out["constructor_attrs"] = (lambda d: [type(d.service).__name__, type(d.artifacts).__name__])(m.DatabaseFacts(SimpleNamespace(store=store, org=org), FakeArtifacts({})))
    return out


# ----- ArtifactReader, project_receipt, execution_activity -------------------------------------------------------------------------------------
def reader_cases(api):
    m = api.module
    out = {"constants": {"ACTIVITY_REFS": m.ACTIVITY_REFS, "ACTIVITY_BODY_BYTES": m.ACTIVITY_BODY_BYTES, "RECENT_TERMINAL_SECONDS": m.RECENT_TERMINAL_SECONDS,
                         "ARTIFACT_REF": m.ARTIFACT_REF.pattern, "CLAUDE_LABELS": sorted(m.CLAUDE_LABELS), "CODEX_LABELS": m.CODEX_LABELS, "PLAIN_STATUSES": sorted(m.PLAIN_STATUSES),
                         "ENVELOPE_KEYS": sorted(m.ENVELOPE_KEYS), "TERMINAL_EXECUTION": sorted(m.TERMINAL_EXECUTION), "ACTIVE_EXECUTION": sorted(m.ACTIVE_EXECUTION),
                         "COMPACT_ONLY": m.COMPACT_ONLY, "LANE_SESSIONS_SCHEMA": m.LANE_SESSIONS_SCHEMA, "LANE_SESSION_LIMIT": m.LANE_SESSION_LIMIT, "UNINSTRUMENTED": m.UNINSTRUMENTED}}
    case = Case()
    try:
        root = case.root / "artifacts"
        good = store_text(root, envelope(claude("tool_completed", "completed")))
        unicode_ref = store_text(root, "한글 본문 \u2603")
        empty_ref = store_text(root, "")
        tampered = store_text(root, envelope(claude("result", "success")))
        (root / (tampered[7:] + ".txt")).write_bytes(b'{"tampered": true}')
        bad_utf8 = b"\xff\xfe"
        key = hashlib.sha256(bad_utf8).hexdigest()
        (root / (key + ".txt")).write_bytes(bad_utf8)
        base = json.dumps(envelope(claude("tool_completed", "completed")))
        fits = base[:-1] + ', "pad": "' + "x" * (m.ACTIVITY_BODY_BYTES - len(base) - 11) + '"}'
        assert len(fits.encode()) == m.ACTIVITY_BODY_BYTES
        exact = store_text(root, fits)
        over = store_text(root, fits[:-2] + 'x"}')
        huge = store_text(root, "y" * (m.ACTIVITY_BODY_BYTES * 3))
        outside = store_text(case.root / "outside", envelope(claude("tool_completed", "completed", marker="outside")))
        (root / (outside[7:] + ".txt")).symlink_to(case.root / "outside" / (outside[7:] + ".txt"))
        dangling = "sha256:" + "d" * 64
        (root / ("d" * 64 + ".txt")).symlink_to(case.root / "nowhere")
        directory = "sha256:" + "c" * 64
        (root / ("c" * 64 + ".txt")).mkdir()
        fifo = "sha256:" + "e" * 64
        os.mkfifo(root / ("e" * 64 + ".txt"))
        before = case.tree()
        reader = m.ArtifactReader(root)
        refs = {"good": good, "unicode": unicode_ref, "empty_body": empty_ref, "tampered": tampered, "bad_utf8": "sha256:" + key, "exact_limit": exact, "one_over": over,
                "huge": huge, "symlink_to_outside": outside, "dangling_symlink": dangling, "directory": directory, "fifo": fifo, "missing": "sha256:" + "f" * 64,
                "none": None, "int": 5, "list": ["x"], "empty_string": "", "no_prefix": "a" * 64, "upper_hex": "sha256:" + "A" * 64, "short": "sha256:" + "a" * 63,
                "long": "sha256:" + "a" * 65, "newline_tail": "sha256:" + "a" * 64 + "\n", "path_escape": "sha256:../../etc/passwd", "bytes": b"sha256:" + b"a" * 64}
        def read_bounded(ref):
            state, code, text = reader.read(ref)
            return [state, code, text if text is None or len(text) <= 200 else {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()}]
        out["reads"] = {name: call(read_bounded, ref) for name, ref in refs.items()}
        out["available"] = reader.available()
        out["tree_unchanged"] = case.tree() == before
        out["root_is_a_path"] = type(reader.root).__name__
        out["string_root_equal"] = m.ArtifactReader(str(root)).read(good) == reader.read(good)
        missing_root = m.ArtifactReader(case.root / "never-created")
        out["missing_root"] = {"available": missing_root.available(), "read": list(missing_root.read(good)), "invalid_first": list(missing_root.read(None)),
                               "created": (case.root / "never-created").exists()}
        (case.root / "file-root").write_text("a file", "utf-8")
        out["file_root"] = {"available": m.ArtifactReader(case.root / "file-root").available(), "read": list(m.ArtifactReader(case.root / "file-root").read(good))}
        (case.root / "link-root").symlink_to(root)
        out["symlink_root"] = {"available": m.ArtifactReader(case.root / "link-root").available(), "read": list(m.ArtifactReader(case.root / "link-root").read(good))}
        out["text"] = case.text(out["reads"])
    finally:
        case.close()
    return out


def receipt_events():
    return [
        ("claude_tool_started_read", claude("tool_started", "started", tool="Read")), ("claude_tool_started_mcp", claude("tool_started", "started", tool="mcp__private_server__tool")),
        ("claude_tool_started_canary", claude("tool_started", "started", tool=CANARY)), ("claude_tool_started_no_tool", claude("tool_started", "started")),
        ("claude_tool_completed", claude("tool_completed", "completed")), ("claude_tool_completed_tool_dropped", claude("tool_completed", "completed", tool="Read")),
        ("claude_session_started", claude("session_started", "started")), ("claude_permission_denied", claude("permission_denied", "denied")),
        ("claude_message", claude("message", "emitted")), ("claude_result_success", claude("result", "success")), ("claude_result_error", claude("result", "error_max_turns")),
        ("claude_result_error_bare", claude("result", "error")), ("claude_result_unknown", claude("result", CANARY)), ("claude_result_none", claude("result", None)),
        ("claude_unknown_kind", claude(CANARY, CANARY)), ("claude_status_unknown_plain", claude("message", "weird")), ("claude_status_none", claude("tool_completed", None)),
        ("claude_status_failed", claude("tool_completed", "failed")), ("claude_occurred", claude("tool_completed", "completed", occurred_at_ms=1790550000000)),
        ("claude_occurred_bool", claude("tool_completed", "completed", occurred_at_ms=True)), ("claude_occurred_zero", claude("tool_completed", "completed", occurred_at_ms=0)),
        ("claude_occurred_negative", claude("tool_completed", "completed", occurred_at_ms=-5)), ("claude_occurred_too_big", claude("tool_completed", "completed", occurred_at_ms=10 ** 14)),
        ("claude_occurred_float", claude("tool_completed", "completed", occurred_at_ms=1790550000000.0)), ("claude_occurred_just_under", claude("tool_completed", "completed", occurred_at_ms=10 ** 14 - 1)),
        ("codex_command", codex("item/completed", {"id": CANARY, "type": "commandExecution", "status": "completed", "command": "rm -rf " + CANARY, "cwd": "/srv/" + CANARY,
                                                  "aggregatedOutput": CANARY})),
        ("codex_mcp_unknown_status", codex("item/completed", {"id": "x", "type": "mcpToolCall", "server": CANARY, "tool": CANARY, "arguments": CANARY, "status": CANARY})),
        ("codex_unknown_type", codex("item/completed", {"id": "x", "type": CANARY, "text": CANARY})), ("codex_file_change_failed", codex("item/completed", {"id": "x", "type": "fileChange", "status": "failed"})),
        ("codex_agent_message_no_status", codex("item/completed", {"id": "x", "type": "agentMessage"})), ("codex_reasoning", codex("item/completed", {"id": "x", "type": "reasoning", "status": "completed"})),
        ("codex_no_item", codex("item/completed")), ("codex_unknown_method", codex(CANARY)), ("codex_token_usage", codex("thread/tokenUsage/updated")),
        ("codex_item_status_in_progress", codex("item/completed", {"id": "x", "type": "fileChange", "status": "inProgress"})),
        ("codex_item_completed_at", codex("item/completed", {"id": "x", "type": "fileChange", "completedAtMs": 1790551000000})),
        ("codex_params_not_dict", {"method": "item/completed", "params": "x"}), ("codex_params_list", {"method": "item/completed", "params": [1]}),
        ("codex_emitted_at", {"method": "item/completed", "emittedAtMs": 1790552000000, "params": {}}),
        ("codex_completed_bool_then_emitted", {"method": "item/completed", "emittedAtMs": 1790552000000, "params": {"completedAtMs": True, "item": {"completedAtMs": 0, "type": "fileChange"}}}),
        ("codex_item_not_dict", {"method": "item/completed", "params": {"item": "x"}}), ("codex_method_not_str", {"method": 5}), ("provider_unknown", {"provider": "other", "method": None}),
        ("empty_event", {}), ("event_str", "x"),
        ("wrong_claude_type_list", claude(["tool_started"], "started")), ("wrong_claude_type_dict", claude({"kind": CANARY}, "completed")),
        ("wrong_claude_status_list", claude("tool_started", ["started"])), ("wrong_claude_result_status_dict", claude("result", {"status": CANARY})),
        ("wrong_claude_status_int", claude("tool_completed", 7)), ("wrong_claude_tool_list", claude("tool_started", "started", tool=["Read"])),
        ("wrong_claude_tool_dict", claude("tool_started", "started", tool={"name": CANARY})),
        ("wrong_codex_type_list", codex("item/completed", {"id": "x", "type": ["commandExecution"]})), ("wrong_codex_type_dict", codex("item/completed", {"id": "x", "type": {"kind": CANARY}})),
        ("wrong_codex_status_list", codex("item/completed", {"id": "x", "type": "fileChange", "status": [CANARY]}))]


def receipt_cases(api):
    m = api.module
    out = {}
    for name, event in receipt_events():
        text = json.dumps(envelope(event, defect=CANARY, previous=CANARY))
        view = call(m.project_receipt, text)
        out[name] = view
        if "value" in view:
            assert CANARY not in json.dumps(view["value"]), name
    texts = {"malformed_flag": json.dumps(envelope("<repr " + CANARY + ">", malformed=True, defect=CANARY)), "malformed_flag_with_event": json.dumps(envelope(claude("result", "success"), malformed=True)),
             "event_not_dict": json.dumps(envelope([1, 2])), "event_none": json.dumps(envelope(None)), "malformed_not_bool": json.dumps({"event": {}, "malformed": "no", "extra": CANARY}),
             "malformed_int": json.dumps({"event": {}, "malformed": 0}), "malformed_missing": json.dumps({"event": {}}), "extra_key": json.dumps({"event": {}, "malformed": False, "x": 1}),
             "only_known_keys": json.dumps({"event": {"provider": "claude-code-cli", "type": "message"}, "malformed": False, "defect": None, "previous": None}),
             "not_json": "{", "empty": "", "truncated": '{"event": ', "duplicate_key": '{"event": {}, "event": {}, "malformed": false}', "nan": '{"event": {}, "malformed": false, "defect": NaN}',
             "infinity": '{"event": {}, "malformed": false, "defect": Infinity}', "neg_infinity": '{"event": {}, "malformed": false, "defect": -Infinity}',
             "list_body": "[1]", "string_body": '"x"', "number_body": "5", "null_body": "null", "deep_nesting": "[" * 100000 + "]" * 100000, "deep_object": '{"a":' * 5000 + "1" + "}" * 5000,
             "unicode": json.dumps(envelope(claude("message", "emitted"), defect="한글"), ensure_ascii=False)}
    for name, text in texts.items():
        out[name] = call(m.project_receipt, text)
    out["non_string_inputs"] = {repr(v): call(m.project_receipt, v) for v in (None, 5, [], b"{}")}
    out["canary_leaked"] = CANARY in json.dumps(out)
    return out


def activity_cases(api):
    m = api.module
    out = {}
    case = Case()
    try:
        root = case.root / "artifacts"
        member = store_text(root, envelope(claude("tool_completed", "completed"), previous=store_text(root, envelope(claude("result", "success")))))
        foreign = store_text(root, envelope(claude("session_started", "started")))
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), progress([member], last=foreign), reader, NOW)
        out["membership"] = {"status": status, "items": items, "calls": reader.calls == [member], "refs": [i["receipt_ref"] == member for i in items]}

        valid = store_text(root, envelope(claude("tool_completed", "completed")))
        corrupt = store_text(root, '{"event": ')
        duplicate = store_text(root, '{"event": {}, "event": {}, "malformed": false}')
        flagged = store_text(root, envelope("<repr " + CANARY + ">", malformed=True, defect=CANARY))
        shaped = store_text(root, {"event": {}, "malformed": "no", "extra": CANARY})
        missing = "sha256:" + "f" * 64
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), progress([valid, corrupt, duplicate, flagged, shaped, missing]), reader, NOW)
        out["mixed_legacy"] = {"status": status, "items": items, "calls": len(reader.calls), "canary": CANARY in json.dumps(items)}
        reader = Spy(api, root)
        out["only_failures"] = call(lambda: list(m.execution_activity(row(), progress([corrupt, missing]), reader, NOW)))
        reader = Spy(api, root)
        out["malformed_only"] = {name: call(lambda p=p: list(m.execution_activity(row(), p, reader, NOW))) for name, p in {
            "int": progress([], malformed_events=2, malformed_recent=[ZERO]), "zero": progress([], malformed_events=0), "bool": progress([], malformed_events=True),
            "string": progress([], malformed_events="3"), "absent": progress([]), "recent_string": progress("sha256:abc", malformed_events=1), "recent_none": progress(None)}.items()}
        out["malformed_only_reads"] = reader.calls

        good = store_text(root, envelope(claude("tool_completed", "completed")))
        bad_body = store_text(root, envelope(claude(["tool_started"], "started")))
        raising = store_text(root, envelope(claude("result", "success")))

        class Failing(Spy):
            def read(self, reference):
                if reference == raising:
                    self.calls.append(reference)
                    raise PermissionError(CANARY)
                return super().read(reference)
        reader = Failing(api, root)
        status, items = m.execution_activity(row(), progress([["x"], bad_body, {"ref": good}, raising, None, good]), reader, NOW)
        out["wrong_typed_refs"] = {"status": status, "calls": reader.calls == [bad_body, raising, good],
                                   "states": [(i["state"], i["error_type"], i["receipt_ref"] in (None, bad_body, raising, good)) for i in items],
                                   "refs": [i["receipt_ref"] for i in items], "last": items[-1], "canary": CANARY in json.dumps(items)}

        class Odd:
            def __init__(self, answer):
                self.answer = answer

            def read(self, reference):
                if isinstance(self.answer, Exception):
                    raise self.answer
                return self.answer
        out["odd_readers"] = {name: call(lambda r=r: list(m.execution_activity(row(), progress([good]), r, NOW))) for name, r in {
            "returns_none": Odd(None), "returns_two": Odd(("ok", None)), "ok_with_none_text": Odd(("ok", None, None)), "ok_with_list_text": Odd(("ok", None, ["x"])),
            "ok_with_bytes_text": Odd(("ok", None, b"{}")), "state_other": Odd(("weird", "code", None)), "unavailable": Odd(("unavailable", "runtime_unavailable", None)),
            "value_error": Odd(ValueError("x"))}.items()}
        out["reader_none"] = {"legacy": call(lambda: list(m.execution_activity(row(), progress([good]), None, NOW))),
                              "compact": call(lambda: list(m.execution_activity(row(), compact_progress([good]), None, NOW)))}

        refs = [store_text(root, envelope(claude("tool_completed", "completed", padding=str(index)))) for index in range(8)]
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), progress(refs), reader, NOW)
        out["last_six"] = {"calls": reader.calls == refs[-6:], "status": status, "len": len(items), "sequences": [i["sequence"] for i in items]}

        first = store_text(root, envelope(codex("item/completed", {"id": "a", "type": "fileChange", "completedAtMs": 1790550999000})))
        second = store_text(root, envelope(codex("item/completed", {"id": "b", "type": "commandExecution"})))
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), progress([first, second, first, second]), reader, NOW)
        out["order_and_dedup"] = {"calls": reader.calls == [first, second], "refs": [i["receipt_ref"] == first for i in items], "sequences": [i["sequence"] for i in items],
                                  "collected": [i["collected_at"] for i in items], "occurred": [i["occurred_at"] for i in items]}
        out["last_record_annotation"] = {}
        for name, extra in {"seq_zero": {"sequence": 0}, "seq_negative": {"sequence": -1}, "seq_bool": {"sequence": True}, "seq_str": {"sequence": "7"}, "seq_none": {"sequence": None},
                            "collected_naive": {"collected": "2026-09-28T00:59:30"}, "collected_bad": {"collected": "garbage"}, "collected_none": {"collected": None},
                            "collected_offset": {"collected": "2026-09-28T09:59:30+09:00"}, "last_other": {"last": foreign}, "last_none_ring": {}}.items():
            ref_list = [first, second]
            p = progress(ref_list, **{k: v for k, v in extra.items()}) if "last" not in extra else progress(ref_list, last=extra["last"])
            r2 = m.execution_activity(row(), p, Spy(api, root), NOW)
            out["last_record_annotation"][name] = [[i["sequence"], i["collected_at"]] for i in r2[1]]

        table = {}
        statuses = [("running", None), ("queued", None), ("pending", None), ("retry", None), ("succeeded", (NOW - timedelta(seconds=600)).isoformat()),
                    ("succeeded", (NOW - timedelta(seconds=601)).isoformat()), ("failed", (NOW + timedelta(seconds=5)).isoformat()), ("failed", None), ("succeeded", "not a time"),
                    ("cancelled", NOW.isoformat()), ("superseded", NOW.isoformat()), ("blocked", NOW.isoformat()), ("expired", NOW.isoformat()), ("unknown", NOW.isoformat()),
                    ("archived", NOW.isoformat()), (None, NOW.isoformat()), ("", NOW.isoformat()), (["succeeded"], NOW.isoformat()), ({"s": "running"}, None),
                    ("succeeded", "2026-09-28T00:55:00"), ("succeeded", "2026-09-28T09:55:00+09:00"), ("succeeded", 5)]
        ref = store_text(root, envelope(claude("result", "success")))
        for status_, completed in statuses:
            reader = Spy(api, root)
            result = m.execution_activity(row(status_, completed_at=completed), progress([ref]), reader, NOW)
            table[f"{status_!r}|{completed}"] = [result[0], len(reader.calls)]
        out["selection"] = table
        out["recent_window_parameter"] = {str(seconds): m.execution_activity(row("succeeded", completed_at=(NOW - timedelta(seconds=30)).isoformat()), progress([ref]), Spy(api, root), NOW, seconds)[0]
                                          for seconds in (0, 29, 30, 31, 600)}
        out["lineage"] = {f"{g!r}/{a!r}": call(lambda g=g, a=a: list(m.execution_activity(row(), progress([ref], generation=g, attempt=a), Spy(api, root), NOW)))
                          for g, a in ((1, 1), (2, 2), (None, 1), ("2", 1), (2, True), (True, 1), (2.0, 1), (2, None), (2, 1))}
        out["no_progress"] = call(lambda: list(m.execution_activity(row(), None, Spy(api, root), NOW)))
        out["row_generation_none"] = call(lambda: list(m.execution_activity({"id": "task-1", "status": "running"}, progress([ref], generation=None, attempt=None), Spy(api, root), NOW)))

        # compact (S2b) path
        start = store_text(root, api.canonical(api.build_receipt(execution="task-1", transport="claude_cli", event=claude("tool_started", status="started", tool="Read"), activity_sequence=1,
                                                                 progress_sequence=None, generation=2, attempt=1, collected_at=NOW_ISO, raw_ref=None)))
        other = store_text(root, api.canonical(api.build_receipt(execution="task-OTHER", transport="claude_cli", event=claude("tool_started", status="started", tool="Read"), activity_sequence=2,
                                                                 progress_sequence=None, generation=2, attempt=1, collected_at=NOW_ISO, raw_ref=None)))
        c_corrupt = store_text(root, '{"schema": ')
        c_shaped = store_text(root, api.canonical({**api.build_receipt(execution="task-1", transport="claude_cli", event=claude("tool_started", status="started"), activity_sequence=3,
                                                                      progress_sequence=None, generation=2, attempt=1, collected_at=NOW_ISO, raw_ref=None), "extra": CANARY}))
        raw = store_text(root, json.dumps(envelope(claude("tool_completed", "completed"))))
        linked = store_text(root, api.canonical(api.build_receipt(execution="task-1", transport="claude_cli", event=claude("tool_completed", status="completed"), activity_sequence=2,
                                                                  progress_sequence=3, generation=2, attempt=1, collected_at=NOW_ISO, raw_ref=raw)))
        codex_item = store_text(root, api.canonical(api.build_receipt(execution="task-1", transport="app_server", event={"method": "item/completed", "params": {
            "item": {"id": CANARY, "type": "mcpToolCall", "status": CANARY, "server": CANARY}, "completedAtMs": 1790550000000}}, activity_sequence=4, progress_sequence=1, generation=None,
            attempt=None, collected_at=NOW_ISO, raw_ref=raw)))
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), compact_progress([start, other, c_corrupt, c_shaped, linked, codex_item, start, "bad"]), reader, NOW)
        out["compact_members"] = {"status": status, "calls": reader.calls == [start, other, c_corrupt, c_shaped, linked, codex_item], "items": items, "canary": CANARY in json.dumps(items),
                                  "raw_followed": raw in reader.calls}
        reader = Spy(api, root)
        out["compact_first_item"] = m.execution_activity(row(), compact_progress([start]), reader, NOW)
        legacy = store_text(root, json.dumps(envelope(claude("tool_completed", "completed"))))
        selection = {}
        for name, overrides in {"synchronized": {}, "watermark_none": {"activity_progress_sequence": None}, "watermark_behind": {"activity_progress_sequence": 2},
                                "watermark_bool": {"activity_progress_sequence": True, "sequence": 1}, "watermark_zero_sequence_absent": {"activity_progress_sequence": 0, "sequence": 0},
                                "watermark_negative": {"activity_progress_sequence": -1, "sequence": -1}, "ring_empty": {"activity_recent": []}, "ring_string": {"activity_recent": "sha256:x"},
                                "ring_missing": {"activity_recent": None}, "sequence_bool": {"sequence": True, "activity_progress_sequence": 1},
                                "sequence_missing_zero_watermark": {"sequence": None, "activity_progress_sequence": 0}}.items():
            p = {**compact_progress([start]), "recent": [legacy], "last_record": legacy, **overrides}
            result = call(lambda p=p: [m.execution_activity(row(), p, Spy(api, root), NOW)[0], [i["source"] for i in m.execution_activity(row(), p, Spy(api, root), NOW)[1]]])
            selection[name] = result
        p_no_sequence = {k: v for k, v in {**compact_progress([start]), "recent": [legacy], "last_record": legacy, "activity_progress_sequence": 0}.items() if k != "sequence"}
        selection["sequence_key_absent_watermark_zero"] = call(lambda: [i["source"] for i in m.execution_activity(row(), p_no_sequence, Spy(api, root), NOW)[1]])
        out["compact_selection"] = selection
        reader = Spy(api, root)
        missing_progress = {**compact_progress(["sha256:" + "c" * 64]), "recent": [legacy], "last_record": legacy}
        status, items = m.execution_activity(row(), missing_progress, reader, NOW)
        out["compact_no_fallback"] = {"status": status, "items": items, "calls": reader.calls}
        reader = Spy(api, root)
        status, items = m.execution_activity(row(), {**compact_progress([linked]), "recent": [raw], "last_record": raw}, reader, NOW)
        out["compact_raw_ref_is_data"] = {"calls": reader.calls == [linked], "raw_ref": items[0]["raw_ref"] == raw}
        reader = Spy(api, root)
        out["compact_failing_reader"] = call(lambda: list(m.execution_activity(row(), compact_progress([start]), Failing(api, root), NOW)))
        out["compact_receipt_bad_binding_none_row_id"] = call(lambda: list(m.execution_activity({"status": "running", "generation": 2, "attempt": 1}, compact_progress([start]), Spy(api, root), NOW)))
        out["compact_body_too_large"] = call(lambda: list(m.execution_activity(row(), compact_progress([store_text(root, "z" * (m.ACTIVITY_BODY_BYTES + 5))]), Spy(api, root), NOW)))
    finally:
        case.close()
    return out


def resolver_cases(api):
    m = api.module
    out = {}
    case = Case()
    try:
        lanes = [{"id": lane, "schema": "lane_" + lane, "runtime": str(case.root / ("rt-" + lane))} for lane in ("a", "b")]
        resolve = m.lane_artifact_resolver()
        ref = store_text(case.root / "rt-a" / "artifacts", envelope(claude("tool_completed", "completed")))
        reader_a = resolve(lanes[0])
        out["lane_a"] = list(reader_a.read(ref))
        out["lane_b"] = list(resolve(lanes[1]).read(ref)[:2])
        out["b_root_created"] = (case.root / "rt-b" / "artifacts").exists()
        out["cached"] = resolve(lanes[0]) is reader_a
        moved = {**lanes[0], "runtime": str(case.root / "rt-a2")}
        out["moved_is_new"] = resolve(moved) is not reader_a
        out["schema_changed_is_new"] = resolve({**lanes[0], "schema": "lane_other"}) is not reader_a
        out["id_changed_is_new"] = resolve({**lanes[0], "id": "z"}) is not reader_a
        out["other_resolvers_do_not_share"] = m.lane_artifact_resolver()(lanes[0]) is not reader_a
        out["root_is_the_registered_artifacts_dir"] = reader_a.root == case.root / "rt-a" / "artifacts"
        out["reader_type"] = type(reader_a).__name__
        out["extra_keys_ignored"] = call(lambda: type(resolve({**lanes[1], "extra": 1})).__name__)
        out["missing_keys"] = {key: call(lambda key=key: resolve({k: v for k, v in lanes[0].items() if k != key})) for key in ("id", "schema", "runtime")}
        out["tree_has_no_rt_b"] = sorted(p.name for p in case.root.iterdir())
    finally:
        case.close()
    return out


# ----- lane_view ---------------------------------------------------------------------------------------------------------------------------------
def lane_store(api, root, many=0, with_sessions=True):
    """A FIXTURE lane store: two operations, tasks, a decision, progress with retained receipts, reservations and a durable worker session."""
    store = api.MemoryStore()
    artifacts = root / "artifacts"
    r1 = store_text(artifacts, envelope(claude("session_started", "started")))
    r2 = store_text(artifacts, envelope(claude("tool_completed", "completed")))
    secret_text = "objective=" + CANARY
    with store.transaction() as tx:
        tx.put("operations", "op1", {"id": "op1", "status": "running", "assignment_message_id": "t1", "correlation_id": "corr-1", "claimed_at": "2026-09-28T00:00:00+00:00",
                                     "updated_at": "2026-09-28T00:10:00+00:00", "owner_handoff": True, "calls": {"reserved": 3, "settled": 2},
                                     "continuation": {"session": {"task_id": "job-1"}}, "goal": {"criterion": secret_text}})
        tx.put("operations", "op2", {"id": "op2", "status": "failed", "task_id": "t2", "decision_id": "d1", "correlation_id": "corr-2", "reason_code": "evidence_gate_refused",
                                     "lead_accepted": False, "calls": {"reserved": 2, "settled": 1, "other": 9}, "finished_at": "2026-09-28T00:50:00+00:00", "owner_handoff": False})
        tx.put("operations", "op3", {"id": "op3", "status": "running", "correlation_id": 5, "assignment_message_id": 7})
        tx.put("tasks", "t1", {"id": "t1", "agent": "implementer", "status": "running", "generation": 2, "attempt": 1, "created_at": "2026-09-28T00:00:00+00:00",
                               "lease_until": "2026-09-28T01:30:00+00:00", "error": "password=" + CANARY, "worktree": "/srv/" + CANARY,
                               "message": {"correlation_id": "corr-1", "what": {"action": "implement", "details": {"plan": {"objective": secret_text}, "prompt": CANARY}}},
                               "result": {"accepted": True}, "context_ref": "sha256:" + "9" * 64})
        tx.put("tasks", "t2", {"id": "t2", "agent": "reviewer", "status": "succeeded", "generation": 1, "attempt": 1, "created_at": "2026-09-28T00:20:00+00:00",
                               "completed_at": "2026-09-28T00:55:00+00:00", "phase": "explicit", "message": {"correlation_id": "corr-2"}})
        tx.put("tasks", "t3", {"id": "t3", "agent": "implementer", "status": "failed", "created_at": "2026-09-27T00:00:00+00:00", "completed_at": "2026-09-27T01:00:00+00:00",
                               "message": {"correlation_id": "corr-1"}})
        tx.put("tasks", "t4", {"id": "t4", "status": "queued", "message": {"when": {"created_at": "2026-09-28T00:58:00+00:00"}, "what": {"action": "queued-action"}}})
        tx.put("tasks", "t5", {"id": "t5", "status": "weird"})
        tx.put("decisions_pending", "d1", {"id": "d1", "actor": "review_lead", "status": "blocked", "result": {"accepted": False, "reason": CANARY}, "created_at": "2026-09-28T00:30:00+00:00",
                                           "generation": 1, "attempt": 1, "completed_at": None})
        tx.put("execution_progress", "t1", {"id": "t1", "sequence": 7, "generation": 2, "attempt": 1, "provider": "claude-code-cli", "occurred_at": "2026-09-28T00:40:00+00:00",
                                            "collected_at": "2026-09-28T00:59:30+00:00", "last_event": "claude/result/" + CANARY, "recent": [r1, r2], "last_record": r2,
                                            "last_completed": {"type": CANARY, "status": "error_" + CANARY, "sequence": 5, "occurred_at": None, "evidence": "ev"}, "malformed_events": 1,
                                            "activity_dropped": 4})
        tx.put("execution_progress", "t2", {"id": "t2", "sequence": 3, "generation": 1, "attempt": 1, "last_completed": {"type": "result", "status": "success", "sequence": 3},
                                            "recent": [r1], "last_record": r1, "collected_at": "2026-09-28T00:55:00+00:00", "activity_dropped": -3})
        tx.put("invocation_reservations", "r1", {"id": "r1", "bucket": "tasks", "task_id": "t1", "generation": 2, "attempt": 1, "invocation": 1, "stage": "implement",
                                                  "status": "settled", "outcome": "ok", "reason": "done", "reserved_at": "2026-09-28T00:01:00+00:00", "settled_at": "2026-09-28T00:20:00+00:00",
                                                  "elapsed_seconds": 1140, "within_budget": True, "usage": {"source": "provider", "total_tokens": 1234},
                                                  "request": {"assignment": {"provider": "claude", "identity": "id", "transport": "cli", "model_source": "policy"},
                                                              "options": {"model": "m-1"}, "prompt": CANARY}})
        tx.put("invocation_reservations", "r2", {"id": "r2", "bucket": "tasks", "task_id": "t1", "generation": 2, "attempt": 1, "invocation": 2, "status": "reserved",
                                                  "reserved_at": "2026-09-28T00:30:00+00:00", "usage": {"source": "unknown", "total_tokens": 99}, "request": {"options": {}}})
        tx.put("invocation_reservations", "r3", {"id": "r3", "task_id": "t2", "generation": 1, "attempt": 1, "invocation": 1, "status": "settled", "usage": {"total_tokens": 5}})
        tx.put("invocation_reservations", "r4", {"id": "r4", "bucket": "decisions_pending", "task_id": "d1", "status": "settled", "request": None})
        if with_sessions:
            tx.put("worker_sessions", "job-1", {"task_id": "job-1", "state": "checkpointed", "session_id": "ws-1", "version": 4, "owner": {"generation": 2, "attempt": 1, "execution": "t1"},
                                                "identity": {"model": "m", "secret": CANARY}, "checkpoints": [{"archive": "a1", "transcript": CANARY}], "candidates": [{}],
                                                "reviews": [{"decision_id": f"d{i}", "phase": "p", "outcome": "accepted"} for i in range(10)], "reason": None,
                                                "cleanup": None, "promotion": None})
            tx.put("worker_sessions", "job-2", {"task_id": "job-2", "state": "closed", "version": 1})
        for index in range(many):
            tx.put("tasks", f"m{index:03d}", {"id": f"m{index:03d}", "agent": "implementer", "status": "running" if index % 3 else "succeeded", "generation": 1, "attempt": 1,
                                              "created_at": f"2026-09-28T00:{index % 60:02d}:00+00:00", "completed_at": f"2026-09-28T00:{index % 60:02d}:30+00:00"})
    return store


class RecordingStore:
    def __init__(self, inner):
        self.inner, self.scanned, self.transactions = inner, [], 0

    def transaction(self):
        import contextlib
        owner = self

        @contextlib.contextmanager
        def cm():
            owner.transactions += 1
            with owner.inner.transaction() as tx:
                class Tx:
                    def __getattr__(self, name):
                        if name in ("put", "put_node", "put_edge", "graph"):
                            raise AssertionError("a write through lane_view: " + name)
                        target = getattr(tx, name)
                        if name == "scan":
                            return lambda bucket: (owner.scanned.append(bucket), target(bucket))[1]
                        return target
                yield Tx()
        return cm()


def lane_view_cases(api):
    m = api.module
    out = {}
    cases = [Case(), Case()]
    try:
        stores = [lane_store(api, cases[0].root), lane_store(api, cases[1].root, with_sessions=False)]
        # lane b's artifact root is gone: its activity is unavailable while every session fact stays listed
        shutil.rmtree(cases[1].root / "artifacts")
        before = [copy.deepcopy(s.data) for s in stores]
        recording = RecordingStore(stores[0])
        view_a = m.lane_view(recording, m.ArtifactReader(cases[0].root / "artifacts"), NOW)
        out["lane_a"] = {"view": summarize(view_a), "digest": digest(view_a)}
        out["scanned_buckets"] = recording.scanned
        out["one_transaction"] = recording.transactions
        out["worker_sessions_bucket_read"] = "worker_sessions" in recording.scanned
        view_b = m.lane_view(m.ReadOnlyStore(stores[1]), m.ArtifactReader(cases[1].root / "artifacts"), NOW)
        out["lane_b_unavailable_root"] = {"view": summarize(view_b), "digest": digest(view_b)}
        out["lane_b_statuses"] = {v["id"]: [v["status"], v["activity_status"], [a["error_type"] for a in v["activity"]]] for v in view_b["executions"]}
        out["per_lane_isolation"] = {"a_sessions": view_a["worker_sessions"], "b_sessions": view_b["worker_sessions"],
                                     "a_counts": view_a["counts"], "b_counts": view_b["counts"], "same_ids": sorted(v["id"] for v in view_a["executions"]) == sorted(v["id"] for v in view_b["executions"]),
                                     "a_owner_of_t1": [v["worker_session"] for v in view_a["executions"] if v["id"] == "t1"],
                                     "b_owner_of_t1": [v["worker_session"] for v in view_b["executions"] if v["id"] == "t1"]}
        out["secret_free"] = {"canary": CANARY in json.dumps([view_a, view_b]), "fields_absent": [word not in json.dumps(view_a) for word in ("objective", "prompt", "transcript", "worktree", "context_ref",
                                                                                                                                              "password", "checkpoints", "candidates")]}
        out["no_secret_keys"] = sorted({key for view in view_a["executions"] for key in view})
        out["stores_unchanged"] = [s.data == b for s, b in zip(stores, before)]
        out["reader_none"] = {"digest": digest(m.lane_view(m.ReadOnlyStore(stores[0]), None, NOW)), "statuses": {v["id"]: [v["activity_status"], [a["error_type"] for a in v["activity"]]]
                                                                                                                for v in m.lane_view(m.ReadOnlyStore(stores[0]), None, NOW)["executions"]}}
        default = m.lane_view(m.ReadOnlyStore(stores[0]), m.ArtifactReader(cases[0].root / "artifacts"))
        out["default_now"] = {"statuses": {v["id"]: [v["status"], v["activity_status"]] for v in default["executions"]}, "total": default["total"]}
        out["window_parameter"] = {str(s): {v["id"]: v["activity_status"] for v in m.lane_view(m.ReadOnlyStore(stores[0]), m.ArtifactReader(cases[0].root / "artifacts"), NOW, s)["executions"]}
                                   for s in (0, 60, 100000)}
        out["lane_view_positional_shape"] = m.lane_view(m.ReadOnlyStore(stores[0]), m.ArtifactReader(cases[0].root / "artifacts"), NOW, 600) == view_a

        many = lane_store(api, cases[0].root, many=60)
        big = m.lane_view(m.ReadOnlyStore(many), m.ArtifactReader(cases[0].root / "artifacts"), NOW)
        out["truncated"] = {"total": big["total"], "shown": len(big["executions"]), "truncated": big["truncated"], "counts": big["counts"], "invocations": big["invocations"],
                            "worker_sessions": big["worker_sessions"], "order": [[v["id"], v["status"]] for v in big["executions"]][:20], "digest": digest(big)}

        real = m.execution_activity
        try:
            def explode(*args, **kwargs):
                raise RuntimeError(CANARY)
            m.execution_activity = explode
            exploded = m.lane_view(m.ReadOnlyStore(stores[0]), m.ArtifactReader(cases[0].root / "artifacts"), NOW)
        finally:
            m.execution_activity = real
        out["activity_failure"] = {"statuses": {v["id"]: [v["status"], v["activity_status"], v["activity"], v["activity_dropped"]] for v in exploded["executions"]},
                                   "canary": CANARY in json.dumps(exploded), "restored": m.execution_activity is real}

        empty = m.lane_view(m.ReadOnlyStore(api.MemoryStore()), None, NOW)
        out["empty_store"] = empty
        bad = api.MemoryStore()
        with bad.transaction() as tx:
            tx.put("tasks", "x", {"status": "running"})
        out["task_without_id"] = call(m.lane_view, m.ReadOnlyStore(bad), None, NOW)
        bad_sessions = api.MemoryStore()
        with bad_sessions.transaction() as tx:
            tx.put("worker_sessions", "x", {"task_id": "x", "state": "weird", "owner": "not a dict"})
            tx.put("operations", "o", {"id": "o", "assignment_message_id": "t", "continuation": {"session": {"task_id": "x"}}})
            tx.put("tasks", "t", {"id": "t", "status": "running", "created_at": NOW_ISO})
        out["odd_session_rows"] = call(m.lane_view, m.ReadOnlyStore(bad_sessions), None, NOW)

        class Broken:
            def transaction(self):
                raise RuntimeError("injected lane outage")
        out["store_failure"] = call(m.lane_view, Broken(), None, NOW)
        # the worker-session bucket name is a V9 literal on the target; both sides read the same bucket
        wrong = api.MemoryStore()
        with wrong.transaction() as tx:
            tx.put("worker_session", "x", {"task_id": "x", "state": "closed"})
            tx.put("worker_sessions", "y", {"task_id": "y", "state": "active"})
        out["session_bucket_name"] = call(lambda: m.lane_view(m.ReadOnlyStore(wrong), None, NOW)["worker_sessions"])
    finally:
        for case in cases:
            case.close()
    return out


def scope_cases(api):
    m = api.module
    out = {}
    pairs = [("/zeus-fixture/some-repo", None), ("/zeus-fixture/some-repo", ""), ("/zeus-fixture/some-repo", "   "), ("/zeus-fixture/some-repo/", "Label"),
             ("/zeus-fixture/some-repo", "  padded  "), ("/zeus-fixture/some-repo", "Zeus 고정 운영 원장 · 과거 격리 실행 제외 password=secret"), ("/zeus-fixture/some-repo", "x" * 300),
             ("/zeus-fixture/some-repo", "token=" + CANARY), ("/zeus-fixture/some-repo", 5), ("/zeus-fixture/some-repo", 0), ("/zeus-fixture/some-repo", ["a"]),
             ("/zeus-fixture/a/../other", None), (Path("/zeus-fixture/path-object"), None), ("/", None), ("/zeus-fixture/한글-저장소", None), ("/zeus-fixture/some-repo", "a" * 195 + "token=" + CANARY)]
    out["labels"] = [{"input": [str(p), repr(lbl)[:40]], "result": call(m.scope_label, p, lbl)} for p, lbl in pairs]
    out["keyword_label"] = call(m.scope_label, "/zeus-fixture/r", label="k")
    out["repository_none"] = call(m.scope_label, None)
    out["repository_int"] = call(m.scope_label, 5)
    out["canary_leaked"] = CANARY in json.dumps(out)
    return out


def run(api) -> dict:
    return {"read_only": read_only_cases(api), "safe_text": helper_safe_text(api), "container_scope": helper_container_scope(api), "parse_observed": helper_parse_observed(api),
            "persisted_measurements": persisted_cases(api), "audit_progress": audit_cases(api), "database_facts": database_cases(api), "artifact_reader": reader_cases(api),
            "project_receipt": receipt_cases(api), "execution_activity": activity_cases(api), "lane_artifact_resolver": resolver_cases(api), "lane_view": lane_view_cases(api),
            "scope_label": scope_cases(api)}
