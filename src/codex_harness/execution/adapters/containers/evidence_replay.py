"""The container run of one evidence replay (S8 V26 option C): a fresh candidate copy, a fresh network-none credential-free container, held and retired.

Layer: adapters
Context: execution
Owns: ContainerEvidenceReplay (`replay`: the unresolved-run refusal, the cleanup-ledger record, the fresh snapshot copy, create, verify controls, `hold`/start/capture, stop, `retire` and the snapshot removal of ONE already authorized argv; `summary`: the isolation's projection that enters the evidence identity)
Does not own: authorization, claim parsing, budgets, classification, archival and the bounded attached capture (evidence.adapters.evidence_inspection: the capture arrives as the `capture` argument), the evidence port it satisfies (evidence.ports.ContainerReplay), the container commands and the control rule (execution.adapters.containers.owned_container, execution.domain.container_spec), the durable run record (execution.adapters.containers.cleanup_ledger), process creation (the injected `runner`)
Entry points: ContainerEvidenceReplay
Contracts: INV-ISOLATED-WORKER-001, INV-ROLE-CONTAINER-001

Moved from M7 `adapters/isolated_evidence.py` `DockerEvidenceInspector._replay` (SOURCE e38aa722) through named rules (DESIGN-s8 §27.1 V26 rule E-1, S8 batch B5b, A/evidence/rebuild/s8/batch-b5b-move/transcribe.py): the body is M7's, except E-1a (the method is `replay` and takes the keyword-only `capture`), E-1c (`OwnedContainer(..., runner=self.runner)`, the S3 runner), E-1d (`_capture(` is the `capture(` argument) and E-1b (`container_args(...)` gains `user=host_user()`, as `launcher.py` does since S3 RESEARCH F-R6: M7 computed the same value inside `container_args`, so the argv is unchanged). Composition (S10) builds it with the S3 runner. The first paragraph of the method docstring is M7's.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from codex_harness.execution.adapters.containers.cleanup_ledger import (
    advance,
    hold,
    new_record,
    retire,
    unresolved_runs,
)
from codex_harness.execution.adapters.containers.owned_container import (
    OwnedContainer,
    docker_environment,
    host_user,
)
from codex_harness.execution.adapters.containers.staging import scan_tree
from codex_harness.execution.domain.container_spec import WORKSPACE, container_args, summary
from codex_harness.kernel.errors import IsolationError
from codex_harness.kernel.ids import digest


class ContainerEvidenceReplay:
    """The evidence side's `ContainerReplay` port over the execution containers."""

    def __init__(self, isolation: dict, root, docker: str = "docker", *, runner):
        self.isolation, self.root, self.docker, self.runner = isolation, Path(root), docker, runner

    def summary(self) -> dict:
        return summary(self.isolation)

    def replay(self, argv, cwd, timeout, max_bytes, env, *, capture, progress=None, workdir=WORKSPACE):
        """One authorized argv in one fresh container over one fresh candidate copy.

        The caller's per-call `progress` check reaches the attached capture exactly as it does on
        the host (research-dispatch-001). Its refusal is an interruption of that capture, so `hold`
        stops and confirms this container by its exact id before the refusal propagates; preparation
        and the lifecycle record are unchanged.

        `workdir` is the container directory the check runs in: the mounted root by default, and a
        host-declared project context (INV-PROJECT-EVIDENCE-001 version 2) under it. The copy, the
        mount, the image and every control are identical either way."""
        run_id = uuid4().hex
        directory = self.root / run_id
        snapshot = directory / "workspace"
        workspace = str(Path(cwd).resolve())
        container = OwnedContainer(self.isolation, self.docker, run_id, "verifier", runner=self.runner)
        context = {"container": {"name": container.name, "image": self.isolation["image"], "network": "none",
                                 "credentials": "none", "run_id": run_id}}
        record = None
        try:
            pending = unresolved_runs(self.root, workspace)
            if pending:
                # Visible and refused, like the worker: a retained replay container is never doubled.
                context["container"]["unresolved"] = pending
                raise IsolationError("isolation_unresolved_run")
            snapshot.mkdir(parents=True)
            record = new_record(directory, role="verifier", workspace=workspace, config=self.isolation,
                                container=container, argv=list(argv), snapshot=str(snapshot))
            files = scan_tree(Path(cwd))
            for name in files:
                target = snapshot.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(cwd).joinpath(*name.split("/")), target)
            context["container"]["snapshot_sha256"] = digest(files)
            advance(record, "prepared", snapshot_sha256=context["container"]["snapshot_sha256"])
            args = container_args(self.isolation, name=container.name, run_id=run_id, role="verifier", network="none",
                                  mounts=[(str(snapshot.resolve()), WORKSPACE)], environment=dict(env), pass_names=(),
                                  entry=list(argv), workdir=workdir, user=host_user())
            container.create(args, docker_environment())
            context["container"]["id"] = record["container"] = container.id
            advance(record, "created", container=container.id)
            context["container"]["controls"] = container.verify({WORKSPACE}, "none")
        except (IsolationError, OSError) as exc:
            code = exc.reason_code if isinstance(exc, IsolationError) else type(exc).__name__
            if container.id is not None:
                context["container"]["cleanup"] = container.remove()  # never started: exact id, not forced
            if record is not None and (container.id is None or context["container"]["cleanup"]["removed"]):
                try:
                    advance(record, "refused", reason=code)
                    shutil.rmtree(snapshot, ignore_errors=True)
                except IsolationError:
                    pass  # the record stays where it was last written: unresolved and visible
            return {"failure": "isolated_replay_unavailable: " + code, "returncode": None, "duration_seconds": 0.0,
                    **context}
        context["container"]["record"] = record["record"]
        # The inherited bounded capture owns the deadline, output cap and client tree; `hold` owns the
        # container: durable before start, stopped and confirmed by exact id however capture exits.
        # The capture's own `cleanup` record is its positive proof; returned without one is unknown.
        try:
            run, stopped = hold(container, record, lambda: capture(
                [self.docker, "start", "--attach", container.id], None, timeout, max_bytes, docker_environment(),
                progress=progress), proof=lambda value: value["cleanup"])
        except IsolationError as exc:  # a lifecycle step could not be written: nothing is removed on a guess
            return {"failure": "isolated_replay_unrecorded: " + exc.reason_code + "; recovery record " + record["record"]
                    + " container " + container.id, "returncode": None, "duration_seconds": 0.0, **context}
        context["container"]["stop"] = stopped
        if not stopped["confirmed"]:
            # Unknown container OR unknown/missing capture proof: retained and unresolved, never retired.
            reason = "capture_cleanup_unconfirmed" if stopped["container_confirmed"] else "container_stop_unconfirmed"
            return {**run, **context, "failure": reason + "; recovery record " + record["record"]
                    + " container " + container.id}
        if not run.get("failure") and not run.get("terminated"):
            run["returncode"] = stopped.get("exit_code")  # the container's own exit, not the client's
        cleanup = retire(container, record, {**run, **context}, run.get("failure") or "replayed")
        context["container"]["cleanup"] = cleanup
        if not cleanup["evidence_written"]:
            return {**run, **context, "failure": "replay_evidence_unwritten; container retained; recovery record "
                    + record["record"] + " container " + container.id}
        if cleanup["removed"]:
            shutil.rmtree(snapshot, ignore_errors=True)  # exactly this replay's own snapshot; the record stays
        return {**run, **context}
