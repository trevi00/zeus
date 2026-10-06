"""INV-ISOLATED-WORKER-001: deterministic evidence replay in fresh, credential-free containers.

Authorization, claim parsing, budgets, classification, binding and archival are the inherited
`EvidenceInspector`'s; this backend only changes WHERE an already authorized argv runs: a fresh
copy of the candidate, the same immutable image, network none, no token and no service
credential, the same filesystem and resource controls as the worker. No candidate command runs
on the host, and an unavailable container is a named failure, never a host replay.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.evidence_inspection import EvidenceInspector, _capture
from codex_harness.adapters.isolated_worker import (
    TRUSTED_PYTHON,
    WORKSPACE,
    IsolationError,
    OwnedContainer,
    advance,
    container_args,
    docker_environment,
    hold,
    new_record,
    retire,
    scan_tree,
    summary,
    unresolved_runs,
)
from codex_harness.adapters.project_evidence import (
    ProjectEvidenceInspector,
    container_binding,
    resolve_container_profile,
)
from codex_harness.domain.model import digest, require

CONTAINER_ENVIRONMENT = {"HOME": "/tmp", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                         "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": WORKSPACE}


def container_environment(cwd=None) -> dict:
    env = dict(CONTAINER_ENVIRONMENT)
    if cwd is not None and (Path(cwd) / "src").is_dir():
        env["PYTHONPATH"] = WORKSPACE + "/src"  # the candidate's src, as the host replay binds it
    return env


class DockerEvidenceInspector(EvidenceInspector):
    def __init__(self, artifacts, isolation: dict, root, docker: str = "docker", policy=None):
        super().__init__(artifacts, policy, interpreter=TRUSTED_PYTHON)
        self.isolation, self.root, self.docker = isolation, Path(root), docker

    def _trusted(self, candidate):
        # The image's interpreter: a container path, so there is no host file to verify and none is run.
        return TRUSTED_PYTHON

    def _python(self):
        return "container:" + self.isolation["image"]

    def snapshot(self, cwd=None):
        """The identity describes the container context: image, limits, network and driver are in the
        cache key, so a changed image or configuration never reads back an older inspection."""
        environment = container_environment(cwd)
        identity = {"policy_hash": self.policy["policy_hash"], "environment_names": sorted(environment),
                    "environment_digest": digest(sorted(environment.items())), "interpreter": TRUSTED_PYTHON,
                    "cwd": str(Path(cwd).resolve()) if cwd is not None else None,
                    "container": {**summary(self.isolation), "network": "none", "credentials": "none",
                                  "workspace": WORKSPACE, "snapshot": "fresh copy per replay"},
                    "platform": "linux-container"}
        return {"identity": identity, "environment": environment, "interpreter": TRUSTED_PYTHON}

    def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None, workdir=WORKSPACE):
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
        container = OwnedContainer(self.isolation, self.docker, run_id, "verifier")
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
                                  entry=list(argv), workdir=workdir)
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
            run, stopped = hold(container, record, lambda: _capture(
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


class IsolatedProjectEvidenceInspector(ProjectEvidenceInspector):
    """INV-PROJECT-EVIDENCE-001 version 2: the host's declared checks, replayed in the pinned image.

    Exactly one thing differs from the host profile inspector: WHERE an already authorized,
    interpreter-bound check runs. The profile, the required denominator, the claim parsing, the
    classification, the aggregate deadline, the archive and the cancellation/cleanup ownership stay
    inherited; the execution is the verifier container above - one fresh, network-none,
    credential-free container of the same image over a fresh candidate copy, entered in the check's
    own container context directory. No candidate command runs on the host, and an unavailable
    container is a named replay failure, never a host replay.
    """

    # The verifier replay is not reimplemented here: this is the same function object, so the
    # container ownership, records, cleanup debt and refusals cannot drift between the two routes.
    _replay = DockerEvidenceInspector._replay

    def __init__(self, artifacts, profile, isolation: dict, root, docker: str = "docker", policy=None):
        super().__init__(artifacts, profile, policy, interpreter=TRUSTED_PYTHON)
        # Refused here, before any snapshot or container: version, image and interpreter must agree.
        self.execution = container_binding(profile, isolation)
        self.isolation, self.root, self.docker = isolation, Path(root), docker

    def _trusted(self, candidate):
        # A container path: there is no host file to verify and none is run. Nothing else is accepted.
        require(candidate in (None, TRUSTED_PYTHON), "The isolated project inspector runs the image interpreter only")
        return TRUSTED_PYTHON

    def _python(self):
        return "container:" + self.isolation["image"]

    def snapshot(self, cwd=None):
        """The container identity (image, limits, network, driver) AND the container-resolved project
        contexts, both in the cache key: a changed image, profile, context or dependency digest can
        never read back an older inspection."""
        require(cwd is not None, "Project evidence snapshot requires the candidate workspace")
        project = resolve_container_profile(self.profile, cwd, self.isolation)
        # The identity environment is the one every context shares; per-context PYTHONPATH values are
        # bound by the project digest below, and each replay runs under its own context environment.
        environment = {k: v for k, v in CONTAINER_ENVIRONMENT.items()}
        identity = {"policy_hash": self.policy["policy_hash"], "environment_names": sorted(environment),
                    "environment_digest": digest(sorted(environment.items())), "interpreter": TRUSTED_PYTHON,
                    "cwd": str(Path(cwd).resolve()),
                    "container": {**summary(self.isolation), "network": "none", "credentials": "none",
                                  "workspace": WORKSPACE, "snapshot": "fresh copy per replay"},
                    "platform": "linux-container",
                    "project": {"digest": project["digest"], "profile_digest": project["profile_digest"],
                                "execution": project["execution"], "workspace": project["workspace"],
                                "contexts": {name: {k: v for k, v in context.items()
                                                    if k not in ("environment", "workspace")}
                                             for name, context in project["contexts"].items()}}}
        return {"identity": identity, "environment": environment, "interpreter": TRUSTED_PYTHON, "project": project}

    def _execute_check(self, argv, context, timeout, max_bytes, progress=None):
        """`context['workspace']` is the HOST checkout this context was resolved against and is what
        the replay copies; every executing value (workdir, interpreter, environment) is the image's."""
        return self._replay(argv, context["workspace"], timeout, max_bytes, dict(context["environment"]),
                            progress=progress, workdir=context["cwd"])
