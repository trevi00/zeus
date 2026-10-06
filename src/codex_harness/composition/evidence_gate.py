"""The EvidenceGate and the evidence-inspector selection (M7 `Executor._inspect_evidence`, OWNER-DECISIONS-S10 #7).

Layer: composition
Owns: `EvidenceGate`, `evidence_inspector`
Does not own: the inspections and their ledger (`evidence.application.evidence_inspection.EvidenceInspections`), the
inspectors (`evidence.adapters`), the lease progress (`execution.application.lease_progress`), the ownership check
(`coordination.application.workflow.Workflow._owned`)
Entry points: evidence_inspector, EvidenceGate
Contracts: INV-EVIDENCE-001, INV-OBSERVATION-001, INV-ISOLATED-WORKER-001, INV-PROJECT-EVIDENCE-001

Moved from M7 `adapters/executor.py` (SOURCE e38aa722): `Executor._inspect_evidence` :1580-1625 and
`_inspection_finished` :1627-1642 (the `EvidenceGate`; its `inspect` is RunTask's `evidence_gate.inspect(task, result,
workspace, heartbeat)` port), the inspector selection of `Executor.__init__` :402-412 (`evidence_inspector`) and
`adapters/isolated_worker.py` `IsolatedWorker.inspector` :1219-1230, whose two cases are inlined over the isolation
object's `config`, `root / "replays"` and `docker` (the verifier inspectors moved to `evidence` in S8, so the
selection is composition's). The statements are M7's apart from the import homes and the S8 ports: `process_tree` on
every inspector and `containers=ContainerEvidenceReplay(...)` on the two isolated ones.
"""
from __future__ import annotations

import time

from codex_harness.evidence.adapters.evidence_inspection import EvidenceInspector
from codex_harness.evidence.adapters.isolated_evidence import (
    DockerEvidenceInspector,
    IsolatedProjectEvidenceInspector,
)
from codex_harness.evidence.adapters.project_evidence import ProjectEvidenceInspector
from codex_harness.evidence.domain.evidence import STATES
from codex_harness.evidence.domain.project_evidence import requires_container
from codex_harness.execution.adapters.containers.evidence_replay import ContainerEvidenceReplay
from codex_harness.execution.application.lease_progress import LeaseProgress
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.kernel.analysis import safe_code
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest
from codex_harness.observation.domain.observation import INSPECTION_VERDICTS, inspection_verdict


def evidence_inspector(artifacts, *, isolation=None, evidence_profile=None):
    """The verifier backend of one selection (M7 `Executor.__init__` :402-412).

    INV-ISOLATED-WORKER-001: a version-1 (HOST) project-evidence profile has no in-container mapping, so that pair is
    refused, never run on the host; a version-2 (container) profile REQUIRES the matching host isolation."""
    container_profile = requires_container(evidence_profile) if evidence_profile is not None else False
    require(isolation is None or evidence_profile is None or container_profile,
            "Isolated worker mode refuses a host project evidence profile")
    require(not container_profile or isolation is not None,
            "A container project evidence profile requires the host isolated worker")
    if isolation is None:
        return (EvidenceInspector(artifacts, process_tree=ProcessTree) if evidence_profile is None
                else ProjectEvidenceInspector(artifacts, evidence_profile, process_tree=ProcessTree))
    root = isolation.root / "replays"
    containers = ContainerEvidenceReplay(isolation.config, root, isolation.docker, runner=run_process)
    if container_profile:
        return IsolatedProjectEvidenceInspector(artifacts, evidence_profile, isolation.config, root,
                                                docker=isolation.docker, containers=containers,
                                                process_tree=ProcessTree)
    return DockerEvidenceInspector(artifacts, isolation.config, root, docker=isolation.docker,
                                   containers=containers, process_tree=ProcessTree)


class EvidenceGate:
    """RunTask's `evidence_gate` port: the executor's own inspection of a worker's claims under its lease."""

    def __init__(self, evidence, workflow, observer):
        self.evidence, self.workflow, self.observer = evidence, workflow, observer

    def inspect(self, task, result, workspace_path, heartbeat=None):
        claims = result.get("tests") if isinstance(result.get("tests"), list) else []
        # INV-OBSERVATION-001: the inspection boundary is observable from the ledger identities this
        # execution already has. The returned verdict and the review gate that reads it are unchanged.
        execution = self.observer.for_lease(task)
        correlation = self.observer.correlation(task)
        refs = [result["execution_ref"]] if type(result.get("execution_ref")) is str else []
        self.observer.emit("development.evidence_inspection_started", "started", execution=execution,
                           correlation_id=correlation, causation_id=task["id"], evidence_refs=refs,
                           attributes={"claims": len(claims)})
        started = time.monotonic()
        # The replays below are the executor's own work under the same lease the provider ran under,
        # and they are the longest part of it: the ownership check travels with them (INV-EVIDENCE-001).
        progress = LeaseProgress(self.workflow, task, heartbeat=heartbeat)
        # ...and the ledger's own transactions carry the same ownership check, so a cached row and a
        # new one are both read and written by an owner that still holds this execution. The guard
        # runs INSIDE the transaction it is given; it opens none of its own.
        ownership_refusals = []

        def guard(tx):
            try:
                return self.workflow._owned(tx, task)
            except BaseException as exc:
                ownership_refusals.append(exc)
                raise
        try:
            row = self.evidence.inspect(task, result["candidate"], claims, workspace_path, progress=progress,
                                        guard=guard)
        except Exception as exc:
            # Never a success: the inspection did not complete or was not recorded. The exception's
            # own text is not part of the identity of that fact, and a wrapped foreign message may
            # carry a secret, so the type and a digest of the message identify it instead - the same
            # wording the observation records use for foreign errors.
            error_type, message_sha256 = type(exc).__name__, digest(str(exc))[:16]
            self._inspection_finished(execution, correlation, task, "inspection_error", refs,
                                      claims=len(claims), elapsed=time.monotonic() - started,
                                      error_type=error_type, message_sha256=message_sha256)
            if progress.refusal is exc or any(exc is refusal for refusal in ownership_refusals):
                # The lease ended this, not the inspection: a stale owner publishes no verdict at all
                # and the original error keeps its type for the executor's containment path.
                raise
            return {"verdict": "inspection_error", "cause": error_type + ": message_sha256=" + message_sha256,
                    "claims": len(claims)}
        self._inspection_finished(execution, correlation, task, row["verdict"], refs, claims=len(claims),
                                  elapsed=time.monotonic() - started, inspection_id=row["id"],
                                  denominator=row["denominator"])
        return {"inspection_id": row["id"], "verdict": row["verdict"], "denominator": row["denominator"]}

    def _inspection_finished(self, execution, correlation, task, verdict, evidence_refs, *, claims,
                             elapsed, inspection_id=None, denominator=None, error_type=None,
                             message_sha256=None) -> None:
        """How the inspection ended, with its denominator; unknown and error never read as success."""
        outcome, reason_code, severity = inspection_verdict(verdict)
        counts = denominator if isinstance(denominator, dict) else {}
        self.observer.emit("development.evidence_inspection_finished", outcome, execution=execution,
                           correlation_id=correlation, causation_id=task["id"], reason_code=reason_code,
                           severity=severity, evidence_refs=evidence_refs,
                           attributes={"inspection_id": inspection_id,
                                       "verdict": safe_code(verdict, tuple(INSPECTION_VERDICTS)),
                                       "claims": claims, "findings": counts.get("claims"),
                                       "elapsed_seconds": float(elapsed),
                                       "error_type": error_type, "message_sha256": message_sha256,
                                       **{state: counts.get(state) for state in STATES}})
