"""Reference driver: `intake.frontdesk_adapter` (M7 `adapters/frontdesk.py`: `execute_frontdesk`, `clean_checkout`, the desk output schema and
prompt, and the monitoring evidence builder `monitoring_facts`/`monitoring_evidence` with its default `snapshot_path`).

The API holds the plain M7 objects `tests/test_frontdesk.py` uses: `adapters.frontdesk` (the module under characterization),
`adapters.monitoring_readiness.readiness` (the endpoint's rule the desk must agree with), `adapters.store.MemoryStore`,
`application.service.Harness`, `application.frontdesk.FrontDesk`/`message_id_of`, `bootstrap.organization`. The executor, its git and `_run` are the
scenario's LABELLED doubles. `default_path` is the M7-only seam over `snapshot_path` (the runtime file `execute_frontdesk(snapshot=None)` and
`monitoring_evidence()` read), exactly what M7's tests monkeypatch; the target has none (DESIGN-s8 §12.1 V17).
The clock and the id source are the harness's (`determinism.install`); `API.datetime` is the datetime class that install put into the M7 modules."""

import contextlib
import sys
from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

import determinism  # noqa: E402
import s8_frontdesk_adapter  # noqa: E402

from codex_harness.adapters import frontdesk as adapter  # noqa: E402
from codex_harness.adapters.monitoring_readiness import readiness  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import execution_time  # noqa: E402,F401
from codex_harness.application import frontdesk as application  # noqa: E402
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
# M7 draws `execution_time.DOMAIN` (this process's clock-domain identity, recorded on every task) at import: pin it, as pilot 84 does
FakeDateTime = determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e5e5"}})


def reset():
    CLOCK.reset()
    IDS.reset()


@contextlib.contextmanager
def max_bytes(value):
    """The M7 test's `monkeypatch.setattr(frontdesk_adapter, "MONITORING_MAX_BYTES", 10)`."""
    saved = adapter.MONITORING_MAX_BYTES
    adapter.MONITORING_MAX_BYTES = value
    try:
        yield
    finally:
        adapter.MONITORING_MAX_BYTES = saved


class DefaultPath:
    """The M7-only seam: `snapshot_path` replaced as M7's tests do (`monkeypatch.setattr(frontdesk_adapter, "snapshot_path", lambda: path)`)."""

    @contextlib.contextmanager
    def install(self, path):
        saved = adapter.snapshot_path
        adapter.snapshot_path = lambda: path
        try:
            yield
        finally:
            adapter.snapshot_path = saved

    @staticmethod
    def collected(age):
        """An ISO `collected_at` that is `age` seconds old on the harness clock the M7 modules read."""
        return (CLOCK.now(timezone.utc) - timedelta(seconds=age)).isoformat()

    def current(self):
        return adapter.snapshot_path()

    def raising(self, exc):
        saved = adapter.snapshot_path

        def fail():
            raise exc

        adapter.snapshot_path = fail
        try:
            return adapter.monitoring_evidence()
        finally:
            adapter.snapshot_path = saved


API = SimpleNamespace(
    datetime=FakeDateTime, MemoryStore=MemoryStore, FrontDesk=application.FrontDesk, Harness=Harness, organization=organization,
    DeskRunner=application.DeskRunner, message_id_of=application.message_id_of, advance=CLOCK.advance, reset=reset,
    execute_frontdesk=adapter.execute_frontdesk, clean_checkout=adapter.clean_checkout, monitoring_facts=adapter.monitoring_facts,
    monitoring_evidence=adapter.monitoring_evidence, readiness=readiness, max_bytes=max_bytes, default_path=DefaultPath(),
    constants={name: getattr(adapter, name) for name in s8_frontdesk_adapter.CONSTANT_NAMES})

if __name__ == "__main__":
    driver.finish("reference", "intake.frontdesk_adapter", s8_frontdesk_adapter.run(API))
