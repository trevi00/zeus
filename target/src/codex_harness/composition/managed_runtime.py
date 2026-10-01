"""Composition of the managed Fleet child processes: the launcher, the entry inside the sealed runtime and the
labelled fixture workload (DESIGN-s7 adapters-move §9, v2 amendment).

Layer: composition
Owns: `launch`, `entry`, `run_fixture`, `FixtureLauncher`, `fixture_config`, `fixture_manifest` and the wired
    `supervise` (M7 `adapters/managed_runtime.py` composition roots, SOURCE e38aa722; bodies are M7's apart from the
    counted rules below)
Does not own: `fleet_gate` and `run_fleet` (M7 `bootstrap.build` / `fleet_cli`: S10 carry, no target home yet)
Entry points: entry, launch, supervise, run_fixture
Contracts: INV-HOST-DELIVERY-001, INV-OWNER-ACTIONS-001

Counted rules against M7: the S5 Fleet is the four target objects (registry, admission, pause) composed over the
labelled in-memory store; `FixtureLauncher` creates its children through the injected `processes`; `entry` reports the
effective image and profile digest through `startup_receipt` as the 42a service does; `entry(state_dir, "fleet")`
raises `NotImplementedError` (S10 carry: `run_fleet`); `supervise` is wired with `launcher=launch`, and `gate` stays
required (`fleet_gate` is S10).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from codex_harness.composition.configuration import settings
from codex_harness.context.adapters import worker_profile
from codex_harness.coordination.application.fleet.admission import AdmissionControl
from codex_harness.coordination.application.fleet.pause import FleetPause
from codex_harness.coordination.application.fleet.registry import FleetRegistry
from codex_harness.coordination.application.fleet.runner import FleetRunner
from codex_harness.delivery.adapters import host_delivery, managed_runtime
from codex_harness.delivery.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    RECEIPT_FILE,
    _read_json,
    _write_json,
)
from codex_harness.delivery.adapters.managed_runtime import (
    EXIT_REFUSED,
    FIXTURE_JOBS_FILE,
    LAUNCHER_JOURNAL,
    MODULE,
    TARGET_FILE,
    Materializer,
    RuntimeControl,
    runtime_environment,
)
from codex_harness.delivery.domain.host_delivery import (
    MANAGED_KINDS,
    REGISTRY_SCHEMA,
    DeliveryRefused,
    descriptor_digest,
    same_path,
    validate_descriptor,
    validate_targets,
)
from codex_harness.delivery.domain.managed_runtime import (
    WORKLOAD_FIXTURE,
    WORKLOADS,
    EnvironmentUnqualified,
)
from codex_harness.host_os.adapters.background_service import run_owned
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses
from codex_harness.intake.domain.operation_manifest import validate_manifest
from codex_harness.routing.adapters.provider_policy import packaged_policy
from codex_harness.storage.adapters.memory_store import MemoryStore

FIXTURE_DIR = "fixture"
FIXTURE_INTERVAL = 0.2
_FIXTURE_CHILD = ("import os, sys, time\n"
                  "deadline = time.monotonic() + 300\n"
                  "while not os.path.exists(sys.argv[1]) and time.monotonic() < deadline:\n"
                  "    time.sleep(0.05)\n")


class FixtureLauncher:
    """Labelled controlled Fleet workload launcher: each job is a REAL child process that waits for
    its release marker. No `zeus operate run`, model, provider, ledger or network is involved."""

    def __init__(self, root: Path, processes):
        self.root, self.processes = root, processes

    @staticmethod
    def budget_exhausted(budget: dict) -> bool:
        return False

    def launch(self, job: dict) -> dict:
        marker = self.root / ("release-" + job["id"])
        process = self.processes.popen([sys.executable, "-c", _FIXTURE_CHILD, str(marker)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        return {"job_id": job["id"], "process": process}

    @staticmethod
    def wait(handles: list, seconds: float) -> list:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            finished = [h for h in handles if h["process"].poll() is not None]
            if finished or time.monotonic() >= deadline:
                return finished
            time.sleep(0.05)

    @staticmethod
    def outcome(handle: dict, job: dict) -> dict:
        code = handle["process"].returncode
        return {"status": "accepted" if code == 0 else "failed", "reason_code": "fixture_workload",
                "exit_code": code}


def fixture_config(root: Path) -> dict:
    return {"schema": "urn:zeus:fleet:1", "id": "managed-fixture", "max_parallel": 1,
            "budget": {"per_host": 4, "total": 8},
            "lanes": [{"id": "fixture", "team": "fixture", "repository": str(root / "repository"),
                       "schema": "lane_fixture", "redis_namespace": "managed-fixture",
                       "runtime": str(root / "runtime")}]}


def fixture_manifest(job_id: str) -> dict:
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": job_id, "base_revision": "a" * 40,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture " + job_id,
                 "rationale": "labelled controlled Fleet workload"},
        "plan": {"objective": "fixture", "acceptance_criteria": ["fixture"],
                 "allowed_paths": ["fixture/" + job_id + ".md"]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


def run_fixture(state_dir: Path, control: RuntimeControl) -> dict:
    """The labelled controlled Fleet workload: the real `FleetRunner` and control hooks over an
    in-memory Fleet whose queued jobs are the ids listed in `fixture-jobs.json`."""
    root = state_dir / FIXTURE_DIR
    root.mkdir(parents=True, exist_ok=True)
    store = MemoryStore()
    registry, admission, pause = FleetRegistry(store), AdmissionControl(store), FleetPause(store)
    registry.register(fixture_config(root))
    goal = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture",
            "base_revision": "a" * 40, "bytes": 7}
    jobs = _read_json(state_dir / FIXTURE_JOBS_FILE)
    for job_id in jobs if isinstance(jobs, list) else []:
        registry.enqueue("fixture", fixture_manifest(str(job_id)), goal, [])
    launcher = FixtureLauncher(root, ChokepointProcesses())
    runner = FleetRunner(registry, admission, pause, launcher, interval=FIXTURE_INTERVAL, control=control)
    return runner.run(once=False)


def _effective():
    try:
        host = settings()
    except Exception:
        # M7 `_host_settings`: a malformed host configuration invents none; the receipt then carries no image.
        host = {}
    return host_delivery.effective_worker_image(host), host_delivery.effective_profile_digest(worker_profile)


def entry(state_dir: str, workload: str) -> int:
    """Runs inside the sealed runtime: report the identity actually loaded, then run the workload."""
    root = Path(state_dir)
    try:
        descriptor = validate_descriptor(_read_json(root / DESCRIPTOR_FILE))
    except DeliveryRefused:
        return EXIT_REFUSED
    if workload not in WORKLOADS:
        return EXIT_REFUSED
    image, digest = _effective()
    receipt = host_delivery.startup_receipt(descriptor, image=image, profile_digest=digest)
    _write_json(root / RECEIPT_FILE, receipt)
    control = RuntimeControl(root, receipt)
    if workload == WORKLOAD_FIXTURE:
        run_fixture(root, control)
    else:
        raise NotImplementedError("S10 carry: run_fleet (bootstrap/fleet_cli)")
    return 0


def launch(state_dir: str, descriptor_sha256: str, workload: str) -> int:
    """Re-verify the sealed runtime against the descriptor this launch was for, then own its child.

    Nothing from the runtime is imported here. A target snapshot, a descriptor or a sealed directory
    that does not verify starts nothing and exits `2`; the controller then sees no startup receipt.
    """
    root = Path(state_dir)
    try:
        target = validate_targets({"schema": REGISTRY_SCHEMA,
                                   "targets": [_read_json(root / TARGET_FILE)]})["targets"][0]
        descriptor = validate_descriptor(_read_json(root / DESCRIPTOR_FILE))
        if target["kind"] not in MANAGED_KINDS or not same_path(target["state_dir"], root) \
                or descriptor_digest(descriptor) != descriptor_sha256 or workload not in WORKLOADS:
            return EXIT_REFUSED
        Materializer(target, processes=ChokepointProcesses()).verify(descriptor)
    except (DeliveryRefused, EnvironmentUnqualified):
        return EXIT_REFUSED
    argv = [target["python"], "-m", MODULE, "entry", "--state-dir", str(root), "--workload", workload]
    return run_owned(argv, cwd=descriptor["root"], env=runtime_environment(target, descriptor),
                     journal=root / LAUNCHER_JOURNAL)


def supervise(state_dir: str, *, gate, launcher=launch) -> int:
    return managed_runtime.supervise(state_dir, gate=gate, launcher=launcher)
