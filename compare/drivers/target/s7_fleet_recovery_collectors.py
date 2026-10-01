"""Target driver: `delivery.fleet_recovery_collectors` on the target tree (S7 pilot 48; DESIGN-s7 adapters-move §14).

The API holds the moved `coordination.adapters.fleet_recovery` names with the V6 injections closed over the wiring
`composition.fleet_recovery.collectors` supplies, so the common module runs unchanged and under the reference's names:
- `state` (`docker_state` over the composition's `_docker`), `run_records` (execution's `cleanup_ledger.run_records`) and
  `git_source` (`host_os.adapters.git_source.GitSource`) are the wired defaults; a `state=` or `source=` the case supplies
  wins, exactly as in M7. `docker_state` is the wired partial itself.
- `budget` is never defaulted: execution's CallBudget is the S10 carry, and the cases always pass their own double (probe
  002: the machine ledger is unreachable and named).
- `verify_schema`/`verify` keep M7's lazy default, which now resolves `coordination.adapters.fleet_runtime`
  (`verify_lane_schema` moved ahead; the cases pass their LABELLED verify double).
- `RESOLVED` is `execution.domain.container_spec`; `LaunchRefused`, `FleetRefused`, `normalize_path` and
  `repository_identity` are `coordination.domain.fleet`; `digest` is the kernel's.
- `patched(**attrs)` replaces attributes of the TARGET adapter module (the one patched name, `_owned_copy`, moved unchanged).

The clock: this driver installs no determinism; the collectors read `clock=`, so each collector call is given the SAME
`determinism.FakeClock` the reference installs (as an ISO UTC reader) unless the case passes its own `clock=`."""

import contextlib
import sys
from datetime import timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import s7_fleet_recovery_collectors  # noqa: E402

from codex_harness.composition import fleet_recovery as composition  # noqa: E402
from codex_harness.coordination.adapters import fleet_recovery as adapter  # noqa: E402
from codex_harness.coordination.domain import fleet_recovery as policy  # noqa: E402
from codex_harness.coordination.domain.fleet import (  # noqa: E402
    FleetRefused,
    LaunchRefused,
    normalize_path,
    repository_identity,
)
from codex_harness.execution.domain.container_spec import RESOLVED  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402

CLOCK = determinism.FakeClock()
WIRING = composition.collectors(budget=None)  # `budget` is the S10 carry: every case passes its own


def fake_utcnow():
    return CLOCK.now(timezone.utc).isoformat()


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


def collect_recovery_proof(evidence, lane, **kwargs):
    kwargs.setdefault("state", WIRING.state)
    kwargs.setdefault("run_records", WIRING.run_records)
    kwargs.setdefault("clock", fake_utcnow)
    return adapter.collect_recovery_proof(evidence, lane, **kwargs)


def collect_relocation_proof(request, config, jobs, **kwargs):
    kwargs.setdefault("state", WIRING.state)
    kwargs.setdefault("run_records", WIRING.run_records)
    kwargs.setdefault("git_source", WIRING.git_source)
    kwargs.setdefault("clock", fake_utcnow)
    return adapter.collect_relocation_proof(request, config, jobs, **kwargs)


def collect_host_migration_proof(request, jobs, **kwargs):
    kwargs.setdefault("state", WIRING.state)
    kwargs.setdefault("run_records", WIRING.run_records)
    kwargs.setdefault("git_source", WIRING.git_source)
    kwargs.setdefault("clock", fake_utcnow)
    return adapter.collect_host_migration_proof(request, jobs, **kwargs)


def listed_runs(runtime, field):
    return adapter.listed_runs(runtime, field, run_records=WIRING.run_records)


def checkout_identity(path, source=None):
    return adapter.checkout_identity(path, source, git_source=WIRING.git_source)


def run_record(runtime, worktree, evidence):
    return adapter._run_record(runtime, worktree, evidence, run_records=WIRING.run_records)


def active_runs(runtime, lane_id, state):
    return adapter._active_runs(runtime, lane_id, state, run_records=WIRING.run_records)


def independent(path):
    return adapter._independent(path, git_source=WIRING.git_source)


def queued_bindings(target, jobs):
    return adapter._queued_bindings(target, jobs, git_source=WIRING.git_source)


API = SimpleNamespace(
    collect_recovery_proof=collect_recovery_proof, collect_relocation_proof=collect_relocation_proof,
    collect_host_migration_proof=collect_host_migration_proof, verify_copy_manifest=adapter.verify_copy_manifest,
    runner_state=adapter.runner_state, listed_runs=listed_runs, checkout_identity=checkout_identity,
    docker_state=WIRING.state, run_root=adapter.run_root, LaneReader=adapter.LaneReader,
    hash_file=adapter._hash_file, hash_bounded=adapter._hash_bounded, resolved_directory=adapter._resolved_directory,
    run_record=run_record, recorded_slots=adapter._recorded_slots, machine_slot=adapter._machine_slot,
    active_runs=active_runs, independent=independent, writable=adapter._writable,
    queued_bindings=queued_bindings, relative=adapter._relative, move_roots=adapter._move_roots,
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
    driver.finish("target", "delivery.fleet_recovery_collectors", s7_fleet_recovery_collectors.run(API))
