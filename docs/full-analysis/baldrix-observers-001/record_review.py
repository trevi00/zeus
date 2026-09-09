"""Bind bounded evidence observer reads to pinned Git bytes without executing source."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-observers-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/observers/" + name + ".py") for name in ("__init__", "evidence_fab")]
    support = [record(path, ranges) for path, ranges in (
        ("scripts/lib/replay/constants.py", None),
        ("scripts/tests/test_evidence_fab.py", None),
        ("scripts/handlers/post_tool/agent_outcome_audit.py", [[40, 136], [219, 471]]),
        ("settings.json", [[250, 279]]),
    )]
    assert sum(row["bytes"] for row in primary) == 7819
    scope = [{"source": row["source"], "revision": row["revision"], "path": row["path"], "sha256": row["pinned_sha256"]} for row in primary]
    checkpoint = {
        "partition": "baldrix:scripts/lib/observers:001",
        "scope_sha256": "3febc60e9994a8aef5daa7e32cf300bcc257c9379549268479d2fd254794ccd1",
        "record_scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        "record_scope_hash_encoding": "Python json.dumps(scope, sort_keys=True), UTF-8",
        "scope_items": scope, "primary_count": 2, "primary_bytes": 7819,
        "primary_body_read_complete": True, "root_supporting_count": 4,
        "root_supporting_full": 2, "root_supporting_partial": 2,
        "original_unit_modules_executed": 1, "original_unit_tests_passed": 11,
        "original_component_programs_completed": 1,
        "unit_fixture_limits": "Original unit invokes real methods, files and controlled children with synthetic claims; RC backoff mutation does not change imported float. Not human/model acceptance.",
        "component_limits": "Original methods and actual isolated files/permissions/controlled Python children; no clock/method/subprocess/provider patch. Synthetic claims do not establish historical fabrication or human/model/OS acceptance.",
        "actual_provider_model_invocations": 0, "whole_analysis_complete": False,
        "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": len(primary), "support": len(support), "bytes": 7819}))


if __name__ == "__main__":
    main()
