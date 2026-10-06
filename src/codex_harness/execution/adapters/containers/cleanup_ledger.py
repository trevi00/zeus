"""The durable run record of every owned container (`run.json`) and the one ownership/cleanup rule.

Layer: adapters
Context: execution
Owns: the run record (`new_record`, `advance`, `run_records`, `unresolved_runs`), the cleanup-proof join
    (`join_cleanup`, `cleanup_debt`), the ownership rule of every started container (`hold`), retirement
    after durable observations (`retire`) and the operator reconcile of a retained run (`reconcile`)
Does not own: the docker calls (owned_container), the credential ledger that reads the same resolved
    states (credentials.adapters.codex_custody)
Entry points: new_record, advance, run_records, unresolved_runs, recovery_reference, join_cleanup,
    cleanup_debt, retire, hold, reconcile
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/isolated_worker` (the run-record half), characterized first by the
`containers.profiles` golden (record lifecycle states per profile and refusal). RESEARCH-S3 G7/F-R4: a
retained run whose container is not proven gone stays unresolved (it blocks a new run of the same
workspace and the next Codex credential admission); container absence alone never clears recorded
client debt.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from codex_harness.execution.adapters.containers import owned_container
from codex_harness.execution.domain import container_spec as spec
from codex_harness.kernel.errors import IsolationError


def _write_record(path: Path, record: dict) -> dict:
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return {"file": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def new_record(directory: Path, *, role: str, workspace: str, config: dict, container, **extra) -> dict:
    """The durable owner of one container, worker or verifier: exact run, name and label from the
    first write, the exact id as soon as it is known."""
    return {"run_id": container.run_id, "role": role, "workspace": workspace, "image": config["image"],
            "isolation_digest": config["digest"], "container": None, "container_name": container.name,
            "label": spec.LABEL + "=" + container.run_id, "record": str(Path(directory) / "run.json"), **extra,
            "lifecycle": [], "state": None}


def advance(record: dict, state: str, **detail) -> None:
    """One durable lifecycle step. A step that cannot be written is a named failure, never assumed."""
    previous = record["state"]
    record["lifecycle"].append({"state": state, "at": time.time(), **detail})
    record["state"] = state
    try:
        _write_record(Path(record["record"]), record)
    except OSError as exc:
        record["lifecycle"].pop()
        record["state"] = previous
        raise IsolationError("evidence_write_failed", state + " " + type(exc).__name__) from exc


def recovery_reference(container, record: dict) -> dict:
    return {"container": container.id, "name": container.name, "record": record["record"]}


def run_records(root: Path) -> list:
    records = []
    for path in sorted(Path(root).glob("*/run.json")) if Path(root).is_dir() else []:
        try:
            records.append(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            records.append({"run_id": path.parent.name, "state": "unreadable", "workspace": None,
                            "record": str(path)})
    return records


def unresolved_runs(root: Path, workspace: str | None = None) -> list:
    """Retained runs whose container is not proven gone. An unreadable record counts for every workspace."""
    return [{key: row.get(key) for key in ("run_id", "state", "container", "workspace", "record")}
            for row in run_records(root)
            if row.get("state") not in spec.RESOLVED and (workspace is None or row.get("workspace") in (workspace, None))]


def join_cleanup(stop: dict, proofs: list) -> dict:
    """The one cleanup-proof join (C and P of the lifecycle table). C is the container's own stop
    confirmation; P is EVERY supplied client/capture proof being a record whose `confirmed` is exactly
    True. No proof, a missing one (None) or a malformed one is unknown, and no supplied false/unknown
    is ever overwritten by another true. The proofs themselves stay in the durable stop."""
    container = stop.get("confirmed") is True
    client = bool(proofs) and all(isinstance(proof, dict) and proof.get("confirmed") is True for proof in proofs)
    return {**stop, "confirmed": container and client, "container_confirmed": container, "client_confirmed": client}


def cleanup_debt(record: dict) -> str | None:
    """The same join read back from the durable record: None only when the last recorded stop is a
    full positive join, otherwise the named reason retirement (and, for client debt, reconcile) refuses."""
    stops = [step["stop"] for step in record.get("lifecycle") or [] if isinstance(step.get("stop"), dict)]
    if not stops:
        return "stop_unrecorded"
    if stops[-1].get("client_confirmed") is not True:
        return "client_cleanup_unconfirmed"
    return None if stops[-1].get("confirmed") is True else "container_stop_unconfirmed"


def _emit_cleanup(observer, record: dict, outcome: str, reason: str) -> None:
    """One `operations.cleanup_recorded` at a terminal cleanup decision (DESIGN-s10 §17c, R-a54 (3)). Optional: with no
    observer nothing is emitted. Callers that pass one (S10 F2): the isolated runtimes (the executor's observer, set by
    `composition.operation.build_executor` through `IsolatedWorker.observer`) and `composition.process_entries.isolated_worker_reconcile`
    (its own `isolated-worker-runs` observer); `ContainerEvidenceReplay` (an S8 AST pin) and the fleet recovery collectors, which only read
    run records, pass none. `resource` follows the record kind: a verifier run is the verification stack, any
    other owned run a container. Closed vocabulary only; the record's paths, names and ids are never attributes."""
    if observer is None:
        return
    observer.emit("operations.cleanup_recorded", "observed", attributes={
        "resource": "verification_stack" if record.get("role") == "verifier" else "container",
        "cleanup_outcome": outcome, "cleanup_reason": reason})


