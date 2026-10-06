"""Evidence ports of active-generation maintenance (INV-HOST-DELIVERY-MAINTENANCE-001).

The use case (`application.host_delivery.HostDelivery.maintain`) decides; this module only reads,
and each port refuses with one fixed code and one allowlisted field, never a value:

* `CredentialObserver` - the safe PRIMARY-selection booleans of the NEW generation's supervisor and
  entry, bound to their process identity. It runs the owner's accepted credential observation helper
  (DN-2) by an owner-configured absolute path pinned by sha256, under this interpreter with `-B`, a
  fixed two-variable environment, `/` as its directory and no stdin, and parses boolean-only output.
  The helper's bytes are verified before and after each run, and each pid's start ticks before and
  after, so a replaced helper or a reused pid refuses. Nothing it reads - no token, digest, path or
  environment - is kept: only pids, start ticks, the helper's pinned digest and the booleans.
* `trusted_authority_reader` - the bytes of the recorded user directive a maintenance document names
  (`authority`), from the control runtime's content-addressed artifact store (DN-1), read without
  following a final link and verified by sha256. It never creates a directory.
* `LazyArtifacts` - the same `FileArtifacts` store, constructed only on the first `put`, so a read-only
  path (every `--check`) creates nothing.
* `control_action_reader` - one read of the control store's owner-action row
  (INV-OWNER-ACTIONS-001); nothing is written.
* `LazyCanaryExecutor` - the one-job maintenance canary executor of INV-FLEET-001's narrow amendment,
  built over the real lane launcher only when `arm` actually dispatches.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from codex_harness.adapters.host_migration_evidence import (
    HostReader,
    Unreadable,
    boottime_offset_usec,
)
from codex_harness.application.owner_actions import BUCKET_ACTIONS
from codex_harness.domain.host_delivery import DeliveryRefused

# The record the domain validator binds to the observation (`validate_credential_evidence`).
CREDENTIAL_EVIDENCE_SCHEMA = "urn:zeus:maintenance-credential-evidence:1"
HELPER_SETTING = "ZEUS_MAINTENANCE_CREDENTIAL_HELPER"
HELPER_SHA256_SETTING = "ZEUS_MAINTENANCE_CREDENTIAL_HELPER_SHA256"
QUALIFICATION_DEADLINE_SETTING = "ZEUS_MAINTENANCE_QUALIFICATION_DEADLINE"
# Nothing of this process's environment reaches the helper: no connection string, no credential.
HELPER_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
HELPER_OUTPUT_FIELDS = frozenset({"pid", "has_token", "is_primary", "is_secondary"})
HELPER_OUTPUT_LIMIT = 4096
HELPER_MAX_BYTES = 1024 * 1024
HELPER_TIMEOUT = 30
AUTHORITY_MAX_BYTES = 262144
EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _primary_unverified(field: str) -> DeliveryRefused:
    return DeliveryRefused("maintenance_primary_unverified", field)


def _pid(value) -> bool:
    return type(value) is int and 0 < value < 2 ** 31


def run_helper(argv: list, *, timeout: float, env: dict, limit: int, cwd: str = "/") -> subprocess.CompletedProcess:
    """Run the helper once: exactly `env`, `cwd`, no stdin, its own session. Its stdout is read up to
    `limit` bytes within `timeout`; more, or the deadline, ends its session and is `Unreadable`. Its
    stderr is discarded unread, so no diagnostic text of the helper can reach a record or a log."""
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env, cwd=cwd, close_fds=True, start_new_session=True)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Unreadable("helper_timeout")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output += chunk
                    if len(output) > limit:
                        raise Unreadable("helper_output")
        returncode = process.wait(max(0.0, deadline - time.monotonic()))
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait()
        raise
    finally:
        process.stdout.close()
    return subprocess.CompletedProcess(argv, returncode, bytes(output), b"")


class CredentialObserver:
    """`(target, identity) -> record`: the credential-selection booleans of the new generation.

    `identity` is `{"supervisor_pid", "entry_pid", "invocation_id"}` from the coordinator's fresh
    observation; the record is validated and bound to that observation by the domain
    (`validate_credential_evidence`). Every defect raises `maintenance_primary_unverified` naming
    `helper` (not the pinned helper, not runnable, nonzero exit), `helper_output` (anything but the
    exact boolean document for the requested pid) or `identity` (a pid that is not present, or whose
    start changed while it was observed). There is no fallback and no retry.
    """

    def __init__(self, helper: str, helper_sha256: str, *, python: str = sys.executable, runner=None,
                 process_reader=None, timeout: float = HELPER_TIMEOUT):
        self.helper, self.helper_sha256 = str(helper), helper_sha256
        self.python, self.runner, self.timeout = python, runner or run_helper, timeout
        self.process_reader = process_reader

    def _read_process(self, pid: int):
        if self.process_reader is None:
            reader = HostReader()
            self.process_reader = lambda value: reader.process(value, boottime_offset_usec())
        return self.process_reader(pid)

    def _start_ticks(self, pid: int) -> int:
        try:
            process = self._read_process(pid)
        except Exception as exc:
            raise _primary_unverified("identity") from exc
        if not (isinstance(process, dict) and process.get("state") == "present" and process.get("pid") == pid
                and type(process.get("start_ticks")) is int):
            raise _primary_unverified("identity")
        return process["start_ticks"]

    def _verify_helper(self) -> None:
        """The helper file is, right now, exactly the pinned bytes (read without following a link)."""
        try:
            data = HostReader.file(self.helper, HELPER_MAX_BYTES)
        except Exception as exc:
            raise _primary_unverified("helper") from exc
        if not data or hashlib.sha256(data).hexdigest() != self.helper_sha256:
            raise _primary_unverified("helper")

    def _booleans(self, pid: int) -> dict:
        """One helper run for one pid: its exact boolean document, or a refusal."""
        self._verify_helper()
        try:
            result = self.runner([self.python, "-B", self.helper, "process", str(pid)], timeout=self.timeout,
                                 env=dict(HELPER_ENV), limit=HELPER_OUTPUT_LIMIT, cwd="/")
        except Unreadable as exc:
            raise _primary_unverified("helper_output") from exc
        except Exception as exc:
            raise _primary_unverified("helper") from exc
        self._verify_helper()
        if result.returncode != 0:
            raise _primary_unverified("helper")
        stdout = result.stdout if isinstance(result.stdout, bytes) else str(result.stdout or "").encode("utf-8")
        if len(stdout) > HELPER_OUTPUT_LIMIT:
            raise _primary_unverified("helper_output")
        try:
            document = json.loads(stdout.decode("utf-8"))
        except ValueError as exc:
            raise _primary_unverified("helper_output") from exc
        if not (isinstance(document, dict) and set(document) == HELPER_OUTPUT_FIELDS
                and type(document["pid"]) is int and document["pid"] == pid
                and all(type(document[key]) is bool for key in ("has_token", "is_primary", "is_secondary"))):
            raise _primary_unverified("helper_output")
        return {key: document[key] for key in ("has_token", "is_primary", "is_secondary")}

    def _observe(self, pid: int) -> dict:
        before = self._start_ticks(pid)
        booleans = self._booleans(pid)
        if self._start_ticks(pid) != before:
            # The pid changed hands while it was observed: these booleans belong to nobody.
            raise _primary_unverified("identity")
        return {"pid": pid, "start_ticks": before, **booleans}

    def __call__(self, target: dict, identity: dict) -> dict:
        if not (isinstance(identity, dict) and set(identity) == {"supervisor_pid", "entry_pid", "invocation_id"}
                and _pid(identity["supervisor_pid"]) and _pid(identity["entry_pid"])
                and identity["supervisor_pid"] != identity["entry_pid"]
                and type(identity["invocation_id"]) is str and HEX32.fullmatch(identity["invocation_id"])):
            raise _primary_unverified("identity")
        supervisor = self._observe(identity["supervisor_pid"])
        entry = self._observe(identity["entry_pid"])
        return {"schema": CREDENTIAL_EVIDENCE_SCHEMA, "observed_at": _utcnow(),
                "invocation_id": identity["invocation_id"], "helper_sha256": self.helper_sha256,
                "supervisor": supervisor, "entry": entry}


def credential_observer(settings: dict) -> CredentialObserver | None:
    """The owner-configured helper (an absolute path) and its pinned sha256, or None when either is
    absent or malformed - which the use case refuses as `maintenance_primary_unverified`."""
    settings = settings or {}
    helper, pinned = settings.get(HELPER_SETTING), settings.get(HELPER_SHA256_SETTING)
    if not (type(helper) is str and helper and type(pinned) is str and HEX64.fullmatch(pinned)):
        return None
    path = Path(helper)
    if not path.is_absolute() or ".." in path.parts:
        return None
    return CredentialObserver(str(path), pinned)


def trusted_authority_reader(root: Path):
    """`(ref) -> bytes` over the content-addressed artifact store at `root` (`<hex>.txt`), read only.

    The ref must be `sha256:<64 hex>`; the file must be a regular file (a final link is not followed) of
    1..`AUTHORITY_MAX_BYTES` bytes whose sha256 is exactly that hex. Anything else refuses
    `maintenance_authority_unverified` naming `authority`. Nothing is created, and the bytes are only
    returned to the caller, which verifies and never stores or prints them."""
    root = Path(root)

    def read(ref) -> bytes:
        if not (type(ref) is str and EVIDENCE_REF.fullmatch(ref)):
            raise DeliveryRefused("maintenance_authority_unverified", "authority")
        key = ref.partition(":")[2]
        try:
            data = HostReader.file(root / (key + ".txt"), AUTHORITY_MAX_BYTES)
        except Exception as exc:
            raise DeliveryRefused("maintenance_authority_unverified", "authority") from exc
        if not data or hashlib.sha256(data).hexdigest() != key:
            raise DeliveryRefused("maintenance_authority_unverified", "authority")
        return data

    return read


class LazyArtifacts:
    """`FileArtifacts` at `root`, constructed (and its directory created) on the first `put` only."""

    def __init__(self, root):
        self.root, self._store = Path(root), None

    def put(self, body: str, source: str) -> dict:
        if self._store is None:
            from codex_harness.adapters.artifacts import FileArtifacts

            self._store = FileArtifacts(str(self.root))
        return self._store.put(body, source)


def control_action_reader(store):
    """`(action_id) -> row | None`: one read transaction of the control store's owner-action row."""

    def read(action_id):
        if not (type(action_id) is str and HEX64.fullmatch(action_id)):
            return None
        with store.transaction() as tx:
            return tx.get(BUCKET_ACTIONS, action_id)

    return read


