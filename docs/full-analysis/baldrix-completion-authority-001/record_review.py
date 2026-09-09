"""Record full primary bodies and exact supporting reading, without source imports."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None, prior=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-completion-authority-001/resolution.md"
    if prior:
        row["prior_body_read_ref"] = prior
    return row


def main():
    primary = [record("scripts/lib/" + name + ".py") for name in ("ac_tree", "axis_scores_log", "completion_gate", "coverage_gate")]
    support = [record(path, spans) for path, spans in (
        ("scripts/lib/evaluator_dispatcher.py", [[590, 638], [694, 751]]),
        ("commands/harness-autopilot.md", [[75, 91], [94, 112], [191, 243], [271, 288]]),
        ("commands/harness-evaluate.md", [[147, 161]]),
        ("scripts/tests/test_ac_tree.py", None),
        ("scripts/tests/test_axis_scores_log.py", [[1, 155]]),
        ("scripts/validators/coverage_gate.py", None),
        ("scripts/cli/meeting_ingest.py", [[1, 96]]),
        ("scripts/lib/paths.py", [[100, 150], [203, 235]]),
        ("scripts/cli/milestone_step.py", [[175, 217]]),
    )]
    support.extend((
        record("scripts/handlers/stop/autopilot_continue.py", prior="docs/full-analysis/baldrix-stop-001/files.json"),
        record("scripts/lib/event_store.py", prior="docs/full-analysis/baldrix-engine-001/supporting-evidence.json"),
    ))
    assert sum(r["bytes"] for r in primary) == 39337
    scope = [{"source": r["source"], "revision": r["revision"], "path": r["path"], "sha256": r["pinned_sha256"]} for r in primary]
    checkpoint = {
        "scope": "baldrix completion authority semantic slice; lib001/lib002 remain partial",
        "scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        "scope_hash_encoding": "Python json.dumps(scope, sort_keys=True), UTF-8",
        "scope_items": scope, "primary_count": 4, "primary_bytes": 39337,
        "primary_body_read_complete": True, "supporting_count": 11, "prior_reads_explicit": 2,
        "original_completion_selfcheck_assertions": 28, "original_component_programs": 1,
        "original_unit_test_modules_executed": 1, "original_ac_unit_tests_passed": 17,
        "actual_model_evaluator_or_host_executions": 0,
        "whole_analysis_complete": False, "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(checkpoint))


if __name__ == "__main__":
    main()
