"""Bind bounded calibration reads to pinned Git bytes without executing source."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-calibration-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/calibration/" + name + ".py") for name in ("__init__", "breaker_proposer", "proposer", "threshold_metrics", "threshold_proposer", "threshold_registry")]
    support = [record(path, ranges) for path, ranges in (
        ("scripts/lib/no_degradation_gate.py", None),
        ("scripts/lib/threshold_policy.py", None),
        ("scripts/tests/test_threshold_tuning.py", None),
        ("scripts/lib/operator_ledger.py", [[71, 137]]),
        ("scripts/lib/skill_token_budget.py", None),
        ("scripts/handlers/prompt/skill_match.py", [[40, 67], [391, 474]]),
    )]
    assert sum(row["bytes"] for row in primary) == 43851
    scope = [{"source": row["source"], "revision": row["revision"], "path": row["path"], "sha256": row["pinned_sha256"]} for row in primary]
    checkpoint = {
        "partition": "baldrix:scripts/lib/calibration:001",
        "scope_sha256": "6e068fc63c99a989ac5c2f321cc0f61777e09a62ae16eb994a7d04aa6d37309c",
        "record_scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        "record_scope_hash_encoding": "Python json.dumps(scope, sort_keys=True), UTF-8",
        "scope_items": scope, "primary_count": 6, "primary_bytes": 43851,
        "primary_body_read_complete": True, "root_supporting_count": 6,
        "root_supporting_full": 4, "root_supporting_partial": 2,
        "original_unit_modules_executed": 1, "original_unit_tests_passed": 16,
        "original_component_programs_completed": 1,
        "unit_fixture_limits": "Original unit injects registry/path and telemetry fixtures with real methods/temp files; not human/model/concurrency acceptance.",
        "component_limits": "Original methods, real isolated JSON/YAML/ready flags, synthetic events and literal source policy tokens. No clock/method/provider patch; not actual user approval, consumer relevance or OS concurrency.",
        "actual_provider_model_invocations": 0, "whole_analysis_complete": False,
        "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": len(primary), "support": len(support), "bytes": 43851}))


if __name__ == "__main__":
    main()
