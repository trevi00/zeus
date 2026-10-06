"""The R5 F-1 steps 1-12 (stop before publish), side-neutral: nothing here imports `codex_harness`; each side's driver
(`a.py`, `b.py`) supplies `api` (the use cases built over its own tree, outside production composition).

Layer: harness (never shipped). Rehearsal design "7. R5", critique #14, REBUILD-DESIGN-v2 §1.4 F-1.

CRITIQUE #14: these are HARNESS drivers. The use cases are built here with fixture transports and the fixture lead /
conductor verdicts; `ZEUS_COMPOSITION_PROFILE=production` is NOT set for R5 (R3 and R6 leaf runs keep it). The record says so.

Steps (the flow rows of F-1) and the use cases that perform them:
  1  fleet_resume       Fleet.resume (the copy shows the Fleet paused; resumed IN THE COPY through the product use case)
  2  backlog_register   FleetBacklog.register (row 1: binding before enqueue)
  3  backlog_admit      FleetBacklog.tick: select, intent, Fleet.enqueue, confirm, link (rows 1, 3)
  4  fleet_admit        Fleet.admit_one: the transactional admission of the queued job (row 3)
  5  operation_claim    Operation.claim: own the id, record the binding, queue the assignment (rows 5, 6)
  6  run_task           the real executor/RunTask over the FIXTURE provider transport (rows 7, 8); the unexpected transport raises
  7  review_lead        the lead review decision (row 10), fixture verdict; proposes and reviews the release
  8  review_conductor   the conductor review decision (row 10), fixture verdict; queues the release (row 12)
  stop: nothing here publishes (row 13).
Rows 2, 4, 9 and 11 are in-process in the use cases above (no CLI, no lane launcher process, no owner-action scheduler):
the lane launcher and the owner-action delivery registration spawn processes or need the live scheduler, so they are
named gaps in the record (`not_exercised`).

Determinism: every step starts its id counter at a step-scoped base (`step_index * ID_STRIDE`), so a side that draws one
id more or fewer in an earlier step cannot shift every later key (M7 `envelope()` draws a uuid even when `message_id` is
replaced; the existing compare families already match id-for-id per family). Ids of the scenario's own records carry the
nonce `rh-<run8>`. Both sides read the same scripted clock (`advance`).
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

DRIVERS = Path(__file__).resolve().parents[2] / "drivers"
sys.path.insert(0, str(DRIVERS / "common"))
sys.path.insert(0, str(DRIVERS.parent / "harness"))

import s5_operation as op_fix  # noqa: E402
import s8_fleet_backlog as bl_fix  # noqa: E402

ID_STRIDE = 10_000
STEPS = ("fleet_resume", "backlog_register", "backlog_admit", "fleet_admit", "operation_claim", "run_task",
         "review_lead", "review_conductor")
NOT_EXERCISED = ("row 2 lane launcher argv (spawns a process)", "row 4 operate-run argv (spawns a process)",
                 "row 11 owner-action delivery registration (needs the live scheduler)", "rows 13-15 publish and later")
PLAN = {"title": "Fixture plan", "objective": "Tighten one fixture", "summary": "fixture",
        "acceptance_criteria": ["fixture passes"], "allowed_paths": ["src/fixture.py"],
        "evidence": "fixture", "risk": "low", "rollback": "revert"}
CANDIDATE = {"revision": "revision", "base": "base", "tree": "tree", "author": "worker:implementation"}


class Scenario:
    """`api` supplies: `store` (RecordingStore over the side's PostgresStore), `clock`/`ids` (the fake sources),
    `advance(seconds)`, `reseed(base)`, `fleet`, `backlog`, `validate_manifest`, `loader_api`, `operation`, `run_task`
    (`new_task(envelope args) -> None`, `execute(agent) -> dict|None`), `decisions` (`seed(...)`, `decide(agent)`),
    `release_ids()`, and `recorder`."""

    def __init__(self, api, run8: str, *, unstubbed: str | None = None):
        self.api, self.run8, self.unstubbed = api, run8, unstubbed
        self.nonce = "rh-" + run8
        self.results: dict[str, dict] = {}
        self.manifest = None

    def _step(self, index: int, name: str, call):
        self.api.reseed((index + 1) * ID_STRIDE)
        self.api.advance(1)
        marker = self.api.log.mark()
        try:
            value = {"ok": True, "value": call()}
        except Exception as exc:  # a refusal is a recorded step result, never silently dropped
            value = {"ok": False, "error": type(exc).__name__, "message": str(exc)[:200],
                     "trace": traceback.format_exc().splitlines()[-3:]}
        value["units"] = self.api.log.units_since(marker)
        self.results[name] = value
        return value

    def run(self) -> dict:
        api, nonce = self.api, self.nonce
        plan_id, item_id, op_id = nonce + "-plan", nonce + "-item-1", nonce + "-op-1"
        lane = "a"
        items = [bl_fix.item(item_id, lane=lane)]
        document = bl_fix.plan(api.loader_api, items, plan_id=plan_id, lane=lane)
        manifest = bl_fix.manifest(api.loader_api, op_id, ["docs/" + item_id + ".md"])
        loader = lambda item: {"manifest": manifest, "goal": dict(bl_fix.GOAL),  # noqa: E731
                               "repository": bl_fix.lane_identity(api.loader_api, item["lane"])}
        steps = [
            ("fleet_resume", lambda: _digest(api.fleet.resume())),
            ("backlog_register", lambda: _digest(api.backlog.register(document, bl_fix.pin()))),
            ("backlog_admit", lambda: _digest(api.backlog.tick(plan_id, loader))),
            ("fleet_admit", lambda: _digest(api.fleet.admit_one())),
            ("operation_claim", lambda: _digest(api.operation.claim(op_fix.manifest(id=op_id), op_fix.IDENTITY,
                                                                    op_fix.BOUND_GOAL))),
            ("run_task", lambda: self._run_task()),
            ("review_lead", lambda: self._review("review_lead", "lead:improvement")),
            ("review_conductor", lambda: self._review("review_conductor", "conductor")),
        ]
        for index, (name, call) in enumerate(steps):
            result = self._step(index, name, call)
            if not result["ok"]:
                break  # fail closed: later steps would run on a state the earlier step did not produce
        return {"steps": self.results, "completed": [s for s in STEPS if self.results.get(s, {}).get("ok")]}

    def _run_task(self) -> dict:
        self.api.run_task.submit_plan(PLAN)
        self.api.advance(1)
        outcome = self.api.run_task.execute("lead:improvement")
        status = None if outcome is None else outcome.get("status")
        if status != "succeeded":
            # The executor records a transport error on the task row instead of raising: fail the scenario closed here, with
            # the recorded error (this is how an unstubbed or unexpected transport surfaces).
            raise RuntimeError(f"task ended {status!r}: {str((outcome or {}).get('error'))[:160]}")
        return {"status": status, "provider_calls": self.api.run_task.provider_calls()}

    def _review(self, phase: str, actor: str) -> dict:
        decisions = self.api.decisions
        release = decisions.latest_release_id() if phase == "review_conductor" else None
        if phase == "review_conductor" and release is None:
            raise RuntimeError("the lead review left no release to review")
        decisions.seed(phase, actor, CANDIDATE, release)
        self.api.advance(1)
        outcome = decisions.decide(actor)
        return {"status": None if outcome is None else outcome.get("status"), "release_proposed": release is not None}


class UnitLog:
    """The unit boundaries of a `recorder.Recorder`, per step: `mark()` then `units_since(mark)` -> one row per
    BEGIN..COMMIT/ROLLBACK, `{label, outcome, writes: [[bucket, key]...]}` in execution order (unit ids are ordinal)."""

    def __init__(self, recorder):
        self.recorder = recorder

    def mark(self) -> int:
        return len(self.recorder.events)

    def units_since(self, mark: int) -> list[dict]:
        units: dict[str, dict] = {}
        order: list[str] = []
        for event in self.recorder.events[mark:]:
            if event["kind"] == "BEGIN":
                units[event["unit"]] = {"label": event.get("label", ""), "outcome": None, "writes": [], "depth": event["depth"]}
                order.append(event["unit"])
            elif event["kind"] == "write" and event["unit"] in units:
                units[event["unit"]]["writes"].append([event["bucket"], event["key"]])
            elif event["kind"] in ("COMMIT", "ROLLBACK") and event["unit"] in units:
                units[event["unit"]]["outcome"] = event["kind"]
        return [units[u] for u in order]

    def violations(self) -> list[dict]:
        return list(self.recorder.violations)


def _digest(value) -> dict:
    """A bounded view of a use-case return value: its top-level keys and their scalar values (no record bodies)."""
    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    return {k: (v if isinstance(v, (str, int, float, bool)) or v is None else type(v).__name__)
            for k, v in sorted(value.items())}


def dump(path: Path, document: dict) -> None:
    Path(path).write_text(json.dumps(document, sort_keys=True, ensure_ascii=False, indent=1), encoding="utf-8")
