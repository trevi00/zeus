"""The opt-in managed Fleet host target: sealed immutable runtimes and a real Fleet entry (HOST-RUNTIME.md).

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

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import codex_harness
from codex_harness.adapters.commands import no_console_kwargs, run_process
from codex_harness.adapters.host_delivery import (
    DESCRIPTOR_FILE,
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
    startup_receipt,
)
from codex_harness.domain.host_delivery import (
    KIND_MANAGED,
    KIND_MANAGED_SYSTEMD,
    MANAGED_KINDS,
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
from codex_harness.domain.managed_runtime import (
    HEARTBEAT_FILE,
    HEARTBEAT_MAX_AGE,
    LISTING_FILE,
    LOCK_PATH,
    MANIFEST_FILE,
    MATERIALIZED_PATHS,
    SEAL_FILES,
    STAGE_PREFIX,
    WORK_IDLE,
    WORK_UNKNOWN,
    WORKLOAD_FIXTURE,
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
FIXTURE_DIR = "fixture"
FIXTURE_INTERVAL = 0.2
_FIXTURE_CHILD = ("import os, sys, time\n"
                  "deadline = time.monotonic() + 300\n"
                  "while not os.path.exists(sys.argv[1]) and time.monotonic() < deadline:\n"
                  "    time.sleep(0.05)\n")


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

    def __init__(self, target: dict, *, timeout: int = GIT_TIMEOUT):
        self.target, self.timeout = target, timeout

    def _git(self, *args, stdin: bytes | None = None) -> subprocess.CompletedProcess:
        """Read-only Git in the owner's source repository: argv only, never a shell."""
        try:
            return subprocess.run(["git", "-C", self.target["source"], *args], input=stdin,
                                  capture_output=True, timeout=self.timeout, **no_console_kwargs())
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
        stage = final.parent / (STAGE_PREFIX + revision + "-" + uuid.uuid4().hex[:8])
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
    environment["PYTHONPATH"] = str(Path(codex_harness.__file__).resolve().parent.parent)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def runtime_image(target: dict, environment: dict) -> str:
    """The worker image the child will actually be configured with, read as its `settings()` will."""
    from codex_harness.adapters.configuration import aliases, read_env

    try:
        config = {**aliases(read_env(Path(target["source"]))), **aliases(dict(environment))}
    except (OSError, ValueError) as exc:
        raise DeliveryRefused("runtime_settings_unreadable", "source") from exc
    return effective_worker_image(config)


# ----- the managed host target ------------------------------------------------------------------
class ManagedFleetTarget(ProcessHostTarget):
    """A Fleet runner in a sealed runtime, owned through the trusted launcher. Nothing is killed."""

    kind = KIND_MANAGED

    def __init__(self, *, workload: str = WORKLOAD_FLEET, heartbeat_max_age: float = HEARTBEAT_MAX_AGE,
                 stop_timeout: float = STOP_TIMEOUT, fleet=None, **kwargs):
        super().__init__(**kwargs)
        if workload not in WORKLOADS:
            raise ValueError("unknown managed workload")
        self.workload, self.heartbeat_max_age = workload, heartbeat_max_age
        self.stop_timeout = stop_timeout
        # The Fleet authority of the activation gate: `application.fleet.Fleet` over the host store
        # in production (`host_ports(fleet=...)`), a labelled in-memory Fleet for the fixture
        # workload. None is never "no debt": every start then refuses `fleet_authority_unconfigured`.
        self.fleet = fleet

    # --- the sealed runtime ---------------------------------------------------------------------
    def materialize(self, target: dict, descriptor: dict, *, authorize=None) -> dict:
        """Seal (or revalidate) the descriptor's runtime. Ownership is proven before any write."""
        if authorize is not None:
            authorize()
        return Materializer(target).materialize(descriptor)

    def verify(self, target: dict, descriptor: dict) -> dict:
        return Materializer(target).verify(descriptor)

    def _prepare(self, target: dict, descriptor: dict) -> dict:
        """Every refusal a launch could meet, BEFORE anything on the target is stopped."""
        manifest = self.verify(target, descriptor)
        if not Path(target["python"]).is_file():
            raise DeliveryRefused("runtime_interpreter_unavailable", "python")
        environment = runtime_environment(target, descriptor)
        if runtime_image(target, environment) != descriptor["worker_image"]:
            raise DeliveryRefused("runtime_image_mismatch", "worker_image")
        return {"root": Path(descriptor["root"]), "environment": environment, "manifest": manifest}

    def _launch(self, target: dict, descriptor: dict, context: dict) -> dict:
        """Exactly one trusted launcher, and the launch record that identifies it, under the guard."""
        _write_json(self.path(target, TARGET_FILE), owner_target(target))
        argv = [target["python"], "-m", MODULE, "launch", "--state-dir", str(self.state_dir(target)),
                "--descriptor-sha256", descriptor_digest(descriptor), "--workload", self.workload]
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, cwd=str(self.state_dir(target)),
                                   env=launcher_environment(),
                                   **no_console_kwargs(process_group=True))
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

    def __init__(self, *, runner=run_process, timeout: int = 60, **kwargs):
        super().__init__(**kwargs)
        self.runner, self.timeout = runner, timeout

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
        _write_json(self.path(target, TARGET_FILE), owner_target(target))
        request = validate_launch_request({
            "schema": LAUNCH_REQUEST_SCHEMA, "target_id": target["target_id"],
            "descriptor_sha256": descriptor_digest(descriptor),
            "manifest_sha256": manifest_digest(context["manifest"]), "workload": self.workload,
            "requested_at": _utcnow()})
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


