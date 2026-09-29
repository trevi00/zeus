"""Reference driver: one task execution from claim to report (REBUILD-DESIGN-v2 §5.3 S4, RESEARCH-S4 D1-D4).

Scenario family `execution.run_task`. Runs M7 `Executor.execute_one('lead:improvement')` for a `plan`
task with an injected fixture transport (the in-process `AppServer` AND `ClaudeCodeRuntime` names are
replaced in this driver process; the Claude stub refuses loudly, so a routing change can never reach a
provider), a fake clock, deterministic ids and a fixed disposable workspace root. Cases:

- success: the transport answers a schema-valid plan;
- refusal_before_entry: the transport refuses before it reports entry (no process);
- provider_failure: the transport returns a named provider failure (usage limit) after entry;
- timeout: the transport raises the Codex turn-budget error after entry;
- partial: every turn is interrupted (context rotation) until the handoff budget is exhausted;
- lease_lost: while the provider runs another owner re-claims the row (generation and durable fence
  advance): the stale holder's terminal write must commit nothing;
- context_overflow: the required task contract exceeds the context budget (no reservation, no entry).

For each case it reports, without payloads: the returned status/error class, the task row fields that
carry ownership (status, attempt, generation, error prefix), the invocation reservations (status,
outcome, usage source, reason, invocation index), the bucket set written with row counts, the event
and outbox message kinds, and how many provider calls happened.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import shutil  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402

from codex_harness.adapters import executor as executor_module  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.executor import Executor  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_fence, execution_time, workflow  # noqa: E402,F401
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain.model import ContractError, envelope  # noqa: E402

ROOT = Path("/tmp/zeus-rebuild-s4-run-task")
MARKER = ".zeus-rebuild-s4-disposable"
CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000c0c0"}})
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


class ClaudeRefused:
    """The unexpected transport: constructing it is a driver failure, never a provider call."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("ClaudeCodeRuntime reached in the S4 run-task fixture")


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
    sys.executable = str(interpreter)
    service = Harness(MemoryStore(), organization())
    artifacts = FileArtifacts(str(root / "artifacts"))
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
                with service.store.transaction() as tx:
                    row = next(r for r in tx.scan("tasks") if r["status"] == "running")
                    generation = row["generation"] + 1
                    execution_fence.advance(tx, "tasks", row["id"], generation, "other-owner")
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

    executor_module.AppServer = FixtureTransport
    executor_module.ClaudeCodeRuntime = ClaudeRefused
    executor = Executor(service, SimpleNamespace(repository=root, _git=lambda *a, **kw: "harness"),
                        artifacts)
    objective = ("x" * 40000) if case == "context_overflow" else PLAN["objective"]
    details = {"plan": {**PLAN, "objective": objective}}
    executor.workflow.submit(envelope("task.assign", "conductor", "lead:improvement", "plan", details,
                                      "fixture"))
    CLOCK.advance(1)
    outcome = executor.execute_one("lead:improvement")
    with service.store.transaction() as tx:
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
    driver.finish("reference", "execution.run_task", out)


if __name__ == "__main__":
    main()
