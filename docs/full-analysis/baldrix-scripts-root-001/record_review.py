"""Bind exact root-script primary/supporting reads to immutable source bytes."""
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-scripts-root-001/resolution.md"
    return row


def main():
    primary = [record("scripts/" + name) for name in (
        "context-bar.sh", "file-changed-handler.py", "install_pre_commit.sh",
        "jacoco-gap.py", "mermaid-validate.py",
    )]
    support = [record("scripts/tests/test_install_hooks.py"), record(".github/workflows/ci.yml")]
    support.extend(record(path, ranges) for path, ranges in (
        ("scripts/handlers/post_tool/reviewer.py", [[1, 444]]),
        ("scripts/handlers/session/init.py", [[1, 121], [791, 843]]),
        ("settings.json", [[319, 349]]),
        ("skills/java/springboot-3.2/testing.md", [[21, 53], [157, 186]]),
    ))
    assert sum(r["bytes"] for r in primary) == 26711
    checkpoint = {
        "partition": "baldrix:scripts:001",
        "scope_sha256": "88f312e063cef98546adc6c289ba4b0670596f45b361f52b9790626619ca4d34",
        "primary_count": 5, "primary_bytes": 26711, "primary_body_read_complete": True,
        "root_supporting_count": 6, "root_supporting_fresh_full": 2,
        "root_supporting_fresh_partial": 4, "prior_read_reused": 0,
        "original_unit_tests_passed": 5, "unit_oracle": "Static installer-text assertions, not installed-hook execution",
        "original_component_programs_completed": 1,
        "component_scope": "Actual original CLI processes on synthetic files and actual ephemeral Git repo/worktree hook installation. Missing-jq original Bash failure observed separately from passing unit tests.",
        "actual_push_or_full_generated_hook_suite_executions": 0,
        "actual_provider_model_task_invocations": 0,
        "whole_analysis_complete": False, "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": 5, "support": 6, "bytes": 26711}))


if __name__ == "__main__":
    main()
