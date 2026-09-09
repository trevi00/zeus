"""Bind bounded breaker reads to pinned Git bytes without executing source."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-breakers-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/breakers/" + name + ".py") for name in ("__init__", "composite", "config")]
    support = [record(path, ranges) for path, ranges in (
        ("scripts/lib/atomic_json.py", None),
        ("scripts/cli/breaker_override.py", None),
        ("scripts/tests/test_composite_breaker.py", None),
        ("scripts/tests/test_breaker_config.py", None),
        ("scripts/handlers/post_tool/agent_outcome_audit.py", [[382, 456]]),
        ("scripts/engine/external_jury.py", [[132, 201]]),
        ("scripts/tests/test_external_jury_retry.py", [[140, 186]]),
    )]
    assert sum(row["bytes"] for row in primary) == 28465
    scope = [{"source": row["source"], "revision": row["revision"], "path": row["path"], "sha256": row["pinned_sha256"]} for row in primary]
    checkpoint = {
        "partition": "baldrix:scripts/lib/breakers:001",
        "scope_sha256": "486f22b87fc9e170e280e10691430fa2dc270c00702cb7a0fe8a6037fde74551",
        "record_scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        "record_scope_hash_encoding": "Python json.dumps(scope, sort_keys=True), UTF-8",
        "scope_items": scope, "primary_count": 3, "primary_bytes": 28465,
        "primary_body_read_complete": True, "root_supporting_count": 7,
        "root_supporting_full": 4, "root_supporting_partial": 3,
        "original_unit_modules_executed": 2, "original_unit_tests_passed": 34,
        "original_component_programs_completed": 1,
        "unit_fixture_limits": "Injected clocks/emitter callbacks/config module path plus real temporary files. Not concurrent-process or model/human acceptance.",
        "component_limits": "Real isolated JSON/YAML/filesystem permission faults and original methods. No clock/method/provider patch. Stale seeded record is not actual holder death or concurrent-process test.",
        "actual_provider_model_invocations": 0, "whole_analysis_complete": False,
        "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": len(primary), "support": len(support), "bytes": 28465}))


if __name__ == "__main__":
    main()
