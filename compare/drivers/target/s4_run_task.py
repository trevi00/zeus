"""Target driver: `execution.run_task` on the target tree (RunTask composed by hand, as S10 will).

It mirrors `drivers/reference/s4_run_task.py` case for case, using the same fixture transport, the loud Claude stub,
the same fixed disposable workspace root and the same reported summary. The substitutions:
- **Composition by hand.** Instead of M7's Executor: coordination Workflow (submit with the real adoption gate
  and the `no_operations` park stub, see s4_submit), TaskOwnership, Breaker/InvocationBreaker, SessionCheckpoints
  and ExecutionRecords; the target InvocationLedger; the moved Observer; the S2 ContextComposer over the same
  fixture git; execution.adapters Transports with the fixture as the host App Server and the Claude stub.
- **Ids and clocks injected.** They come from the same scripted sources, never patched in. The observer's process
  run id is drawn where M7's Executor constructor draws it.
- **Host facts.** `host_python` and the review interpreter are the fixture interpreter the reference installs as
  `sys.executable`. The host hook configuration is `{}`: no hook is active here, so M7's NativeHooks.configuration()
  returns `{}` too.
"""

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
from codex_harness.coordination.application import execution_fence, execution_time  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.message import envelope  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from s1_target import PortClock, PortIds  # noqa: E402
from s4_run_task_composition import run_task_for  # noqa: E402

ROOT = Path("/tmp/zeus-rebuild-s4-run-task")
MARKER = ".zeus-rebuild-s4-disposable"
CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
PORT, PIDS = PortClock(CLOCK), PortIds(IDS)
execution_time.DOMAIN = "00000000-0000-4000-8000-00000000c0c0"  # the reference's clock-domain identity
ORG = packaged_organization()
PLAN = {"title": "Fixture plan", "objective": "Tighten one fixture", "summary": "fixture",
        "acceptance_criteria": ["fixture passes"], "allowed_paths": ["src/fixture.py"],
        "evidence": "fixture", "risk": "low", "rollback": "revert"}
CASES = ("success", "refusal_before_entry", "provider_failure", "timeout", "partial", "lease_lost",
         "context_overflow")


def fresh_root() -> Path:
    if ROOT.exists():
        if not (ROOT / MARKER).exists():
            raise SystemExit(f"{ROOT} exists and is not a labelled disposable S4 root")
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    (ROOT / MARKER).write_text("disposable S4 run-task workspace\n", encoding="utf-8")
    return ROOT





def schema_answer(schema: dict) -> dict:
    """A minimal value for a closed object schema (strings, string lists, integers, booleans)."""
    answer = {}
    for name, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type")
        if name in PLAN:
            answer[name] = PLAN[name]
        elif kind == "array":
            answer[name] = []
        elif kind == "integer":
            answer[name] = 0
        elif kind == "boolean":
            answer[name] = False
        elif kind == "object":
            answer[name] = schema_answer(spec)
        else:
            answer[name] = "fixture"
    return answer


def run_case(case: str) -> dict:
    root = fresh_root()
    CLOCK.reset()
    IDS.reset()
    interpreter = root / "bin" / "python"
    interpreter.parent.mkdir()
    interpreter.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    interpreter.chmod(0o755)
    store = MemoryStore()
    artifacts = FileArtifacts(str(root / "artifacts"), clock=PORT)
    calls = []

    class FixtureTransport:
        enters_on_open = case != "refusal_before_entry"

        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def run(self, prompt, cwd, schema, *args, **kw):
            calls.append(case)
            if case == "refusal_before_entry":
                raise ContractError("Codex App Server is unavailable")
            event = {"method": "item/completed", "params": {"item": {"id": "c" + str(len(calls)),
                                                                     "type": "command"}}}
            kw["on_event"](event)
            CLOCK.advance(1)
            if case == "timeout":
                raise ContractError("Codex turn execution budget exceeded")
            if case == "lease_lost":
                with store.transaction() as tx:
                    row = next(r for r in tx.scan("tasks") if r["status"] == "running")
                    generation = row["generation"] + 1
                    execution_fence.advance(tx, "tasks", row["id"], generation, "other-owner", clock=PORT)
                    row.update(generation=generation, owner="other-owner", lease_owner="other-owner")
                    tx.put("tasks", row["id"], row)
            base = {"events": [event], "thread_id": "thread-" + case, "turn_id": "turn-" + str(len(calls)),
                    "usage": {"totalTokens": 123}, "rotate": False, "interrupted": False}
            if case == "provider_failure":
                return {**base, "answer": None,
                        "failure": {"cause": "codex-provider-usage-limit-exceeded"}}
            if case == "partial":
                return {**base, "answer": None, "rotate": True, "interrupted": True}
            return {**base, "answer": schema_answer(schema)}

    git = SimpleNamespace(repository=root, _git=lambda *a, **kw: "harness")
    run_task, workflow = run_task_for(store, ORG, artifacts, git, interpreter, FixtureTransport, clock=PORT, ids=PIDS,
                                      monotonic=CLOCK.monotonic)
    objective = ("x" * 40000) if case == "context_overflow" else PLAN["objective"]
    details = {"plan": {**PLAN, "objective": objective}}
    workflow.submit(envelope("task.assign", "conductor", "lead:improvement", "plan", details, "fixture",
                             clock=PORT, ids=PIDS))
    CLOCK.advance(1)
    outcome = run_task.execute_one("lead:improvement")
    with store.transaction() as tx:
        rows = tx.records()
    buckets = {}
    for row in rows:
        buckets[row["bucket"]] = buckets.get(row["bucket"], 0) + 1
    task = next(r["body"] for r in rows if r["bucket"] == "tasks")
    reservations = sorted(
        ({"status": r["body"]["status"], "outcome": r["body"].get("outcome"),
          "usage_source": r["body"]["usage"]["source"], "reason": r["body"].get("reason"),
          "invocation": r["body"]["invocation"], "generation": r["body"]["generation"],
          "attempt": r["body"]["attempt"]}
         for r in rows if r["bucket"] == "invocation_reservations"),
        key=lambda x: (x["generation"], x["attempt"], x["invocation"]))
    events = sorted(r["body"].get("type") for r in rows if r["bucket"] == "events")
    outbox = sorted("{} {}>{}:{} sent={}".format(
        r["body"]["message"]["type"], r["body"]["message"]["who"]["sender"],
        r["body"]["message"]["who"]["recipient"], r["body"]["message"]["what"]["action"], r["body"]["sent"])
        for r in rows if r["bucket"] == "outbox")
    error = task.get("error")
    shutil.rmtree(root)
    return {
        "returned": None if outcome is None else {"status": outcome.get("status"),
                                                  "same_row": outcome.get("id") == task["id"]},
        "task": {"status": task["status"], "attempt": task["attempt"], "generation": task["generation"],
                 "lease_owner": ("none" if task.get("lease_owner") is None else "other"
                                 if task.get("lease_owner") == "other-owner" else "claimant"),
                 "error_class": None if not isinstance(error, str) else error.split(":", 1)[0],
                 "error": error if isinstance(error, str) and len(error) <= 160 else
                 (None if error is None else "len>160"),
                 "result_keys": sorted(task["result"]) if isinstance(task.get("result"), dict) else None},
        "reservations": reservations,
        "buckets": dict(sorted(buckets.items())),
        "events": events,
        "outbox": outbox,
        "provider_calls": len(calls),
    }


def main() -> None:
    out = {case: run_case(case) for case in CASES}
    driver.finish("target", "execution.run_task", out)


if __name__ == "__main__":
    main()
