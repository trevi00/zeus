"""Target driver: `delivery.migration_evidence_cli` on the target tree (S11 unit AR4-T; the S10 operator CLI).

The API is the target `delivery.migration_evidence` driver's (loaded from its file under a private module name, so its V6
injections, clock seam and `environ` hook are the ones that family already proves equal) plus the S10 CLI the reference
family reaches through M7 `adapters.host_migration_evidence` and `adapters.host_migration`:
- `main` and `parser` are `entry.processes.host_migration`'s; `cli_ports` is `composition.host_migration_evidence_cli`'s;
- `patched(**attrs)` routes each patched name to the module that now holds it, as M7's one producer module held them all:
  `cli_ports` and `HostReader` to `composition.host_migration_evidence_cli` (where `observe_command` and `cli_ports` read
  them), `bounded_run` to the delivery evidence adapter (where `HostReader` defaults its runner from it);
- `LaneSnapshotStore` is `observation.adapters.collectors`'; `forbid_writer_store` and `patch_connect` act on the target
  `PostgresStore` constructor and on `psycopg.connect`, which `LaneSnapshotStore` reads at connect time;
- `conninfo_to_dict` and `OperationalError` are psycopg's.

The clock seam is the evidence driver's `fake_utcnow`."""

import contextlib
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from unittest import mock  # noqa: E402

import psycopg  # noqa: E402
import s7_migration_evidence_cli  # noqa: E402
from codex_harness.composition import host_migration_evidence_cli as composition  # noqa: E402
from codex_harness.delivery.adapters import host_migration_evidence as adapter  # noqa: E402
from codex_harness.entry.processes import host_migration as entry  # noqa: E402
from codex_harness.observation.adapters.collectors import LaneSnapshotStore  # noqa: E402
from codex_harness.storage.adapters import postgres_store  # noqa: E402
from psycopg import OperationalError  # noqa: E402
from psycopg.conninfo import conninfo_to_dict  # noqa: E402

_path = Path(__file__).resolve().with_name("s7_migration_evidence.py")
_spec = importlib.util.spec_from_file_location("target_s7_migration_evidence", _path)
evidence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evidence)

_HOMES = {"cli_ports": composition, "HostReader": composition, "bounded_run": adapter}


@contextlib.contextmanager
def patched(**attributes):
    with contextlib.ExitStack() as stack:
        for name, value in attributes.items():
            stack.enter_context(mock.patch.object(_HOMES[name], name, value))
        yield


def patch_connect(function):
    return mock.patch.object(psycopg, "connect", function)


def forbid_writer_store(record):
    def refuse(*args, **kwargs):
        record.append(1)
        raise AssertionError("writer store constructed")

    return mock.patch.object(postgres_store.PostgresStore, "__init__", refuse)


API = evidence.SimpleNamespace(**{
    **vars(evidence.API), "main": entry.main, "parser": entry.parser, "cli_ports": composition.cli_ports,
    "LaneSnapshotStore": LaneSnapshotStore, "patched": patched, "patch_connect": patch_connect,
    "forbid_writer_store": forbid_writer_store, "conninfo_to_dict": conninfo_to_dict,
    "OperationalError": OperationalError})

if __name__ == "__main__":
    with evidence.fake_utcnow():
        result = s7_migration_evidence_cli.run(API)
    driver.finish("target", "delivery.migration_evidence_cli", result)