def fleet_gate(target_id: str, descriptor_sha256: str) -> dict:
    """The production debt authority of `supervise`: the host store's actual Fleet."""
    from codex_harness.application.fleet import Fleet
    from codex_harness.bootstrap import build

    return Fleet(build().store).activation_gate(target_id, descriptor_sha256)


def _journal(root: Path, event: str, **facts) -> None:
    """One flushed JSON line of what `supervise` decided: codes and ids, never paths or values."""
    line = json.dumps({"event": event, "at": _utcnow(), "invocation_id": os.environ.get("INVOCATION_ID"),
                       **facts}, sort_keys=True)
    with open(root / SUPERVISOR_JOURNAL, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def supervise(state_dir: str, *, gate=fleet_gate, launcher=None) -> int:
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
    return (launcher or launch)(str(root), request["descriptor_sha256"], request["workload"])


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


def run_fleet(control: RuntimeControl) -> dict:
    """The REAL existing Fleet CLI runner, with the host store and lanes of this host's own
    configuration, and the managed control added. This is what the owner's actual cutover runs."""
    from codex_harness.adapters import fleet_cli
    from codex_harness.bootstrap import build

    return fleet_cli.run(build(), argparse.Namespace(once=False), control=control)


class FixtureLauncher:
    """Labelled controlled Fleet workload launcher: each job is a REAL child process that waits for
    its release marker. No `zeus operate run`, model, provider, ledger or network is involved."""

    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def budget_exhausted(budget: dict) -> bool:
        return False

    def launch(self, job: dict) -> dict:
        marker = self.root / ("release-" + job["id"])
        process = subprocess.Popen([sys.executable, "-c", _FIXTURE_CHILD, str(marker)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **no_console_kwargs())
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
    from codex_harness.adapters.providers import packaged_policy
    from codex_harness.domain.operation import validate_manifest

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
    from codex_harness.adapters.store import MemoryStore
    from codex_harness.application.fleet import Fleet, FleetRunner

    root = state_dir / FIXTURE_DIR
    root.mkdir(parents=True, exist_ok=True)
    fleet = Fleet(MemoryStore())
    fleet.register(fixture_config(root))
    goal = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "fixture",
            "base_revision": "a" * 40, "bytes": 7}
    jobs = _read_json(state_dir / FIXTURE_JOBS_FILE)
    for job_id in jobs if isinstance(jobs, list) else []:
        fleet.enqueue("fixture", fixture_manifest(str(job_id)), goal, [])
    runner = FleetRunner(fleet, FixtureLauncher(root), interval=FIXTURE_INTERVAL, control=control)
    return runner.run(once=False)


def entry(state_dir: str, workload: str) -> int:
    """Runs inside the sealed runtime: report the identity actually loaded, then run the workload."""
    root = Path(state_dir)
    try:
        descriptor = validate_descriptor(_read_json(root / DESCRIPTOR_FILE))
    except DeliveryRefused:
        return EXIT_REFUSED
    if workload not in WORKLOADS:
        return EXIT_REFUSED
    receipt = startup_receipt(descriptor)
    _write_json(root / RECEIPT_FILE, receipt)
    control = RuntimeControl(root, receipt)
    if workload == WORKLOAD_FIXTURE:
        run_fixture(root, control)
    else:
        run_fleet(control)
    return 0


# ----- the fixed trusted launcher --------------------------------------------------------------------
def launch(state_dir: str, descriptor_sha256: str, workload: str) -> int:
    """Re-verify the sealed runtime against the descriptor this launch was for, then own its child.

    Nothing from the runtime is imported here. A target snapshot, a descriptor or a sealed directory
    that does not verify starts nothing and exits `2`; the controller then sees no startup receipt.
    """
    from codex_harness.adapters.background_service import run_owned

    root = Path(state_dir)
    try:
        target = validate_targets({"schema": REGISTRY_SCHEMA,
                                   "targets": [_read_json(root / TARGET_FILE)]})["targets"][0]
        descriptor = validate_descriptor(_read_json(root / DESCRIPTOR_FILE))
        if target["kind"] not in MANAGED_KINDS or not same_path(target["state_dir"], root) \
                or descriptor_digest(descriptor) != descriptor_sha256 or workload not in WORKLOADS:
            return EXIT_REFUSED
        Materializer(target).verify(descriptor)
    except (DeliveryRefused, EnvironmentUnqualified):
        return EXIT_REFUSED
    argv = [target["python"], "-m", MODULE, "entry", "--state-dir", str(root), "--workload", workload]
    return run_owned(argv, cwd=descriptor["root"], env=runtime_environment(target, descriptor),
                     journal=root / LAUNCHER_JOURNAL)


def main(argv=None) -> int:
    """`python -m codex_harness.adapters.managed_runtime launch|entry|supervise --state-dir DIR ...`.

    Only the managed target itself (or, for `supervise`, its owner-fixed unit) starts these; every owner
    command goes through `zeus host-delivery`.
    """
    parser = argparse.ArgumentParser(prog=MODULE)
    sub = parser.add_subparsers(dest="command", required=True)
    launcher = sub.add_parser("launch")
    launcher.add_argument("--state-dir", required=True, dest="state_dir")
    launcher.add_argument("--descriptor-sha256", required=True, dest="descriptor_sha256")
    launcher.add_argument("--workload", required=True, choices=list(WORKLOADS))
    child = sub.add_parser("entry")
    child.add_argument("--state-dir", required=True, dest="state_dir")
    child.add_argument("--workload", required=True, choices=list(WORKLOADS))
    supervised = sub.add_parser("supervise")
    supervised.add_argument("--state-dir", required=True, dest="state_dir")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command == "launch":
        return launch(args.state_dir, args.descriptor_sha256, args.workload)
    if args.command == "supervise":
        return supervise(args.state_dir)
    return entry(args.state_dir, args.workload)


__all__ = ["FIXTURE_JOBS_FILE", "LAUNCHER_JOURNAL", "LAUNCH_REQUEST_FILE", "LAUNCH_REQUEST_SCHEMA", "MODULE",
           "SUPERVISOR_JOURNAL", "TARGET_FILE", "FixtureLauncher", "ManagedFleetTarget", "Materializer",
           "RuntimeControl", "SystemdManagedFleetTarget", "entry", "fixture_config", "fleet_gate", "gate_refusal",
           "launch", "launcher_environment", "main", "owner_target", "run_fixture", "run_fleet",
           "runtime_environment", "runtime_image", "scan", "supervise", "validate_launch_request"]


if __name__ == "__main__":
    sys.exit(main())
