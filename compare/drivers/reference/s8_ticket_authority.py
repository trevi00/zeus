"""Reference driver: `intake.ticket_authority` (M7 `adapters/ticket_authority.py`: `TicketAuthority`).

The API holds the plain M7 module. Its `run_process` (the `adapters.commands` import, which would spawn `ssh-keygen`) is replaced by the scenario's
LABELLED runner on the module itself, set where each authority is made; its `datetime` is rebound by the harness's `determinism.install` to the scripted
clock, as every loaded `codex_harness` module's is (the clock the scenario advances). No real `ssh-keygen`, key or git repository is used."""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_ticket_authority  # noqa: E402

from codex_harness.adapters import ticket_authority as module  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest, require  # noqa: E402

CLOCK = determinism.FakeClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
determinism.install(CLOCK, determinism.FakeIds())


def make(git, artifacts, trust_commit, runner):
    module.run_process = runner   # the labelled runner replaces the module's `run_process`
    return module.TicketAuthority(git, artifacts, trust_commit)


API = SimpleNamespace(
    clock=CLOCK, utc=timezone.utc, make=make, TicketAuthority=module.TicketAuthority, POLICY_PATH=module.POLICY_PATH, PRINCIPAL=module.PRINCIPAL,
    ContractError=ContractError, canonical=canonical, digest=digest, require=require)

if __name__ == "__main__":
    driver.finish("reference", "intake.ticket_authority", s8_ticket_authority.run(API))
