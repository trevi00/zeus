"""Reference driver: `intake.frontdesk` (M7 `application.frontdesk`: `FrontDesk`, `DeskRunner`, `correlation_of`, `message_id_of`).

The API holds the plain M7 objects `tests/test_frontdesk.py` uses:
- `adapters.store.MemoryStore`, `adapters.contracts.validate_message`, `bootstrap.organization`; `application.frontdesk`: `FrontDesk`,
  `DeskRunner`, `LEAD`, `SUMMARY_TURNS`, `correlation_of`, `message_id_of`; `application.service.Harness`;
  `application.workflow`: `Workflow`, `ClaimGuardRefused`; `domain.frontdesk` (the front-door domain: constants, `prior_turns`,
  `validate_answer`, `DeskRefused`); `domain.model.canonical`; `ports.MessageDeliveryError`.
The executor, bus and collector are the scenario's LABELLED doubles. Plain M7 objects or lambdas over them only. The clock and the id
source are the harness's (`determinism.install`)."""

import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_frontdesk  # noqa: E402

from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import frontdesk as application  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import ClaimGuardRefused, Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import frontdesk as domain  # noqa: E402
from codex_harness.domain.model import canonical  # noqa: E402
from codex_harness.ports import MessageDeliveryError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(
    MemoryStore=MemoryStore, FrontDesk=application.FrontDesk, DeskRunner=application.DeskRunner, LEAD=application.LEAD,
    SUMMARY_TURNS=application.SUMMARY_TURNS, correlation_of=application.correlation_of, message_id_of=application.message_id_of,
    Harness=Harness, Workflow=Workflow, ClaimGuardRefused=ClaimGuardRefused, organization=organization, domain=domain,
    validate_message=validate_message, canonical=canonical, MessageDeliveryError=MessageDeliveryError,
    advance=CLOCK.advance, reset=reset)

if __name__ == "__main__":
    driver.finish("reference", "intake.frontdesk", s8_frontdesk.run(API))
