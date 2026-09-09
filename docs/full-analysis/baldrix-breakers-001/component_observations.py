"""Original breaker functions with real isolated files; no patched clocks or providers."""
import json
import os
from pathlib import Path
import tempfile
import time

from lib.breakers.composite import CompositeBreaker
from lib.breakers.config import BreakerThresholds
from lib.breakers import config


def record(breaker, **values):
    path = Path(breaker.record_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")


def outcome(fn):
    try:
        return {"value": fn()}
    except Exception as exc:
        return {"exception": type(exc).__name__, "message": str(exc)}


def main():
    assert str(config.CONFIG_PATH).startswith("/tmp/")
    observations = {"kind": "original_composite_breaker_file_observations", "mocking": False}
    with tempfile.TemporaryDirectory(prefix="breaker-observe-") as td:
        def breaker(label, **kwargs):
            return CompositeBreaker("worker", "failure", label, base_dir=td, **kwargs)

        b = breaker("corrupt")
        path = Path(b.record_path)
        path.parent.mkdir(parents=True)
        path.write_text("{", encoding="utf-8")
        observations["corrupt"] = {"admitted": b.try_acquire(), "snapshot": b.snapshot().state.value, "raw": path.read_text()}

        b = breaker("half-idle")
        record(b, state="half_open", history=[], probe_in_flight=False)
        observations["half_open_without_reservation"] = {
            "first": b.try_acquire(), "second": b.try_acquire(),
            "persisted_probe_in_flight": json.loads(Path(b.record_path).read_text())["probe_in_flight"],
        }

        old = breaker("late-owner")
        fresh = breaker("late-owner")
        record(old, state="half_open", history=[], trip_count=1, probe_in_flight=True, probe_reserved_at=time.time() - 121)
        admitted = fresh.try_acquire()
        closed = old.record_success()
        observations["late_result_after_reclaim"] = {"new_admitted": admitted, "old_result_returned": closed.value, "current_state": fresh.snapshot().state.value}

        for label, state in (
            ("nan-cooloff", dict(state="open", history=[], cool_off_until=float("nan"))),
            ("nan-reservation", dict(state="half_open", history=[], probe_in_flight=True, probe_reserved_at=float("nan"))),
            ("history-null", dict(state="closed", history=None)),
            ("trip-infinity", dict(state="open", history=[], trip_count=float("inf"))),
        ):
            b = breaker(label)
            record(b, **state)
            observations[label] = outcome(b.try_acquire)

        b = breaker("save-denied")
        record(b, state="open", history=[], trip_count=1, cool_off_until=0, probe_in_flight=False)
        directory = Path(b.record_path).parent
        directory.chmod(0o555)
        try:
            observations["save_failure"] = {"first_admitted": b.try_acquire(), "second_admitted": b.try_acquire(), "persisted_state": b.snapshot().state.value}
        finally:
            directory.chmod(0o700)

        collision_a = CompositeBreaker("a/b", "c", "collision", base_dir=td)
        collision_b = CompositeBreaker("a_b", "c", "collision", base_dir=td)
        delimiter_a = CompositeBreaker("a__b", "c", "collision", base_dir=td)
        delimiter_b = CompositeBreaker("a", "b__c", "collision", base_dir=td)
        outside_project = str(Path(td) / "still-isolated-outside-breakers")
        escape = CompositeBreaker("a", "b", outside_project, base_dir=td)
        observations["identity_paths"] = {
            "slash_alias_same_path": collision_a.record_path == collision_b.record_path,
            "delimiter_alias_same_path": delimiter_a.record_path == delimiter_b.record_path,
            "absolute_project_escapes_breakers_subdir": not Path(escape.record_path).is_relative_to(Path(td) / "breakers"),
            "no_write_for_escape_case": True,
        }

        th = BreakerThresholds(trip_per_mode=99, trip_any_mode=5, trip_any_window=20)
        for project, modes in (("distinct", ["other"]), ("duplicate", ["other", "other"])):
            b = breaker(project, thresholds=th, any_mode_keys=modes)
            sibling = CompositeBreaker("worker", "other", project, base_dir=td)
            record(sibling, state="closed", history=[False, False])
            observations["cross_mode_" + project] = b.record_failure().value

        for label, modes in (("good-last", ["bad", "good"]), ("bad-last", ["good", "bad"])):
            b = breaker(label, thresholds=th, any_mode_keys=modes)
            for mode, history in (("bad", [False] * 5), ("good", [True] * 20)):
                sibling = CompositeBreaker("worker", mode, label, base_dir=td)
                record(sibling, state="closed", history=history)
            observations["secondary_order_" + label] = b.record_failure().value

        observations["bool_override"] = {
            "returned": config.apply_override("trip_per_mode", True, token=config.TOKEN_SAFE),
            "raw_yaml": config.CONFIG_PATH.read_text(encoding="utf-8"),
            "effective_trip_per_mode": config.resolve_thresholds().trip_per_mode,
        }
        config.CONFIG_PATH.write_text("version: 99\noverrides:\n  trip_per_mode: -1\n  trip_window: 0\n", encoding="utf-8")
        resolved = config.resolve_thresholds()
        observations["unchecked_file_policy"] = {"trip_per_mode": resolved.trip_per_mode, "trip_window": resolved.trip_window}
        b = breaker("invalid-window")
        b.record_failure()
        for _ in range(12):
            b.record_success()
        observations["zero_window_history_length"] = len(b.snapshot().history)
    observations["uid"] = os.getuid()
    print(json.dumps(observations, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
