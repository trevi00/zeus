"""Target driver: `evidence.isolated_inspector` on the target tree (S8 batch B5b: `evidence.adapters.isolated_evidence` with its container replay in
`execution.adapters.containers.evidence_replay`).

The API mirrors the reference driver's names over the target homes. Composition's wiring is done here: the inspectors get a `ContainerEvidenceReplay`
as `containers` (its S3 runner refuses every call: no docker call may bypass the scripted `docker_call`) and a process-tree port that is the REAL host_os
`ProcessTree`, reached through a switch so that `spawning(spawn)` replaces `spawn` for a step the way the reference driver patches `ProcessTree.spawn`.
The one docker-call function (`owned_container.docker_call`) is replaced by the scenario's scripted client, exactly as `s3_containers.py` does;
`evidence_replay.uuid4` and the host uid/gid are made deterministic. An injected capture replaces the inspector's `_capture_fn`."""

import contextlib
import functools
import hashlib
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

import s8_isolated_inspector  # noqa: E402
from codex_harness.evidence.adapters import container_contract as cc  # noqa: E402
from codex_harness.evidence.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.evidence.adapters import isolated_evidence as ie  # noqa: E402
from codex_harness.evidence.application.evidence_inspection import EvidenceInspections  # noqa: E402
from codex_harness.evidence.domain.project_evidence import (  # noqa: E402
    SCHEMA,
    SCHEMA_V2,
    parse_profile,
)
from codex_harness.execution.adapters.containers import cleanup_ledger as cl  # noqa: E402
from codex_harness.execution.adapters.containers import evidence_replay as er  # noqa: E402
from codex_harness.execution.adapters.containers import owned_container as oc  # noqa: E402
from codex_harness.execution.domain import container_spec as spec  # noqa: E402
from codex_harness.host_os.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402
from codex_harness.kernel.ids import digest  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402

REAL_SPAWN = ProcessTree.spawn
CURRENT = [REAL_SPAWN]


def runner(argv, cwd=None, timeout=120, input_text=None, env=None):
    raise AssertionError("no docker call may bypass the scripted docker_call")


class SwitchPort:
    """The process-tree port: the real class's `spawn`, unless a step replaced it."""

    @staticmethod
    def spawn(*args, **kwargs):
        return CURRENT[0](*args, **kwargs)


def install_docker(fake):
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

    er.uuid4 = fixed


class RootFollows:
    """`root` lives on the container replay in the target; a scenario that moves the inspector's root moves it there too."""

    @property
    def root(self):
        return self._root

    @root.setter
    def root(self, value):
        self._root = Path(value)
        containers = getattr(self, "containers", None)
        if containers is not None:
            containers.root = Path(value)


class DockerInspector(RootFollows, ie.DockerEvidenceInspector):
    pass


class ProjectInspector(RootFollows, ie.IsolatedProjectEvidenceInspector):
    pass


def make_docker(artifacts, isolation, root):
    return DockerInspector(artifacts, isolation, root, containers=er.ContainerEvidenceReplay(isolation, root, runner=runner),
                           process_tree=SwitchPort)


def make_project(artifacts, profile, isolation, root):
    return ProjectInspector(artifacts, profile, isolation, root, containers=er.ContainerEvidenceReplay(isolation, root, runner=runner),
                            process_tree=SwitchPort)


@contextlib.contextmanager
def spawning(spawn):
    old = CURRENT[0]
    CURRENT[0] = spawn
    try:
        yield
    finally:
        CURRENT[0] = old


@contextlib.contextmanager
def injected_capture(insp, capture):
    """The attached capture the replay uses: the inspector's `_capture_fn` (None keeps the real one)."""
    if capture is None:
        yield
        return
    old = insp._capture_fn
    insp._capture_fn = capture
    try:
        yield
    finally:
        insp._capture_fn = old


@contextlib.contextmanager
def patched(name, value):
    old = getattr(ei, name)
    setattr(ei, name, value)
    try:
        yield
    finally:
        setattr(ei, name, old)


API = SimpleNamespace(
    make_docker=make_docker, make_project=make_project, install_docker=install_docker, set_ids=set_ids, set_uuid=set_uuid, spawning=spawning,
    injected_capture=injected_capture, patched=patched, real_spawn=lambda: REAL_SPAWN,
    real_capture=lambda insp: functools.partial(ei._capture, process_tree=SwitchPort),
    ledger_get=lambda name: getattr(cl, name), ledger_set=lambda name, value: setattr(cl, name, value),
    OwnedContainer=oc.OwnedContainer,
    new_container=lambda isolation, run_id: oc.OwnedContainer(isolation, "docker", run_id, "verifier", runner=runner),
    run_records=cl.run_records, unresolved_runs=cl.unresolved_runs, reconcile=lambda directory: cl.reconcile(directory, "docker", runner=runner),
    retire=cl.retire, load_isolation=oc.load_host_isolation, digest=digest, LABEL=spec.LABEL, INSPECT_FORMAT=spec.INSPECT_FORMAT,
    TOKEN_NAME=spec.TOKEN_NAME, TRUSTED_PYTHON=cc.TRUSTED_PYTHON, CONTAINER_ENVIRONMENT=ie.CONTAINER_ENVIRONMENT,
    container_environment=ie.container_environment, DockerEvidenceInspector=ie.DockerEvidenceInspector, FileArtifacts=FileArtifacts,
    MemoryStore=MemoryStore, EvidenceInspections=EvidenceInspections, packaged_policy=ei.packaged_policy, parse_profile=parse_profile,
    SCHEMA=SCHEMA, SCHEMA_V2=SCHEMA_V2, ContractError=ContractError, IsolationError=IsolationError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-isolated-") as raw:
        result = s8_isolated_inspector.run(API, Path(raw))
    driver.finish("target", "evidence.isolated_inspector", result)
