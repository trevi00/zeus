"""Scenario body `storage.memory` (REBUILD-DESIGN-v2 §5.3 S1: store transaction semantics, the §2.9
recorder against the store, artifact put/read bounds, bounded artifact queries, artifact collection).

Layer: harness (never shipped). `api` provides: MemoryStore, FileArtifacts, reader (the bounded
reader module: parser/run/main), query (artifact_query), maintenance(store, artifacts) -> collector,
ContractError. The scripted clock is bound by the driver.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import time
from pathlib import Path

import recorder as rec
from s1_common import outcome, relative, sha


class Injected(RuntimeError):
    pass


def memory_store(api) -> dict:
    out: dict = {}
    store = api.MemoryStore()
    with store.transaction() as tx:
        tx.put("b", "k2", {"v": 2})
        tx.put("b", "k1", {"v": 1, "list": [1, {"x": "y"}]})
        tx.put("c", "k", {"n": [1]})
        tx.put("b", "k3", {"v": 3})
        copy = tx.get("b", "k1")
        copy["v"] = 99
        copy["list"][1]["x"] = "mutated"
        out["get_returns_copy"] = tx.get("b", "k1") == {"v": 1, "list": [1, {"x": "y"}]}
    try:
        with store.transaction() as tx:
            tx.put("b", "k4", {"v": 4})
            tx.put("b", "k1", {"v": "overwritten"})
            raise Injected("rollback")
    except Injected:
        pass
    with store.transaction(fail_fast=True) as tx:
        out["after_rollback"] = {"k4": tx.get("b", "k4"), "k1": tx.get("b", "k1")}
        out["missing"] = tx.get("b", "absent")
        out["scan_b"] = tx.scan("b")
        out["scan_empty"] = tx.scan("nothing")
        out["records"] = tx.records()
        out["entries"] = [tx.entries("b"), tx.entries("b", after="k1"), tx.entries("b", after="k1", limit=1),
                          tx.entries("b", after="k9")]
        graph = tx.graph()
        graph.put_node({"id": "n1", "repository": "r", "kind": "module", "body": {"a": 1},
                        "source_ref": "s", "revision": "v", "properties": {}})
        graph.put_edge("n1", "n2", "imports")
    with store.transaction() as tx:
        out["graph_rows"] = [tx.scan("knowledge_nodes"), tx.scan("knowledge_edges")]
    # A body put by value is copied: mutating the caller's dict after put changes nothing stored.
    body = {"v": [1]}
    with store.transaction() as tx:
        tx.put("d", "k", body)
    body["v"].append(2)
    with store.transaction() as tx:
        out["put_copies_body"] = tx.get("d", "k") == {"v": [1]}
    # Nested transactions on the in-process store (recorded as a nested BEGIN violation by the
    # recorder): the inner draft commits first, then the outer draft replaces it.
    with store.transaction() as outer:
        outer.put("n", "outer", {"v": 1})
        with store.transaction() as inner:
            inner.put("n", "inner", {"v": 2})
    with store.transaction() as tx:
        out["nested_outcome"] = sorted(r["id"] for r in tx.records() if r["bucket"] == "n")
    return out


def recorder_controls(api) -> dict:
    """The S0 §2.9 recorder over this side's store: each control must produce its verdict."""
    out = {}

    def completion(e):
        return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "succeeded"

    def intent(e):
        return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "running"

    authority = {"releases", "release_queue"}

    def case(name, body):
        store = rec.RecordingStore(api.MemoryStore())
        try:
            body(store, store.recorder)
        except Injected:
            pass
        r = store.recorder
        with store._inner.transaction() as tx:
            rows = [[x["bucket"], x["id"], (x["body"] or {}).get("status")] for x in tx.records()]
        out[name] = {"verdict": r.classify(authority, completion),
                     "violations": sorted({v["kind"] for v in r.violations}),
                     "effect_protocol": sorted(set(r.effect_protocol(intent, completion))),
                     "trace": r.trace(), "durable_rows": rows}

    def atomic(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
        r.effect("provider_call")
        with store.transaction() as tx:
            r.fence("lease", True)
            tx.put("releases", "r1", {"status": "proposed"})
            tx.put("release_queue", "q", {"status": "queued"})
            tx.put("decisions_pending", "d", {"status": "succeeded"})

    def rollback(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
        r.effect("provider_call")
        with store.transaction() as tx:
            tx.put("releases", "r1", {"status": "proposed"})
            raise Injected("after release, before decision")

    def split(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
        r.effect("provider_call")
        with store.transaction() as tx:
            tx.put("releases", "r1", {"status": "proposed"})
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "succeeded"})
            raise Injected("terminal write failed")

    def stale(store, r):
        with store.transaction() as tx:
            r.fence("lease", False)
            tx.put("decisions_pending", "d", {"status": "succeeded"})

    def fabricated(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "succeeded"})

    def effect_inside(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
            r.effect("provider_call")

    def nested(store, r):
        with store.transaction() as tx:
            tx.put("decisions_pending", "d", {"status": "running"})
            with store.transaction() as inner:
                inner.put("outbox", "m", {"status": "pending"})

    for name, body in (("atomic_commit", atomic), ("atomic_rollback", rollback), ("partial_commit", split),
                       ("stale_fence", stale), ("fabricated_completion", fabricated),
                       ("effect_inside_unit", effect_inside), ("nested_begin", nested)):
        case(name, body)
    return out


def artifacts(api, root: Path, clock) -> dict:
    out: dict = {}
    store_root = root / "store" / "artifacts"
    arts = api.FileArtifacts(str(store_root))
    clock.reset()
    first = arts.put("hello é world", "fixture:one")
    clock.advance(2)
    again = arts.put("hello é world", "fixture:two")
    doc = arts.put(json.dumps({"a": [1, 2, {"b": "c"}], "d": "text"}, sort_keys=True), "fixture:doc")
    arr = arts.put("[1, 2]", "fixture:array")
    out["receipts"] = [first, again, doc, arr]
    out["files"] = sorted(p.name for p in store_root.iterdir())
    out["lock_file_beside_root"] = (store_root.parent / "artifacts.lock").exists()
    ref = first["ref"]
    out["read"] = [outcome(lambda: arts.read(ref)), outcome(lambda: arts.read(ref, 6, 3)),
                   outcome(lambda: arts.read(ref, 0, 32000)), outcome(lambda: arts.read(ref, 0, 32001)),
                   outcome(lambda: arts.read(ref, -1, 5)), outcome(lambda: arts.read(ref, 0, 0)),
                   outcome(lambda: arts.read("sha256:" + "a" * 63)), outcome(lambda: arts.read("md5:" + "a" * 64)),
                   outcome(lambda: arts.read("sha256:" + "b" * 64))]
    out["text"] = [outcome(lambda: arts.text(ref, 1024)), outcome(lambda: arts.text(ref, 3)),
                   outcome(lambda: arts.text(ref, 0)), outcome(lambda: arts.text(ref, 1024 * 1024 + 1)),
                   outcome(lambda: arts.text(ref, True))]
    out["document"] = [outcome(lambda: arts.document(doc["ref"])), outcome(lambda: arts.document(arr["ref"])),
                       outcome(lambda: arts.document(ref))]
    out["inspect"] = [outcome(lambda: arts.inspect(ref)), outcome(lambda: arts.inspect(doc["ref"]))]
    out["search"] = [outcome(lambda: arts.search(ref, "WORLD")), outcome(lambda: arts.search(ref, "")),
                     outcome(lambda: arts.search(ref, "x", 101)), outcome(lambda: arts.search(doc["ref"], "\"", 1))]
    key = ref[7:]
    (store_root / (key + ".json")).write_text(json.dumps({"ref": ref, "bytes": 1}), encoding="utf-8")
    out["inspect_bad_metadata"] = outcome(lambda: arts.inspect(ref))
    (store_root / (key + ".txt")).write_bytes(b"tampered")
    out["modified"] = [outcome(lambda: arts.read(ref)), outcome(lambda: arts.put("hello é world", "again"))]
    return relative(out, {"ROOT": str(root)})


def reader(api, root: Path) -> dict:
    out: dict = {}
    arts = api.FileArtifacts(str(root / "reader" / "artifacts"))
    body = json.dumps({"alpha": {"beta": [1, 2, 3], "t~/x": "tilde"}, "long": "x" * 1500,
                       "text": "Needle in a haystack; another needle here."}, sort_keys=True)
    ref = arts.put(body, "fixture:reader")["ref"]
    base = ["--root", str(root / "reader" / "artifacts"), "--ref", ref]
    argvs = {
        "index": base + ["index"], "index_small": base + ["index", "--limit", "512"],
        "index_cursor": base + ["index", "--cursor", "3", "--limit", "600"],
        "page": base + ["page", "--limit", "700"], "page_cursor": base + ["page", "--cursor", "1000", "--limit", "900"],
        "pointer": base + ["pointer", "--pointer", "/alpha/beta"],
        "pointer_escape": base + ["pointer", "--pointer", "/alpha/t~0~1x"],
        "pointer_missing": base + ["pointer", "--pointer", "/nope"],
        "pointer_bad": base + ["pointer", "--pointer", "alpha"],
        "search": base + ["search", "--query", "NEEDLE"],
        "limit_low": base + ["page", "--limit", "511"], "limit_high": base + ["page", "--limit", "32001"],
        "cursor_negative": base + ["page", "--cursor", "-1"],
        "cursor_beyond": base + ["page", "--cursor", "999999"],
        "bad_ref": ["--root", str(root / "reader" / "artifacts"), "--ref", "sha256:zz", "page"],
        "missing_root": ["--root", str(root / "nowhere"), "--ref", ref, "page"],
    }
    for name, argv in argvs.items():
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = outcome(lambda a=argv: api.reader.main(a))
        out[name] = relative({"result": result, "stdout_sha256": sha(stdout.getvalue()),
                              "stdout_chars": len(stdout.getvalue()), "stdout_head": stdout.getvalue()[:300],
                              "stderr": stderr.getvalue()}, {"ROOT": str(root)})
    q = api.query
    out["query_constants"] = [q.CONTRACT, q.DEFAULT_LIMIT, q.MAX_LIMIT, q.MIN_LIMIT]
    out["query_direct"] = [outcome(lambda: q.page("sha256:x", "abc", 0, 512)),
                           outcome(lambda: q.search("sha256:x", "aXbxc", "x", 0, 512)),
                           outcome(lambda: q.index("sha256:x", '{"a": NaN}', 0, 512)),
                           outcome(lambda: q.index("sha256:x", '{"a": 1, "a": 2}', 0, 512)),
                           outcome(lambda: q.pointer("sha256:x", '["\\ud800"]', "/0", 0, 512)),
                           outcome(lambda: q.validate_bounds(0, 512)), outcome(lambda: q.validate_bounds(-1, 512))]
    return out


def maintenance(api, root: Path, clock) -> dict:
    out: dict = {}
    arts_root = root / "maint" / "artifacts"
    arts = api.FileArtifacts(str(arts_root))
    clock.reset()
    child = arts.put("leaf evidence", "fixture:leaf")["ref"]
    parent = arts.put("parent cites " + child, "fixture:parent")["ref"]
    unreferenced_old = arts.put("unreferenced old", "fixture:old")["ref"]
    unreferenced_new = arts.put("unreferenced new", "fixture:new")["ref"]
    missing = "sha256:" + "c" * 64
    old = time.time() - 30 * 86400
    for ref in (child, parent, unreferenced_old):
        os.utime(arts_root / (ref[7:] + ".txt"), (old, old))
    store = api.MemoryStore()
    with store.transaction() as tx:
        tx.put("evidence", "e1", {"ref": parent, "also": missing})
    collector = api.maintenance(store, arts)
    out["days_refused"] = outcome(lambda: collector.collect(days=0))
    out["dry_run"] = collector.collect()
    out["files_after_dry_run"] = len(list(arts_root.glob("*.txt")))
    clock.advance(5)
    out["apply"] = collector.collect(apply=True)
    out["remaining"] = sorted("sha256:" + p.stem for p in arts_root.glob("*.txt"))
    out["expected_remaining"] = sorted([child, parent, unreferenced_new])
    with store.transaction() as tx:
        out["rows"] = tx.records()
    clock.advance(5)
    out["apply_again"] = collector.collect(apply=True)
    with store.transaction() as tx:
        out["events_after_second_apply"] = len(tx.scan("events"))
    out["refs"] = {"child": child, "parent": parent, "unreferenced_old": unreferenced_old,
                   "unreferenced_new": unreferenced_new}
    return out


def run(api, root: Path, clock) -> dict:
    return {"memory_store": memory_store(api), "recorder_controls": recorder_controls(api),
            "artifacts": artifacts(api, root, clock), "reader": reader(api, root),
            "maintenance": maintenance(api, root, clock)}
