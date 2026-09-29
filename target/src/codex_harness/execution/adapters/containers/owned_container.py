"""One uniquely named, labelled container owned by one run, over an injected docker runner.

Layer: adapters
Context: execution
Owns: the docker client environment allow-list (`docker_environment`), the bounded docker call
    (`docker_call`), `preflight` (daemon, immutable image, worker token), `OwnedContainer` (create,
    label recovery, inspect, verify-before-start, bounded stop, exact removal), the host-side inputs
    of the pure spec (`host_user`, `operator_home`) and the driver identity (`DRIVER_HASH`,
    `load_host_isolation`)
Does not own: the argv or the control rule (execution.domain.container_spec), the durable run record
    (execution.adapters.containers.cleanup_ledger), process creation (host_os: the `ProcessRunner`
    port is injected; nothing here creates a process)
Entry points: OwnedContainer, docker_environment, docker_call, preflight, host_user, operator_home,
    load_host_isolation, DRIVER_HASH
Contracts: INV-ROLE-CONTAINER-001

Moved from SOURCE M7 `adapters/isolated_worker` (`_docker`, `docker_environment`, `preflight`,
`OwnedContainer`), characterized first by the `containers.profiles` golden (I1 (f)2: create -> inspect ->
record -> start; a refusal after create removes the exact never-started container). RESEARCH-S3 G1/G7:
every command names the exact id; nothing filters by a common prefix; stop confirms by inspection within
the cleanup window.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from codex_harness.execution.domain import container_spec as spec
from codex_harness.kernel.errors import IsolationError

# The driver identity bound into the isolation configuration digest: this module and the spec it
# applies (M7 hashed its own `isolated_worker.py`; the moved code has a new identity by design).
DRIVER_HASH = hashlib.sha256(Path(spec.__file__).read_bytes() + Path(__file__).read_bytes()).hexdigest()


def load_host_isolation(host_settings) -> dict | None:
    return spec.load_isolation(host_settings, driver_sha256=DRIVER_HASH)


def host_user() -> str:
    """The container user for this broker process (its own non-root ids, else the fixed fallback)."""
    if not hasattr(os, "getuid"):
        return spec.container_user(None, None)
    return spec.container_user(os.getuid(), os.getgid())


def operator_home() -> str:
    return str(Path.home())


def docker_environment(base=None, *, token: bool = False) -> dict:
    """The docker client's environment: an allow-list, with the worker token only for the one
    `create` that names it. The value never appears in an argv."""
    source = os.environ if base is None else base
    env = {name: source[name] for name in spec.DOCKER_CLIENT_ENVIRONMENT if name in source}
    if token and source.get(spec.TOKEN_NAME):
        env[spec.TOKEN_NAME] = source[spec.TOKEN_NAME]
    return env


def docker_call(runner, docker, args, *, timeout, env=None):
    """One bounded docker client call through the injected runner; a spawn failure or timeout is a
    completed process with no exit code and the failure's type name, never an exception."""
    try:
        return runner([docker, *args], timeout=timeout, env=env if env is not None else docker_environment())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([docker, *args], None, "", type(exc).__name__)


def preflight(config: dict, docker: str = "docker", environment=None, *, token: bool = True, runner) -> dict:
    """Refuse before any provider entry: no daemon, no such immutable image, or no worker token."""
    seconds = config["limits"]["docker_command_seconds"]
    env = docker_environment(environment)
    daemon = docker_call(runner, docker, ["version", "--format", "{{.Server.Version}}"], timeout=seconds, env=env)
    if daemon.returncode != 0 or not daemon.stdout.strip():
        raise IsolationError("docker_unavailable")
    image = docker_call(runner, docker, ["image", "inspect", "--format", "{{.Id}}", config["image"]],
                        timeout=seconds, env=env)
    if image.returncode != 0 or image.stdout.strip() != config["image"]:
        raise IsolationError("worker_image_unavailable")
    source = os.environ if environment is None else environment
    if token and not source.get(spec.TOKEN_NAME):
        raise IsolationError("worker_token_missing", spec.TOKEN_NAME + " is not set for this process")
    return {"docker_server": daemon.stdout.strip(), "image": config["image"],
            "token": {"name": spec.TOKEN_NAME, "present": bool(source.get(spec.TOKEN_NAME))} if token else None}


