"""Bind selected fresh re-reviews and direct supporting source ranges."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-test-runners-001/resolution.md"
    return row


def main():
    prior_path = ROOT / "docs/full-analysis/baldrix-tests-001/files.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    rows = []
    for name in ("run_all.py", "run_units.py", "conftest.py"):
        row = record("scripts/tests/" + name)
        previous = next(x for x in prior if x["path"] == row["path"])
        assert previous["pinned_sha256"] == row["pinned_sha256"]
        row["fresh_full_reread"] = True
        row["global_primary_increment"] = 0
        row["prior_primary"] = {
            "ledger": prior_path.relative_to(ROOT).as_posix(),
            "ledger_sha256": hashlib.sha256(prior_path.read_bytes()).hexdigest(),
            "row": previous, "review_ref": previous["review_ref"],
            "review_sha256": hashlib.sha256((ROOT / previous["review_ref"].split("#")[0]).read_bytes()).hexdigest(),
        }
        rows.append(row)
    support = [record(p) for p in (
        "scripts/validators/__init__.py", "scripts/lib/telemetry_log.py", "scripts/lib/paths.py",
        "scripts/tests/test_autopilot_compaction.py", "scripts/lib/autopilot_compaction.py",
        "scripts/install_pre_commit.sh", ".github/workflows/ci.yml", "scripts/cli/state_leak_check.py",
        "scripts/cli/canary_apply.py",
    )]
    support.append(record("scripts/lib/graduation.py", [[1, 165], [196, 220]]))
    checkpoint = {
        "kind": "selected_prior_primary_fresh_rereview", "source_partition": "baldrix:scripts/tests:001",
        "primary_files": 3, "primary_bytes": 34092, "new_global_primary_files": 0,
        "supporting_records": 10, "supporting_full": 9, "supporting_partial": 1,
        "original_compaction_manual_tests_passed": 6, "full_original_suites_executed": 0,
        "original_helper_observation_programs": 1, "mocked_provider_or_method_results": 0,
        "original_helper_observation_executions": 2,
        "actual_claude_review_and_discussion_processes": 2,
        "recorder_fault_and_control_processes": 7,
        "whole_analysis_complete": False, "adoption_approved": False,
    }
    for name, value in (("rereviewed-files.json", rows), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"fresh_rereview": len(rows), "new_global_primary": 0, "support": len(support)}))


if __name__ == "__main__":
    main()