def retire(container, record: dict, result: dict, outcome: str, *, files: dict | None = None,
           removed: dict | None = None, observer=None) -> dict:
    """Observations first, durably and outside the container; only then is the exact stopped container
    removed. An observation that cannot be written keeps the container and its recovery reference, and
    a record without a full positive cleanup join is never retired: nothing is written or removed."""
    reference = recovery_reference(container, record)
    debt = cleanup_debt(record)
    if debt is not None:
        return {"removed": False, "exit_code": None, "evidence_written": False, "recovery": reference, "refused": debt}
    try:
        record["retained_files"] = {name: _write_record(Path(record["record"]).with_name(name), body)
                                    for name, body in (files or {}).items()}
        record["result"] = result
        advance(record, "evidence_retained", outcome=outcome)
    except (IsolationError, OSError):
        return {"removed": False, "exit_code": None, "evidence_written": False, "recovery": reference}
    removal = container.remove()
    if removal["removed"]:
        advance(record, "removed", **(removed or {}))
        _emit_cleanup(observer, record, "removed", "completed")
    else:
        _emit_cleanup(observer, record, "failed", "removal_failed")
    return {**removal, "evidence_written": True, "recovery": None if removal["removed"] else reference}


def hold(container, record: dict, body, *, client=None, proof=None, detail=None, observer=None):
    """The one ownership rule of every started container, worker and verifier alike. The exact
    run/name/label/id is durable at `start_requested` before `body` may start anything; however `body`
    ends (return, cancel, deadline, observer failure, KeyboardInterrupt) the container gets one bounded
    stop and confirmation. Unconfirmed is recorded as `stop_unconfirmed` with its recovery reference.
    Returns (value, stop); an exception of `body` propagates after the record says what was confirmed.

    A return of `body` is not proof that its resources are gone. Positive cleanup proof comes from the
    `client` callback (the worker's own tree) and/or from `proof(value)` (the verifier capture's
    `cleanup` record), or the `capture_cleanup` of the exception that replaced the return; with `proof`
    given, an absent or malformed record is unknown. `join_cleanup` combines them with the stop."""
    try:
        advance(record, "start_requested", recovery=recovery_reference(container, record))
    except IsolationError:
        container.remove()  # never started and no durable owner: exact id, not forced
        raise
    value, interrupted, capture, supplied = None, None, None, proof is not None
    try:
        value = body()
        if proof is not None:
            try:
                capture = proof(value)
            except Exception:  # a value the proof cannot be read from is a missing proof
                capture = None
    except BaseException as exc:
        interrupted = type(exc).__name__
        # A body that reclaimed its own client tree before propagating says what it left (the shared
        # bounded capture does); unreclaimed client debt is never a confirmed stop.
        capture = getattr(exc, "capture_cleanup", None)
        supplied = supplied or capture is not None
        raise
    finally:
        stopped = container.stop(container.config["limits"]["cleanup_seconds"])
        proofs = [client()] if client is not None else []
        if supplied:
            proofs.append(capture)
            stopped = {**stopped, "capture_cleanup": capture}
        stopped = join_cleanup(stopped, proofs)
        if not stopped["confirmed"]:
            advance(record, "stop_unconfirmed", stop=stopped, interrupted=interrupted,
                    recovery=recovery_reference(container, record))
            _emit_cleanup(observer, record, "held", "still_in_use")  # not proven stopped: the run stays unresolved
        else:
            described = detail(value) if detail is not None and interrupted is None else {}
            advance(record, "stop_confirmed", stop=stopped, interrupted=interrupted, **described)
            if interrupted is not None:
                retire(container, record, {"interrupted": interrupted, "stop": stopped}, "interrupted", observer=observer)
    return value, stopped


