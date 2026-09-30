"""Reference driver: `delivery.fleet_recovery_collectors` (M7 `adapters/fleet_recovery.py`, the host-side proofs of the
two storage-recovery owner operations and of the host migration).

The API holds plain M7 objects. From `adapters.fleet_recovery`:
- the functions `collect_recovery_proof`, `collect_relocation_proof`, `collect_host_migration_proof`,
  `verify_copy_manifest`, `runner_state`, `listed_runs`, `checkout_identity`, `docker_state`, `run_root` and the class
  `LaneReader`;
- the private names `_hash_file`, `_hash_bounded`, `_resolved_directory`, `_run_record`, `_recorded_slots`,
  `_machine_slot`, `_active_runs`, `_independent`, `_writable`, `_queued_bindings`, `_relative`, `_move_roots`,
  `_bind_entry`, `_link_entry`, `_linked`, `_actual`, `_actual_root`, `_declared_parts`, `_own_chain`, `_owned_copy`
  and `_schema_provisioned` (each as the same name without the underscore);
- the constants `RUN_ROOT`, `COPY_ENTRY_FIELDS`, `READ_BYTES`, `MAX_COPY_BYTES` and `JOURNAL_LINES`.

From `domain.fleet_recovery`: `CLOSED_INVOCATIONS`, `STOPPED_STATES`, `COPY_MANIFEST_SCHEMA`, `COPY_OWNERSHIP`, `MOVABLE`,
`PROOF_SCHEMA`, `RELOCATION_PROOF_SCHEMA` and `HOST_MIGRATION_PROOF_SCHEMA`. From `domain.fleet`: `FleetRefused`,
`repository_identity` and `normalize_path`; `LaunchRefused` (`application.fleet`); `RESOLVED` (`adapters.isolated_worker`);
`digest` (`domain.model`).

One hook, a context manager that restores what it changed: `patched(**attrs)` replaces attributes of the adapter module
(the tests' `monkeypatch.setattr(fleet_recovery, "_owned_copy", ...)` pre-fix controls).

The module reads its clock through `determinism.install` (the default `clock=utcnow` of the collectors); it reads no id
source."""

import contextlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_fleet_recovery_collectors  # noqa: E402

from codex_harness.adapters import fleet_recovery as adapter  # noqa: E402
from codex_harness.adapters.isolated_worker import RESOLVED  # noqa: E402
from codex_harness.application.fleet import LaunchRefused  # noqa: E402
from codex_harness.domain import fleet_recovery as policy  # noqa: E402
from codex_harness.domain.fleet import (  # noqa: E402
    FleetRefused,
    normalize_path,
    repository_identity,
)
from codex_harness.domain.model import digest  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)


@contextlib.contextmanager
def patched(**attributes):
    saved = {name: getattr(adapter, name) for name in attributes}
    for name, value in attributes.items():
        setattr(adapter, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(adapter, name, value)


API = SimpleNamespace(
    collect_recovery_proof=adapter.collect_recovery_proof, collect_relocation_proof=adapter.collect_relocation_proof,
    collect_host_migration_proof=adapter.collect_host_migration_proof, verify_copy_manifest=adapter.verify_copy_manifest,
    runner_state=adapter.runner_state, listed_runs=adapter.listed_runs, checkout_identity=adapter.checkout_identity,
    docker_state=adapter.docker_state, run_root=adapter.run_root, LaneReader=adapter.LaneReader,
    hash_file=adapter._hash_file, hash_bounded=adapter._hash_bounded, resolved_directory=adapter._resolved_directory,
    run_record=adapter._run_record, recorded_slots=adapter._recorded_slots, machine_slot=adapter._machine_slot,
    active_runs=adapter._active_runs, independent=adapter._independent, writable=adapter._writable,
    queued_bindings=adapter._queued_bindings, relative=adapter._relative, move_roots=adapter._move_roots,
    bind_entry=adapter._bind_entry, link_entry=adapter._link_entry, linked=adapter._linked, actual=adapter._actual,
    actual_root=adapter._actual_root, declared_parts=adapter._declared_parts, own_chain=adapter._own_chain,
    owned_copy=adapter._owned_copy, schema_provisioned=adapter._schema_provisioned, RUN_ROOT=adapter.RUN_ROOT,
    COPY_ENTRY_FIELDS=adapter.COPY_ENTRY_FIELDS, READ_BYTES=adapter.READ_BYTES, MAX_COPY_BYTES=adapter.MAX_COPY_BYTES,
    JOURNAL_LINES=adapter.JOURNAL_LINES, CLOSED_INVOCATIONS=policy.CLOSED_INVOCATIONS,
    STOPPED_STATES=policy.STOPPED_STATES, COPY_MANIFEST_SCHEMA=policy.COPY_MANIFEST_SCHEMA,
    COPY_OWNERSHIP=policy.COPY_OWNERSHIP, MOVABLE=policy.MOVABLE, PROOF_SCHEMA=policy.PROOF_SCHEMA,
    RELOCATION_PROOF_SCHEMA=policy.RELOCATION_PROOF_SCHEMA, HOST_MIGRATION_PROOF_SCHEMA=policy.HOST_MIGRATION_PROOF_SCHEMA,
    FleetRefused=FleetRefused, LaunchRefused=LaunchRefused, repository_identity=repository_identity,
    normalize_path=normalize_path, RESOLVED=RESOLVED, digest=digest, patched=patched)

if __name__ == "__main__":
    driver.finish("reference", "delivery.fleet_recovery_collectors", s7_fleet_recovery_collectors.run(API))
