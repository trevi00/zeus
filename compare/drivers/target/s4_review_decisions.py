"""Target driver: `review.decisions` on the target tree (coordination claim_decision -> review ReviewDecisions).

The reference runs M7 `Executor.decide_one` (the claim transaction, the verdict, then the commit unit) with a
fixture `_run`. Here composition's order is reproduced by hand:
- coordination claims; the owner id is the next scripted id, drawn where decide_one draws it;
- then ReviewDecisions decides, with the same fixture verdict behind the VerdictInvoker port.
Ids and clocks are injected from the same scripted sources. The observer's process run id is drawn where M7's
Executor constructor draws it. The target is never monkeypatched. The cases and the reported summary are the
reference's (no payloads).
"""

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
from codex_harness.coordination.application import execution_time  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.kernel.policy import POLICY  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402
from s4_decision_composition import Composition  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, PIDS = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000d4d4"  # the reference's clock-domain identity
ORG = packaged_organization()


def case(root: Path, name: str, phase: str, actor: str, verdict: dict, loop: dict | None = None) -> dict:
    CLOCK.reset()
    IDS.reset()
    tmp = root / name
    tmp.mkdir(parents=True)
    store = MemoryStore()
    git = SimpleNamespace(repository=tmp, inspect=lambda *a: {},
                          review_workspace=lambda *a: str(tmp),
                          _git=lambda *a, **k: "" if a[0] == "status" else "revision")
    executor = Composition(store, ORG, git, clock=PORT, ids=PIDS, monotonic=CLOCK.monotonic)
    candidate = {"revision": "revision", "base": "base", "tree": "tree",
                 "author": "worker:implementation"}
    data = {"candidate": candidate, "source_actor": "worker:implementation",
            "occurrence_id": "occurrence", "source_task_id": "task", "evidence_ref": "fixture:error"}
    if phase == "review_conductor":
        release = executor.releases.propose(candidate, {"checks": ["tests"]})
        executor.releases.review(release["id"], "lead:improvement", "revision", True, "fixture:lead")
        data["release_id"] = release["id"]
    message = envelope("task.assign", "lead:improvement", "worker:implementation", "implement",
                       {}, "correlation", clock=PORT, ids=PIDS)
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

    executor.verdict = run
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
    driver.finish("target", "review.decisions", out)


if __name__ == "__main__":
    main()
