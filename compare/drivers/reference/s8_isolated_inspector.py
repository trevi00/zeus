"""Reference driver: `evidence.isolated_inspector` (M7 `adapters/isolated_evidence.py`: `DockerEvidenceInspector`,
`IsolatedProjectEvidenceInspector`, `CONTAINER_ENVIRONMENT`, `container_environment`).

The API holds plain M7 objects. The one docker-call function `isolated_worker._docker` is replaced by the scenario's scripted client (no daemon, no docker
process: the R-P guard would refuse one), exactly as the S3 reference driver does; `uuid4` of `isolated_evidence` and the host uid/gid are made
deterministic; the attached capture an injected function replaces is `isolated_evidence._capture` (the name the module imported). Children are real:
`ProcessTree.spawn` is replaced the way M7's tests patch it (the class attribute, read at call time)."""

import contextlib
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

driver.start("reference")

import s8_isolated_inspector  # noqa: E402

from codex_harness.adapters import evidence_inspection as ei  # noqa: E402
from codex_harness.adapters import isolated_evidence as ie  # noqa: E402
from codex_harness.adapters import isolated_worker as iw  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.process_tree import ProcessTree  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.evidence_inspection import EvidenceInspections  # noqa: E402
from codex_harness.domain.model import ContractError, digest  # noqa: E402
from codex_harness.domain.project_evidence import SCHEMA, SCHEMA_V2, parse_profile  # noqa: E402

REAL_SPAWN = ProcessTree.spawn


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

    ie.uuid4 = fixed


@contextlib.contextmanager
def spawning(spawn):
    """M7's tests patch the class attribute; the capture reads `ProcessTree.spawn` at call time."""
    original = ProcessTree.__dict__["spawn"]
    ProcessTree.spawn = staticmethod(spawn)
    try:
        yield
    finally:
        ProcessTree.spawn = original


@contextlib.contextmanager
def injected_capture(insp, capture):
    """The attached capture the replay uses: `isolated_evidence._capture` (None keeps the real one)."""
    if capture is None:
        yield
        return
    old = ie._capture
    ie._capture = capture
    try:
        yield
    finally:
        ie._capture = old


@contextlib.contextmanager
def patched(name, value):
    old = getattr(ei, name)
    setattr(ei, name, value)
    try:
        yield
    finally:
        setattr(ei, name, old)


def make_docker(artifacts, isolation, root):
    return ie.DockerEvidenceInspector(artifacts, isolation, root)


def make_project(artifacts, profile, isolation, root):
    return ie.IsolatedProjectEvidenceInspector(artifacts, profile, isolation, root)


API = SimpleNamespace(
    make_docker=make_docker, make_project=make_project, install_docker=install_docker, set_ids=set_ids, set_uuid=set_uuid, spawning=spawning,
    injected_capture=injected_capture, patched=patched, real_spawn=lambda: REAL_SPAWN, real_capture=lambda insp: ei._capture,
    ledger_get=lambda name: getattr(iw, name), ledger_set=lambda name, value: setattr(iw, name, value),
    OwnedContainer=iw.OwnedContainer, new_container=lambda isolation, run_id: iw.OwnedContainer(isolation, "docker", run_id, "verifier"),
    run_records=iw.run_records, unresolved_runs=iw.unresolved_runs, reconcile=lambda directory: iw.reconcile(directory),
    retire=iw.retire, load_isolation=iw.load_isolation, digest=digest, LABEL=iw.LABEL, INSPECT_FORMAT=iw.INSPECT_FORMAT,
    TOKEN_NAME=iw.TOKEN_NAME, TRUSTED_PYTHON=iw.TRUSTED_PYTHON, CONTAINER_ENVIRONMENT=ie.CONTAINER_ENVIRONMENT,
    container_environment=ie.container_environment, DockerEvidenceInspector=ie.DockerEvidenceInspector, FileArtifacts=FileArtifacts,
    MemoryStore=MemoryStore, EvidenceInspections=EvidenceInspections, packaged_policy=ei.packaged_policy, parse_profile=parse_profile,
    SCHEMA=SCHEMA, SCHEMA_V2=SCHEMA_V2, ContractError=ContractError, IsolationError=iw.IsolationError)

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zeus-s8-isolated-") as raw:
        result = s8_isolated_inspector.run(API, Path(raw))
    driver.finish("reference", "evidence.isolated_inspector", result)
