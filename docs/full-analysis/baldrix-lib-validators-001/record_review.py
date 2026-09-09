"""Record exact primary bodies and joined fresh/prior caller reads; no source execution."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-lib-validators-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/validators/" + name + ".py") for name in ("__init__", "boilerplate", "cross_ref", "semantic", "structural")]
    support = [record("scripts/tests/test_" + name + ".py") for name in ("structural", "semantic", "cross_ref", "boilerplate")]
    caller = record("scripts/handlers/post_tool/agent_outcome_audit.py")
    prior_path = ROOT / "docs/full-analysis/baldrix-observers-001/supporting-evidence.json"
    prior = next(r for r in json.loads(prior_path.read_text(encoding="utf-8")) if r["path"] == caller["path"])
    assert prior["pinned_sha256"] == caller["pinned_sha256"]
    caller["read_basis"] = "Joined current reads 1-39 and 137-219 with exact prior observer reads 40-136 and 219-471; not a second fresh full read"
    caller["prior_read_evidence"] = {
        "ledger": prior_path.relative_to(ROOT).as_posix(), "ledger_sha256": digest(prior_path.read_bytes()),
        "row": prior, "review_ref": prior["review_ref"],
        "review_sha256": digest((ROOT / prior["review_ref"]).read_bytes()),
        "current_fresh_ranges": [[1, 39], [137, 219]],
    }
    support.append(caller)
    support.extend((record("scripts/lib/operator_ledger.py", [[211, 276]]), record("scripts/lib/calibration/proposer.py", [[78, 177]])))
    assert sum(r["bytes"] for r in primary) == 39639
    checkpoint = {
        "partition": "baldrix:scripts/lib/validators:001",
        "scope_sha256": "472776938cb3976606c189d8a3817afc613c25029036b6a11f0fd390309c035b",
        "primary_count": 5, "primary_bytes": 39639, "primary_body_read_complete": True,
        "root_supporting_count": 7, "root_supporting_fresh_full": 4,
        "root_supporting_fresh_partial": 2, "root_supporting_joined_current_prior_full": 1,
        "original_unit_modules_executed": 4, "original_unit_tests_passed": 61,
        "original_component_programs_completed": 1, "actual_provider_model_invocations": 0,
        "execution_limits": "Actual original functions and isolated files with synthetic schemas/summaries/evidence. No method/clock/subprocess/provider patch; no historical claim truth, host hook/ledger, model/human/nativeWindowsWSL acceptance.",
        "whole_analysis_complete": False, "partition_complete": False, "adoption_approved": False,
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"primary": 5, "support": 7, "bytes": 39639}))


if __name__ == "__main__":
    main()
