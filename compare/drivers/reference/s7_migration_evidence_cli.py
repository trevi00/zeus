"""Reference driver: `delivery.migration_evidence_cli` (the in-process operator CLI cases of M7
`adapters/host_migration_evidence.py` and `adapters/host_migration.py`: `main`, `parser`, `cli_ports`; split out of
`delivery.migration_evidence`, S7 pilot 46). The api is the evidence reference driver's, unchanged.

The API holds plain M7 objects.
- From `adapters.host_migration_evidence`: `observe`, `Ports`, `HostReader`, `bounded_run`, `boottime_offset_usec`,
  `Unreadable`, `validate_request`, `cli_ports`, `SYSTEMCTL`, `JOURNALCTL`, `COMMAND_ENV`, `MAX_COMMAND_BYTES`.
- From `adapters.host_migration`: `main`, `parser` and `document_bytes` (`_document_bytes`).
- From `adapters.host_delivery`: `owner_qualified_canary`. From `adapters.release_verifier`: `HostFacts`.
  From `adapters.store`: `MemoryStore`. From `adapters.monitoring`: `LaneSnapshotStore`.
- From `application.host_migration`: `HostMigrations` and the bucket `BUCKET`. From `application.host_delivery`:
  `BUCKET_TARGETS`, `BUCKET_PLANS`, `BUCKET_INTENTS`, `BUCKET_DESCRIPTORS`.
- Domain: `policy` (`domain.host_migration_evidence`), `migration` (`domain.host_migration`, with `MANIFEST_SCHEMA`),
  `ACTIVE`, `DESCRIPTOR_SCHEMA`, `PLAN_SCHEMA`, `RECEIPT_SCHEMA`, `descriptor_digest`, `new_intent`, `plan_digest`,
  `validate_plan`, `validate_targets` (`domain.host_delivery`), `blob_id`, `new_manifest` (`domain.managed_runtime`),
  `digest` (`domain.model`), `DELIVERY_CANARY`, `action_id`, `canary_receipt`, `canary_request`
  (`domain.owner_actions`).
- `launcher_emit` and `launcher_path`: the unchanged deploy/aibox launcher's `emit` and its path, loaded from the
  SOURCE checkout (`ZEUS_REBUILD_SOURCE_ROOT`); its own lines are what the journal fixtures carry.
- The in-process CLI hooks, each restored after the case, as M7's monkeypatch does: `patched(**attributes)` (attributes
  of the producer module), `environ(values)` (the process environment), `patch_connect(function)` (`psycopg.connect`),
  `forbid_writer_store(record)` (the `PostgresStore` constructor) and `conninfo_to_dict`, `OperationalError` (psycopg).
- `advance(seconds)` moves the driver's fake clock, because `determinism.install` freezes `time.monotonic` and
  `bounded_run`'s deadline reads it.

The module reads no other clock and no id source."""

import contextlib
import importlib.util
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import determinism  # noqa: E402
import psycopg  # noqa: E402
import s7_migration_evidence_cli  # noqa: E402
from psycopg import OperationalError  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

from codex_harness.adapters import host_delivery, host_migration  # noqa: E402
from codex_harness.adapters import host_migration_evidence as producer  # noqa: E402
from codex_harness.adapters import store as stores  # noqa: E402
from codex_harness.adapters.monitoring import LaneSnapshotStore  # noqa: E402
from codex_harness.adapters.release_verifier import HostFacts  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application import host_delivery as delivery_application  # noqa: E402
from codex_harness.application import host_migration as migration_application  # noqa: E402
from codex_harness.domain import host_delivery as delivery  # noqa: E402
from codex_harness.domain import host_migration as migration  # noqa: E402
from codex_harness.domain import host_migration_evidence as policy  # noqa: E402
from codex_harness.domain import managed_runtime, owner_actions  # noqa: E402
from codex_harness.domain.model import digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)

LAUNCHER_PATH = Path(os.environ["ZEUS_REBUILD_SOURCE_ROOT"]).resolve() / "deploy" / "aibox" / "zeus_aibox_service.py"
_spec = importlib.util.spec_from_file_location("zeus_aibox_service_evidence", LAUNCHER_PATH)
_launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_launcher)


@contextlib.contextmanager
def patched(**attributes):
    with contextlib.ExitStack() as stack:
        for name, value in attributes.items():
            stack.enter_context(mock.patch.object(producer, name, value))
        yield


@contextlib.contextmanager
def environ(values):
    with mock.patch.dict(os.environ, values):
        yield


def patch_connect(function):
    return mock.patch.object(psycopg, "connect", function)


def forbid_writer_store(record):
    def refuse(*args, **kwargs):
        record.append(1)
        raise AssertionError("writer store constructed")

    return mock.patch.object(stores.PostgresStore, "__init__", refuse)


API = SimpleNamespace(
    observe=producer.observe, Ports=producer.Ports, HostReader=producer.HostReader,
    bounded_run=producer.bounded_run, boottime_offset_usec=producer.boottime_offset_usec,
    Unreadable=producer.Unreadable, validate_request=producer.validate_request, cli_ports=producer.cli_ports,
    SYSTEMCTL=producer.SYSTEMCTL, JOURNALCTL=producer.JOURNALCTL, COMMAND_ENV=producer.COMMAND_ENV,
    MAX_COMMAND_BYTES=producer.MAX_COMMAND_BYTES, main=host_migration.main, parser=host_migration.parser,
    document_bytes=host_migration._document_bytes, owner_qualified_canary=host_delivery.owner_qualified_canary,
    HostFacts=HostFacts, MemoryStore=MemoryStore, LaneSnapshotStore=LaneSnapshotStore,
    HostMigrations=migration_application.HostMigrations, BUCKET=migration_application.BUCKET,
    BUCKET_TARGETS=delivery_application.BUCKET_TARGETS, BUCKET_PLANS=delivery_application.BUCKET_PLANS,
    BUCKET_INTENTS=delivery_application.BUCKET_INTENTS, BUCKET_DESCRIPTORS=delivery_application.BUCKET_DESCRIPTORS,
    policy=policy, migration=migration, MANIFEST_SCHEMA=migration.MANIFEST_SCHEMA, ACTIVE=delivery.ACTIVE,
    DESCRIPTOR_SCHEMA=delivery.DESCRIPTOR_SCHEMA, PLAN_SCHEMA=delivery.PLAN_SCHEMA,
    RECEIPT_SCHEMA=delivery.RECEIPT_SCHEMA, descriptor_digest=delivery.descriptor_digest,
    new_intent=delivery.new_intent, plan_digest=delivery.plan_digest, validate_plan=delivery.validate_plan,
    validate_targets=delivery.validate_targets, blob_id=managed_runtime.blob_id,
    new_manifest=managed_runtime.new_manifest, digest=digest, DELIVERY_CANARY=owner_actions.DELIVERY_CANARY,
    action_id=owner_actions.action_id, canary_receipt=owner_actions.canary_receipt,
    canary_request=owner_actions.canary_request, launcher_emit=_launcher.emit, launcher_path=str(LAUNCHER_PATH),
    patched=patched, environ=environ, patch_connect=patch_connect, forbid_writer_store=forbid_writer_store,
    conninfo_to_dict=conninfo_to_dict, OperationalError=OperationalError, advance=CLOCK.advance)

if __name__ == "__main__":
    driver.finish("reference", "delivery.migration_evidence_cli", s7_migration_evidence_cli.run(API))
