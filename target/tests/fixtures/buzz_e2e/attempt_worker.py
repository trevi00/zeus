"""Buzz D2: the fixture attempt worker of the isolated end-to-end runner, plus the fixture Zeus builders it shares.

Standalone, NOT collected by pytest. The runner starts it in its own process group; it is never left running. It holds
ONE claimed task's fence generation (the row the runner's `Workflow.claim` returned, re-read here) and, every second,
attempts the terminal write's guard in a PostgreSQL transaction: `execution_fence.require_current(tx, "tasks", id,
generation, owner)` (INV-EXECUTION-IDENTITY-001). The first refusal is recorded as `fence_lost` and the worker exits.
With `--complete-on FILE` the worker instead performs the REAL terminal write, `Workflow.complete`, once FILE exists
(the `_owned` check inside it re-reads the same fence); that is the "fixture work" that finishes while the bridge is
down (DESIGN-D §4 step 9).

The DSN comes from the 0600 file named by the environment variable ZEUS_E2E_DSN_FILE (never argv); it is never printed.
The status file (`--status-file`, rewritten atomically) holds counts and flags only: attempts, fence_ok, fence_lost,
completed, error (an exception class name).

    python attempt_worker.py --task ID --generation N --owner OWNER --organization FILE --status-file FILE [--complete-on FILE]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from codex_harness.coordination.application import execution_fence
from codex_harness.coordination.application.operation_finalization import park
from codex_harness.coordination.application.workflow import Workflow
from codex_harness.intake.application import tickets
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS
from codex_harness.research.application.audit_gate import require_adoption
from codex_harness.routing.domain.organization import Agent, Organization
from codex_harness.storage.adapters.postgres_store import PostgresStore

DSN_ENV = "ZEUS_E2E_DSN_FILE"
PERIOD_SECONDS = 1.0


def load_organization(path) -> Organization:
    """The fixture organization, validated as the bridge's `BridgeConfig.load_organization` validates it."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    organization = Organization({a["id"]: Agent(**a) for a in data["agents"]})
    organization.validate()
    return organization


def build_workflow(store, organization) -> Workflow:
    """The target `Workflow`, wired exactly as `composition.buzz_world.zeus_world` wires it (claim: `Workflow.claim`)."""
    return Workflow(store, organization, ticket_binding=tickets.ticket_binding,
                    TicketSuperseded=tickets.TicketSuperseded, adoption=require_adoption, park_terminal=park,
                    clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)


class Status:
    """The worker's status file: written whole, atomically (tmp + rename), counts and flags only."""

    def __init__(self, path):
        self.path = Path(path)
        self.body = {"attempts": 0, "fence_ok": 0, "fence_lost": False, "completed": False, "error": None,
                     "started_at": time.time()}
        self.write()

    def write(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.body), encoding="utf-8")
        os.replace(tmp, self.path)


def attempt_guard(store, task_id, generation, owner) -> None:
    """The terminal write's guard: `ContractError` when the durable fence no longer matches the held generation."""
    with store.transaction() as tx:
        execution_fence.require_current(tx, "tasks", task_id, generation, owner)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Buzz D2 fixture attempt worker (never run by pytest)")
    parser.add_argument("--task", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--complete-on")
    args = parser.parse_args(argv)
    status = Status(args.status_file)
    store = PostgresStore(Path(os.environ[DSN_ENV]).read_text(encoding="utf-8").strip())
    workflow = build_workflow(store, load_organization(args.organization))
    with store.transaction() as tx:
        task = tx.get("tasks", args.task)
    if task is None or task["generation"] != args.generation or task["lease_owner"] != args.owner:
        status.body["error"] = "task_not_held"
        status.write()
        return 1
    while True:
        status.body["attempts"] += 1
        try:
            if args.complete_on and Path(args.complete_on).exists():
                workflow.complete(task, {"summary": "fixture work completed while the bridge was down"})
                status.body["completed"] = True
                status.write()
                return 0
            attempt_guard(store, args.task, args.generation, args.owner)
            status.body["fence_ok"] += 1
        except ContractError as exc:  # the fence moved on (cancel advanced it) or the row is no longer ours
            status.body["fence_lost"] = True
            status.body["error"] = type(exc).__name__
            status.write()
            return 0
        except Exception as exc:  # noqa: BLE001 - a store failure is reported by class, never by message
            status.body["error"] = type(exc).__name__
        status.write()
        time.sleep(PERIOD_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
