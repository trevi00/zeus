"""Target driver: `delivery.migration_evidence` on the target tree (S7 pilot 46).

The API holds the moved `delivery.adapters.host_migration_evidence` names with the V6 injections closed over the wiring a
composition would pass (DESIGN-s7 adapters-move §9.4), so the common module runs unchanged:
- `HostReader` is the moved class with `processes` closed over the chokepoint (`ChokepointProcesses()`): a subclass whose
  constructor adds that one keyword. Every case passes its own `facts`, runner, clock and offset as in the reference, and
  the class's static reads (`file`, `exists`, `current`, `release_present`) are the moved ones.
- `bounded_run` is the moved function with `processes` closed over the same chokepoint.
- `HostFacts` is the moved `host_os.adapters.host_facts` class (pilot 46 move-ahead).
- `main`, `parser`, `cli_ports`, `patched`, `patch_connect`, `forbid_writer_store`, `LaneSnapshotStore`, `conninfo_to_dict`
  and `OperationalError` (the S10 operator CLI) are not part of the target api: their cases are
  `delivery.migration_evidence_cli`.
- `launcher_emit` and `launcher_path` are the unchanged deploy/aibox launcher, loaded from the SOURCE tree as the
  reference loads it.

The clock seam (as in pilot 44): this driver installs no fake clock. The reference's install of its fake clock also freezes
`time.monotonic`; here `bounded_run`'s deadline reads the real monotonic clock, so the one deadline case crosses its
0.5 s deadline by itself, and `advance` only moves the driver's own `determinism.FakeClock` (it ends where it began).
For the run the module's `_utcnow` default is substituted with that same fake clock (a module-attribute substitution,
restored afterwards); every case passes its own `Clock` to `Ports`, so the substitution is the same seam as in the transfer
driver, not a read path of this family."""

import contextlib
import importlib.util
import os
import sys
from datetime import timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import determinism  # noqa: E402
import s7_migration_evidence  # noqa: E402
from codex_harness.coordination.domain import owner_actions  # noqa: E402
from codex_harness.delivery.adapters import host_delivery, host_migration  # noqa: E402
from codex_harness.delivery.adapters import host_migration_evidence as adapter  # noqa: E402
from codex_harness.delivery.application import host_migration as migration_application  # noqa: E402
from codex_harness.delivery.application.host_delivery import state as delivery_state  # noqa: E402
from codex_harness.delivery.domain import host_delivery as delivery  # noqa: E402
from codex_harness.delivery.domain import host_migration as migration  # noqa: E402
from codex_harness.delivery.domain import host_migration_evidence as policy  # noqa: E402
from codex_harness.delivery.domain import managed_runtime  # noqa: E402
from codex_harness.host_os.adapters.host_facts import HostFacts  # noqa: E402
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

CLOCK = determinism.FakeClock()
PROCESSES = ChokepointProcesses()

LAUNCHER_PATH = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_evidence", LAUNCHER_PATH)
_launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launcher)


class HostReader(adapter.HostReader):
    """The moved `HostReader` with the V6 `processes` closed over the chokepoint (what composition passes)."""

    def __init__(self, **kwargs):
        super().__init__(processes=PROCESSES, **kwargs)


def bounded_run(argv, **kwargs):
    return adapter.bounded_run(argv, processes=PROCESSES, **kwargs)


@contextlib.contextmanager
def environ(values):
    with mock.patch.dict(os.environ, values):
        yield


API = SimpleNamespace(
    observe=adapter.observe, Ports=adapter.Ports, HostReader=HostReader, bounded_run=bounded_run,
    boottime_offset_usec=adapter.boottime_offset_usec, Unreadable=adapter.Unreadable,
    validate_request=adapter.validate_request, SYSTEMCTL=adapter.SYSTEMCTL, JOURNALCTL=adapter.JOURNALCTL,
    COMMAND_ENV=adapter.COMMAND_ENV, MAX_COMMAND_BYTES=adapter.MAX_COMMAND_BYTES,
    document_bytes=host_migration._document_bytes, owner_qualified_canary=host_delivery.owner_qualified_canary,
    HostFacts=HostFacts, MemoryStore=MemoryStore, HostMigrations=migration_application.HostMigrations,
    BUCKET=migration_application.BUCKET, BUCKET_TARGETS=delivery_state.BUCKET_TARGETS,
    BUCKET_PLANS=delivery_state.BUCKET_PLANS, BUCKET_INTENTS=delivery_state.BUCKET_INTENTS,
    BUCKET_DESCRIPTORS=delivery_state.BUCKET_DESCRIPTORS, policy=policy, migration=migration,
    MANIFEST_SCHEMA=migration.MANIFEST_SCHEMA, ACTIVE=delivery.ACTIVE, DESCRIPTOR_SCHEMA=delivery.DESCRIPTOR_SCHEMA,
    PLAN_SCHEMA=delivery.PLAN_SCHEMA, RECEIPT_SCHEMA=delivery.RECEIPT_SCHEMA,
    descriptor_digest=delivery.descriptor_digest, new_intent=delivery.new_intent, plan_digest=delivery.plan_digest,
    validate_plan=delivery.validate_plan, validate_targets=delivery.validate_targets,
    blob_id=managed_runtime.blob_id, new_manifest=managed_runtime.new_manifest, digest=digest,
    DELIVERY_CANARY=owner_actions.DELIVERY_CANARY, action_id=owner_actions.action_id,
    canary_receipt=owner_actions.canary_receipt, canary_request=owner_actions.canary_request,
    launcher_emit=_launcher.emit, launcher_path=str(LAUNCHER_PATH), environ=environ, advance=CLOCK.advance)


@contextlib.contextmanager
def fake_utcnow():
    saved = adapter._utcnow
    adapter._utcnow = lambda: CLOCK.now(timezone.utc).isoformat()
    try:
        yield
    finally:
        adapter._utcnow = saved


if __name__ == "__main__":
    with fake_utcnow():
        result = s7_migration_evidence.run(API)
    driver.finish("target", "delivery.migration_evidence", result)
