"""Bind bounded root body reads to the pinned source; no upstream execution."""
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-seams-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/seams/" + name + ".py") for name in
               ("__init__", "base", "java_socket", "dart_socket", "proto", "parity", "transform")]
    support = [record(path) for path in (
        "scripts/lib/extractors/base.py", "scripts/tests/test_seams.py",
        "scripts/cli/seam_scan.py", "scripts/validators/seam_parity_drift.py",
        "scripts/validators/__init__.py", "scripts/lib/paths.py",
        "scripts/lib/telemetry_log.py", "scripts/cli/seam_gate.py",
        "atlas/seam-registry/seams.spec.yaml",
    )]
    support.append(record("scripts/lib/graduation.py", [[1, 125], [199, 216]]))
    assert sum(r["bytes"] for r in primary) == 24216
    checkpoint = {
        "partition": "baldrix:scripts/lib/seams:001",
        "scope_sha256": "bdb8b8af3b18af7b8b51c423b22f613a6bc56670e522a28bda0aaec9731d2020",
        "primary_count": 7, "primary_bytes": 24216, "primary_body_read_complete": True,
        "root_supporting_count": 10, "root_supporting_fresh_full": 9,
        "root_supporting_fresh_partial": 1, "prior_read_reused": 0,
        "original_unit_attempts": [
            {"prefix": "seams-unit", "passed": 22, "failed": 4, "returncode": 1,
             "reason": "Image lacks yaml; four CLI import paths fail. Failure preserved."},
            {"prefix": "seams-unit-with-yaml", "passed": 26, "failed": 0, "returncode": 0,
             "reason": "Existing immutable image with YAML, overridden service entrypoint, same isolation."},
        ],
        "original_component_programs_completed": 1, "actual_provider_model_task_invocations": 0,
        "execution_limits": "Original functions and actual synthetic scratch files. No method/provider patch, fleet/compiler/wire/human/device/native WindowsWSL acceptance.",
        "whole_analysis_complete": False, "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": 7, "support": 10, "bytes": 24216}))


if __name__ == "__main__":
    main()
