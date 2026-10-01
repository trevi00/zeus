"""ACCEPTANCE A50-A53: provider window observations, markers ordered before validity (DESIGN §3.8)."""

import pytest
from fixtures import T0, Rig, claude_init, rate_limit, start_row, user_line

COORD = "fleet-autonomy-cont-1-events.jsonl"
OTHER = "fleet-other-events.jsonl"
FUTURE = T0 + 3 * 86400  # a reset time safely after every scan below


def state(prom, slot="primary", window="seven_day"):
    names = ("current", "stale", "expired", "unavailable")
    hot = [n for n in names if prom.sum("zeus_llm_provider_window_state", slot=slot, window=window, state=n) == 1]
    assert len(hot) == 1, f"one-hot violated: {hot}"
    assert prom.count("zeus_llm_provider_window_state", slot=slot, window=window) == 4
    return hot[0]


def utilization(prom, slot="primary", window="seven_day"):
    return prom.count("zeus_llm_provider_utilization_ratio", slot=slot, window=window)


def coordinator(rig, rel, *lines, slot="primary"):
    rig.credential_receipt("coordinator:fleet", rel, selection=slot)
    return rig.stream(rel, *lines)


def test_a50_a_fresh_append_does_not_refresh_a_stale_observation(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0),
                rate_limit("rl-1", five_hour=(0.5, FUTURE), seven_day=(0.4, FUTURE)))
    prom = rig.scan(advance=30)
    assert state(prom) == "current" and state(prom, window="five_hour") == "current"
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day",
                    freshness="current") == pytest.approx(0.4)
    rig.stream(COORD, *[user_line(T0 + 600 * n) for n in range(1, 13)])  # unrelated lines for two hours
    prom = rig.scan(advance=7200)
    assert state(prom) == "stale"  # observed_at stays T0 (the preceding timestamped line)
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day",
                    freshness="stale") == pytest.approx(0.4)
    assert prom.sum("zeus_llm_provider_window_observed_timestamp_seconds", slot="primary", window="seven_day",
                    provenance="stream_preceding_timestamp") == pytest.approx(T0)
    assert prom.sum("zeus_llm_provider_window_resets_timestamp_seconds", slot="primary", window="seven_day") == FUTURE
    assert rig.sql("SELECT DISTINCT provenance FROM rate_observations") == [("stream_preceding_timestamp",)]


def test_a50_the_time_bracket_is_the_nearest_preceding_timestamp_not_a_following_one(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0 + 100), user_line(T0 + 200),
                rate_limit("rl-1", seven_day=(0.4, FUTURE)), user_line(T0 + 900))
    rig.scan(advance=1000)
    assert rig.sql("SELECT observed_at FROM rate_observations WHERE window='seven_day'") == [(T0 + 200,)]


def routine_attempt(rig, task, attempt, slot, lines, at):
    rig.record(task, start_row(task, attempt, at, advisor=None, resumed=attempt > 1),
               {"event": "credential_selected", "attempt": attempt, "selection": slot, "has_token": True})
    rig.events(task, attempt, claude_init(), *lines)


def test_a51_slots_are_separate_series_and_an_older_late_observation_does_not_supersede(tmp_path):
    rig = Rig(tmp_path)
    routine_attempt(rig, "slot-task", 1, "primary", [
        user_line(T0 + 10), rate_limit("a1", seven_day=(0.30, FUTURE), five_hour=(0.1, FUTURE))], T0)
    routine_attempt(rig, "slot-task", 2, "secondary", [
        user_line(T0 + 100), rate_limit("b1", seven_day=(0.70, FUTURE))], T0 + 90)
    prom = rig.scan(advance=200)
    assert state(prom, "primary") == "current" and state(prom, "secondary") == "current"
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day") == pytest.approx(0.30)
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="secondary", window="seven_day") == pytest.approx(0.70)
    assert state(prom, "secondary", "five_hour") == "unavailable"  # the secondary slot never reported it
    prom = rig.scan(advance=3500)  # each slot ages on its own observation time (T0+10 and T0+100)
    assert state(prom, "primary") == "stale" and state(prom, "secondary") == "current"
    assert state(rig.scan(advance=20), "secondary") == "stale"
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0 + 3600), rate_limit("c1", seven_day=(0.55, FUTURE)),
                slot="primary")
    prom = rig.scan(advance=10)
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day") == pytest.approx(0.55)
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="secondary", window="seven_day") == pytest.approx(0.70)
    coordinator(rig, OTHER, claude_init(model="opus"), user_line(T0 + 20), rate_limit("d1", seven_day=(0.99, FUTURE)),
                slot="primary")  # arrives late, observed earlier
    prom = rig.scan(advance=10)
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day") == pytest.approx(0.55)


def test_a51_an_unlinked_stream_is_slot_unknown(tmp_path):
    rig = Rig(tmp_path)
    rig.record("slot-task", start_row("slot-task", 1, T0, advisor=None),
               {"event": "credential_selected", "attempt": 1, "selection": "injected", "has_token": True})
    rig.events("slot-task", 1, claude_init(), user_line(T0 + 1), rate_limit("a1", seven_day=(0.3, FUTURE)))
    prom = rig.scan(advance=30)
    assert state(prom, "unknown") == "current" and prom.count("zeus_llm_provider_window_state", slot="primary") == 0


