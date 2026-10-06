"""The opt-in managed Fleet host target: sealed immutable runtimes, the managed targets and the systemd binding (HOST-RUNTIME.md).

Layer: adapters
Context: delivery
Owns: Materializer, ManagedFleetTarget, SystemdManagedFleetTarget, supervise, RuntimeControl (M7 `adapters/managed_runtime.py` S7 core: the sealing, the managed target lifecycle, the launch request and the supervisor decisions)
Does not own: the child-process composition roots `fleet_gate`, `run_fleet`, `FixtureLauncher`, `run_fixture`, `entry`, `launch` and the `main` parser (composition/managed_runtime.py and entry/processes/managed_runtime.py), process creation (the host_os chokepoint, injected as `processes`/`runner`)
Entry points: Materializer, ManagedFleetTarget, SystemdManagedFleetTarget, supervise, runtime_image
Contracts: INV-HOST-DELIVERY-001, INV-OWNER-ACTIONS-001, INV-HOST-DELIVERY-MAINTENANCE-001

S7 named transcription of M7 `adapters/managed_runtime.py` (SOURCE e38aa722) through the declared rules (DESIGN-s7 adapters-move §8/§9, A/evidence/rebuild/s7/managed-runtime-adapter/transcribe.py): the excluded composition roots, the injected process creation and configuration, and the import homes; every body is otherwise M7's. M7 docstring follows.

The opt-in managed Fleet host target: sealed immutable runtimes and a real Fleet entry (HOST-RUNTIME.md).

Four concrete things live here; policy stays in `domain.managed_runtime` and `domain.host_delivery`.

* `Materializer` resolves an exact reviewed revision in the OWNER's source repository with Git
  itself (so a linked worktree's `commondir` is Git's business, not a copied claim), reads the
  tracked blobs of `src`, `pyproject.toml` and `uv.lock` with `git cat-file`, checks every blob id,
  stages them under `<managed root>/runtimes/.stage-<revision>-<id>`, verifies the stage against its
  own manifest and seals it with one atomic rename to `<managed root>/runtimes/<revision>`. It never
  imports candidate code, never writes into the source checkout, never overwrites or deletes a
  directory, and a stage that did not seal is left in place under its own name as recovery evidence.
  A lost response is answered by revalidating the sealed directory, never by sealing again.
* `ManagedFleetTarget` is `ProcessHostTarget` with the same guard, descriptor, instance authority
  and launch record, plus: the sealed runtime is verified (containment, manifest, every file,
  revision, lockfile, interpreter, effective worker image) BEFORE anything is stopped; the drain and
  the stop read the instance's own heartbeat; and nothing is ever killed - a stop is a pause, a
  proven idle heartbeat and the graceful stop file, or it is refused.
* `launch` is the fixed trusted launcher. It runs the CONTROLLER's code, from the state directory,
  re-verifies the sealed runtime against the descriptor it was launched for, and starts the child
  through the incumbent `background_service.run_owned` owner (Windows job object, POSIX process
  group) with the sealed `src` as the only `PYTHONPATH` entry and bytecode writing disabled.
* `entry` is what runs INSIDE the sealed runtime: it reports the identity it actually loaded (the
  incumbent `startup_receipt`) and runs the real `zeus fleet run` runner with the descriptor-bound
  pause, stop and heartbeat control. The `fixture` workload is the labelled controlled Fleet
  workload for tests: the same `FleetRunner`, an in-memory Fleet, and children that are real
  processes waiting for a release marker. No model, provider or network is involved in it.

What a plan or a descriptor can say is unchanged: a target id, a reviewed revision, an image and a
profile. The source, the managed root, the state directory, the interpreter, the qualified lockfile
and the workload are owner or controller configuration, and none of them ever reaches a command
line from a candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.delivery.adapters.host_delivery import (
    DESCRIPTOR_FILE,
    MAX_STATE_BYTES,
    PAUSE_FILE,
    RECEIPT_FILE,
    STATE_FILE,
    STOP_FILE,
    STOP_POLL,
    STOP_TIMEOUT,
    ProcessHostTarget,
    _alive,
    _read_json,
    _write_json,
    effective_worker_image,
)
from codex_harness.delivery.domain.host_delivery import (
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    MANAGED_SYSTEMD_UNIT,
    MANAGED_TARGET_FIELDS,
    REGISTRY_SCHEMA,
    SHA256,
    DeliveryRefused,
    descriptor_digest,
    same_path,
    validate_descriptor,
    validate_targets,
)
from codex_harness.delivery.domain.host_migration_evidence import SKEW_USEC, usec_of
from codex_harness.delivery.domain.managed_runtime import (
    HEARTBEAT_FILE,
    HEARTBEAT_MAX_AGE,
    LISTING_FILE,
    LOCK_PATH,
    MANIFEST_FILE,
    MATERIALIZED_PATHS,
    SEAL_FILES,
    STAGE_PREFIX,
    WORK_BUSY,
    WORK_IDLE,
    WORK_UNKNOWN,
    WORKLOAD_FLEET,
    WORKLOADS,
    EnvironmentUnqualified,
    blob_id,
    check_environment,
    check_runtime_path,
    check_sealed,
    manifest_digest,
    new_heartbeat,
    new_manifest,
    safe_runtime_path,
    validate_listing,
    validate_manifest,
    work_verdict,
)
from codex_harness.kernel.ids import digest

MODULE = "codex_harness.adapters.managed_runtime"
# The owner registry entry of the target, written by the controller under the target guard for the
# trusted launcher; the launcher validates it again with the incumbent registry grammar.
TARGET_FILE = "managed-target.json"
LAUNCHER_JOURNAL = "launcher-journal.jsonl"
MAX_SEAL_BYTES = 4 * 1024 * 1024
GIT_TIMEOUT = 120
EXIT_REFUSED = 2

# Labelled controlled Fleet workload (tests only): job ids to enqueue, and the release markers the
# waiting children exit on.
FIXTURE_JOBS_FILE = "fixture-jobs.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_seal(path: Path):
    """A bounded seal file, or None; the seal files are larger than ordinary state files."""
    return _read_json(path, MAX_SEAL_BYTES)


def scan(root: Path) -> list | None:
    """Every plain file under a runtime directory as `[path, blob]`, except the two seal files.

    Anything that is not a plain file - a symlinked file or directory, a device - makes the whole
    listing None, which no manifest can ever match.
    """
    files = []
    for directory, dirnames, filenames in os.walk(root):
        for name in dirnames:
            if os.path.islink(os.path.join(directory, name)):
                return None
        for name in filenames:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                return None
            relative = path.relative_to(root).as_posix()
            if relative in SEAL_FILES:
                continue
            files.append([relative, blob_id(path.read_bytes())])
    return sorted(files)


def owner_target(target: dict) -> dict:
    """The owner registry fields of a managed target and nothing else (a store row adds its own)."""
    return {key: target[key] for key in sorted(MANAGED_TARGET_FIELDS)}


# ----- the materializer --------------------------------------------------------------------------
class Materializer:
    """Seal one reviewed revision of the owner's source into its immutable runtime directory."""

    def __init__(self, target: dict, *, processes=None, timeout: int = GIT_TIMEOUT, new_hex=None):
        self.target, self.processes, self.timeout = target, processes, timeout
        self.new_hex = new_hex

    def _git(self, *args, stdin: bytes | None = None) -> subprocess.CompletedProcess:
        """Read-only Git in the owner's source repository: argv only, never a shell."""
        try:
            return self.processes.run(["git", "-C", self.target["source"], *args], input=stdin,
                                      capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Git itself is unavailable: an outage, never a verdict about the revision.
            raise RuntimeError("git unavailable") from exc

    def resolve(self, revision: str) -> str:
        """The commit must be EXACTLY this revision in the owner's source; returns its tree id."""
        commit = self._git("rev-parse", "--verify", "--quiet", revision + "^{commit}")
        if commit.returncode or commit.stdout.decode("ascii", "replace").strip() != revision:
            raise DeliveryRefused("runtime_revision_unresolved", "revision")
        tree = self._git("rev-parse", "--verify", "--quiet", revision + "^{tree}")
        value = tree.stdout.decode("ascii", "replace").strip()
        if tree.returncode or len(value) != 40:
            raise DeliveryRefused("runtime_revision_unresolved", "revision")
        return value

    def listing(self, revision: str) -> list[tuple[str, str, str]]:
        """`(path, mode, blob)` of every tracked runtime file at the revision; nothing else."""
        listed = self._git("ls-tree", "-r", "-z", "--full-tree", revision, "--", *MATERIALIZED_PATHS)
        if listed.returncode:
            raise DeliveryRefused("runtime_listing_unavailable", "revision")
        rows = []
        for entry in (e for e in listed.stdout.split(b"\0") if e):
            header, _, raw = entry.partition(b"\t")
            parts = header.decode("ascii", "replace").split()
            path = raw.decode("utf-8", "replace")
            if len(parts) != 3 or not safe_runtime_path(path) or path in SEAL_FILES:
                raise DeliveryRefused("runtime_listing_invalid", "files")
            mode, kind, blob = parts
            if kind == "commit":
                raise DeliveryRefused("runtime_submodule_unsupported", "files")
            if kind != "blob" or mode not in {"100644", "100755"}:
                # A symlink (120000) could point anywhere once sealed; it is refused, not followed.
                raise DeliveryRefused("runtime_entry_unsupported", "files")
            rows.append((path, mode, blob))
        return rows

    def blobs(self, rows) -> dict[str, bytes]:
        """The exact tracked bytes of every blob, each checked against its own Git blob id."""
        request = b"".join(blob.encode("ascii") + b"\n" for _, _, blob in rows)
        shown = self._git("cat-file", "--batch", stdin=request)
        if shown.returncode:
            raise DeliveryRefused("runtime_content_unavailable", "files")
        output, position, contents = shown.stdout, 0, {}
        for path, _, blob in rows:
            end = output.find(b"\n", position)
            header = output[position:end].decode("ascii", "replace").split()
            if end < 0 or len(header) != 3 or header[0] != blob or header[1] != "blob":
                raise DeliveryRefused("runtime_content_invalid", "files")
            size = int(header[2])
            data = output[end + 1:end + 1 + size]
            if len(data) != size or blob_id(data) != blob:
                raise DeliveryRefused("runtime_content_invalid", "files")
            contents[path] = data
            position = end + 1 + size + 1
        return contents

    def verify(self, descriptor: dict) -> dict:
        """The sealed directory the descriptor names is, right now, exactly its sealed manifest."""
        final = Path(check_runtime_path(self.target, descriptor))
        if final.is_symlink() or not final.is_dir():
            raise DeliveryRefused("runtime_unsealed", "root")
        manifest = validate_manifest(_read_seal(final / MANIFEST_FILE))
        listing = validate_listing(_read_seal(final / LISTING_FILE), manifest)
        return check_sealed(manifest, listing, descriptor, self.target, scan(final))

    def _sealed(self, descriptor: dict, *, recovered: bool) -> dict:
        manifest = self.verify(descriptor)
        return {"sealed": True, "revision": manifest["revision"],
                "manifest_sha256": manifest_digest(manifest), "files": manifest["files"],
                "recovered": recovered}

    def materialize(self, descriptor: dict) -> dict:
        """Seal the descriptor's revision once; an existing directory is revalidated, never replaced."""
        final = Path(check_runtime_path(self.target, descriptor))
        if os.path.lexists(final):
            # A lost response, a restart or a second owner: the same immutable result or a refusal.
            return self._sealed(descriptor, recovered=True)
        revision = descriptor["revision"]
        tree = self.resolve(revision)
        rows = self.listing(revision)
        contents = self.blobs(rows)
        lock = contents.get(LOCK_PATH)
        lock_sha256 = None if lock is None else hashlib.sha256(lock).hexdigest()
        # The environment gate comes before anything is written: an unqualified dependency set
        # leaves no stage behind, only a named unavailable environment.
        check_environment(lock_sha256, self.target)
        manifest, listing = new_manifest(revision, tree, [(path, blob) for path, _, blob in rows],
                                         lock_sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        stage = final.parent / (STAGE_PREFIX + revision + "-" + (self.new_hex or (lambda: uuid.uuid4().hex))()[:8])
        stage.mkdir()
        for path, mode, _ in rows:
            destination = stage / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contents[path])
            destination.chmod(0o555 if mode == "100755" else 0o444)
        for name, document in ((LISTING_FILE, listing), (MANIFEST_FILE, manifest)):
            (stage / name).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
            (stage / name).chmod(0o444)
        if scan(stage) != listing:
            # The stage is not what was read from Git; it stays, under its own name, as evidence.
            raise DeliveryRefused("runtime_stage_invalid", "files")
        try:
            os.rename(stage, final)
        except OSError:
            if os.path.lexists(final):
                # Another owner sealed first; this stage stays as evidence and theirs is checked.
                return self._sealed(descriptor, recovered=True)
            raise
        return self._sealed(descriptor, recovered=False)


# ----- environments ----------------------------------------------------------------------------
def runtime_environment(target: dict, descriptor: dict) -> dict:
    """The child's environment: the sealed `src` is its ONLY `PYTHONPATH` entry, bytecode writing is
    off (a sealed directory stays byte-identical), and host configuration is read from the owner's
    source repository exactly as the unmanaged Fleet reads it today."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(descriptor["root"]) / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["ZEUS_REPOSITORY"] = environment["HARNESS_REPOSITORY"] = target["source"]
    return environment


def launcher_environment() -> dict:
    """The trusted launcher imports THIS controller's code, never the runtime it is launching."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def runtime_image(target: dict, environment: dict, configuration) -> str:
    """The worker image the child will actually be configured with, read as its `settings()` will."""
    try:
        config = {**configuration.aliases(configuration.read_env(Path(target["source"]))),
                  **configuration.aliases(dict(environment))}
    except (OSError, ValueError) as exc:
        raise DeliveryRefused("runtime_settings_unreadable", "source") from exc
    return effective_worker_image(config)


# ----- the managed host target ------------------------------------------------------------------
class ManagedFleetTarget(ProcessHostTarget):
    """A Fleet runner in a sealed runtime, owned through the trusted launcher. Nothing is killed."""

    kind = KIND_MANAGED

    def __init__(self, *, configuration, workload: str = WORKLOAD_FLEET, heartbeat_max_age: float = HEARTBEAT_MAX_AGE,
                 stop_timeout: float = STOP_TIMEOUT, fleet=None, **kwargs):
        super().__init__(**kwargs)
        if workload not in WORKLOADS:
            raise ValueError("unknown managed workload")
        self.workload, self.heartbeat_max_age = workload, heartbeat_max_age
        self.stop_timeout = stop_timeout
        self.configuration = configuration
        # The Fleet authority of the activation gate: `application.fleet.Fleet` over the host store
        # in production (`host_ports(fleet=...)`), a labelled in-memory Fleet for the fixture
        # workload. None is never "no debt": every start then refuses `fleet_authority_unconfigured`.
        self.fleet = fleet

    # --- the sealed runtime ---------------------------------------------------------------------
    def materialize(self, target: dict, descriptor: dict, *, authorize=None) -> dict:
        """Seal (or revalidate) the descriptor's runtime. Ownership is proven before any write."""
        if authorize is not None:
            authorize()
        return Materializer(target, processes=self.processes).materialize(descriptor)

    def verify(self, target: dict, descriptor: dict) -> dict:
        return Materializer(target, processes=self.processes).verify(descriptor)

    def _prepare(self, target: dict, descriptor: dict) -> dict:
        """Every refusal a launch could meet, BEFORE anything on the target is stopped."""
        manifest = self.verify(target, descriptor)
        if not Path(target["python"]).is_file():
            raise DeliveryRefused("runtime_interpreter_unavailable", "python")
        environment = runtime_environment(target, descriptor)
        if runtime_image(target, environment, self.configuration) != descriptor["worker_image"]:
            raise DeliveryRefused("runtime_image_mismatch", "worker_image")
        return {"root": Path(descriptor["root"]), "environment": environment, "manifest": manifest}

    # --- the owner target snapshot the launcher and `supervise` re-validate -----------------------
    @staticmethod
    def _owner_target_bytes(target: dict) -> bytes:
        """The exact bytes `_write_json` gives the owner registry entry of this target."""
        return json.dumps(owner_target(target), sort_keys=True).encode("utf-8")

    def _owner_target_on_disk(self, target: dict) -> bytes | None:
        """The bytes of the snapshot as a regular file (never through a link), or None."""
        path = self.path(target, TARGET_FILE)
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def _target_file_matches(self, target: dict) -> bool:
        """INV-HOST-DELIVERY-MAINTENANCE-001: the snapshot on the target is byte-identical to the entry."""
        return self._owner_target_on_disk(target) == self._owner_target_bytes(target)

    def _write_owner_target(self, target: dict) -> None:
        """Publish the owner target snapshot for the launcher, without touching an identical one.

        A byte-identical snapshot is left exactly as it is - no rewrite, no new inode, no touched mtime -
        because its provenance is observed later (INV-HOST-DELIVERY-MAINTENANCE-001, S2M-18). An absent or
        differing one is replaced atomically as before. No mtime is ever edited or backdated here."""
        if self._target_file_matches(target):
            return
        _write_json(self.path(target, TARGET_FILE), owner_target(target))

    def _launch(self, target: dict, descriptor: dict, context: dict) -> dict:
        """Exactly one trusted launcher, and the launch record that identifies it, under the guard."""
        self._write_owner_target(target)
        argv = [target["python"], "-m", MODULE, "launch", "--state-dir", str(self.state_dir(target)),
                "--descriptor-sha256", descriptor_digest(descriptor), "--workload", self.workload]
        process = self.processes.popen(argv, process_group=True, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       cwd=str(self.state_dir(target)), env=launcher_environment())
        record = {"pid": process.pid, "started_at": _utcnow(),
                  "descriptor_sha256": descriptor_digest(descriptor),
                  "manifest_sha256": manifest_digest(context["manifest"])}
        _write_json(self.path(target, STATE_FILE), record)
        return {"started": True, "pid": process.pid, "launch": record}

    # --- what the running instance is doing ------------------------------------------------------
    def _pids(self, target: dict) -> tuple:
        """The launcher this component started AND the child that reported its own startup."""
        receipt = self.receipt(target)
        child = receipt.get("pid") if isinstance(receipt, dict) else None
        return self._state(target).get("pid"), child

    def running(self, target: dict) -> bool:
        """Running while EITHER process is alive: a child whose launcher was killed outright (the
        documented POSIX limit of the incumbent owner) is still a Fleet runner on this target."""
        return any(_alive(pid) for pid in self._pids(target))

    def heartbeat(self, target: dict):
        path = self.path(target, HEARTBEAT_FILE)
        document = _read_json(path)
        # A file that exists but cannot be read is unreadable, never missing.
        return "unreadable" if document is None and path.exists() else document

    def work(self, target: dict, *, require_paused: bool) -> dict:
        return work_verdict(self.heartbeat(target), self.receipt(target),
                            now=datetime.now(timezone.utc), max_age=self.heartbeat_max_age,
                            require_paused=require_paused)

    def _pause(self, target: dict) -> None:
        current = self.current(target)
        _write_json(self.path(target, PAUSE_FILE + ".json"),
                    {"paused": True, "at": _utcnow(),
                     "descriptor_sha256": None if current is None else descriptor_digest(current)})

    def drain(self, target: dict, *, authorize=None) -> dict:
        """Close admission and report the instance's OWN work; unknown is unconfirmed, never idle."""
        with self.guard(target, authorize):
            self._pause(target)
            running = self.running(target)
            verdict = self.work(target, require_paused=True) if running else None
        if not running:
            return {"drained": True, "unconfirmed": 0, "running": False, "active": 0, "work": None}
        return {"drained": verdict["state"] == WORK_IDLE,
                "unconfirmed": 1 if verdict["state"] == WORK_UNKNOWN else 0, "running": True,
                "active": verdict["active"], "work": verdict}

    def stop(self, target: dict) -> dict:
        """Pause, wait (bounded) for a proven idle heartbeat, then ask for a graceful exit.

        Active or unknown work refuses the stop with its own code, and the instance keeps running
        with admission closed; no signal is ever sent, so no owned child is ever killed from here.
        """
        pid = self._state(target).get("pid")
        if not self.running(target):
            return {"stopped": True, "was_running": False, "pid": pid}
        self._pause(target)
        deadline = time.monotonic() + self.stop_timeout
        verdict = self.work(target, require_paused=True)
        while verdict["state"] != WORK_IDLE and self.running(target) \
                and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
            verdict = self.work(target, require_paused=True)
        if not self.running(target):
            return {"stopped": True, "was_running": True, "pid": pid}
        if verdict["state"] != WORK_IDLE:
            return {"stopped": False, "was_running": True, "pid": pid,
                    "reason_code": "instance_work_" + verdict["state"], "work": verdict}
        _write_json(self.path(target, STOP_FILE + ".json"), {"stop": True, "at": _utcnow()})
        deadline = time.monotonic() + self.stop_timeout
        while self.running(target) and time.monotonic() < deadline:
            time.sleep(STOP_POLL)
        alive = self.running(target)
        return {"stopped": not alive, "was_running": True, "pid": pid,
                "reason_code": "instance_stop_unconfirmed" if alive else None}

    def _activation_gate(self, target: dict, descriptor: dict) -> None:
        """Paused durable admission plus settled Fleet debt, or no activation (HOST-RUNTIME.md).

        One Fleet transaction commits the admission pause (retained afterwards as this activation's
        hold); a second one re-checks that pause and reads every reserving worker job and held
        execution unit. A pause that could not be committed or acknowledged refuses
        `fleet_pause_unknown` (no durable pause is claimed); a failed debt read after the committed
        pause `fleet_debt_unknown`; a pause changed between the two `fleet_control_changed`; any held
        debt `fleet_debt_held`; an unconfigured authority `fleet_authority_unconfigured`, because
        unknown is never settled. A dead controller or an idle heartbeat does not count: only this
        read does. Called under the target guard, before the stop and again before the launch; no
        store transaction is open across process I/O."""
        if self.fleet is None:
            raise DeliveryRefused("fleet_authority_unconfigured", "fleet")
        try:
            gate = self.fleet.activation_gate(target["target_id"], descriptor_digest(descriptor))
        except Exception as exc:
            raise DeliveryRefused("fleet_pause_unknown", "fleet") from exc
        refusal = gate_refusal(gate)
        if refusal is not None:
            raise DeliveryRefused(refusal, "fleet")

    def _retire(self, target: dict) -> None:
        super()._retire(target)
        try:
            self.path(target, HEARTBEAT_FILE).unlink()
        except OSError:
            pass


def gate_refusal(gate: dict) -> str | None:
    """The named refusal of one `Fleet.activation_gate` answer, or None when admission is paused and
    the Fleet debt is settled. Unknown is never settled."""
    if gate.get("reason_code") == "debt_unknown":
        return "fleet_debt_unknown"
    if gate.get("reason_code") == "control_changed":
        return "fleet_control_changed"
    if gate.get("paused") is not True or gate.get("settled") is not True:
        return "fleet_debt_held"
    return None


# ----- the systemd-supervised binding (aibox SPEC s14 G3, INV-OWNER-ACTIONS-001) ------------------------
# The managed target above launches its trusted launcher as a detached child of the CONTROLLER. On a
# Linux host whose delivery controller is itself a systemd service that child stays in the controller's
# control group, so a controller restart would end the Fleet (KillMode=control-group) and
# `KillMode=process` would weaken the agreed ownership policy. This binding changes only WHO launches and
# supervises the guardian: the controller writes the launch request under the target guard and starts the
# ONE owner-fixed unit; the unit's ExecStart (`supervise`, controller code from the stable release)
# re-validates the persisted request, target, descriptor, sealed runtime and Fleet debt, then runs the
# incumbent `launch` in the unit's own control group. Materialize, verify, drain, stop, heartbeat and
# startup receipt are inherited unchanged; nothing here sends a signal or runs `systemctl stop`.
LAUNCH_REQUEST_FILE = "managed-launch.json"
LAUNCH_REQUEST_SCHEMA = "urn:zeus:managed-launch-request:1"
LAUNCH_REQUEST_FIELDS = {"schema", "target_id", "descriptor_sha256", "manifest_sha256", "workload", "requested_at"}
SUPERVISOR_JOURNAL = "supervisor-journal.jsonl"
UNIT_ACTIVE_STATES = ("active", "activating", "deactivating", "reloading")
UNIT_STOPPED_STATES = ("inactive", "failed")


def validate_launch_request(document) -> dict:
    """The controller's persisted launch request; anything else starts nothing."""
    if not (isinstance(document, dict) and set(document) == LAUNCH_REQUEST_FIELDS
            and document["schema"] == LAUNCH_REQUEST_SCHEMA and document["workload"] in WORKLOADS
            and all(type(document[key]) is str and SHA256.fullmatch(document[key])
                    for key in ("descriptor_sha256", "manifest_sha256"))
            and type(document["target_id"]) is str and type(document["requested_at"]) is str):
        raise DeliveryRefused("launch_request_invalid", "request")
    return dict(document)


class SystemdManagedFleetTarget(ManagedFleetTarget):
    """The managed Fleet target whose guardian is owned by the owner-fixed systemd unit.

    `runner` is the `systemctl` port (argv only). Control rights used: `show` and `start` of exactly
    `MANAGED_SYSTEMD_UNIT`; a stop is the inherited graceful stop (pause, proven idle heartbeat, stop
    file) and the unit ends when its launcher returns. Unit state is read, never guessed: an unknown
    `ActiveState` raises instead of reading as stopped."""

    kind = KIND_MANAGED_SYSTEMD

    def __init__(self, *, runner, timeout: int = 60, process_reader=None, **kwargs):
        super().__init__(**kwargs)
        self.runner, self.timeout = runner, timeout
        # `process_reader(pid)` answers in the `HostReader.process` shape (INV-HOST-MIGRATION-001's accepted
        # `/proc` reader), injected by composition (`delivery_hosts.process_reader`: the reader needs the host_os
        # facts and chokepoint, which an adapter may not import). Without one nothing is read: every process is
        # `unknown`, and the coordinator's policy refuses on an unknown fact.
        self.process_reader = process_reader

    @staticmethod
    def unit(target: dict) -> str:
        if target.get("service") != MANAGED_SYSTEMD_UNIT:
            raise DeliveryRefused("target_unit_not_allowed", "service")
        return MANAGED_SYSTEMD_UNIT + ".service"

    def _show(self, target: dict) -> dict:
        result = self.runner(["systemctl", "show", self.unit(target), "-p", "ActiveState", "-p", "MainPID",
                              "-p", "InvocationID"], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("managed unit state unavailable")
        return dict(line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line)

    def unit_active(self, target: dict) -> bool:
        state = self._show(target).get("ActiveState")
        if state in UNIT_ACTIVE_STATES:
            return True
        if state in UNIT_STOPPED_STATES:
            return False
        raise RuntimeError("managed unit state unavailable")

    def running(self, target: dict) -> bool:
        """The unit's control group owns the launcher and the sealed child, so its state answers
        first; a recorded or self-reported pid still alive is also a runner on this target."""
        return self.unit_active(target) or super().running(target)

    def _launch(self, target: dict, descriptor: dict, context: dict) -> dict:
        """The launch request, then ONE `systemctl start` of the owner-fixed unit, under the guard."""
        self._write_owner_target(target)
        request = validate_launch_request({
            "schema": LAUNCH_REQUEST_SCHEMA, "target_id": target["target_id"],
            "descriptor_sha256": descriptor_digest(descriptor),
            "manifest_sha256": manifest_digest(context["manifest"]), "workload": self.workload,
            # An active-generation maintenance binds its launch to its own request time (S2R F1); every other
            # launch is stamped now, exactly as before.
            "requested_at": context.get("requested_at") or _utcnow()})
        _write_json(self.path(target, LAUNCH_REQUEST_FILE), request)
        result = self.runner(["systemctl", "start", self.unit(target)], timeout=self.timeout)
        if result.returncode:
            raise RuntimeError("managed unit could not be started")
        shown = self._show(target)
        main_pid = shown.get("MainPID") or ""
        record = {"pid": int(main_pid) if main_pid.isdigit() and int(main_pid) > 0 else None,
                  "service": target["service"], "invocation_id": shown.get("InvocationID") or None,
                  "started_at": _utcnow(), "descriptor_sha256": request["descriptor_sha256"],
                  "manifest_sha256": request["manifest_sha256"]}
        _write_json(self.path(target, STATE_FILE), record)
        return {"started": True, "pid": record["pid"], "launch": record}

    # --- the managed generation observation (INV-HOST-DELIVERY-MAINTENANCE-001) ----------------------
    def generation_observation(self, target: dict) -> dict:
        """What this target's executing generation IS right now, as bounded safe facts. Read only.

        No lock is taken and nothing is written or created: the files are read bounded, the unit with ONE
        additional `systemctl show` of fixed properties, the two processes through the accepted `/proc`
        reader. A fact that cannot be observed is None (or `unknown`), never a guess, and this never
        raises for one. Paths, the raw control group, environment file names and argv never leave here:
        they are hashed, counted or compared in memory. The coordinator's pure policy
        (`classify_restart`, `new_generation_refusal`) decides what the facts permit.
        """
        receipt_document = self.receipt(target)
        receipt = receipt_document if isinstance(receipt_document, dict) else None
        launch_document = self.launch_record(target)
        launch = launch_document if isinstance(launch_document, dict) else None
        try:
            request = validate_launch_request(_read_json(self.path(target, LAUNCH_REQUEST_FILE)))
        except DeliveryRefused:
            request = None
        try:
            running = self._liveness(target, receipt)
        except Exception:
            running = None
        receipt_present = os.path.lexists(self.path(target, RECEIPT_FILE))
        unit, control_group, unit_read = self._unit_observation(target)
        supervisor, entry = self._process_observation(unit, control_group, unit_read, receipt, receipt_present)
        return {"schema": GENERATION_OBSERVATION_SCHEMA, "observed_at": _utcnow(),
                "running": running if running is None else bool(running),
                "receipt": receipt, "receipt_present": receipt_present,
                "launch": launch, "launch_present": os.path.lexists(self.path(target, STATE_FILE)),
                "launch_sha256": None if launch is None else digest(launch),
                "launch_request_sha256": None if request is None else digest(request),
                "launch_request_requested_at": None if request is None else _aware_text(request["requested_at"]),
                "target_file_matches": self._target_file_matches(target),
                "control_user_matches": _control_user_matches(target),
                "unit": unit, "supervisor": supervisor, "entry": entry, "work": self._work_observation(target)}

    def _unit_observation(self, target: dict) -> tuple:
        """`(facts, raw control group, read)`: the raw group is for in-memory comparison only. A failed
        read leaves every fact None and `read` False."""
        facts = dict.fromkeys(("active_state", "invocation_id", "main_pid", "exec_main_pid",
                               "need_daemon_reload", "control_group_sha256", "environment_files_sha256",
                               "drop_in_count"))
        try:
            argv = ["systemctl", "show", self.unit(target)]
            for name in GENERATION_UNIT_PROPERTIES:
                argv += ["-p", name]
            result = self.runner(argv, timeout=self.timeout)
            text = result.stdout.decode("utf-8") if isinstance(result.stdout, bytes) else result.stdout
        except Exception:
            return facts, None, False
        if result.returncode or not isinstance(text, str) or len(text) > MAX_UNIT_SHOW_CHARS:
            return facts, None, False
        values: dict = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in GENERATION_UNIT_PROPERTIES:
                values.setdefault(key, []).append(value)
        single = {key: rows[0] for key, rows in values.items() if len(rows) == 1}
        state = single.get("ActiveState")
        invocation = single.get("InvocationID")
        group = single.get("ControlGroup")
        group = group if isinstance(group, str) and group.startswith("/") else None
        reload = single.get("NeedDaemonReload")
        facts.update({
            "active_state": state if isinstance(state, str) and UNIT_STATE.fullmatch(state) else None,
            "invocation_id": invocation if isinstance(invocation, str) and INVOCATION.fullmatch(invocation) else None,
            "main_pid": _positive_pid(single.get("MainPID")),
            "exec_main_pid": _positive_pid(single.get("ExecMainPID")),
            "need_daemon_reload": {"yes": True, "no": False}.get(reload) if isinstance(reload, str) else None,
            "control_group_sha256": None if group is None else _sha256_text(group),
            # Several `EnvironmentFiles=` lines are one ordered list; only its digest is kept.
            "environment_files_sha256": _sha256_text("\n".join(values.get("EnvironmentFiles", []))),
            "drop_in_count": (len(single["DropInPaths"].split()) if "DropInPaths" in single
                              else 0 if "DropInPaths" not in values else None)})
        return facts, group, True

    def _read_process(self, pid: int) -> dict:
        if self.process_reader is None:
            raise RuntimeError("no process reader is wired")
        return self.process_reader(pid)

    def _process(self, pid) -> dict | None:
        """One process identity in the `HostReader.process` shape, or None when it cannot be read."""
        if pid is None:
            return None
        try:
            answer = self._read_process(pid)
        except Exception:
            return {"pid": pid, "state": "unknown"}
        return answer if isinstance(answer, dict) else {"pid": pid, "state": "unknown"}

    def _process_observation(self, unit: dict, control_group, unit_read: bool, receipt,
                             receipt_present: bool) -> tuple:
        """The supervisor (the unit's main process) and the entry (the pid its own receipt names). No pid
        to read is `absent` only when its source was read and names none: a unit without a main process,
        or no receipt file at all."""
        main_pid = unit["main_pid"]
        supervisor_process = self._process(main_pid)
        supervisor = {"pid": main_pid, "state": _process_state(supervisor_process, known=unit_read),
                      "start_ticks": _start_ticks(supervisor_process),
                      "is_main_pid": (None if main_pid is None or unit["exec_main_pid"] is None
                                      else main_pid == unit["exec_main_pid"])}
        raw_pid = receipt.get("pid") if receipt is not None else None
        entry_pid = raw_pid if type(raw_pid) is int and raw_pid > 0 else None
        entry_process = self._process(entry_pid)
        present = entry_process is not None and entry_process.get("state") == "present"
        ppid, cgroup = (entry_process.get("ppid"), entry_process.get("cgroup")) if present else (None, None)
        entry = {"pid": entry_pid, "state": _process_state(entry_process, known=not receipt_present),
                 "start_ticks": _start_ticks(entry_process),
                 "parent_is_supervisor": (None if type(ppid) is not int or main_pid is None
                                          else ppid == main_pid),
                 "in_unit_cgroup": (None if not isinstance(cgroup, str) or control_group is None
                                    else cgroup == control_group),
                 "started_before_receipt": _started_before(entry_process if present else None, receipt)}
        return supervisor, entry

    def _work_observation(self, target: dict) -> dict:
        """The instance's own heartbeat verdict, projected to its four safe facts."""
        try:
            verdict = self.work(target, require_paused=False)
        except Exception:
            verdict = {}
        state = verdict.get("state")
        code = verdict.get("reason_code")
        return {"state": state if state in (WORK_IDLE, WORK_BUSY, WORK_UNKNOWN) else WORK_UNKNOWN,
                "reason_code": code if isinstance(code, str) and REASON_CODE.fullmatch(code) else None,
                "active": verdict.get("active") if type(verdict.get("active")) is int else None,
                "unresolved": verdict.get("unresolved") if type(verdict.get("unresolved")) is int else None}


# The observation of INV-HOST-DELIVERY-MAINTENANCE-001 (the literal the domain validator checks), and the one
# additional `systemctl show` it reads. `EnvironmentFiles` may span several lines.
GENERATION_OBSERVATION_SCHEMA = "urn:zeus:managed-generation-observation:1"
GENERATION_UNIT_PROPERTIES = ("ActiveState", "MainPID", "ExecMainPID", "InvocationID", "NeedDaemonReload",
                              "ControlGroup", "EnvironmentFiles", "DropInPaths")
MAX_UNIT_SHOW_CHARS = 256 * 1024
UNIT_STATE = re.compile(r"^[a-z][a-z-]{0,31}$")
INVOCATION = re.compile(r"^[0-9a-f]{32}$")
REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PROCESS_STATES = ("present", "absent", "replaced", "unknown")


def _aware_text(value) -> str | None:
    """An aware ISO timestamp of at most 64 characters as written, or None (an unreadable fact)."""
    if type(value) is not str or not 0 < len(value) <= 64:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if moment.tzinfo is not None else None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_pid(value) -> int | None:
    """`MainPID`/`ExecMainPID` as a pid; `0` (no process) and anything unparseable are None."""
    if not (isinstance(value, str) and value.isascii() and value.isdigit()):
        return None
    number = int(value)
    return number if 0 < number < 2 ** 31 else None


def _process_state(process, *, known: bool) -> str:
    """No pid to read is `absent` when its source proved there is none (`known`), else `unknown`;
    otherwise the reader's own state."""
    if process is None:
        return "absent" if known else "unknown"
    state = process.get("state")
    return state if state in PROCESS_STATES else "unknown"


def _start_ticks(process) -> int | None:
    if process is None or process.get("state") != "present":
        return None
    ticks = process.get("start_ticks")
    return ticks if type(ticks) is int else None


def _started_before(process, receipt) -> bool | None:
    """Whether this process started no later than the receipt it is named by (within the clock skew):
    a reused pid - a process that started after the receipt was written - answers False."""
    started = usec_of(receipt.get("started_at")) if receipt is not None else None
    start_usec = process.get("start_usec") if process is not None else None
    if started is None or type(start_usec) is not int:
        return None
    # `start_usec` is CLOCK_MONOTONIC; its wall time is now minus the monotonic time elapsed since.
    wall_now_usec = time.time_ns() // 1000
    monotonic_now_usec = time.monotonic_ns() // 1000
    return wall_now_usec - (monotonic_now_usec - start_usec) <= started + SKEW_USEC


def _control_user_matches(target: dict) -> bool | None:
    """The polkit/start capability proxy (DN-6): this process's euid owns the target state directory."""
    try:
        return os.geteuid() == os.stat(target["state_dir"]).st_uid
    except (AttributeError, KeyError, OSError, TypeError):
        return None


def _journal(root: Path, event: str, **facts) -> None:
    """One flushed JSON line of what `supervise` decided: codes and ids, never paths or values."""
    line = json.dumps({"event": event, "at": _utcnow(), "invocation_id": os.environ.get("INVOCATION_ID"),
                       **facts}, sort_keys=True)
    with open(root / SUPERVISOR_JOURNAL, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def supervise(state_dir: str, *, gate, launcher) -> int:
    """The unit's ExecStart after the host launcher's fence/activation checks: re-validate everything the
    controller persisted, then run the incumbent `launch` in THIS unit's control group.

    A (re)start of the unit - the controller's start, a bounded `Restart=on-failure` or a boot - passes
    the same checks: the persisted request names this target and the descriptor that is on it now, the
    sealed runtime still verifies to the manifest the controller launched, no stop was requested, the
    instance that reported last is not still alive, and the Fleet's activation gate (a committed pause,
    then settled debt) holds. Any refusal starts nothing and
    exits `EXIT_REFUSED`, which the unit declares non-restartable; unresolved debt refuses new work."""
    root = Path(state_dir)
    try:
        request = validate_launch_request(_read_json(root / LAUNCH_REQUEST_FILE))
        target = validate_targets({"schema": REGISTRY_SCHEMA,
                                   "targets": [_read_json(root / TARGET_FILE)]})["targets"][0]
        if target["kind"] != KIND_MANAGED_SYSTEMD or not same_path(target["state_dir"], root) \
                or request["target_id"] != target["target_id"]:
            raise DeliveryRefused("launch_request_foreign", "target_id")
        if os.path.lexists(root / (STOP_FILE + ".json")):
            raise DeliveryRefused("stop_requested", "state_dir")
        previous = _read_json(root / RECEIPT_FILE)
        if isinstance(previous, dict) and _alive(previous.get("pid")):
            # The instance that reported last is still running (a restart whose control-group cleanup did
            # not end it): starting another would make two Fleet runners. Held for its owner instead.
            raise DeliveryRefused("previous_instance_alive", "pid")
        descriptor = validate_descriptor(_read_json(root / DESCRIPTOR_FILE))
        if descriptor_digest(descriptor) != request["descriptor_sha256"]:
            raise DeliveryRefused("descriptor_changed", "descriptor")
        if manifest_digest(Materializer(target).verify(descriptor)) != request["manifest_sha256"]:
            raise DeliveryRefused("runtime_manifest_changed", "root")
        try:
            verdict = gate(target["target_id"], request["descriptor_sha256"])
        except Exception as exc:
            raise DeliveryRefused("fleet_pause_unknown", "fleet") from exc
        refusal = gate_refusal(verdict if isinstance(verdict, dict) else {})
        if refusal is not None:
            raise DeliveryRefused(refusal, "fleet")
    except (DeliveryRefused, EnvironmentUnqualified) as exc:
        try:
            _journal(root, "refused", reason_code=getattr(exc, "reason_code", "environment_unqualified"))
        except OSError:
            pass
        return EXIT_REFUSED
    _journal(root, "launch", descriptor_sha256=request["descriptor_sha256"], workload=request["workload"])
    return launcher(str(root), request["descriptor_sha256"], request["workload"])


# ----- inside the sealed runtime ------------------------------------------------------------------
class RuntimeControl:
    """The descriptor-bound control a running instance reads and the heartbeat it writes."""

    def __init__(self, state_dir: Path, receipt: dict):
        self.root, self.receipt = Path(state_dir), receipt

    def admission_open(self) -> bool:
        # Any pause file closes admission, readable or not: an unknown pause is a pause.
        return not os.path.lexists(self.root / (PAUSE_FILE + ".json"))

    def stop_requested(self) -> bool:
        return os.path.lexists(self.root / (STOP_FILE + ".json"))

    def activation(self) -> str:
        """The descriptor this instance runs: the only activation hold it may release."""
        return self.receipt["descriptor_sha256"]

    def heartbeat(self, state: dict) -> None:
        _write_json(self.root / HEARTBEAT_FILE,
                    new_heartbeat(self.receipt, at=_utcnow(), admission=state["admission"],
                                  active=state["active"], unresolved=state["unresolved"]))


__all__ = ["FIXTURE_JOBS_FILE", "GENERATION_OBSERVATION_SCHEMA", "GENERATION_UNIT_PROPERTIES", "LAUNCHER_JOURNAL", "LAUNCH_REQUEST_FILE", "LAUNCH_REQUEST_SCHEMA", "MODULE",
           "SUPERVISOR_JOURNAL", "TARGET_FILE", "ManagedFleetTarget", "Materializer", "RuntimeControl",
           "SystemdManagedFleetTarget", "gate_refusal", "launcher_environment", "owner_target", "runtime_environment",
           "runtime_image", "scan", "supervise", "validate_launch_request"]
