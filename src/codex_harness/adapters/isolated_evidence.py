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
    container_args,
    docker_environment,
    scan_tree,
    summary,
)
from codex_harness.domain.model import digest

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

    def _replay(self, argv, cwd, timeout, max_bytes, env):
        """One authorized argv in one fresh container over one fresh candidate copy."""
        run_id = uuid4().hex
        directory = self.root / run_id
        snapshot = directory / "workspace"
        container = OwnedContainer(self.isolation, self.docker, run_id, "verifier")
        context = {"container": {"name": container.name, "image": self.isolation["image"], "network": "none",
                                 "credentials": "none", "run_id": run_id}}
        try:
            files = scan_tree(Path(cwd))
            for name in files:
                target = snapshot.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(Path(cwd).joinpath(*name.split("/")), target)
            snapshot.mkdir(parents=True, exist_ok=True)
            context["container"]["snapshot_sha256"] = digest(files)
            args = container_args(self.isolation, name=container.name, run_id=run_id, role="verifier", network="none",
                                  mounts=[(str(snapshot.resolve()), WORKSPACE)], environment=dict(env), pass_names=(),
                                  entry=list(argv), workdir=WORKSPACE)
            container.create(args, docker_environment())
            context["container"]["id"] = container.id
            context["container"]["controls"] = container.verify({WORKSPACE}, "none")
        except (IsolationError, OSError) as exc:
            code = exc.reason_code if isinstance(exc, IsolationError) else type(exc).__name__
            if container.id is not None:
                context["container"]["cleanup"] = container.remove()
            return {"failure": "isolated_replay_unavailable: " + code, "returncode": None, "duration_seconds": 0.0,
                    **context}
        # The inherited bounded capture owns the deadline, output cap and client tree; the container
        # itself is then stopped and confirmed by exact id whatever the client did.
        run = _capture([self.docker, "start", "--attach", container.id], None, timeout, max_bytes, docker_environment())
        stopped = container.stop(self.isolation["limits"]["cleanup_seconds"])
        context["container"]["stop"] = stopped
        if not stopped["confirmed"]:
            return {**run, **context, "failure": "container_stop_unconfirmed; recovery container " + container.id}
        if not run.get("failure") and not run.get("terminated"):
            run["returncode"] = stopped.get("exit_code")  # the container's own exit, not the client's
        cleanup = container.remove()
        context["container"]["cleanup"] = cleanup
        if cleanup["removed"]:
            shutil.rmtree(directory, ignore_errors=True)  # exactly this replay's own snapshot
        else:
            context["container"]["recovery"] = {"container": container.id, "name": container.name, "snapshot": str(directory)}
        return {**run, **context}
