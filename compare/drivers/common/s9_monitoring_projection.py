"""Shared S9 scenario steps (`observation.monitoring_projection`): M7 `application/monitoring.py` (`age_seconds`, `Monitoring`, `initiatives`).

Layer: harness (never shipped)

`api.mon` is the side's monitoring-projection module (`age_seconds`, `Monitoring`, `initiatives`) and `api.POLICY` the side's policy singleton. Mirrors the
`Monitoring` and `initiatives` tests of `tests/test_monitoring.py` with a fixed `now`: `age_seconds` over every timestamp shape, the `Monitoring`
projection over scripted facts (health freshness, notifications attention/observed/unknown, task counts, agent execution state, expired leases, the
policy snapshot, the stamped time and the initiatives), and `initiatives` over every stage and release shape. Facts are deep-copied before each call
(the projection mutates and returns the facts it reads); the read callable is counted. No clock, store, process or network.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def call(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:200]}


def ago(**delta):
    return (NOW - timedelta(**delta)).isoformat()


def project(api, facts, now=NOW):
    reads = []

    def read():
        reads.append(1)
        return copy.deepcopy(facts)
    result = call(api.mon.Monitoring(SimpleNamespace(read=read)).snapshot, now)
    return {"result": result, "reads": len(reads)}


def ages(api) -> dict:
    mon = api.mon
    stamps = [ago(seconds=0), ago(seconds=30), ago(seconds=120), ago(seconds=121), ago(hours=3), (NOW + timedelta(seconds=5)).isoformat(),
              "2026-09-18T11:59:00", "2026-09-18T20:59:00+09:00", "not-a-time", "", None, 5, ["x"], {}]
    out = {"each": [call(mon.age_seconds, s, NOW) for s in stamps]}
    out["naive_now"] = call(mon.age_seconds, ago(seconds=5), datetime(2026, 9, 18, 12))
    out["naive_stamp_aware_now"] = call(mon.age_seconds, "2026-09-18T11:59:00", NOW)
    out["integer_valued_float"] = [type(r["value"]).__name__ for r in (call(mon.age_seconds, ago(seconds=0), NOW),
                                                                       call(mon.age_seconds, ago(seconds=7), NOW))]
    return out


def base_facts(**over):
    facts = {"health": {"status": "healthy", "checked_at": ago(seconds=10)}, "agents": [{"id": "worker"}, {"id": "idle"}],
             "tasks": [{"id": "run", "agent": "worker", "status": "running", "lease_until": (NOW + timedelta(seconds=30)).isoformat()},
                       {"id": "old", "agent": "worker", "status": "running", "lease_until": ago(seconds=1)},
                       {"id": "q", "agent": "worker", "status": "queued"},
                       {"id": "done", "agent": "idle", "status": "succeeded"}],
             "decisions": [{"id": "dec", "agent": "idle", "status": "pending"},
                           {"id": "decr", "agent": "idle", "status": "running", "lease_until": NOW.isoformat()}]}
    facts.update(over)
    return facts


def snapshots(api) -> dict:
    out = {"scripted": project(api, base_facts())}
    out["now_is_stamped"] = out["scripted"]["result"]["value"]["observed_at"] == NOW.isoformat()
    out["policy_equals_singleton"] = out["scripted"]["result"]["value"]["policy"] == api.POLICY.snapshot()
    health = {}
    for name, h in (("fresh", {"status": "degraded", "checked_at": ago(seconds=120)}), ("stale", {"status": "healthy", "checked_at": ago(seconds=121)}),
                    ("no_status", {"checked_at": ago(seconds=5)}), ("naive", {"status": "healthy", "checked_at": "2026-09-18T11:59:59"}),
                    ("future", {"status": "healthy", "checked_at": (NOW + timedelta(seconds=9)).isoformat()}),
                    ("missing_at", {"status": "healthy"}), ("empty", {}), ("none", None), ("junk_at", {"status": "healthy", "checked_at": 7})):
        health[name] = project(api, base_facts(health=h))
    health["absent"] = project(api, {k: v for k, v in base_facts().items() if k != "health"})
    out["health"] = health
    notes = {}
    for name, n in (("default", None),
                    ("quarantined", {"status_counts": {"quarantined": 1}, "last_batch": {"at": ago(seconds=5)}}),
                    ("retry_stale", {"status_counts": {"retry": 2}, "last_batch": {"at": ago(hours=1)}}),
                    ("error_no_batch", {"status_counts": {"error": 1}, "last_batch": {}}),
                    ("publishing", {"status_counts": {"publishing": 3}, "last_batch": {"at": ago(seconds=1)}}),
                    ("observed", {"status_counts": {"sent": 4}, "last_batch": {"at": ago(seconds=120)}}),
                    ("observed_zero_counts", {"status_counts": {"quarantined": 0, "retry": 0}, "last_batch": {"at": ago(seconds=3)}}),
                    ("unknown_stale", {"status_counts": {"sent": 4}, "last_batch": {"at": ago(seconds=121)}}),
                    ("unknown_no_at", {"status_counts": {}, "last_batch": {}}),
                    ("junk_at", {"status_counts": {}, "last_batch": {"at": "x"}})):
        facts = base_facts()
        if n is not None:
            facts["notifications"] = n
        notes[name] = project(api, facts)
    notes["missing_keys"] = project(api, base_facts(notifications={"status_counts": {}}))
    out["notifications"] = notes
    shapes = {}
    shapes["no_tasks_no_agents"] = project(api, {"tasks": [], "decisions": [], "agents": []})
    shapes["missing_tasks"] = project(api, {"decisions": [], "agents": []})
    shapes["missing_agents"] = project(api, {"tasks": [], "decisions": []})
    shapes["task_without_status"] = project(api, {"tasks": [{"id": "x"}], "decisions": [], "agents": []})
    shapes["agent_row_without_agent_key"] = project(api, {"tasks": [{"id": "x", "status": "queued"}], "decisions": [], "agents": [{"id": "a"}]})
    shapes["expired_and_stale_health"] = project(api, {
        "health": {"status": "healthy", "checked_at": ago(minutes=3)}, "agents": [{"id": "worker"}], "decisions": [],
        "tasks": [{"id": "old", "agent": "worker", "status": "running", "lease_until": ago(seconds=1)},
                  {"id": "new", "agent": "worker", "status": "queued"}]})
    shapes["running_without_lease"] = project(api, {"agents": [{"id": "w"}], "decisions": [], "tasks": [
        {"id": "a", "agent": "w", "status": "running"}, {"id": "b", "agent": "w", "status": "running", "lease_until": None},
        {"id": "c", "agent": "w", "status": "running", "lease_until": "bad"}]})
    shapes["lease_equal_to_now_is_live"] = project(api, {"agents": [{"id": "w"}], "decisions": [], "tasks": [
        {"id": "a", "agent": "w", "status": "running", "lease_until": NOW.isoformat()}]})
    shapes["queue_statuses"] = project(api, {"agents": [{"id": "w"}], "tasks": [
        {"id": str(i), "agent": "w", "status": s} for i, s in enumerate(("queued", "retry", "pending", "blocked", "failed"))],
        "decisions": [{"id": "dq", "agent": "w", "status": "pending"}]})
    shapes["facts_extra_keys_kept"] = project(api, {"tasks": [], "decisions": [], "agents": [], "custom": {"a": 1}, "releases": []})
    facts = base_facts()
    before = copy.deepcopy(facts)
    api.mon.Monitoring(SimpleNamespace(read=lambda: facts)).snapshot(NOW)
    shapes["input_not_mutated"] = {"same_object_returned": facts is api.mon.Monitoring(SimpleNamespace(read=lambda: facts)).snapshot(NOW),
                                   "facts_were_mutated_in_place": facts != before}
    shapes["read_failure"] = project_failure(api)
    out["shapes"] = shapes
    return out


def project_failure(api):
    def read():
        raise RuntimeError("facts down")
    return call(api.mon.Monitoring(SimpleNamespace(read=read)).snapshot, NOW)


def row(id, phase, status="succeeded", created=None, **extra):
    base = {"id": id, "correlation": "goal", "phase": phase, "status": status, "created_at": created or ago(hours=1), "objective": "Improve " + id}
    base.update(extra)
    return base


def initiative_cases(api) -> dict:
    out = {}

    def init(name, facts, now=NOW):
        out[name] = call(api.mon.initiatives, copy.deepcopy(facts), now)

    init("empty", {"tasks": [], "decisions": []})
    init("no_correlation", {"tasks": [{"id": "a", "phase": "plan", "status": "queued"}], "decisions": []})
    init("no_plan_or_implement", {"tasks": [row("r", "review_lead")], "decisions": []})
    init("completed_implementation_blocked_review",
         {"tasks": [row("impl", "implement", created=NOW.isoformat())],
          "decisions": [row("review", "review_lead", "blocked", created=NOW.isoformat(), reason="Cannot inspect candidate")], "releases": []})
    init("awaiting_next_stage", {"tasks": [row("impl", "implement", created=NOW.isoformat())], "decisions": [], "releases": []})
    init("failed_canary_expired_lease",
         {"tasks": [{"id": "impl", "correlation": "goal", "phase": "implement", "status": "running", "revision": "abc",
                     "lease_until": ago(seconds=1)}],
          "decisions": [], "releases": [{"id": "release", "revision": "abc", "status": "rejected", "checks": {"cli": {"passed": False}}}]})
    init("running_stage", {"tasks": [row("p", "plan", "running", lease_until=(NOW + timedelta(seconds=30)).isoformat(), progress_at=ago(seconds=5))],
                           "decisions": []})
    init("running_lease_none", {"tasks": [row("p", "plan", "running")], "decisions": []})
    init("queued_pending_retry", {"tasks": [row("p", "plan", "queued"), row("i", "implement", "retry", created=ago(minutes=30))],
                                  "decisions": [row("rl", "review_lead", "pending")]})
    init("rejected", {"tasks": [row("i", "implement", accepted=False)], "decisions": [row("rl", "review_lead", "succeeded", accepted=True)]})
    init("accepted_false_not_succeeded", {"tasks": [row("i", "implement", "failed", accepted=False)], "decisions": []})
    init("later_row_wins", {"tasks": [row("i1", "implement", "failed", created=ago(hours=3)), row("i2", "implement", "succeeded", created=ago(hours=2))],
                            "decisions": []})
    init("created_at_missing_sorted_first", {"tasks": [row("i1", "implement", created=ago(hours=1)), {**row("i2", "implement", "failed"), "created_at": None}],
                                             "decisions": []})
    for name, release in (("verified_all_pass", {"status": "verified", "checks": {"a": {"passed": True}, "b": {"passed": True}}}),
                          ("verified_one_unknown", {"status": "verified", "checks": {"a": {"passed": True}, "b": {}}}),
                          ("active_pass", {"status": "active", "checks": {"a": {"passed": True}}}),
                          ("superseded_pass", {"status": "superseded", "checks": {"a": {"passed": True}}}),
                          ("candidate_pass", {"status": "candidate", "checks": {"a": {"passed": True}}}),
                          ("no_checks_active", {"status": "active"}),
                          ("rolled_back", {"status": "rolled_back", "checks": {"a": {"passed": True}}}),
                          ("failed_check_beats_status", {"status": "active", "checks": {"a": {"passed": False}, "b": {"passed": True}}}),
                          ("no_status", {"checks": {"a": {"passed": True}}})):
        facts = {"tasks": [row("i", "implement", release_id="rel")], "decisions": [],
                 "releases": [{"id": "rel", "created_at": ago(minutes=5), **release}]}
        init("release_" + name, facts)
    init("release_by_revision", {"tasks": [row("i", "implement", revision="r1")], "decisions": [],
                                 "releases": [{"id": "x", "revision": "r1", "status": "active", "checks": {"a": {"passed": True}}}]})
    init("release_latest_of_two", {"tasks": [row("i", "implement", release_id="a", revision="r1")], "decisions": [], "releases": [
        {"id": "a", "status": "superseded", "created_at": ago(hours=2), "checks": {"c": {"passed": True}}},
        {"id": "b", "revision": "r1", "status": "active", "created_at": ago(hours=1), "checks": {"c": {"passed": True}}}]})
    init("release_unrelated", {"tasks": [row("i", "implement", release_id="zzz")], "decisions": [],
                               "releases": [{"id": "other", "status": "active", "checks": {"a": {"passed": True}}}]})
    init("releases_absent", {"tasks": [row("i", "implement")], "decisions": []})
    init("objective_and_reason", {"tasks": [{"id": "i", "correlation": "g", "phase": "implement", "status": "failed", "error": "boom"}],
                                  "decisions": []})
    init("reason_prefers_reason", {"tasks": [{"id": "i", "correlation": "g", "phase": "implement", "status": "failed", "error": "boom", "reason": "why"}],
                                   "decisions": []})
    for name, stamp in (("fresh", dict(progress_at=ago(seconds=120))), ("stale", dict(progress_at=ago(seconds=121))),
                        ("completed_at", dict(completed_at=ago(seconds=10))), ("created_only", dict(created=ago(seconds=60))),
                        ("junk", dict(progress_at="junk")), ("future", dict(progress_at=(NOW + timedelta(seconds=30)).isoformat()))):
        created = stamp.pop("created", None)
        init("activity_" + name, {"tasks": [row("i", "implement", "queued", created=created, **stamp)], "decisions": []})
    init("two_initiatives_sorted", {"tasks": [
        {**row("a1", "implement", "succeeded", created=ago(hours=5)), "correlation": "a"},
        {**row("b1", "implement", "blocked", created=ago(hours=9)), "correlation": "b"},
        {**row("c1", "plan", "succeeded", created=ago(hours=1)), "correlation": "c"},
        {**row("d1", "plan", "failed", created=ago(hours=2)), "correlation": "d"}], "decisions": []})
    init("missing_tasks_key", {"decisions": []})
    init("row_without_id_in_release_lookup", {"tasks": [row("i", "implement")], "decisions": [], "releases": [{"status": "active"}]})
    return out


def run(api) -> dict:
    out = {"age_seconds": ages(api), "snapshot": snapshots(api), "initiatives": initiative_cases(api)}
    out["initiative_case_count"] = len(out["initiatives"])
    return out
