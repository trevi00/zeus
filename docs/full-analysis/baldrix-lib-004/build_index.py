"""Inert metadata recorder: never imports or executes upstream source code."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/full-analysis/baldrix-lib-004"
BASE = ROOT / ".runtime/absorption/sources/baldrix"
manifest = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
index = {row["path"]: row for row in manifest["inventory"]}
scope = json.loads((OUT / "inventory.json").read_text(encoding="utf-8"))
partitions = json.loads((ROOT / "docs/full-analysis/partitions.json").read_text(encoding="utf-8"))
assert scope == next(row for row in partitions if row["partition"] == scope["partition"])
assert scope["scope_sha256"] == "a425e01613dffed3bdba907af81db84992401d176dba7f531b4852173e6747e8"
assert manifest["revision"] == "cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2"

SUPPORTS = [
    ("scripts/cli/graduate_validator.py", [(65, 145)], "Tick, history consumer and direct graduate success output."),
    ("scripts/validators/__init__.py", [(70, 123)], "Import-time registry and direct scan adapter."),
    ("scripts/lib/brain_store.py", [(269, 306)], "Snapshot restoration calling restore_streak."),
    ("scripts/cron/scheduler_driver.py", [(140, 160)], "Scheduled maintenance registration of graduation tick."),
    ("scripts/cli/meeting_ingest.py", [(40, 83)], "Grounding caller, deficit forwarding and human-approved help text."),
    ("scripts/cron/run_ledger_compaction.py", [(75, 148)], "Archive then live replacement, ack and flag consumption."),
    ("scripts/cli/reverse_engineer.py", [(180, 227)], "Post-write floor, no_roundtrip condition and rollback."),
    ("scripts/tests/test_graduation.py", [(88, 130), (147, 195)], "Injected watermark and ready-only graduation fixtures."),
    ("scripts/tests/test_l2_promoter.py", [(203, 293)], "Frame mocks, cascade cases and ID-set-only idempotency oracle."),
    ("scripts/cron/probe_hook_latency.py", [(44, 76)], "Non-None samples recorded; no success/warning field persisted."),
    ("scripts/cron/run_l2_promotion.py", [(124, 185)], "Wrapper exception handling and promotion acknowledgement."),
    ("scripts/cli/insight_index_pollution_detector.py", [(54, 100), (111, 157)], "Measure versus detect parameters; unconditional flag consumption after loop."),
    ("scripts/handlers/stop/learner.py", [(120, 185)], "Assistant summary to L1 digest and unchecked append return."),
    ("scripts/handlers/session/init.py", [(60, 68), (108, 127), (350, 367)], "Handoff constant use, separate bounded reader and graduation tick."),
    ("scripts/handlers/pre_tool/guard.py", [(52, 69), (213, 243)], "Pattern imports, solo override and command rewrite."),
    ("scripts/cli/heartbeat_check.py", [(32, 101)], "Invalid timestamps skipped and unavailable module-level event emitter."),
    ("scripts/lib/phase_tree.py", [(39, 47), (94, 120), (251, 278)], "Status enum, promotion heuristic and parser default."),
    ("commands/harness-audit.md", [(50, 68)], "Documented audit command and LLM scoring instructions treated as data."),
    ("scripts/cli/dashboard_model.py", [(143, 176)], "Direct import_graph consumer scans twice."),
    ("scripts/tests/test_jsonl_cache.py", [(25, 70)], "Malformed rows, same-object caching and append invalidation oracles."),
    ("scripts/lib/golden_signals.py", [(182, 216)], "Actual probe subprocess setup; failed probes retain numeric values."),
    ("scripts/handlers/prompt/mode_detector.py", [(102, 133)], "Actual additional_context caller and fail-open top-level handling."),
    ("scripts/tests/test_guard_patterns.py", [(162, 187)], "Quoted heredoc no-warning oracle and historical limitation claim."),
    ("scripts/lib/event_store.py", [(1, 117)], "Fresh full body read confirms only EventStore.append, no module-level append."),
    ("scripts/lib/evaluator_dispatcher.py", [(946, 998), (1193, 1215)], "Self-reported completeness and assistive-only verifier contrasted with meta-rule labels."),
    ("settings.json", [(306, 317)], "Absolute Windows SessionStart path and 5-second timeout only."),
]

LINKS = [
    [1, 2, 3, 4, 8, 14], [1], [5], [15, 23], [17], [14, 26], [18],
    [16, 24], [22], [10, 21, 26], [19], [13], [12], [7], [20],
    [9, 11], [9, 11], [6], [25],
]


def metadata(path, ranges):
    raw = (BASE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    row = index[path]
    total_lines = len(raw.decode("utf-8").splitlines())
    expected = row.get("snapshot_sha256")
    assert blob == row["object"], path
    assert len(raw) == row["bytes"], path
    assert expected is None or sha == expected, path
    assert all(1 <= start <= end <= total_lines for start, end in ranges), path
    return {
        "source": "baldrix", "path": path, "revision": manifest["revision"],
        "bytes": len(raw), "git_blob": blob, "raw_git_blob_status": "matched",
        "pinned_sha256": sha, "observed_sha256": None,
        "manifest_sha256": expected,
        "manifest_sha256_status": "matched" if expected else "absent_computed_only",
        "read_ranges": ranges, "total_lines": total_lines,
        "body_read_complete": ranges == [(1, total_lines)],
    }


supports = []
for number, (path, ranges, purpose) in enumerate(SUPPORTS, 1):
    row = metadata(path, ranges)
    row.update({
        "id": f"s{number:02}", "purpose": purpose, "counted_as_primary": False,
        "read_basis": "Fresh source body/ranges read this turn; no prior full-body reuse claimed.",
        "prior_ref": None, "tests_executed": [],
        "test_limits": "Static oracle/fixture/caller analysis only; upstream execution/import 0.",
    })
    supports.append(row)

files = []
for number, item in enumerate(scope["paths"], 1):
    path = item["path"]
    total_lines = len((BASE / "pinned" / path).read_bytes().decode("utf-8").splitlines())
    row = metadata(path, [(1, total_lines)])
    row.update({
        "partition": scope["partition"], "partition_scope_sha256": scope["scope_sha256"],
        "disposition": "body_reviewed_call_test_trace_pending",
        "primary_status": "body_reviewed_call_test_trace_pending",
        "review_ref": f"docs/full-analysis/baldrix-lib-004/review.md#f{number:02}",
        "supporting_ids": [f"s{support:02}" for support in LINKS[number - 1]],
        "read_basis": "Fresh full primary body read; no prior full-body reuse.",
        "tests_executed": [],
        "test_limits": "No upstream execution/import/probe/network/install. Own metadata and lint checks are not source test receipts.",
        "tests_not_run": ["All upstream tests, embedded self-checks and probes unexecuted."],
        "remaining": [
            "See per-file review for untraced callers/config/tests and static inference limits.",
            "Full closure, actual human acceptance, model qualification, current vendor behavior, actual Claude joint review, licensing, platform validation and adoption remain pending.",
        ],
        "adoption_approved": False,
    })
    files.append(row)

assert len(files) == 19 and len({row["path"] for row in files}) == 19
assert sum(row["bytes"] for row in files) == 197421
assert not ({row["path"] for row in files} & {row["path"] for row in supports})
review = (OUT / "review.md").read_text(encoding="utf-8")
assert all(f'<a id="f{number:02}"></a>' in review for number in range(1, 20))
checkpoint = {
    "partition": scope["partition"], "revision": manifest["revision"],
    "primary_count": 19, "primary_bytes": 197421,
    "primary_bodies_read": 19, "primary_body_pending": 0,
    "primary_hashes_matched": 19, "primary_raw_git_blobs_matched": 19,
    "supporting_unique_files": len(supports),
    "supporting_full_bodies": sum(row["body_read_complete"] for row in supports),
    "supporting_partial_bodies": sum(not row["body_read_complete"] for row in supports),
    "supporting_manifest_sha_absent": [row["path"] for row in supports if row["manifest_sha256"] is None],
    "upstream_execution_count": 0, "upstream_import_count": 0,
    "upstream_test_count": 0, "probe_count": 0, "network_count": 0, "installation_count": 0,
    "metadata_checks": ["Exact partition equality", "Raw bytes/SHA-256/Git blob", "Unique paths and ranges", "UTF-8 JSON and review anchors"],
    "own_ruff": "See validation.json; applies only to this metadata recorder.",
    "full_transition_closure": False, "actual_claude_joint_review": False,
    "actual_host_validation": False, "licensing_complete": False,
    "adoption_approved": False, "bounded_static_checkpoint_complete": True,
    "shared_coverage_edited": False, "source_or_runtime_edited": False,
    "commit_or_push": False, "remaining_ref": "docs/full-analysis/baldrix-lib-004/remaining.md",
}
for name, value in [("files.json", files), ("supporting.json", supports), ("checkpoint.json", checkpoint)]:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(checkpoint, ensure_ascii=False, indent=2))
