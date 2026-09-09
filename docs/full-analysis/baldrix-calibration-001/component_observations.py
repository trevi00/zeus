"""Original calibration methods on synthetic inputs and real isolated files.

No patched methods/clock/provider; this is not human, model or concurrency acceptance.
"""
import json
import math
import os
from pathlib import Path

from lib.calibration import proposer, threshold_metrics as metrics
from lib.calibration import threshold_proposer as proposals
from lib.calibration.breaker_proposer import analyze_breaker, propose_breaker_changes
from lib.no_degradation_gate import evaluate_threshold_change
from lib.operator_ledger import project_id_for
from lib import threshold_policy as policy


def main():
    assert os.getuid() == 65534
    name = "skill_match.FULL_BODY_MIN_SCORE"
    events = [
        {"ts": f"2026-06-10T00:00:{i:02d}Z", "top": [
            {"name": "borderline", "score": 3, "body_chars": 500},
            {"name": "higher", "score": 5, "body_chars": 500},
        ]}
        for i in range(40)
    ]
    first = proposals.propose_threshold_changes(events_by_source={"skill-match": events}, min_sample=5)
    chosen = next(p for p in first if p.name == name)
    flag = policy._ready_flag_path(name)
    result = {
        "uid": os.getuid(),
        "initial_proposal": {"current": chosen.current, "suggested": chosen.suggested},
        "initial_flag": json.loads(flag.read_text()),
    }
    result["apply_different_value"] = policy.apply_threshold_override(name, 999, token=policy.TOKEN_RISKY)
    result["effective_after_different_value"] = policy.resolve_threshold(name, 3)
    second = proposals.propose_threshold_changes(events_by_source={"skill-match": events}, min_sample=5)
    chosen = next(p for p in second if p.name == name)
    result["proposal_after_override"] = {"current": chosen.current, "suggested": chosen.suggested}
    flag.write_text("{", encoding="utf-8")
    result["apply_with_corrupt_flag"] = policy.apply_threshold_override(name, 1000, token=policy.TOKEN_RISKY)
    flag.write_text("", encoding="utf-8")
    result["apply_nan_with_empty_flag"] = policy.apply_threshold_override(name, math.nan, token=policy.TOKEN_RISKY)
    result["effective_is_nan"] = math.isnan(policy.resolve_threshold(name, 3))
    result["zero_admissions_metric"] = metrics.full_body_admit_precision(events, 999)
    gate = evaluate_threshold_change(events=events, old_value=3, proposed_value=999,
                                    metric_fn=metrics.full_body_admit_precision,
                                    guard_fn=metrics.non_truncation_rate,
                                    holdout_boundary=events[20]["ts"], min_corpus=5)
    result["zero_admissions_gate"] = {"accept": gate.accept, "reason": gate.reason}
    result["partially_unsized_guard"] = metrics.non_truncation_rate(
        [{"top": [{"score": 5, "body_chars": 10}, {"score": 4}]}], 3)

    ledger = Path("/tmp/calibration-ledger")
    project = "/tmp/calibration-project"
    target = ledger / project_id_for(project) / "custom.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text((json.dumps({"success": False, "failure_modes": []}) + "\n") * 10)
    stats = proposer.analyze_ledger(project, "custom", ledger_root=ledger)
    result["unknown_outcomes"] = {"sample": stats.sample_size, "success": stats.success_count,
                                  "failure": stats.failure_count, "success_rate": stats.success_rate}
    target.write_text(json.dumps({"success": False, "failure_modes": ["evidence_fabrication"] * 3}) + "\n")
    stats = proposer.analyze_ledger(project, "custom", ledger_root=ledger)
    result["duplicate_modes"] = {"failures": stats.failure_count, "mode_counts": stats.failure_mode_counts}
    target.write_text("[]\n")
    try:
        proposer.analyze_ledger(project, "custom", ledger_root=ledger)
    except Exception as exc:
        result["scalar_record_exception"] = type(exc).__name__

    breakers = Path("/tmp/calibration-breakers")
    breaker_path = breakers / project_id_for(project) / "custom__failure.json"
    breaker_path.parent.mkdir(parents=True)
    breaker_path.write_text(json.dumps({"state": "open", "trip_count": 5, "history": [False] * 10}))
    bp = propose_breaker_changes(project, breakers_root=breakers)
    result["all_failures_proposal"] = [{"current": p.current_value, "suggested": p.suggested_value,
                                       "failure_rate": p.evidence.window_failure_rate} for p in bp]
    breaker_path.write_text("{")
    stats = analyze_breaker(breaker_path)
    result["corrupt_breaker_stats"] = None if stats is None else {"history_len": stats.history_len,
                                                               "state": stats.current_state}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
