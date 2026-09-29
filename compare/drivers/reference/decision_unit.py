"""Reference driver: the M7 decision/release/outbox atomic unit (REBUILD-DESIGN-v2 §2.9, F2).

Scenario family `effects.decision_unit`. Runs M7 `Executor.decide_one` -> `_commit_decision` on a
recorded `MemoryStore` with a fixture `_run` (no provider), a fake clock and deterministic ids.
Discriminators (a)-(d) and the recorder's negative controls:
  a  failure after release propose/review, before decisions_pending/outbox -> atomic rollback
  b  stale lease -> fence fails, nothing of the unit commits
  c  same-key replay -> no second effect, no new authority write
  d  the provider effect occurs at depth 0
  controls: split commit (propose opens its own transaction), fence ignored, fabricated
  completion, effect inside a unit -> each must be flagged by the recorder.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import masks  # noqa: E402
import recorder as rec  # noqa: E402

from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import (  # noqa: E402,F401
    execution_recovery,
    execution_time,
    workflow,
)
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import envelope  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000d0d0"}})
AUTHORITY = {"releases", "release_queue", "hooks", "improvement_loops", "incidents"}


def completion(e):
    return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "succeeded"


def intent(e):
    return e["kind"] == "write" and e["bucket"] == "decisions_pending" and e["status"] == "running"


class Injected(RuntimeError):
    pass


def case(root: Path, name: str, phase: str, actor: str, *, failure: str = "none",
         control: str = "none", replay: bool = False) -> dict:
    CLOCK.reset()
    IDS.reset()
    clock = CLOCK
    tmp = root / name
    tmp.mkdir(parents=True)
    masker = masks.Masker("effects.decision_unit")
    store = rec.RecordingStore(MemoryStore(), rec.Recorder(masker.apply))
    recorder = store.recorder
    service = Harness(store, organization())
    git = SimpleNamespace(repository=tmp, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Executor(service, git, FileArtifacts(tmp / "artifacts"))
    candidate = {"revision": "revision", "base": "base", "tree": "tree",
                 "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation",
            "occurrence_id": "occurrence", "source_task_id": "task", "evidence_ref": "fixture:error"}
    if phase == "review_conductor":
        release = executor.releases.propose(candidate, {"checks": ["tests"]})
        executor.releases.review(release["id"], "lead:improvement", "revision", True, "fixture:lead")
        data["release_id"] = release["id"]
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {}, "correlation")
    with store.transaction() as tx:
        tx.put("decisions_pending", "decision", {"id": "decision", "actor": actor, "phase": phase,
               "input": data, "message": message, "status": "pending", "attempt": 0})
    setup_events = len(recorder.events)
    clock.advance(1)

    def run(*args, **kwargs):
        if control == "effect_in_unit":
            with store.transaction():
                recorder.effect("provider_call")
        elif control != "fabricated_completion":
            recorder.effect("provider_call")
        if failure == "stale_lease":
            with store.transaction() as tx:
                row = tx.get("decisions_pending", "decision")
                row.update(owner="replacement", lease_owner="replacement",
                           generation=row["generation"] + 1)
                tx.put("decisions_pending", "decision", row)
        return {"accepted": True, "confirmed": True, "root_cause": "cause", "scope": "scope",
                "execution_ref": "fixture:review", "reason": "fixture"}

    executor._run = run
    owned = executor.workflow._owned

    def fenced(tx, task, *args, **kwargs):
        try:
            current = owned(tx, task, *args, **kwargs)
        except Exception:
            recorder.fence("lease", False)
            if control == "fence_ignored":
                return tx.get(task.get("_bucket", "tasks"), task["id"])
            raise
        recorder.fence("lease", True)
        return current

    executor.workflow._owned = fenced
    if control == "split_commit":
        propose = executor.releases.propose
        executor.releases.propose = lambda c, p, transaction=None: propose(c, p)
    if failure == "before_decision":
        write = recorder.write

        def failing_write(bucket, key, body):
            write(bucket, key, body)
            if bucket == "decisions_pending" and isinstance(body, dict) \
                    and body.get("status") == "succeeded":
                raise Injected("fixture failure after release effects, before decision/outbox")

        recorder.write = failing_write
        executor.decide_one(actor)
        del recorder.write
    else:
        executor.decide_one(actor)
    if replay:
        clock.advance(1)
        executor.decide_one(actor)
    events = recorder.events[setup_events:]
    durable = recorder.durable_writes(setup_events)
    with store.transaction() as tx:
        final = tx.get("decisions_pending", "decision")
        outbox_types = sorted(r["message"]["type"] for r in tx.scan("outbox"))
    return {
        "verdict": recorder.classify(AUTHORITY, completion, setup_events),
        "violations": sorted({v["kind"] for v in recorder.violations}),
        "effect_protocol": sorted(set(recorder.effect_protocol(intent, completion, setup_events))),
        "effects": [{"name": e["name"], "depth": e["depth"]} for e in events
                    if e["kind"] == "effect"],
        "fences": [e["ok"] for e in events if e["kind"] == "fence"],
        "durable_authority_writes": sorted({(e["bucket"], e["status"] or "") for e in durable
                                            if e["bucket"] in AUTHORITY}),
        "decision_status": final["status"],
        "outbox_types": outbox_types,
        "trace": [{k: v for k, v in e.items() if k not in {"seq", "digest", "key"}} for e in events],
        "trace_digests": [e.get("digest") for e in events if e["kind"] == "write"],
    }


def main() -> None:
    cases = {
        "success_review_lead": dict(phase="review_lead", actor="lead:improvement"),
        "success_review_conductor": dict(phase="review_conductor", actor="conductor"),
        "a_failure_before_decision_review_lead": dict(phase="review_lead", actor="lead:improvement",
                                                      failure="before_decision"),
        "a_failure_before_decision_review_conductor": dict(phase="review_conductor", actor="conductor",
                                                           failure="before_decision"),
        "b_stale_lease": dict(phase="review_lead", actor="lead:improvement", failure="stale_lease"),
        "c_same_key_replay": dict(phase="review_lead", actor="lead:improvement", replay=True),
        "control_split_commit": dict(phase="review_lead", actor="lead:improvement",
                                     failure="before_decision", control="split_commit"),
        "control_fence_ignored": dict(phase="review_lead", actor="lead:improvement",
                                      failure="stale_lease", control="fence_ignored"),
        "control_fabricated_completion": dict(phase="review_lead", actor="lead:improvement",
                                              control="fabricated_completion"),
        "control_effect_in_unit": dict(phase="review_lead", actor="lead:improvement",
                                       control="effect_in_unit"),
    }
    with tempfile.TemporaryDirectory(prefix="zeus-s0-decision-") as raw:
        out = {name: case(Path(raw), name, **kw) for name, kw in cases.items()}
    driver.finish("reference", "effects.decision_unit", out)


if __name__ == "__main__":
    main()
