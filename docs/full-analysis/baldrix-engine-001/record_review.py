"""Bind bounded body/support reading to immutable source bytes; no source execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
BASE = ROOT / ".runtime/absorption/sources/baldrix"
MANIFEST = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
INVENTORY = {row["path"]: row for row in MANIFEST["inventory"]}


def record(path, ranges=None, prior=False):
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
    row = {
        "source": "baldrix", "revision": MANIFEST["revision"], "path": path,
        "bytes": len(raw), "git_blob": item["object"], "pinned_sha256": sha,
        "matches_manifest_sha256": sha == expected if expected else None,
        "line_count": lines, "read_ranges": ranges, "read_extent": extent,
        "reader": "Codex root", "disposition": "body_reviewed_call_test_trace_pending",
        "review_ref": "docs/full-analysis/baldrix-engine-001/resolution.md",
        "remaining": ["Complete transitive callers/config/tests", "Platform and acceptance qualification", "License/provenance and Zeus adoption decision"],
    }
    if prior:
        row["prior_body_read_ref"] = "docs/full-analysis/baldrix-cli-005/supporting-evidence.json"
        row["current_work"] = "Same raw source bytes revalidated; previous full body reading reused explicitly"
    return row


def main():
    primary = [record("scripts/engine/" + name + ".py") for name in (
        "__init__", "cli", "debate", "dispatch_retry", "external_jury", "inventory_scan",
        "jury_advisory", "orchestrator", "prompts", "ralph", "trigger_summary",
    )]
    support = [record(path) for path in (
        "scripts/lib/event_store.py", "scripts/lib/telemetry_log.py",
        "scripts/lib/similarity.py", "scripts/lib/phase_detector.py",
        "scripts/lib/atomic_json.py", "scripts/lib/phase_tree.py",
        "scripts/lib/advisory_ack.py", "scripts/lib/providers/__init__.py",
        "scripts/lib/providers/base.py", "scripts/lib/providers/openai.py",
        "scripts/lib/providers/anthropic.py", "scripts/lib/strike_dispatcher.py",
        "scripts/lib/quota_tracker.py", "scripts/tests/test_dispatch_retry.py",
        "requirements.txt", "commands/harness-ralph.md",
    )]
    support.extend(record(path, prior=True) for path in (
        "scripts/lib/paths.py", "scripts/lib/__init__.py", "scripts/tests/__init__.py",
    ))
    support.extend(record(path, ranges) for path, ranges in (
        ("scripts/lib/completion_gate.py", [[1, 150]]),
        ("scripts/tests/test_orchestrator.py", [[725, 892]]),
        ("commands/harness-debate.md", [[21, 93]]),
        ("commands/harness-autopilot.md", [[1, 90], [240, 319]]),
        ("scripts/handlers/stop/autopilot_continue.py", [[560, 711]]),
    ))
    assert len(primary) == 11 and sum(row["bytes"] for row in primary) == 80138
    checkpoint = {
        "partition": "baldrix:scripts/engine:001",
        "scope_sha256": "07fd9d56ed2e63147bb863375c8bfe7e96202549211df12cb3be48567c298bd2",
        "primary_paths": 11, "primary_bytes": 80138, "primary_bodies_complete": True,
        "supporting_paths": len(support), "supporting_full": 19, "supporting_partial": 5,
        "prior_full_body_reads_explicitly_reused": 3, "source_hashes_verified": True,
        "original_unit_tests": {"module": "test_dispatch_retry", "passed": 6, "failed": 0, "injected_callbacks": True, "acceptance": False},
        "component_attempts": {"dependency_import_failed": 1, "completed_original_function_run": 1, "mocking": False, "temporary_input_fixtures": True},
        "actual_provider_worker_validator_hook_executions": 0,
        "whole_analysis_complete": False, "partition_complete": False,
        "adoption_approved": False, "runtime_implemented": False,
        "limits": "Claude static review and root original unit/component execution are separate. No real user/device/E2E, Windows/WSL upstream execution, original source or live-state mutation. Supporting paths do not increase primary coverage.",
    }
    for name, value in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(checkpoint))


if __name__ == "__main__":
    main()
