"""Reference driver: `containers.profiles` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S3, R-C first).

M7 `adapters.isolated_worker` (isolation configuration, `container_args`, `OwnedContainer`, run
records, preflight, `IsolatedClaudeRuntime`) and `adapters.role_containers` (profiles, the Codex
broker, `IsolatedCodexRuntime`). The one docker-call function `isolated_worker._docker` is replaced by
the scenario's scripted client, so no daemon is contacted and no docker process is spawned (the R-P
guard would refuse one); `uuid4` and the host uid/gid are made deterministic. Nothing is modified on
disk outside the scenario's own temporary directory.
"""

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s3_containers  # noqa: E402

from codex_harness.adapters import isolated_worker as iw  # noqa: E402
from codex_harness.adapters import role_containers as rc  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402


def install_docker(fake):
    def scripted(docker, args, *, timeout, env=None):
        code, stdout = fake(list(args), env)
        return subprocess.CompletedProcess([docker, *args], code, stdout, "")

    iw._docker = scripted


def set_ids(uid, gid):
    os.getuid, os.getgid = (lambda: uid), (lambda: gid)


def set_uuid(prefix):
    counter = iter(range(1_000_000))

    def fixed():
        return uuid.UUID(bytes=hashlib.sha256(f"{prefix}:{next(counter)}".encode()).digest()[:16])

    iw.uuid4 = rc.uuid4 = fixed


API = SimpleNamespace(
    load_isolation=iw.load_isolation, container_args=iw.container_args, forbidden_controls=iw.forbidden_controls,
    worker_environment=iw.worker_environment, codex_environment=rc.codex_environment,
    read_only_mounts=iw.read_only_mounts, PROFILES=rc.PROFILES, LIMITS=iw.LIMITS, INSPECT_FORMAT=iw.INSPECT_FORMAT,
    FORBIDDEN_SOURCES=iw.FORBIDDEN_SOURCES, CODEX_CONFIG=rc.CODEX_CONFIG, CODEX_CONFIG_SHA256=rc.CODEX_CONFIG_SHA256,
    CODEX_CLI_VERSION=rc.CODEX_CLI_VERSION, TOKEN_NAME=iw.TOKEN_NAME,
    DOCKER_CLIENT_ENVIRONMENT=iw.DOCKER_CLIENT_ENVIRONMENT,
    claude_runtime=lambda config, root, profile, environment: iw.IsolatedClaudeRuntime(
        config, root, model="claude-fixture-1", profile=profile, environment=environment),
    codex_runtime=lambda config, root, profile, store, environment: rc.IsolatedCodexRuntime(
        config, root, profile=profile, broker=rc.CodexCredentialBroker(store), environment=environment,
        lock_wait_seconds=0.0),
    preflight=lambda config, environment, token: iw.preflight(config, "docker", environment, token=token),
    install_docker=install_docker, set_ids=set_ids, set_uuid=set_uuid,
    IsolationError=iw.IsolationError, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("reference", "containers.profiles", s3_containers.run(API))
