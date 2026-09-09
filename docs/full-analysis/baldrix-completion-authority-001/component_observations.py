"""Call original completion helpers with explicit isolated files; no mocks."""
import json
from pathlib import Path

from lib import ac_tree as ac
from lib import axis_scores_log as axis
from lib import completion_gate as gate
from lib import coverage_gate as coverage
from lib.paths import STATE_DIR


def outcome(fn):
    try:
        return {"value": fn()}
    except Exception as exc:
        return {"exception": type(exc).__name__, "message": str(exc)}


def event_case(sid, event, floor=100.0):
    written = axis.log_axis_event(sid, event)
    return {"written": written, "events": axis.read_axis_events(sid),
            "fresh_verdict": outcome(lambda: gate.latest_fresh_evaluator_verdict(sid, floor))}


def main():
    results = {"kind": "original_completion_components", "mocking": False}
    results["caller_timestamp_schema"] = event_case("caller", {"schema_version": None, "ts": 200.0, "event": "unrelated", "verdict": "approved", "completeness": False})
    results["nan_timestamp"] = event_case("nan-ts", {"ts": float("nan"), "verdict": "approved"})
    results["nan_floor"] = event_case("nan-floor", {"ts": 1.0, "verdict": "approved"}, float("nan"))
    results["invalid_verdict"] = event_case("bad-verdict", {"ts": 200.0, "verdict": []})
    axis.log_verdict_event("marker", {"verdict": "iterate", "cross_target_first_invocation": True, "ts": 1.0}, cross_target=False)
    results["caller_marker_when_false"] = axis.read_axis_events("marker")
    events = STATE_DIR / "orchestrator/order/events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text('\n'.join(json.dumps({"type": "iteration_started", "ts": ts}) for ts in ["2026-09-09T00:01:00Z", "2026-09-09T00:00:00Z"]) + '\n', encoding="utf-8")
    results["iteration_order"] = {"count": gate.count_orchestrator_iterations("order"), "selected_ts": gate.iteration_started_ts("order"), "last_in_file": "2026-09-09T00:00:00Z"}
    events.write_text("[]\n", encoding="utf-8")
    results["iteration_wrong_shape"] = outcome(lambda: gate.count_orchestrator_iterations("order"))
    results["truthy_clean"] = gate.decide_completion(99, validators_passed="false", tests_passed="false", evaluator_verdict="approved", require_evaluator=True)
    results["no_evaluator_closed"] = gate.decide_completion(0, validators_passed=True, tests_passed=True, require_evaluator=True)
    results["empty_ac"] = ac.aggregate([])
    results["string_false_gate"] = ac.aggregate([ac.GateLeaf(lambda _: "false", "strict boolean?")])
    results["invalid_advisory_bool"] = outcome(lambda: ac.aggregate([ac.AdvisoryLeaf(lambda _: True, "cohesion", "bool guard")]))
    results["default_documented_axis"] = outcome(lambda: ac.AdvisoryLeaf(lambda _: 5, "완성도", "documented fallback"))
    # Actual IO error at a read-only source directory, not a fake emitter failure.
    def persist_event(kind, payload):
        with Path("/source").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps([kind, payload]))
    results["emit_io_failure"] = ac.evaluate_emit([ac.GateLeaf(lambda _: True, "gate")], None, persist_event)
    results["duplicate_leaf_ids"] = [ac.GateLeaf(lambda _: True, "same").leaf_id, ac.GateLeaf(lambda _: False, "same").leaf_id]
    atlas = {"nodes": [{"repo": "missing", "present": False}], "blocked_seams": [], "seams": [], "undeclared": []}
    results["coverage"] = {"empty": coverage.evaluate({}), "global": coverage.evaluate(atlas), "empty_scope": coverage.evaluate(atlas, touched_seams=[]), "unknown_scope": coverage.evaluate(atlas, touched_seams=["unknown"])}
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
