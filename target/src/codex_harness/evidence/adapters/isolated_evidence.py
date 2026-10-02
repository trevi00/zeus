"""INV-ISOLATED-WORKER-001: deterministic evidence replay in fresh, credential-free containers.

Authorization, claim parsing, budgets, classification, binding and archival are the inherited
`EvidenceInspector`'s; this backend only changes WHERE an already authorized argv runs: a fresh
copy of the candidate, the same immutable image, network none, no token and no service
credential, the same filesystem and resource controls as the worker. No candidate command runs
on the host, and an unavailable container is a named failure, never a host replay.

Layer: adapters
Context: evidence
Owns: DockerEvidenceInspector (the evidence backend that replays an already authorized argv in a fresh container: its identity, interpreter and snapshot), IsolatedProjectEvidenceInspector (the host's declared project checks replayed in the pinned image)
Does not own: the container lifecycle of a replay (`execution.adapters.containers.evidence_replay.ContainerEvidenceReplay`, injected as `containers` through the `evidence.ports.ContainerReplay` port), authorization, claim parsing, budgets, classification and archival (`evidence.adapters.evidence_inspection`), the profile (`evidence.adapters.project_evidence`), the container constants (`evidence.adapters.container_contract`, equal to the execution values)
Entry points: DockerEvidenceInspector, IsolatedProjectEvidenceInspector, CONTAINER_ENVIRONMENT, container_environment (both imported from `container_contract`)
Contracts: INV-ISOLATED-WORKER-001, INV-PROJECT-EVIDENCE-001

Moved from M7 `adapters/isolated_evidence.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §27.1 V26 rules E-2/E-3, S8 batch B5b, A/evidence/rebuild/s8/batch-b5b-move/transcribe.py): R-ie0 (imports from the evidence homes; no execution name), E-2a (both inspectors take keyword-only `containers=None` and `process_tree=None`; `process_tree` goes to the base), E-2b (`_replay` is the one delegate to `self.containers.replay`, refusing with `containers is not wired` before any snapshot or container; `IsolatedProjectEvidenceInspector._replay` is still the same function object), E-2c (`snapshot` requires the wiring and reads `self.containers.summary()`), E-5 (`CONTAINER_ENVIRONMENT` and `container_environment` live verbatim in `container_contract` and are imported here, so `isolated_evidence.CONTAINER_ENVIRONMENT` remains and the two adapters form no import cycle); every other statement is M7's. The first paragraphs are M7's module docstring.
"""
from __future__ import annotations

from pathlib import Path

from codex_harness.evidence.adapters.container_contract import (
    CONTAINER_ENVIRONMENT,
    TRUSTED_PYTHON,
    WORKSPACE,
    container_environment,
)
from codex_harness.evidence.adapters.evidence_inspection import EvidenceInspector
from codex_harness.evidence.adapters.project_evidence import (
    ProjectEvidenceInspector,
    container_binding,
    resolve_container_profile,
)
from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest


class DockerEvidenceInspector(EvidenceInspector):
    def __init__(self, artifacts, isolation: dict, root, docker: str = "docker", policy=None, *, containers=None,
                 process_tree=None):
        super().__init__(artifacts, policy, interpreter=TRUSTED_PYTHON, process_tree=process_tree)
        self.isolation, self.root, self.docker = isolation, Path(root), docker
        # The container run of a replay (S8 V26 E-2): composition passes the execution-provided `ContainerReplay`.
        self.containers = containers

    def _trusted(self, candidate):
        # The image's interpreter: a container path, so there is no host file to verify and none is run.
        return TRUSTED_PYTHON

    def _python(self):
        return "container:" + self.isolation["image"]

    def snapshot(self, cwd=None):
        """The identity describes the container context: image, limits, network and driver are in the
        cache key, so a changed image or configuration never reads back an older inspection."""
        require(self.containers is not None, "containers is not wired")
        environment = container_environment(cwd)
        identity = {"policy_hash": self.policy["policy_hash"], "environment_names": sorted(environment),
                    "environment_digest": digest(sorted(environment.items())), "interpreter": TRUSTED_PYTHON,
                    "cwd": str(Path(cwd).resolve()) if cwd is not None else None,
                    "container": {**self.containers.summary(), "network": "none", "credentials": "none",
                                  "workspace": WORKSPACE, "snapshot": "fresh copy per replay"},
                    "platform": "linux-container"}
        return {"identity": identity, "environment": environment, "interpreter": TRUSTED_PYTHON}

    def _replay(self, argv, cwd, timeout, max_bytes, env, progress=None, workdir=WORKSPACE):
        """One authorized argv in one fresh container over one fresh candidate copy: the container lifecycle is the injected `ContainerReplay`'s
        (S8 V26 E-1/E-2); `capture` is this inspector's bounded attached capture (`_capture_fn`, with the process-tree port)."""
        require(self.containers is not None, "containers is not wired")
        return self.containers.replay(argv, cwd, timeout, max_bytes, env, capture=self._capture_fn, progress=progress,
                                      workdir=workdir)


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

    def __init__(self, artifacts, profile, isolation: dict, root, docker: str = "docker", policy=None, *, containers=None,
                 process_tree=None):
        super().__init__(artifacts, profile, policy, interpreter=TRUSTED_PYTHON, process_tree=process_tree)
        # Refused here, before any snapshot or container: version, image and interpreter must agree.
        self.execution = container_binding(profile, isolation)
        self.isolation, self.root, self.docker = isolation, Path(root), docker
        self.containers = containers

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
        require(self.containers is not None, "containers is not wired")
        require(cwd is not None, "Project evidence snapshot requires the candidate workspace")
        project = resolve_container_profile(self.profile, cwd, self.isolation)
        # The identity environment is the one every context shares; per-context PYTHONPATH values are
        # bound by the project digest below, and each replay runs under its own context environment.
        environment = {k: v for k, v in CONTAINER_ENVIRONMENT.items()}
        identity = {"policy_hash": self.policy["policy_hash"], "environment_names": sorted(environment),
                    "environment_digest": digest(sorted(environment.items())), "interpreter": TRUSTED_PYTHON,
                    "cwd": str(Path(cwd).resolve()),
                    "container": {**self.containers.summary(), "network": "none", "credentials": "none",
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