def reconcile(run_directory, docker: str = "docker", *, runner, observer=None) -> dict:
    """Operator step for a retained run: mark it removed only when the exact named, labelled
    container is absent. It never removes a container and never touches another run. Container
    absence says nothing about the host-side client/capture: recorded unconfirmed client debt is
    refused by name and the record stays unresolved until that debt is independently resolved."""
    path = Path(run_directory) / "run.json"
    record = json.loads(path.read_text("utf-8"))
    if cleanup_debt(record) == "client_cleanup_unconfirmed":
        _emit_cleanup(observer, record, "debt_recorded", "other")  # the record keeps its unconfirmed client debt
        return {"reconciled": False, "run_id": record["run_id"], "container": record.get("container"),
                "reason": "client_cleanup_unconfirmed"}
    for dependent in record.get("dependents") or []:
        # S3b (fix F1): a parent is never resolved before its dependent (hook discovery) run proves its own
        # container and client gone; that record is reconciled first, by the same rule.
        try:
            state = json.loads(Path(dependent).read_text("utf-8")).get("state")
        except (OSError, ValueError, AttributeError):
            state = "unknown"
        if state not in spec.RESOLVED:
            _emit_cleanup(observer, record, "held", "still_in_use")
            return {"reconciled": False, "run_id": record["run_id"], "container": record.get("container"),
                    "reason": "dependent_unresolved", "dependent": {"record": str(dependent), "state": state}}
    probe = owned_container.OwnedContainer({"limits": spec.LIMITS, "image": record.get("image")}, docker, record["run_id"],
                           record["role"], runner=runner)
    listed = owned_container.docker_call(runner, docker, ["ps", "-a", "--no-trunc", "--filter", "name=^/" + probe.name + "$",
                                          "--format", "{{.ID}}"], timeout=spec.LIMITS["docker_command_seconds"])
    if listed.returncode != 0 or listed.stdout.split():
        if listed.returncode != 0:
            _emit_cleanup(observer, record, "failed", "other")
        else:
            _emit_cleanup(observer, record, "held", "still_in_use")
        return {"reconciled": False, "run_id": record["run_id"], "container": record.get("container"),
                "reason": "docker_unavailable" if listed.returncode != 0 else "container_still_present"}
    record["lifecycle"].append({"state": "removed", "at": time.time(), "by": "reconcile"})
    record["state"] = "removed"
    _write_record(path, record)
    _emit_cleanup(observer, record, "removed", "completed")
    return {"reconciled": True, "run_id": record["run_id"]}
