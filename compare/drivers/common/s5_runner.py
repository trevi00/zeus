"""Shared S5 scenario steps (`coordination.fleet_runner`): M7 `FleetRunner` over a fixture launcher (RESEARCH-S5 D7;
M7 tests/test_fleet.py runner tests). No process is spawned and no provider is reached.

- **One pass.** Independent jobs overlap. Every owned child is drained and finalized once, a refused launch fails,
  an interrupted spawn and an unknown outcome stay `unknown`, and `reconciliation_required` names them.
- **Later runners.** A restarted runner relaunches nothing. A stopped runner admits nothing, and an exhausted
  budget blocks admission with a persisted reason.
- **Control.** A paused control stops new admission while the owned child finishes, and the heartbeats report the
  admission state and the active and unresolved work. An unreadable control closes admission, and an unwritable
  heartbeat is not invented.
- **Adapter ticks.** A reconcile pass that fails and recovers, and backlog outcomes mapped to runner states. Only
  state transitions are logged.
- **Stop.** A stop forwards to a continuation's `request_stop` before any store access.

Layer: harness (never shipped)

`api` supplies MemoryStore, `Fleet(store, clock, token)`, `FleetRunner(fleet, launcher, sleep, interval, **ports)`,
`LaunchRefused` and `validate_manifest(document)`. The compared results are the summaries, the launcher and
control records, the job states and the log records (logger name, level and message).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging

BASE = "a" * 40
ROOT = "/zeus-rebuild-s5-fleet"
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}
ACCEPTED = {"status": "accepted", "reason_code": "lead_accepted", "exit_code": 0, "calls": {"reserved": 2, "settled": 2}}


def canonical_digest(value) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Logs(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        if record.name.startswith(("zeus", "codex_harness")):
            self.records.append([record.name, record.levelname, record.getMessage()])


class FakeLauncher:
    def __init__(self, api, outcomes, refuse=(), explode=(), exhausted=False):
        self.api, self.outcomes, self.refuse, self.explode, self.exhausted = api, outcomes, refuse, explode, exhausted
        self.running, self.peak, self.launched = set(), 0, []

    def budget_exhausted(self, budget):
        return self.exhausted

    def launch(self, job):
        if job["id"] in self.refuse:
            raise self.api.LaunchRefused("isolation_required")
        if job["id"] in self.explode:
            raise OSError("spawn interrupted (fixture)")
        self.launched.append(job["id"])
        self.running.add(job["id"])
        self.peak = max(self.peak, len(self.running))
        return {"job_id": job["id"]}

    def wait(self, handles, seconds):
        return list(handles)

    def outcome(self, handle, job):
        self.running.discard(handle["job_id"])
        return copy.deepcopy(self.outcomes[handle["job_id"]])


class HeldLauncher(FakeLauncher):
    def __init__(self, api, outcomes, on_wait):
        super().__init__(api, outcomes)
        self.released, self.on_wait, self.waits = set(), on_wait, 0

    def wait(self, handles, seconds):
        self.waits += 1
        self.on_wait(self)
        return [h for h in handles if h["job_id"] in self.released]


class RecordingControl:
    def __init__(self):
        self.paused = self.stopping = self.unreadable = self.unwritable = False
        self.beats = []

    def admission_open(self):
        if self.unreadable:
            raise OSError("labelled injected unreadable pause")
        return not self.paused

    def stop_requested(self):
        return self.stopping

    def heartbeat(self, state):
        if self.unwritable:
            raise OSError("labelled injected unwritable heartbeat")
        self.beats.append(dict(state))


def jobs(fleet):
    return {j["id"]: [j["status"], j.get("reason_code")] for j in fleet.status()["jobs"]}


def attempt(fn, *args, **kwargs):
    try:
        return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc)[:160]}


def run(api) -> dict:
    out, logs = {}, Logs()
    root = logging.getLogger()
    root.addHandler(logs)
    previous = root.level
    root.setLevel(logging.DEBUG)

    def manifest(op_id, paths):
        return api.validate_manifest({
            "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
            "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": "r"},
            "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": paths},
            "budget": {"per_host": 4, "total": 8},
            "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}})

    def fleet(max_parallel=2):
        counter, stamp = iter(range(1, 100_000)), iter(range(1, 100_000))
        f = api.Fleet(api.MemoryStore(), lambda: "2026-09-18T00:00:00.%06d+00:00" % next(stamp),
                      lambda: "%032x" % next(counter))
        lanes = [{"id": lane, "team": lane, "repository": ROOT + "/repo-" + lane, "schema": "lane_" + lane,
                  "redis_namespace": "fleet-" + lane, "runtime": ROOT + "/rt-" + lane} for lane in ("a", "b")]
        f.register({"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": max_parallel,
                    "budget": {"per_host": 4, "total": 8}, "lanes": lanes})
        return f

    try:
        # one pass: overlap, drain once, refused/exploded launches, unknown kept
        f = fleet()
        for op, lane, path, deps in (("op-1", "a", "docs/x.md", []), ("op-2", "b", "docs/y.md", []),
                                     ("op-3", "a", "docs/z.md", ["op-1"]), ("op-4", "b", "docs/w.md", []),
                                     ("op-5", "b", "docs/v.md", [])):
            f.enqueue(lane, manifest(op, [path]), GOAL, deps)
        launcher = FakeLauncher(api, {"op-1": ACCEPTED,
                                      "op-2": {"status": "rejected", "reason_code": "lead_rejected", "exit_code": 1},
                                      "op-3": {"status": "unknown", "reason_code": "receipt_missing", "exit_code": 0}},
                                refuse={"op-4"}, explode={"op-5"})
        sleeps = []
        out["pass"] = attempt(api.FleetRunner(f, launcher, sleeps.append, 0).run, once=True)
        out["pass_launcher"] = {"peak": launcher.peak, "launched": launcher.launched, "sleeps": list(sleeps)}
        out["pass_jobs"] = jobs(f)
        again = FakeLauncher(api, {})
        out["restart"] = attempt(api.FleetRunner(f, again, sleeps.append, 0).run, once=True)
        f.enqueue("a", manifest("op-6", ["docs/u.md"]), GOAL, [])
        stopped = api.FleetRunner(f, again, sleeps.append, 0)
        stopped.stop()
        out["stopped"] = attempt(stopped.run, once=False)
        out["restart_launched"] = list(again.launched)
        out["exhausted"] = attempt(api.FleetRunner(f, FakeLauncher(api, {}, exhausted=True), sleeps.append, 0).run,
                                   once=True)
        out["exhausted_jobs"] = jobs(f)

        # a paused control while the owned child finishes; heartbeats
        f = fleet()
        f.enqueue("b", manifest("op-0", ["docs/w.md"]), GOAL, [])
        f.admit_one()
        f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
        control = RecordingControl()

        def script(launcher):
            if launcher.waits == 1:
                control.paused = True
                f.enqueue("a", manifest("op-2", ["docs/y.md"]), GOAL, ["op-1"])
            if launcher.waits == 3:
                launcher.released.add("op-1")
        held = HeldLauncher(api, {"op-1": ACCEPTED, "op-2": ACCEPTED}, script)
        runner = api.FleetRunner(f, held, lambda seconds: setattr(control, "stopping", True), 0, control=control)
        out["paused"] = attempt(runner.run, once=False)
        out["paused_beats"] = list(control.beats)
        out["paused_jobs"] = jobs(f)

        # an unreadable control and an unwritable heartbeat; the plain runner has neither state
        f = fleet()
        f.enqueue("a", manifest("op-1", ["docs/x.md"]), GOAL, [])
        control = RecordingControl()
        control.unreadable = control.unwritable = True
        out["unreadable"] = attempt(api.FleetRunner(f, FakeLauncher(api, {}), sleeps.append, 0, control=control).run,
                                    once=True)
        out["plain"] = attempt(api.FleetRunner(f, FakeLauncher(api, {"op-1": ACCEPTED}), sleeps.append, 0).run,
                               once=True)

        # adapter ticks: reconcile fails then recovers; backlog outcomes; transitions logged once
        f = fleet()
        answers = iter([RuntimeError("down"), RuntimeError("still down"), None])

        def reconcile():
            answer = next(answers, None)
            if answer is not None:
                raise answer
        outcomes = iter([{"outcome": "unavailable", "reason_code": "store_unavailable", "error_type": "OSError"},
                         {"outcome": "unavailable", "reason_code": "store_unavailable", "error_type": "OSError"},
                         {"outcome": "idle"}, {"outcome": "refused", "reason_code": "plan_unregistered",
                                               "error_type": "raw text!"}, ValueError("boom")])

        def backlog():
            answer = next(outcomes)
            if isinstance(answer, Exception):
                raise answer
            return answer
        ticks = api.FleetRunner(f, FakeLauncher(api, {}), sleeps.append, 0, reconcile=reconcile, backlog=backlog)
        out["ticks"] = [attempt(ticks.run, once=True) for _ in range(5)]

        # stop forwards to the continuation before any store access
        class Continuation:
            def __init__(self):
                self.calls = []

            def request_stop(self):
                self.calls.append("request_stop")
                return {"asked": ["launch-1"], "failed": [{"launch": "launch-2", "error_type": "OSError"}]}

            def advance(self, *args, **kwargs):
                self.calls.append("advance")
                return {"outcome": "idle"}
        continuation = Continuation()
        forwarded = api.FleetRunner(fleet(), FakeLauncher(api, {}), sleeps.append, 0, continuation=continuation)
        forwarded.stop()
        out["stop_forwarded"] = {"calls": list(continuation.calls), "stop_request": forwarded.stop_request}
        out["logs"] = list(logs.records)
    finally:
        root.removeHandler(logs)
        root.setLevel(previous)
    return json.loads(json.dumps(out, default=str))
