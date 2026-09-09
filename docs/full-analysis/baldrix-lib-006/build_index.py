"""Metadata-only recorder. Does not import or execute pinned source."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REL = OUT.relative_to(ROOT).as_posix()
SOURCE = ROOT / ".runtime/absorption/sources/baldrix"
REV = "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2"
STATUS = "body_reviewed_call_test_trace_pending"
SUPPORT = [
    ("scripts/handlers/prompt/context_load.py", [[90, 125]], "pipeline summary caller"),
    ("scripts/handlers/prompt/skill_match.py", [[306, 345]], "origin and phase caller"),
    ("scripts/handlers/post_tool/reviewer.py", [[235, 265], [485, 520]], "ratio and repeat caller"),
    ("scripts/handlers/stop/autopilot_continue.py", [[177, 207], [270, 323]], "reflection caller"),
    ("scripts/lib/no_degradation_gate.py", [[1, 77]], "probe acceptance consumer"),
    ("scripts/tests/test_repro_probe.py", [[1, 80]], "classification oracle only"),
    ("skills/_pipeline/stages.yaml", [[1, 150]], "declared gate versus existence"),
    ("scripts/tests/test_pipeline_stage_picker.py", [[1, 90]], "existence oracle and fixture"),
    ("scripts/tests/test_quota_tracker.py", [[1, 62], [82, 147]], "sequential and corrupt oracle"),
    ("scripts/tests/test_psmux.py", [[1, 60], [294, 337]], "host dependency and skip branch"),
    ("scripts/lib/strike_dispatcher.py", [[50, 115]], "raise policy consumer"),
    ("scripts/lib/evaluator_dispatcher.py", [[147, 188]], "empty policy consumer"),
    ("scripts/cli/phase_graph.py", [[25, 86]], "graph build and strict query caller"),
    ("scripts/handlers/post_tool/agent_outcome_audit.py", [[425, 471]], "ledger record producer"),
    ("scripts/lib/writeback_parser.py", [[170, 210]], "denylist proposal validation"),
    ("scripts/lib/writeback_apply.py", [[1, 160]], "operator context shape contract"),
    ("scripts/lib/autopilot_kha_bridge.py", [[85, 130], [274, 295]], "phase projection writer"),
    ("scripts/lib/team_runtime.py", [[42, 86]], "psmux argv worker spawn"),
    ("scripts/cli/canary_apply.py", [[30, 126]], "pending changes direct caller"),
    ("scripts/cron/check_ledger_compaction.py", [[90, 120]], "compaction flag follow-up"),
    ("scripts/lib/atomic_json.py", [[1, 127]], "counter write result and atomicity"),
]
LINKS = {
    1: [14, 20], 3: [15, 16], 4: [2], 5: [19], 6: [2], 7: [17],
    8: [13], 9: [13], 12: [1, 7], 13: [7, 8], 14: [1, 7], 15: [7],
    17: [2], 18: [10, 18], 19: [9, 11, 12, 21], 20: [3, 21],
    21: [4], 22: [4], 23: [3, 21], 24: [5, 6],
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(name, data):
    (OUT / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def main():
    manifest_path = SOURCE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory = json.loads((OUT / "inventory.json").read_text(encoding="utf-8"))
    entries = {r["path"]: r for r in manifest["inventory"]}
    assert manifest["revision"] == REV
    partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
    partition = next(r for r in partitions if r.get("partition") == inventory["partition"])
    assert partition == inventory
    review = (OUT / "review.md").read_text(encoding="utf-8")

    def metadata(path, ranges):
        raw = (SOURCE / "pinned" / path).read_bytes()
        entry = entries[path]
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        digest = sha(raw)
        lines = len(raw.decode("utf-8").splitlines())
        assert len(raw) == entry["bytes"] and blob == entry["object"], path
        expected = entry.get("snapshot_sha256")
        assert expected is None or expected == digest, path
        assert all(1 <= start <= end <= lines for start, end in ranges), path
        return {
            "source": "baldrix", "path": path, "revision": REV,
            "bytes": len(raw), "git_blob": blob, "raw_git_blob_status": "matched",
            "pinned_sha256": digest, "observed_sha256": None,
            "manifest_sha256": expected,
            "manifest_sha256_status": "matched" if expected else "absent_computed_only",
            "read_ranges": ranges, "total_lines": lines,
            "body_read_complete": ranges == [[1, lines]],
            "read_basis": "fresh_pinned_body_read",
        }

    supports = []
    for i, (path, ranges, purpose) in enumerate(SUPPORT, 1):
        row = metadata(path, ranges)
        row.update(id=f"s{i:02}", purpose=purpose, counted_as_primary=False, prior_ref=None)
        supports.append(row)
    rows = []
    for i, item in enumerate(inventory["paths"], 1):
        path = item["path"]
        lines = len((SOURCE / "pinned" / path).read_bytes().decode("utf-8").splitlines())
        row = metadata(path, [[1, lines]])
        anchor = f"f{i:02}"
        assert f'id="{anchor}"' in review
        row.update(
            partition=inventory["partition"], partition_scope_sha256=inventory["scope_sha256"],
            disposition=STATUS, primary_status=STATUS,
            review_ref=f"{REL}/review.md#{anchor}",
            supporting_ids=[f"s{n:02}" for n in LINKS.get(i, [])],
            tests_executed=[], test_limits="Static source only; no upstream import, test, probe or host execution.",
            tests_not_run=["all upstream tests", "Windows/Linux/WSL host behavior"],
            remaining=["full caller/config/test closure", "actual Claude and model qualification",
                       "license", "human experience acceptance", "Zeus adoption approval"],
            adoption_approved=False, prior_primary=None,
        )
        if i == 13:
            prior = ROOT / "docs/full-analysis/baldrix-skill-routing-runtime/files.json"
            old = next(r for r in json.loads(prior.read_text(encoding="utf-8")) if r["path"] == path)
            assert old["pinned_sha256"] == row["pinned_sha256"]
            assert old["revision"] == REV
            assert old["git_blob"] == row["git_blob"]
            old_ref = old["review_ref"]
            old_review = ROOT / old_ref.split("#")[0]
            row["prior_primary"] = {
                "ledger": prior.relative_to(ROOT).as_posix(), "ledger_sha256": sha(prior.read_bytes()),
                "row": old, "review_ref": old_ref, "review_sha256": sha(old_review.read_bytes()),
                "same_revision_raw_sha_git_blob": True, "fresh_read_this_task": True,
                "new_primary_coverage": False,
            }
        rows.append(row)
    assert len(rows) == 24 and sum(r["bytes"] for r in rows) == 189781
    assert not ({r["path"] for r in rows} & {r["path"] for r in supports})
    save("files.json", rows)
    save("supporting.json", supports)
    save("checkpoint.json", {
        "partition": inventory["partition"], "revision": REV,
        "scope_sha256": inventory["scope_sha256"], "primary_count": 24, "primary_bytes": 189781,
        "primary_full_body_read": 24, "primary_body_pending": 0, "prior_primary_overlap": 1,
        "new_primary_paths_relative_to_prior_ledger": 23,
        "supporting_count": len(supports),
        "supporting_full_body": sum(r["body_read_complete"] for r in supports),
        "supporting_partial_body": sum(not r["body_read_complete"] for r in supports),
        "upstream_execution": 0, "upstream_import": 0, "upstream_tests": 0,
        "network": 0, "probes": 0, "install": 0,
        "full_semantic_call_test_closure": False, "actual_claude_complete": False,
        "license_complete": False, "platform_validation_complete": False,
        "human_acceptance_complete": False, "adoption_approved": False,
        "metadata_sha_blob_size_ranges_refs": "passed",
        "manifest_sha256": sha(manifest_path.read_bytes()),
        "review_sha256": sha((OUT / "review.md").read_bytes()),
        "own_ruff": "see validation.json", "checkpoint_complete": True,
    })
    for file in OUT.iterdir():
        if file.is_file() and file.suffix in (".json", ".md", ".py"):
            raw = file.read_bytes()
            raw.decode("utf-8")
            assert b"\r\n" not in raw, file
            if file.suffix == ".json":
                json.loads(raw)
    print("metadata PASS: 24 primary, 21 supporting; raw blob/size/SHA/ranges/refs/UTF-8 LF")


if __name__ == "__main__":
    main()
