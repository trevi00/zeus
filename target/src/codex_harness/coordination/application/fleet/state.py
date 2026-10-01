"""Fleet state shared by the four Fleet objects: bucket names, the control-row vocabulary, the owner-handoff
view and the five read helpers every unit uses inside its own transaction.

Layer: application
Context: coordination
Owns: the Fleet bucket names, read-only views over them and the P2 control-version record's one writer
Does not own: any other write (the four Fleet objects own them)
Entry points: registry, control, control_version, bump_control_version, view, hold_key, repository_aliases, owner_handoff_view
Contracts: INV-FLEET-001

Moved from M7 `application/fleet.py` (SOURCE e38aa722) by the named split (DESIGN-s5 §F); the method
bodies are M7's.
"""

from __future__ import annotations

import re

from codex_harness.coordination.domain.fleet_recovery import canonical_repositories
from codex_harness.coordination.domain.operation import HANDOFF_SCHEMA
from codex_harness.kernel.errors import require

BUCKET_REGISTRY, BUCKET_CONTROL, BUCKET_JOBS = "fleet_registry", "fleet_control", "fleet_jobs"
BUCKET_GRANTS = "fleet_budget_grants"
BUCKET_DELIVERY = "fleet_delivery"
BUCKET_RECOVERY = "fleet_recovery_receipts"
BUCKET_RELOCATION = "fleet_relocations"
BUCKET_HOST_MIGRATION = "fleet_host_migrations"
BUCKET_UNITS = "fleet_units"
# Control-row field naming the managed host activation that paused admission (`activation_gate`).
ACTIVATION_HOLD = "activation_hold"
CONTROL_KEY = "admission"
# P2 (Buzz DESIGN v3 §5, DESIGN-B §5 D-B2-1): the pause-authority version lives in its OWN record, never in the
# CONTROL_KEY row; `bump_control_version` is its only writer.
AUTHORITY_VERSION_KEY = "authority_version"
SAFE_HANDOFF_VALUE = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")


def _safe_value(value):
    """A short identifier or code, or None. Unlike `safe_code` nothing is truncated at a colon: an
    owner (`lead:improvement`) and a digest id keep their whole value or are dropped entirely."""
    return value if type(value) is str and SAFE_HANDOFF_VALUE.fullmatch(value) else None


def owner_handoff_view(record) -> dict | None:
    """The fleet-visible projection of a lane operation's owner handoff, or None.

    Identities, codes, a bound flag and counts only: no check items, causes, output or manifest
    text cross this boundary, and an unrecognized document is dropped rather than relayed. It is
    delivery VISIBILITY - the job's status, verdict and authority are untouched by it.

    Progress counts are relayed only when the record states BOTH `bound` and `known` as exactly
    true. This check is independent of the writer: a retained older handoff that carries populated
    item lists beside an unbound or unknown inspection shows null progress here, so foreign or
    unidentified evidence cannot be read as work this job completed.
    """
    if not isinstance(record, dict) or record.get("schema") != HANDOFF_SCHEMA:
        return None
    inspection = record.get("inspection") if isinstance(record.get("inspection"), dict) else {}
    credited = inspection.get("bound") is True and inspection.get("known") is True
    counted = lambda key: len(inspection[key]) if credited and isinstance(inspection.get(key), list) else None  # noqa: E731
    return {"schema": HANDOFF_SCHEMA, "id": _safe_value(record.get("id")), "status": _safe_value(record.get("status")),
            "owner": _safe_value(record.get("owner")), "next_action": _safe_value(record.get("next_action")),
            "reason_code": _safe_value(record.get("reason_code")),
            "operation_id": _safe_value(record.get("operation_id")),
            "inspection_id": _safe_value(inspection.get("id")),
            "inspection_bound": inspection.get("bound") is True,
            "inspection_known": inspection.get("known") is True,
            "inspection_reason_code": _safe_value(inspection.get("reason_code")),
            "passed": counted("passed"), "remaining": counted("remaining"),
            "authority": "owner_handoff; visibility only, never a retry, acceptance or release"}


def registry(tx) -> dict | None:
    rows = tx.scan(BUCKET_REGISTRY)
    require(len(rows) <= 1, "Fleet registry holds more than one fleet")
    return rows[0] if rows else None


def control(tx) -> dict:
    """Pause flag and effective budget; an older row without a budget keeps the registered one."""
    return tx.get(BUCKET_CONTROL, CONTROL_KEY) or {"paused": False}


def control_version(tx) -> int:
    """The P2 pause-authority version; an absent record reads 0."""
    record = tx.get(BUCKET_CONTROL, AUTHORITY_VERSION_KEY)
    return record["control_version"] if record else 0


def bump_control_version(tx) -> int:
    """P2: +1 for one committed pause-authority change, in the caller's transaction. Called only by the three owner
    paths (`FleetPause.set_paused_in`, the `activation_gate` hold write, `release_activation_hold`)."""
    version = control_version(tx) + 1
    tx.put(BUCKET_CONTROL, AUTHORITY_VERSION_KEY, {"control_version": version})
    return version


def view(job: dict) -> dict:
    keys = ("id", "operation_id", "lane", "team", "status", "reason_code", "manifest_sha256", "goal",
            "dependencies", "calls", "exit_code", "error_type", "owner_handoff", "created_at", "updated_at",
            "dispatched_at", "finished_at")
    return {k: job.get(k) for k in keys}


def hold_key(control: dict):
    """The pause authority of a control row: paused, and whose activation hold (if any)."""
    hold = control.get(ACTIVATION_HOLD)
    hold = (hold.get("target_id"), hold.get("descriptor_sha256")) if isinstance(hold, dict) else None
    return control.get("paused") is True, hold


def repository_aliases(tx) -> dict:
    """Every repository identity this fleet has used -> the one canonical identity of its
    repository, folded from the immutable relocation receipts in their recorded order.

    Job rows are never rewritten, so this map is how a job frozen before a move is still
    compared against the repository it belongs to. Folding the receipts' edges into one
    equivalence class per repository (`canonical_repositories`) is what keeps that true after
    repeated moves and after a rollback: A->B->A is a cycle, and a plain chain walk over it
    would answer differently depending on which identity a job happens to carry."""
    rows = tx.scan(BUCKET_RELOCATION) + tx.scan(BUCKET_HOST_MIGRATION)
    return canonical_repositories(row.get("repository_aliases") or {}
                                  for row in sorted(rows, key=lambda r: (r["recorded_at"], r["id"])))