def test_a52_i_event_lacking_a_window_is_unavailable_and_the_other_window_is_independent(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0), rate_limit("rl-1", five_hour=(0.2, FUTURE)))
    prom = rig.scan(advance=30)
    assert state(prom, window="seven_day") == "unavailable" and utilization(prom) == 0
    assert state(prom, window="five_hour") == "current" and utilization(prom, window="five_hour") == 1
    assert prom.count("zeus_llm_provider_window_observed_timestamp_seconds", window="seven_day") == 0  # never 0


def test_a52_ii_an_event_with_no_preceding_timestamp_is_never_current(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, COORD, claude_init(model="opus"), rate_limit("rl-1", seven_day=(0.2, FUTURE)), user_line(T0 + 5))
    prom = rig.scan(advance=30)
    assert state(prom) == "unavailable" and utilization(prom) == 0
    assert rig.sql("SELECT marker, observed_at FROM rate_observations WHERE window='seven_day'") == [("value", None)]


def sequence(tmp_path, bad_reading):
    """A52(iii)/A53(ii): valid at t0, newer bad reading at t0+60, replay, late older valid, newer valid at t0+120."""
    rig = Rig(tmp_path)
    t0 = T0 + 10
    coordinator(rig, COORD, claude_init(model="opus"), user_line(t0),
                rate_limit("v1", five_hour=(0.1, FUTURE), seven_day=(0.4, FUTURE)))
    prom = rig.scan(advance=100)
    assert state(prom) == "current"
    rig.stream(COORD, user_line(t0 + 60), rate_limit("v2", five_hour=(0.15, FUTURE), seven_day=bad_reading))
    prom = rig.scan(advance=50)
    after_bad = (state(prom), utilization(prom), state(prom, window="five_hour"))
    assert after_bad == ("unavailable", 0, "current")  # the other window is independent
    assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="five_hour") == pytest.approx(0.15)
    replay = rig.scan(advance=10)
    assert (state(replay), utilization(replay)) == ("unavailable", 0)
    coordinator(rig, OTHER, claude_init(model="opus"), user_line(t0 - 30), rate_limit("v0", seven_day=(0.9, FUTURE)))
    late = rig.scan(advance=10)  # an older valid reading arrives late: no resurrection
    assert (state(late), utilization(late)) == ("unavailable", 0)
    rig.stream(COORD, user_line(t0 + 120), rate_limit("v3", five_hour=(0.2, FUTURE), seven_day=(0.45, FUTURE)))
    restored = rig.scan(advance=10)
    assert state(restored) == "current"
    assert restored.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day") == pytest.approx(0.45)
    return rig


def test_a52_iii_prior_valid_then_newer_missing_window(tmp_path):
    rig = sequence(tmp_path, None)
    assert [r[0] for r in rig.sql("SELECT marker FROM rate_observations WHERE event_key='v2' AND "
                                  "window='seven_day'")] == ["missing"]


def test_a53_ii_prior_valid_then_newer_invalid_reading(tmp_path):
    rig = sequence(tmp_path, {"utilization": float("nan"), "resetsAt": FUTURE})
    assert [r[0] for r in rig.sql("SELECT marker FROM rate_observations WHERE event_key='v2' AND "
                                  "window='seven_day'")] == ["invalid"]


@pytest.mark.parametrize("reading,expected,shown", [
    ((0.5, T0 - 5), "expired", False),  # resetsAt <= now
    ((float("nan"), FUTURE), "unavailable", False),
    ((float("inf"), FUTURE), "unavailable", False),
    ((-0.1, FUTURE), "unavailable", False),
    ((2.5, FUTURE), "unavailable", False),
    (("x", FUTURE), "unavailable", False),
    ((0.5, "soon"), "unavailable", False),
    ((0.5, FUTURE + 9 * 86400), "unavailable", False),  # not within +-8 days of the observation
    ((1.1, FUTURE), "current", True),  # 1.1 with status `rejected` is real (R7) and accepted as reported
])
def test_a53_i_expired_and_invalid_readings(tmp_path, reading, expected, shown):
    rig = Rig(tmp_path)
    event = rate_limit("rl-1", seven_day=reading, status="rejected" if reading[0] == 1.1 else "allowed")
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0), event)
    prom = rig.scan(advance=30)
    assert state(prom) == expected
    assert (utilization(prom) == 1) is shown
    if shown:
        assert prom.sum("zeus_llm_provider_utilization_ratio", slot="primary", window="seven_day") == pytest.approx(1.1)


def test_window_series_never_join_token_metrics_and_replays_add_no_rows(tmp_path):
    rig = Rig(tmp_path)
    coordinator(rig, COORD, claude_init(model="opus"), user_line(T0), rate_limit("rl-1", seven_day=(0.4, FUTURE)))
    rig.scan(advance=30)
    rows = rig.sql("SELECT COUNT(*) FROM rate_observations")[0][0]
    rig.scan(advance=30)
    assert rig.sql("SELECT COUNT(*) FROM rate_observations")[0][0] == rows == 2  # two markers per event, once
    text = (rig.data / "data.prom").read_text()
    window_lines = [ln for ln in text.splitlines() if ln.startswith("zeus_llm_provider_")]
    assert window_lines and all("zeus_llm_tokens" not in ln for ln in window_lines)
