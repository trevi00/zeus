"""Target driver: `containers.profiles` on the target tree (execution container spec, owned container,
cleanup ledger, launcher; credentials broker and scrubber).

Composition's wiring is done here: the one docker-call function (`owned_container.docker_call`) is
replaced by the scenario's scripted client, exactly as the reference driver replaces M7 `_docker`, so
no daemon is contacted, git runs through the host_os chokepoint (`ChokepointProcesses`), the
attached client is the host_os `ProcessTree` (a real `docker start` is refused by the R-P guard, as on
the reference), the credential boundary is the credentials adapters'. `uuid4` of the launcher and the
host uid/gid are made deterministic exactly as the reference driver does.
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

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import s3_containers  # noqa: E402
from codex_harness.credentials.adapters.codex_custody import CodexCredentialBroker  # noqa: E402
from codex_harness.credentials.adapters.scrubber import (  # noqa: E402
    CredentialScrubber,
    OutputUnsanitizable,
)
from codex_harness.credentials.domain import codex_credential as cc  # noqa: E402
from codex_harness.execution.adapters.containers import launcher  # noqa: E402
from codex_harness.execution.adapters.containers import owned_container as oc  # noqa: E402
from codex_harness.execution.domain import container_spec as spec  # noqa: E402
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402


def runner(argv, cwd=None, timeout=120, input_text=None, env=None):
    raise AssertionError("no docker call may bypass the scripted docker_call")


def install_docker(fake):
    """Replace the one docker-call function of this side, as the reference driver replaces M7 `_docker`."""
    def scripted(runner_, docker, args, *, timeout, env=None):
        code, stdout = fake(list(args), env)
        return subprocess.CompletedProcess([docker, *args], code, stdout, "")

    oc.docker_call = scripted


def set_ids(uid, gid):
    os.getuid, os.getgid = (lambda: uid), (lambda: gid)


def set_uuid(prefix):
    counter = iter(range(1_000_000))

    def fixed():
        return uuid.UUID(bytes=hashlib.sha256(f"{prefix}:{next(counter)}".encode()).digest()[:16])

    launcher.uuid4 = fixed


HOST = launcher.ContainerHost(runner=runner, processes=ChokepointProcesses(), trees=ProcessTree)
CREDENTIALS = launcher.CredentialBoundary(scrubber=CredentialScrubber, OutputUnsanitizable=OutputUnsanitizable)

API = SimpleNamespace(
    load_isolation=oc.load_host_isolation,
    container_args=lambda config, **fields: spec.container_args(config, user=oc.host_user(), **fields),
    forbidden_controls=lambda observed: spec.forbidden_controls(observed, home=oc.operator_home()),
    worker_environment=spec.worker_environment, codex_environment=spec.codex_environment,
    read_only_mounts=spec.read_only_mounts, PROFILES=spec.PROFILES, LIMITS=spec.LIMITS,
    INSPECT_FORMAT=spec.INSPECT_FORMAT, FORBIDDEN_SOURCES=spec.FORBIDDEN_SOURCES, CODEX_CONFIG=cc.CODEX_CONFIG,
    CODEX_CONFIG_SHA256=cc.CODEX_CONFIG_SHA256, CODEX_CLI_VERSION=cc.CODEX_CLI_VERSION, TOKEN_NAME=spec.TOKEN_NAME,
    DOCKER_CLIENT_ENVIRONMENT=spec.DOCKER_CLIENT_ENVIRONMENT,
    claude_runtime=lambda config, root, profile, environment: launcher.IsolatedClaudeRuntime(
        config, root, model="claude-fixture-1", profile=profile, environment=environment, host=HOST),
    codex_runtime=lambda config, root, profile, store, environment: launcher.IsolatedCodexRuntime(
        config, root, profile=profile, broker=CodexCredentialBroker(store), environment=environment,
        lock_wait_seconds=0.0, host=HOST, credentials=CREDENTIALS),
    preflight=lambda config, environment, token: oc.preflight(config, "docker", environment, token=token,
                                                              runner=runner),
    install_docker=install_docker, set_ids=set_ids, set_uuid=set_uuid,
    IsolationError=IsolationError, ContractError=ContractError)

if __name__ == "__main__":
    driver.finish("target", "containers.profiles", s3_containers.run(API))
