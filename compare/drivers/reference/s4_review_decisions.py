"""Reference driver: the review accept/reject/rework state machine (REBUILD-DESIGN-v2 §5.3 S4, RESEARCH-S4 D8).

Scenario family `review.decisions`. Runs M7 `Executor.decide_one` -> `_commit_decision` on
`MemoryStore` with a fixture `_run` (no provider; the result is the scripted review verdict), a fake
clock and deterministic ids. Cases:

- lead_accept / conductor_accept: the release is proposed/reviewed; the lead forwards `review.result`
  to the conductor; the conductor queues the release;
- lead_reject_rework / conductor_reject_rework: the improvement loop enters `reworking` and a rework
  assignment (`implement` to the worker / `plan` to the lead) is emitted;
- reject_budget_exhausted: a loop already at `POLICY.max_reworks` stops (`budget_exhausted`), no rework;
- reject_stagnated: the same rejected tree again stops (`stagnated`), no rework;
- blocked / inspection_blocked: a blocked verdict can never approve: no release effect, terminal status;
- blocked_but_accepted: a blocked verdict claiming acceptance is refused (the decision fails).

Reported per case (no payloads): decision status/attempt/generation, the release rows (status and
review verdicts), release_queue statuses, the improvement loop (status, reworks, rejected tree count),
and the outbox message kinds (type sender>recipient:action).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402

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
from codex_harness.domain.policy import POLICY  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000d4d4"}})


def case(root: Path, name: str, phase: str, actor: str, verdict: dict, loop: dict | None = None) -> dict:
    CLOCK.reset()
    IDS.reset()
    tmp = root / name
    tmp.mkdir(parents=True)
    store = MemoryStore()
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
        if loop is not None:
            tx.put("improvement_loops", "correlation", {"id": "correlation", **loop})
    CLOCK.advance(1)
    calls = []

    def run(*args, **kwargs):
        calls.append(phase)
        return {"execution_ref": "fixture:review", "reason": "fixture finding", **verdict}

    executor._run = run
    returned = executor.decide_one(actor)
    with store.transaction() as tx:
        final = tx.get("decisions_pending", "decision")
        releases = sorted(({"status": r.get("status"),
                            "reviews": sorted((v.get("actor"), v.get("accepted")) for v in r.get("reviews", []))}
                           for r in tx.scan("releases")), key=str)
        queue = sorted(r.get("status") for r in tx.scan("release_queue"))
        loop_row = tx.get("improvement_loops", "correlation")
        outbox = sorted("{} {}>{}:{}".format(r["message"]["type"], r["message"]["who"]["sender"],
                                             r["message"]["who"]["recipient"], r["message"]["what"]["action"])
                        for r in tx.scan("outbox"))
    error = final.get("error")
    return {
        "returned_status": None if returned is None else returned.get("status"),
        "decision": {"status": final["status"], "attempt": final["attempt"],
                     "generation": final.get("generation"),
                     "error": error if isinstance(error, str) and len(error) <= 160 else
                     (None if error is None else "len>160")},
        "releases": [{**r, "reviews": [list(v) for v in r["reviews"]]} for r in releases],
        "release_queue": queue,
        "improvement_loop": None if loop_row is None else {
            "status": loop_row.get("status"), "reworks": loop_row.get("reworks"),
            "rejected_trees": len(loop_row.get("rejected_trees", []))},
        "outbox": outbox,
        "provider_calls": len(calls),
    }


def main() -> None:
    accept = {"accepted": True}
    reject = {"accepted": False}
    cases = {
        "lead_accept": dict(phase="review_lead", actor="lead:improvement", verdict=accept),
        "conductor_accept": dict(phase="review_conductor", actor="conductor", verdict=accept),
        "lead_reject_rework": dict(phase="review_lead", actor="lead:improvement", verdict=reject),
        "conductor_reject_rework": dict(phase="review_conductor", actor="conductor", verdict=reject),
        "reject_budget_exhausted": dict(phase="review_lead", actor="lead:improvement", verdict=reject,
                                        loop={"reworks": POLICY.max_reworks, "rejected_trees": ["older"]}),
        "reject_stagnated": dict(phase="review_lead", actor="lead:improvement", verdict=reject,
                                 loop={"reworks": 0, "rejected_trees": ["tree"]}),
        "blocked": dict(phase="review_lead", actor="lead:improvement",
                        verdict={"accepted": False, "blocked": True}),
        "inspection_blocked": dict(phase="review_lead", actor="lead:improvement",
                                   verdict={"accepted": True, "inspection_blocked": True}),
        "blocked_but_accepted": dict(phase="review_lead", actor="lead:improvement",
                                     verdict={"accepted": True, "blocked": True}),
    }
    with tempfile.TemporaryDirectory(prefix="zeus-s4-review-") as raw:
        out = {name: case(Path(raw), name, **kw) for name, kw in cases.items()}
    out["policy"] = {"max_reworks": POLICY.max_reworks}
    driver.finish("reference", "review.decisions", out)


if __name__ == "__main__":
    main()
