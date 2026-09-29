"""Scenario body `knowledge.units` (REBUILD-DESIGN-v2 §5.3 S2: the knowledge context).

Layer: harness (never shipped); standard library only. `api` provides the knowledge modules of one side:
`seams`, `seam_view`, `SeamLedger`, `extract`, `discover`, `experience` (domain), `ExperienceClaims`,
`parse_lesson`, `import_lessons`, `snapshot` (domain), `SnapshotImports`, `privacy` (domain),
`ProfileFlow`, `ProfileScratch`, `promote`, `extract_python`, `LocalEmbeddings`, `MemoryStore`,
`FileArtifacts`, `load_yaml`. Records carry timestamps from the scripted clock, so whole rows are
compared by digest; refusals by type and message. Inputs are synthetic sentinels only.

Fixed paths (injection, never masked): the code-graph fixture lives at a fixed absolute root because
M7 derives the repository id from the path; per-run files live under `work`, reported relatively.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from s1_common import outcome, relative

REV = "a" * 40
POLICY = {"version": 1, "direction": "producer_to_consumer", "require_fidelity": "HIGH", "compare": ["name", "type"]}
GRAPH_ROOT = Path("/tmp/zeus-rebuild-s2-knowledge-graph")
GRAPH_MARKER = ".zeus-rebuild-s2-disposable"
PROJECT = "/home/sentinel-user/work/shop"
PROFILE_POLICY = {
    "version": 1, "purpose": "derive working-style preferences for prompt guidance",
    "fields": {"content": "the preference signal itself", "project_path": "grouping by project, hashed before model input",
               "kind": "restrict to user messages"},
    "read_scope": {"kinds": ["user_message"], "max_records": 50, "max_chars": 300, "projects": [PROJECT]},
    "model": {"name": "local-preference-model", "transport": "local"},
    "retention": {"temporary": "run", "permanent": "profile_only"},
    "notice": {"text": "Messages from the projects you pick are read locally; secrets and paths are excluded "
                       "automatically; raw text is not kept.",
               "claims": ["no_external_transfer", "automatic_exclusion", "raw_not_retained"]}}
MANIFEST = {"version": 1, "required": {
    "experience/lessons.jsonl": {"kind": "jsonl", "schema_version": 2},
    "experience/retractions.jsonl": {"kind": "jsonl", "schema_version": 2,
                                     "required_fields": ["schema_version", "id", "retracts"],
                                     "references": {"retracts": "experience/lessons.jsonl"}, "allow_empty": True},
    "graduation.json": {"kind": "json", "schema_version": 1}}}


def sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def observation(api, name, members, *, package="shop.orders", fidelity="HIGH", unresolved=0):
    return {"identity": api.seams.contract_identity("python", package, name), "kind": "enum",
            "members": [{"name": n, "type": t, "tag": v} for n, t, v in members],
            "fidelity": fidelity, "denominator": {"symbols_found": len(members) + unresolved, "unresolved": unresolved},
            "source": {"path": f'{package.replace(".", "/")}/{name.lower()}.py', "blob_sha": "sha256:" + "b" * 64,
                       "revision": REV, "parser": "python-ast-3.12"}}


def seams(api, work: Path) -> dict:
    s = api.seams
    names = ["PENDING", "PAID", "PAID_LATE", "CANCELLED"]
    out = {"transforms": {
        "partial_map": outcome(lambda: s.effective_transform(
            {"version": 1, "kind": "value_map", "value_map": {"PAID_LATE": "PAID"}}, names)),
        "strip": outcome(lambda: s.effective_transform({"version": 1, "kind": "affix", "strip_prefix": "PAID_"},
                                                       ["PAID_LATE", "LATE"])),
        "unknown_option": outcome(lambda: s.parse_transform({"version": 1, "kind": "affix", "strip_prefx": "X"})),
        "empty_affix": outcome(lambda: s.parse_transform({"version": 1, "kind": "affix"})),
        "noop": outcome(lambda: s.effective_transform({"version": 1, "kind": "value_map", "value_map": {"ABSENT": "X"}},
                                                      names)),
        "not_dict": outcome(lambda: s.parse_transform("identity"))}}
    out["identity"] = {
        "qualified": outcome(lambda: s.contract_identity("python", "shop.orders", "Status")),
        "bad_token": outcome(lambda: s.contract_identity("python", "p q", "n")),
        "high_with_unresolved": outcome(lambda: s.parse_observation(
            observation(api, "Status", [("A", "int", 1)], unresolved=1))),
        "duplicate_member": outcome(lambda: s.parse_observation(
            observation(api, "Status", [("A", "int", 1), ("A", "int", 2)]))),
        "policy": outcome(lambda: s.parse_policy(POLICY)),
        "policy_low": outcome(lambda: s.parse_policy({**POLICY, "require_fidelity": "LOW"}))}
    producer = observation(api, "Status", [("PENDING", "int", 1), ("PAID", "int", 2), ("PAID_LATE", "int", 3)])
    consumer = observation(api, "Status", [("PENDING", "int", 1), ("PAID", "int", 2), ("REFUNDED", "int", 4)],
                           package="shop.billing")
    identity = {"version": 1, "kind": "identity"}
    low = observation(api, "Status", [("PENDING", "int", 1)], fidelity="LOW", unresolved=2)
    out["compare"] = {
        "p2c": outcome(lambda: s.compare(producer, consumer, identity, POLICY)),
        "c2p": outcome(lambda: s.compare(producer, consumer, identity, {**POLICY, "direction": "consumer_to_producer"})),
        "collapsed": outcome(lambda: s.compare(producer, consumer, {"version": 1, "kind": "value_map",
                                                                    "value_map": {"PAID_LATE": "PAID"}}, POLICY)),
        "renamed_both": outcome(lambda: s.compare(producer, consumer, {"version": 1, "kind": "value_map",
                                                                       "value_map": {"PAID_LATE": "REFUNDED"}},
                                                  {**POLICY, "direction": "both"})),
        "blocked_low": outcome(lambda: s.compare(low, consumer, identity, POLICY))}
    src = work / "seams" / "shop" / "orders"
    src.mkdir(parents=True)
    (src / "status.py").write_text(
        "from enum import Enum, IntEnum\n\ndef helper():\n    return 3\n\nclass Status(Enum):\n    PENDING = 1\n"
        "    PAID = 2  # inline\n    A = 3\n    _ignored = 9\n\nclass Priority(IntEnum):\n    LOW = helper()\n"
        "    HIGH = 10\nclass Annotated(Enum):\n    A = 1\n    B: int = 2\n    C: int\n    D = E = 3\n    F, G = 4, 5\n",
        encoding="utf-8")
    (src / "broken.py").write_text("class Status(Enum:\n", encoding="utf-8")
    root = work / "seams"
    out["extract"] = {name: outcome(lambda: api.extract("python", root, path, revision=REV))
                      for name, path in {"status": "shop/orders/status.py", "broken": "shop/orders/broken.py",
                                         "missing": "shop/orders/nope.py"}.items()}
    out["extract"]["java"] = outcome(lambda: api.extract("java", root, "shop/orders/Status.java", revision=REV))
    out["extract"]["no_revision"] = outcome(lambda: api.extract("python", root, "shop/orders/status.py", revision=""))
    out["discover"] = outcome(lambda: api.discover(root, "python", max_files=1))
    ledger = api.SeamLedger(api.MemoryStore())
    rows = {}
    rows["producer"] = outcome(lambda: ledger.record_observation(producer, binding={"revision": REV, "task_id": "t1"}))
    rows["producer_again"] = outcome(lambda: ledger.record_observation(producer, binding={"revision": REV,
                                                                                          "task_id": "t2"}))
    rows["consumer"] = outcome(lambda: ledger.record_observation(consumer, binding={"revision": REV, "task_id": "t1"}))
    rows["wrong_binding"] = outcome(lambda: ledger.record_observation(producer, binding={"revision": "b" * 40}))
    p_id, c_id = rows["producer"]["ok"]["id"], rows["consumer"]["ok"]["id"]
    rows["comparison"] = outcome(lambda: ledger.compare(p_id, c_id, identity, POLICY))
    cmp_id = rows["comparison"]["ok"]["id"]
    rows["approve_worker"] = outcome(lambda: ledger.approve_blocking(cmp_id, actor="worker:github",
                                                                     policy_revision=REV, reason="r"))
    rows["approve"] = outcome(lambda: ledger.approve_blocking(cmp_id, actor="conductor", policy_revision=REV,
                                                              reason="drift blocks"))
    good = json.dumps({"seam_id": "s", "verdict": "DRIFT", "producer": "p", "consumer": "c", "at": "t"})
    rows["import"] = outcome(lambda: ledger.import_jsonl(good + "\n{broken\n" + good + "\n", source_label="up"))
    gate = {"version": 1, "fail_on": ["DRIFT"], "required_seams": ["missing-seam"]}
    rows["view"] = outcome(lambda: ledger.view(gate))
    out["ledger"] = {k: ({"ok_sha256": sha(v["ok"])} if "ok" in v else v) for k, v in rows.items()}
    out["gate_policy"] = {"ok": outcome(lambda: api.seam_view.parse_gate_policy(gate)),
                          "typo": outcome(lambda: api.seam_view.parse_gate_policy({**gate, "fail_on": ["DRFT"]}))}
    return relative(out, {"WORK": str(work)})


def lesson(occurrences=308) -> bytes:
    lines = ["---", "created_by: agent:curator", "created_ts: 1788396067.7754688", "evidence:",
             *["- " + t for t in ["ledger:PASS x1", "ledger:PASS x2", "repair-notes:harness"]],
             "id: lesson:knowledge/lessons/repair.md", "kind: lesson", "lifecycle: active",
             f"occurrences: {occurrences}", "origin: promoted", "pinned: false", "source_families:",
             "- repair::encoding", "trust: confirmed", "---", "", "# 수리 경험: cp949\n"]
    return "\n".join(lines).encode("utf-8")


def experience(api, work: Path) -> dict:
    pinned = {"kind": "pinned", "revision": "a3f8b3be9a0a389329de6e16a6c7db81782041a3"}
    out = {"parse": outcome(lambda: api.parse_lesson("harness", "knowledge/lessons/repair.md", lesson(), pinned,
                                                     load_yaml=api.load_yaml))}
    for name, data in {"tag": b"---\nx: !!python/object/apply:os.system [\"echo\"]\n---\n",
                       "duplicate": b"---\nid: a\nid: b\n---\n", "not_utf8": b"---\nid: a\n---\n\xff\xfe",
                       "not_mapping": b"---\n- orphan\n---\n"}.items():
        out[name] = outcome(lambda: api.parse_lesson("harness", "lessons/x.md", data, pinned, load_yaml=api.load_yaml))
    out["classify"] = outcome(lambda: api.experience.classify_evidence(["ledger:PASS x1", "repair-notes:h", "x"]))
    out["basis_bad"] = outcome(lambda: api.experience.validate_basis({"kind": "pinned", "revision": "short"}))
    directory = work / "lessons"
    directory.mkdir()
    (directory / "repair.md").write_bytes(lesson())
    store = api.MemoryStore()
    artifacts = api.FileArtifacts(str(work / "exp-artifacts"))
    first = outcome(lambda: api.import_lessons([directory], "harness", pinned, store, artifacts, "knowledge/lessons/",
                                               load_yaml=api.load_yaml))
    again = outcome(lambda: api.import_lessons([directory], "harness", pinned, store, artifacts, "knowledge/lessons/",
                                               load_yaml=api.load_yaml))
    (directory / "repair.md").write_bytes(lesson(occurrences=309))
    changed = outcome(lambda: api.import_lessons([directory], "harness", pinned, store, artifacts,
                                                 "knowledge/lessons/", load_yaml=api.load_yaml))
    claims = api.ExperienceClaims(store)
    out["imports"] = {"first": first, "again": again, "changed": changed,
                      "versions": outcome(lambda: claims.versions("harness", "knowledge/lessons/repair.md")),
                      "summary": outcome(claims.summary)}
    return relative(out, {"WORK": str(work)})


def line(**fields) -> bytes:
    return (json.dumps(fields) + "\n").encode("utf-8")


def snapshots(api, work: Path) -> dict:
    good = {"experience/lessons.jsonl": line(schema_version=2, id="l1") + line(schema_version=2, id="l2"),
            "experience/retractions.jsonl": line(schema_version=2, id="r1", retracts="l1"),
            "graduation.json": json.dumps({"schema_version": 1, "id": "grad"}).encode("utf-8")}
    broken = {**good, "experience/lessons.jsonl": good["experience/lessons.jsonl"] + b'{"schema_version": 2\n'}
    dangling = {**good, "experience/retractions.jsonl": line(schema_version=2, id="r1", retracts="nope")}
    missing = {k: v for k, v in good.items() if k != "graduation.json"}
    snap = api.snapshot
    out = {"manifest": outcome(lambda: snap.parse_manifest(MANIFEST)),
           "manifest_escape": outcome(lambda: snap.parse_manifest(
               {"version": 1, "required": {"../x.jsonl": {"kind": "jsonl", "schema_version": 1}}})),
           "valid": outcome(lambda: snap.verify_snapshot(good, MANIFEST)),
           "broken": outcome(lambda: snap.verify_snapshot(broken, MANIFEST)),
           "dangling": outcome(lambda: snap.verify_snapshot(dangling, MANIFEST)),
           "missing": outcome(lambda: snap.verify_snapshot(missing, MANIFEST)),
           "lenient": outcome(lambda: snap.verify_snapshot(broken, MANIFEST, mode="lenient"))}
    imports = api.SnapshotImports(api.MemoryStore(), api.FileArtifacts(str(work / "snap-artifacts")))
    binding = {"source_revision": "a" * 40, "tool_revision": "b" * 40, "environment": "linux"}
    out["import_valid"] = outcome(lambda: imports.import_snapshot(good, MANIFEST, binding=binding))
    out["import_again"] = outcome(lambda: imports.import_snapshot(good, MANIFEST, binding=binding))
    out["import_broken"] = outcome(lambda: imports.import_snapshot(broken, MANIFEST, binding=binding))
    out["import_bad_binding"] = outcome(lambda: imports.import_snapshot(good, MANIFEST, binding={}))
    return out


def privacy(api, work: Path) -> dict:
    p = api.privacy
    policy_hash = p.parse_policy(PROFILE_POLICY)["policy_hash"]

    def consent(choice="grant", at="2026-09-10T00:00:00+00:00", projects=(PROJECT,)):
        return {"user": "u1", "choice": choice, "policy_hash": policy_hash, "at": at, "projects": list(projects)}

    granted = p.parse_consent(consent(), PROFILE_POLICY)
    out = {"policy": outcome(lambda: p.parse_policy(PROFILE_POLICY)),
           "external_claim": outcome(lambda: p.parse_policy({**PROFILE_POLICY, "model": {"name": "r",
                                                                                          "transport": "external"}})),
           "consent": granted,
           "consent_other_policy": outcome(lambda: p.parse_consent({**consent(), "policy_hash": "f" * 64},
                                                                   PROFILE_POLICY)),
           "scan": outcome(lambda: p.scan("mail me@example.com with token sk-" + "z" * 24 + " at /home/sentinel-user/x")),
           "minimize": {name: outcome(lambda: p.minimize(record, PROFILE_POLICY, granted)) for name, record in {
               "ready": {"content": "I prefer short diffs", "project_path": PROJECT, "kind": "user_message"},
               "blocked": {"content": "use password: hunter2-sentinel please", "project_path": PROJECT,
                           "kind": "user_message"},
               "other_project": {"content": "x", "project_path": "/home/other/p", "kind": "user_message"},
               "assistant": {"content": "x", "project_path": PROJECT, "kind": "assistant_message"}}.items()},
           "render_findings": outcome(lambda: p.check_render(
               {"dimensions": {"x": {"evidence": [{"quote": "q"}], "summary": "see /home/sentinel-user/z"}}})),
           "render_extra": outcome(lambda: p.check_render({"dimensions": {"x": {"evidence": []}}, "raw_dump": 1}))}
    flow = api.ProfileFlow(api.MemoryStore(), api.ProfileScratch(work / "scratch"))
    records = [{"content": "I prefer short diffs", "project_path": PROJECT, "kind": "user_message"},
               {"content": "token sk-" + "z" * 24 + " here", "project_path": PROJECT, "kind": "user_message"},
               {"content": "x", "project_path": "/home/other/p", "kind": "user_message"}, "garbage"]
    binding = {"source_revision": "a" * 40, "environment": "linux"}
    lease = "2999-01-01T00:00:00+00:00"
    steps = {"no_consent": outcome(lambda: flow.prepare_model_input("run-1", owner="w1", user="u1",
                                                                    policy=PROFILE_POLICY, records=records,
                                                                    binding=binding, lease_until=lease))}
    steps["consent"] = outcome(lambda: flow.record_consent(PROFILE_POLICY, consent(at="2026-09-10T00:00:01+00:00")))
    steps["ready"] = outcome(lambda: flow.prepare_model_input("run-1", owner="w1", user="u1", policy=PROFILE_POLICY,
                                                              records=records, binding=binding, lease_until=lease))
    steps["render"] = outcome(lambda: flow.render("run-1", {"dimensions": {"x": {"evidence": [{"quote": "q"}]}}}))
    steps["finish_other"] = outcome(lambda: flow.finish("run-1", "w2"))
    steps["finish"] = outcome(lambda: flow.finish("run-1", "w1"))
    out["flow"] = relative(steps, {"WORK": str(work)})
    return out


def promotion(api) -> dict:
    store = api.MemoryStore()
    graph = {"repository": "verified:run-1",
             "nodes": [{"id": "verified:run-1:n1", "repository": "verified:run-1", "kind": "claim", "body": "b",
                        "source_ref": "s", "revision": "r", "properties": {}}],
             "edges": [{"source": "verified:run-1:n1", "target": "verified:run-1:n1", "kind": "self"}]}
    with store.transaction() as tx:
        first = outcome(lambda: api.promote(tx, "run-1", graph, {"decision_id": "d1"}))
        cached = outcome(lambda: api.promote(tx, "run-1", graph, {"decision_id": "d1"}))
        conflict = outcome(lambda: api.promote(tx, "run-1", {**graph, "edges": []}, {}))
        namespace = outcome(lambda: api.promote(tx, "run-2", graph, {}))
    try:
        with store.transaction() as tx:
            api.promote(tx, "run-3", {**graph, "repository": "verified:run-3"}, {})
            raise RuntimeError("commit failure (fixture)")
    except RuntimeError:
        pass
    with store.transaction() as tx:
        rolled_back = {"receipt": tx.get("promotions", "run-3"), "nodes": len(tx.scan("knowledge_nodes"))}
    return {"first": first, "cached": cached, "conflict": conflict, "namespace": namespace, "rollback": rolled_back}


def code_graph(api) -> dict:
    if GRAPH_ROOT.exists():
        if not (GRAPH_ROOT / GRAPH_MARKER).exists():
            raise SystemExit(f"{GRAPH_ROOT} exists and is not a labelled disposable S2 root")
        shutil.rmtree(GRAPH_ROOT)
    (GRAPH_ROOT / "src" / "pkg").mkdir(parents=True)
    (GRAPH_ROOT / GRAPH_MARKER).write_text("disposable\n", encoding="utf-8")
    (GRAPH_ROOT / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (GRAPH_ROOT / "src" / "pkg" / "core.py").write_text(
        "import os\nfrom pkg import util\n\nclass Store:\n    def get(self, key):\n        return util.clean(key)\n\n"
        "def run():\n    return Store().get('k')\n", encoding="utf-8")
    (GRAPH_ROOT / "src" / "pkg" / "util.py").write_text("def clean(value):\n    return value.strip()\n",
                                                        encoding="utf-8")
    try:
        graph = outcome(lambda: api.extract_python(str(GRAPH_ROOT)))
        (GRAPH_ROOT / "src" / "pkg" / "bad.py").write_text("def broken(:\n", encoding="utf-8")
        broken = outcome(lambda: api.extract_python(str(GRAPH_ROOT)))
    finally:
        shutil.rmtree(GRAPH_ROOT)
    if "ok" in graph:
        value = graph["ok"]
        graph = {"ok": {"keys": sorted(value), "nodes": len(value.get("nodes", [])),
                        "edges": len(value.get("edges", [])), "sha256": sha(value),
                        "node_ids": sorted(n["id"] for n in value.get("nodes", []))}}
    return {"graph": graph, "parse_error": broken,
            "missing_root": outcome(lambda: api.extract_python(str(GRAPH_ROOT / "absent"))),
            "embeddings_empty": outcome(lambda: api.LocalEmbeddings("/nonexistent-models").embed([]))}


def run(api, work: Path) -> dict:
    parts = {}
    for name, fn in (("seams", lambda: seams(api, work)), ("experience", lambda: experience(api, work)),
                     ("snapshots", lambda: snapshots(api, work)), ("privacy", lambda: privacy(api, work)),
                     ("promotion", lambda: promotion(api)), ("code_graph", lambda: code_graph(api))):
        parts[name] = fn()
    # Whole records include scripted timestamps and fixed paths: compared by value, and by digest per part.
    return {"parts": json.loads(json.dumps(parts, sort_keys=True, default=str)),
            "part_sha256": {name: sha(value) for name, value in sorted(parts.items())}}
