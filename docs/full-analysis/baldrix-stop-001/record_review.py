"""Record bounded Stop review using the published raw-Git identity helper."""
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
HELPER = ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"
source_record = runpy.run_path(str(HELPER))["record"]


def record(path, ranges=None, prior=None):
    row = source_record(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-stop-001/resolution.md"
    if prior:
        row["prior_body_read_ref"] = prior
        row["current_work"] = "Same raw source bytes revalidated; named previous reading reused explicitly"
    return row


def main():
    primary = [record("scripts/handlers/stop/" + name + ".py") for name in (
        "__init__", "autopilot_continue", "calendar_gate_emitter", "learner", "response_guard", "response_guard_core",
    )]
    support = [record(path) for path in (
        "scripts/lib/autopilot_state.py", "scripts/lib/calendar_gate.py", "scripts/lib/hook_io.py",
        "scripts/lib/work_unit_store.py", "scripts/lib/insight_index.py", "scripts/lib/jsonl_cache.py",
        "scripts/lib/reflexion_loop.py", "scripts/lib/frontmatter.py", "scripts/lib/autopilot_compaction.py",
        "scripts/handlers/__init__.py",
    )]
    prior = "docs/full-analysis/baldrix-engine-001/supporting-evidence.json"
    support.extend(record(path, prior=prior) for path in (
        "scripts/lib/paths.py", "scripts/lib/atomic_json.py", "scripts/lib/telemetry_log.py",
        "scripts/lib/__init__.py", "scripts/lib/event_store.py",
    ))
    support.append(record("scripts/engine/orchestrator.py", prior="docs/full-analysis/baldrix-engine-001/files.json"))
    support.extend((
        record("scripts/tests/test_autopilot_continue.py", [[1, 380]]),
        record("settings.json", [[274, 305]]),
        record("scripts/lib/completion_gate.py", [[1, 150]], prior=prior),
    ))
    assert len(primary) == 6 and sum(r["bytes"] for r in primary) == 66844
    checkpoint = {
        "partition": "baldrix:scripts/handlers/stop:001",
        "scope_sha256": "a5c82a94afd575c556e9ab8c0add3747d4cb12611a52f59e739a85080d964332",
        "primary_paths": 6, "primary_bytes": 66844, "primary_bodies_complete": True,
        "supporting_paths": len(support), "supporting_full": 16, "supporting_partial": 3,
        "prior_reading_reused_explicitly": 7, "source_hashes_verified": True,
        "original_self_check_assertions": {"calendar_lib": 24, "calendar_emitter": 12, "failed": 0},
        "original_Stop_CLI_subprocesses": 4,
        "component_programs": 1, "mocking_in_component_program": False,
        "original_autopilot_unit_module_executed": False,
        "actual_installed_hook_runtime_provider_worker_brain_autosave_executions": 0,
        "whole_analysis_complete": False, "partition_complete": False,
        "adoption_approved": False, "runtime_implemented": False,
        "limits": "Explicit temporary files and JSON payloads in networkless read-only-source Linux container. Original CLI behavior is not installed Claude hook lifecycle, real user/device acceptance or Windows/WSL upstream verification. Supporting records never increase primary coverage.",
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(checkpoint))


if __name__ == "__main__":
    main()
