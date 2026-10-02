"""Target driver: `intake.ticket_authority` on the target tree (S8 batch B1: `intake.adapters.ticket_authority`).

The API mirrors the reference driver's names over the target homes: `TicketAuthority` from `intake.adapters.ticket_authority`, `POLICY_PATH` and
`PRINCIPAL` from the module, the kernel's `ContractError`, `canonical`, `digest` and `require`. The scenario's LABELLED runner reaches the module
through R-ta1 (the keyword-only `run_process`), the scripted clock through R-ta2 (the keyword-only `clock`, the kernel `Clock` port over the harness
clock); the target's standard library and module attributes are never patched."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import determinism  # noqa: E402
import s8_ticket_authority  # noqa: E402
from codex_harness.intake.adapters import ticket_authority as module  # noqa: E402
from codex_harness.kernel.errors import ContractError, require  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from s1_target import PortClock  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))


def make(git, artifacts, trust_commit, runner):
    return module.TicketAuthority(git, artifacts, trust_commit, run_process=runner, clock=PortClock(CLOCK))


API = SimpleNamespace(
    clock=CLOCK, utc=timezone.utc, make=make, TicketAuthority=module.TicketAuthority, POLICY_PATH=module.POLICY_PATH, PRINCIPAL=module.PRINCIPAL,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("target", "intake.ticket_authority", s8_ticket_authority.run(API))