class LazyCanaryExecutor:
    """The one-job maintenance canary executor (INV-FLEET-001 narrow amendment) over the real lane launcher.

    It is built on the first `execute`, which only `arm`'s dispatch attempt calls: restart and bind read
    no Fleet registry for it, and `--check` never receives one."""

    def __init__(self, fleet, settings: dict):
        self.fleet, self.settings, self._executor = fleet, settings, None

    def execute(self, maintenance_id: str, *, permit_sha256: str, proof: dict, max_wait_seconds: float) -> dict:
        if self._executor is None:
            from codex_harness.adapters.fleet_runtime import LaneLauncher
            from codex_harness.application.fleet import MaintenanceCanaryExecutor

            launcher = LaneLauncher(self.fleet.registered()["config"], self.settings)
            self._executor = MaintenanceCanaryExecutor(self.fleet, launcher)
        return self._executor.execute(maintenance_id, permit_sha256=permit_sha256, proof=proof,
                                      max_wait_seconds=max_wait_seconds)


def qualification_deadline(settings: dict) -> str | None:
    """The owner's qualification deadline (`ZEUS_MAINTENANCE_QUALIFICATION_DEADLINE`), an aware ISO time,
    or None when unset. A set but malformed value refuses rather than silently lifting the bound."""
    value = (settings or {}).get(QUALIFICATION_DEADLINE_SETTING)
    if value is None or (type(value) is str and not value.strip()):
        return None
    try:
        moment = datetime.fromisoformat(value.strip()) if type(value) is str and len(value) <= 64 else None
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise DeliveryRefused("maintenance_invalid", "qualification_deadline")
    return value.strip()


__all__ = ["AUTHORITY_MAX_BYTES", "CREDENTIAL_EVIDENCE_SCHEMA", "HELPER_ENV", "HELPER_SETTING",
           "HELPER_SHA256_SETTING", "QUALIFICATION_DEADLINE_SETTING", "CredentialObserver", "LazyArtifacts",
           "LazyCanaryExecutor", "control_action_reader", "credential_observer", "qualification_deadline",
           "run_helper", "trusted_authority_reader"]
