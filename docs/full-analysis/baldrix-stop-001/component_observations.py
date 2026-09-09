"""Original functions and Stop CLI with explicit isolated input files; no mocks."""
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from handlers.stop import autopilot_continue as ac
from handlers.stop import calendar_gate_emitter as emitter
from handlers.stop import learner
from handlers.stop.response_guard_core import analyze_response
from lib import autopilot_state as states
from lib import work_unit_store
from lib.calendar_gate import scan_deadlines


def invoke(payload):
    argv = [sys.executable, "-B", "/source/scripts/handlers/stop/autopilot_continue.py"]
    data = json.dumps(payload).encode("utf-8")
    proc = subprocess.run(argv, input=data, capture_output=True, timeout=10)
    return {
        "argv": argv, "input": payload, "input_sha256": hashlib.sha256(data).hexdigest(),
        "returncode": proc.returncode, "stdout": proc.stdout.decode("utf-8"),
        "stderr": proc.stderr.decode("utf-8"),
        "stdout_sha256": hashlib.sha256(proc.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(proc.stderr).hexdigest(),
    }


def main():
    base = Path("/tmp/stop-review")
    base.mkdir()
    # Use the real throttle API and a current watermark to keep autosave outside
    # this bounded CLI scenario. No provider/worker/brain snapshot is invoked.
    work_unit_store.mark("save")
    result = {"kind": "actual_original_Stop_functions_and_CLI_observations", "mocking": False}
    result["retry_cases"] = {}
    for name, message in (
        ("tag_miss", "Plain response without the required autopilot tag."),
        ("json_error", "<autopilot mode='execute'>{broken</autopilot>"),
    ):
        project = base / name
        project.mkdir()
        sid = "orch-review-" + name
        state = states.new_state(sid, "explicit temporary review fixture", cwd=str(project))
        state.pending_fp = "0123456789abcdef"
        state.reflection_seen_count = 3
        state.reflection_req_count = 5
        assert states.write_state(state)
        payload = {"hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": message, "session_id": "fixture-" + name, "cwd": str(project)}
        before = states.list_active_sids(cwd_filter=str(project))
        first = invoke(payload)
        after_first = states.read_state(sid).to_dict()
        selected_after_first = states.list_active_sids(cwd_filter=str(project))
        second = invoke(payload)
        result["retry_cases"][name] = {
            "selected_before": before, "first": first, "state_after_first": after_first,
            "selected_after_first": selected_after_first, "second": second,
            "state_after_second": states.read_state(sid).to_dict(),
        }
    result["parser"] = {name: ac.parse_autopilot_tag(text) for name, text in (
        ("execute", "<autopilot mode='execute'>{\"goal_reached\":false}</autopilot>"),
        ("emitted_attributes", "<autopilot mode='execute' sid='fixture' iter='1'>{\"goal_reached\":false}</autopilot>"),
        ("advisory_with_result", "<autopilot mode='advisory'></autopilot><iteration-result>{\"goal_reached\":false}</iteration-result>"),
        ("mixed_mode", "<autopilot mode='advisory'></autopilot><autopilot mode='execute'>{\"goal_reached\":true}</autopilot>"),
        ("empty_first", "<autopilot mode='execute'></autopilot><iteration-result>{\"tests_passed\":true}</iteration-result>"),
    )}
    candidates = learner.find_recurring_errors([{"message": "error error error"}])
    result["learner_single_event"] = {"events": 1, "candidates": candidates, "convergence_with_incomplete_payload": learner.terminal_convergence_predicate({"goal_reached": False}, candidates)}
    malformed_shape = base / "history.jsonl"
    malformed_shape.write_text("[]\n", encoding="utf-8")
    try:
        learner.find_recurring_errors(learner._read_tail(malformed_shape, 300))
        result["learner_wrong_shape"] = {"exception": None}
    except Exception as exc:
        result["learner_wrong_shape"] = {"exception": type(exc).__name__, "message": str(exc)}
    calendar_root = base / "calendar"
    (calendar_root / "residual_norm").mkdir(parents=True)
    (calendar_root / "residual_norm/broken.json").write_text("{broken", encoding="utf-8")
    errors = []
    scanned = scan_deadlines(calendar_root, date(2026, 9, 9), on_error=errors)
    result["calendar_all_corrupt"] = {"overdue": len(scanned), "scanner_errors": len(errors), "adapter_payload": emitter.build_block_payload(calendar_root, date(2026, 9, 9))}
    result["legitimate_phase_plan_analysis"] = analyze_response("Phase 2 is approved by the user and the implementation has already begun.")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
