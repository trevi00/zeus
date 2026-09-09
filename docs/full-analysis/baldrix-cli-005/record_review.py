"""Record exact source identity and bounded reader coverage; do not execute upstream."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / ".runtime/absorption/sources/baldrix"
MANIFEST = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
INVENTORY = {row["path"]: row for row in MANIFEST["inventory"]}


def record(path, ranges=None):
    item = INVENTORY[path]
    raw = (BASE / "pinned" / path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    assert len(raw) == item["bytes"]
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item["object"]
    expected = item.get("snapshot_sha256")
    if expected:
        assert sha == expected
    lines = len(raw.decode("utf-8-sig").splitlines())
    extent = "full_body" if ranges is None else "explicit_supporting_ranges"
    if ranges is None:
        ranges = [[1, lines]] if lines else []
    assert all(1 <= start <= end <= lines for start, end in ranges)
    return {
        "source": "baldrix", "revision": MANIFEST["revision"], "path": path,
        "bytes": len(raw), "git_blob": item["object"], "pinned_sha256": sha,
        "matches_manifest_sha256": sha == expected if expected else None,
        "line_count": lines, "read_ranges": ranges, "read_extent": extent,
        "reader": "Codex root", "disposition": "body_reviewed_call_test_trace_pending",
        "review_ref": "docs/full-analysis/baldrix-cli-005/resolution.md",
        "remaining": ["Complete effective registration and transitive callers/config/tests", "Independent platform and acceptance validation", "License/provenance and Zeus implementation/qualification decision"],
    }


def main():
    primary = [record("scripts/cli/" + name + ".py") for name in (
        "team_watch", "telemetry_report", "threshold_override", "trending",
        "validate_project", "writeback_inspect",
    )]
    support = [record(path) for path in (
        "scripts/lib/telemetry_read.py", "scripts/lib/threshold_policy.py",
        "scripts/lib/paths.py", "scripts/lib/__init__.py", "scripts/cli/__init__.py",
        "scripts/tests/__init__.py", "scripts/tests/test_telemetry_report.py",
        "scripts/lib/writeback_token.py", "scripts/lib/writeback_parser.py",
        "scripts/lib/path_denylist.py", "scripts/lib/writeback_apply.py",
    )]
    support.extend(record(path, ranges) for path, ranges in (
        ("scripts/lib/resident_store.py", [[1, 150], [250, 399]]),
        ("scripts/tests/test_validate_project.py", [[1, 110]]),
        ("scripts/lib/team_mailbox.py", [[1, 80], [171, 200]]),
        ("commands/harness-team.md", [[108, 187]]),
        ("scripts/lib/calibration/threshold_registry.py", [[1, 140]]),
        ("scripts/lib/pending_changes.py", [[1, 65], [352, 415], [511, 568]]),
    ))
    assert len(primary) == 6 and sum(row["bytes"] for row in primary) == 83631
    for name, value in (("files.json", primary), ("supporting-evidence.json", support)):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    checkpoint = {
        "partition": "baldrix:scripts/cli:005", "primary_paths": 6,
        "primary_bytes": 83631, "primary_bodies_complete": True,
        "supporting_paths": len(support), "supporting_full": 11, "supporting_partial": 6,
        "source_hashes_verified": True, "original_unit_tests": {"module": "test_telemetry_report", "passed": 19, "failed": 0},
        "original_component_runs": ["UTC0", "KST-9"],
        "original_writeback_policy_worker_executions": 0,
        "whole_analysis_complete": False, "partition_complete": False,
        "adoption_approved": False, "runtime_implemented": False,
        "limits": "Root unit/component execution is separate from Claude static review. No E2E, real user/device, live source mutation, or Windows/WSL upstream execution. Supporting records do not increase primary coverage.",
    }
    (OUT / "checkpoint.json").write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(checkpoint))


if __name__ == "__main__":
    main()