class OwnedContainer:
    """One uniquely named, labelled container. Every command names the exact id; nothing here ever
    filters by a common prefix, and the environment (where the token lives) is never inspected."""

    def __init__(self, config: dict, docker: str, run_id: str, role: str, *, runner):
        self.config, self.docker, self.run_id, self.role, self.runner = config, docker, run_id, role, runner
        self.name = "zeus-" + role + "-" + run_id
        self.id = None
        self.seconds = config["limits"]["docker_command_seconds"]

    def _call(self, args, *, timeout, env=None):
        return docker_call(self.runner, self.docker, args, timeout=timeout, env=env)

    def recover_id(self) -> str | None:
        """Exact name AND label, exactly one match; anything else is not ours to touch."""
        found = self._call(["ps", "-a", "--no-trunc", "--filter", "name=^/" + self.name + "$",
                            "--filter", "label=" + spec.LABEL + "=" + self.run_id, "--format", "{{.ID}}"],
                           timeout=self.seconds)
        ids = found.stdout.split() if found.returncode == 0 else []
        return ids[0] if len(ids) == 1 and spec.CONTAINER_ID.fullmatch(ids[0]) else None

    def create(self, args: list, env: dict) -> str:
        created = self._call(args, timeout=self.seconds, env=env)
        lines = created.stdout.split()
        candidate = lines[-1] if created.returncode == 0 and lines else ""
        self.id = candidate if spec.CONTAINER_ID.fullmatch(candidate) else self.recover_id()
        if self.id is None:
            raise IsolationError("container_create_failed", "exit " + str(created.returncode))
        return self.id

    def inspect(self) -> dict | None:
        shown = self._call(["inspect", "--format", spec.INSPECT_FORMAT, self.id], timeout=self.seconds)
        try:
            body = json.loads(shown.stdout) if shown.returncode == 0 else None
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        body["mounts"] = [{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")}
                          for mount in body.get("mounts") or [] if isinstance(mount, dict)]
        return body

    def verify(self, expected_targets, network: str) -> dict:
        """Selected fields only, checked before start: the image and the mounts are what the host chose.

        `expected_targets` is a set (every bind writable: the existing worker/verifier shape) or a
        {target: writable} mapping; the observed binds must be exactly those targets in exactly those
        modes, and no forbidden socket/home/host flag may appear (INV-ROLE-CONTAINER-001)."""
        observed = self.inspect()
        expected = ({target: True for target in expected_targets} if isinstance(expected_targets, (set, frozenset))
                    else dict(expected_targets))
        if spec.controls_mismatch(observed, image=self.config["image"], run_id=self.run_id, expected=expected,
                                  network=network, home=operator_home()):
            raise IsolationError("container_controls_mismatch")
        return observed

    def state(self, timeout: float | None = None) -> dict | None:
        shown = self._call(["inspect", "--format", "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}",
                            self.id], timeout=self.seconds if timeout is None else timeout)
        parts = shown.stdout.split()
        if shown.returncode != 0 or len(parts) != 3:
            return None
        return {"status": parts[0], "exit_code": int(parts[1]) if parts[1].lstrip("-").isdigit() else None,
                "oom_killed": parts[2] == "true"}

    def stop(self, window: float) -> dict:
        """Kill (when not seen stopped) and confirm by inspection within the cleanup window. Every
        Docker call here is bounded by what remains of that window, never by the general command limit."""
        deadline, killed, last = time.monotonic() + window, False, None
        while (remaining := deadline - time.monotonic()) > 0:
            last = self.state(min(self.seconds, remaining))
            if last is not None and last["status"] in ("exited", "dead", "created"):
                return {"confirmed": True, "killed": killed, **last}
            remaining = deadline - time.monotonic()
            if not killed and remaining > 0:
                self._call(["kill", self.id], timeout=min(self.seconds, remaining))
                killed = True
                continue
            time.sleep(max(0.0, min(0.5, deadline - time.monotonic())))
        return {"confirmed": False, "killed": killed, **(last or {"status": "unknown"})}

    def remove(self) -> dict:
        """Only this exact stopped container, never forced; absence afterwards is the proof."""
        removed = self._call(["rm", self.id], timeout=self.seconds)
        gone = removed.returncode == 0 and self.recover_id() is None
        return {"removed": gone, "exit_code": removed.returncode}
