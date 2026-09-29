"""The one owner of the dedicated Codex product credential store (D3 v3): store, lock, ledger, write-back.

Layer: adapters
Context: credentials
Owns: `read_credential_file` (a credential file as untrusted input), `CodexCredentialBroker` (the
    credential-only store holding exactly `auth.json`; the exclusive lock, quarantine marker and ledger of
    issued per-run copies as siblings of the store; admission; reconcile of prior runs after broker
    death; validated credential-only write-back), `Admission` (one admitted user: the per-run 0600 copy
    in a fresh 0700 home and its durable ledger entry), `discard_tree` (a per-run directory this broker
    created)
Does not own: the container, its argv or run record (execution.adapters.containers); the output boundary
    (credentials.adapters.scrubber); the shape rules (credentials.domain.codex_credential)
Entry points: CodexCredentialBroker, Admission (issue, bind_dependent, settle, release), read_credential_file,
    discard_tree
Contracts: INV-CODEX-CREDENTIAL-001

Moved from SOURCE M7 `adapters/role_containers` (the broker half). Behaviour is the M7 behaviour,
characterized first by the `credentials.custody` golden (I1 (f)4, RC2-F3 3/4/5). RESEARCH-S3 R4 (single-use
refresh tokens, upstream case at Codex CLI 0.156.0): at most one holder of a per-run copy may exist at
a time, and an unsettled or unknown prior run blocks admission instead of being logged; G4: the write-back
accepts the per-run file only as a regular single-link 0600 file of the store's exact shape and
identity while the store is unchanged since issue, and anything else quarantines the store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.credentials.domain.codex_credential import (
    MAX_AUTH_BYTES,
    SETTLED_RUN_STATES,
    credential_shape,
)
from codex_harness.kernel.errors import IsolationError, require


def discard_tree(path) -> None:
    """Remove a per-run directory this broker created, including read-only copies it made."""
    path = Path(path)
    if not path.exists():
        return
    for directory, _, _ in os.walk(path):
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)


def read_credential_file(path) -> bytes:
    """A credential file as untrusted input: a single-link regular 0600 file within bounds, opened
    without following a link. Refusals name the check, never the content."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise IsolationError("credential_file_missing", type(exc).__name__) from exc
    if not stat.S_ISREG(info.st_mode):
        raise IsolationError("credential_file_not_regular")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise IsolationError("credential_file_mode", oct(stat.S_IMODE(info.st_mode)))
    if info.st_nlink != 1:
        raise IsolationError("credential_file_linked")
    if info.st_size > MAX_AUTH_BYTES:
        raise IsolationError("credential_file_too_large")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (opened.st_ino, opened.st_dev) != (info.st_ino, info.st_dev):
            raise IsolationError("credential_file_replaced")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_AUTH_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_AUTH_BYTES:
        raise IsolationError("credential_file_too_large")
    return data


def _fsync_directory(path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, body: dict) -> None:
    data = json.dumps(body, sort_keys=True, indent=1).encode("utf-8")
    temporary = path.with_name("." + path.name + "." + uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


class CodexCredentialBroker:
    """The one owner of the dedicated Codex product credential store (INV-CODEX-CREDENTIAL-001).

    Siblings of the store directory (never inside it) hold the lock, the quarantine marker and the
    ledger of issued per-run copies, so every broker root sharing a store shares one serialization.
    `clock` stamps the ledger and marker (wall-clock seconds); it is never part of a decision."""

    def __init__(self, store, *, clock=time.time):
        self.store = Path(store)
        require(self.store.is_absolute(), "The Codex credential store must be an absolute path")
        self.auth = self.store / "auth.json"
        self.lock_path = self.store.parent / (self.store.name + ".lock")
        self.quarantine_path = self.store.parent / (self.store.name + ".quarantine")
        self.ledger = self.store.parent / (self.store.name + ".ledger")
        self.clock = clock

    # -- the store ----------------------------------------------------------------------------
    def read_store(self) -> tuple:
        try:
            info = os.lstat(self.store)
        except OSError as exc:
            raise IsolationError("codex_credential_store_missing") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise IsolationError("codex_credential_store_invalid", "the store must be a private directory (0700)")
        if sorted(os.listdir(self.store)) != ["auth.json"]:
            raise IsolationError("codex_credential_store_invalid", "the store must hold exactly auth.json")
        data = read_credential_file(self.auth)
        return data, credential_shape(data)

    def quarantined(self) -> dict | None:
        if not self.quarantine_path.exists():
            return None
        try:
            return json.loads(self.quarantine_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {"reason": "unreadable_marker"}

    def _quarantine(self, entry: dict, reason: str) -> None:
        """Hold: the store is left exactly as it is and no further admission happens until the owner
        reviews and removes the marker. The marker names the run and the reason, never a value."""
        _write_json_atomic(self.quarantine_path, {"reason": reason, "run_id": entry.get("run_id"),
                                                  "record": entry.get("record"), "at": self.clock()})
        entry.update(state="quarantined", reason=reason, settled_at=self.clock())
        self._write_entry(entry)

    # -- the ledger ---------------------------------------------------------------------------
    def _entry_path(self, run_id: str) -> Path:
        require(re.fullmatch(r"[0-9a-f]{32}", run_id) is not None, "Invalid run id")
        return self.ledger / (run_id + ".json")

    def _write_entry(self, entry: dict) -> None:
        self.ledger.mkdir(mode=0o700, exist_ok=True)
        _write_json_atomic(self._entry_path(entry["run_id"]), entry)

    def entries(self) -> list:
        rows = []
        for path in sorted(self.ledger.glob("*.json")) if self.ledger.is_dir() else []:
            try:
                rows.append(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError) as exc:
                raise IsolationError("codex_credential_ledger_unreadable", path.name) from exc
        return rows

    # -- admission ----------------------------------------------------------------------------
    def admit(self, *, wait_seconds: float, on_tick=None) -> Admission:
        """The exclusive lock (bounded wait), then no quarantine, then every earlier issued copy
        settled, then a valid store. Any refusal releases the lock and names its reason."""
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - the runtime target is Linux only
            raise IsolationError("codex_credential_lock_unsupported") from exc
        try:
            # Never creates the secrets directory itself; the lock is a regular file, never a link.
            descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError as exc:
            raise IsolationError("codex_credential_store_missing", type(exc).__name__) from exc
        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        try:
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise IsolationError("codex_credential_busy") from None
                    if on_tick is not None:
                        on_tick()
                    time.sleep(0.2)
            marker = self.quarantined()
            if marker is not None:
                raise IsolationError("codex_credential_quarantined", str(marker.get("reason")))
            self.reconcile()
            data, shape = self.read_store()
        except BaseException:
            os.close(descriptor)  # closing the descriptor releases the flock
            raise
        return Admission(self, descriptor, data, shape)

    def reconcile(self) -> list:
        """Settle every issued copy whose run is resolved (its container proven gone); refuse while any
        prior run is unsettled or unknown. Called only under the lock (RC2-F3 5)."""
        settled = []
        for entry in self.entries():
            if entry.get("state") != "issued":
                continue
            try:
                record = json.loads(Path(entry["record"]).read_text("utf-8"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise IsolationError("codex_credential_prior_run_unknown", str(entry.get("run_id"))) from exc
            if record.get("state") not in SETTLED_RUN_STATES:
                raise IsolationError("codex_credential_prior_run_unsettled",
                                     json.dumps({"run_id": entry["run_id"], "state": record.get("state"),
                                                 "record": entry["record"]}, sort_keys=True))
            pending = self._unsettled_dependents(entry)
            if pending:
                # S3b (fix F1): a dependent container of the run (hook discovery) may still hold this copy.
                raise IsolationError("codex_credential_prior_run_unsettled",
                                     json.dumps({"run_id": entry["run_id"], "state": record.get("state"),
                                                 "record": entry["record"], "dependents": pending}, sort_keys=True))
            settled.append(self.settle(entry))
            discard_tree(entry["home"])  # the settled copy's home: its task state never flows anywhere
        return settled

    def _unsettled_dependents(self, entry: dict) -> list:
        """The dependent run records bound to this copy (`Admission.bind_dependent`) that do not prove their
        container gone; an unreadable or missing record is unknown, never settled."""
        pending = []
        for path in entry.get("dependents") or []:
            try:
                state = json.loads(Path(path).read_text("utf-8")).get("state")
            except (OSError, ValueError, AttributeError):
                state = "unknown"
            if state not in SETTLED_RUN_STATES:
                pending.append({"record": str(path), "state": state})
        return pending

    def settle(self, entry: dict) -> dict:
        """Credential-only write-back of one stopped run's per-run copy. Unchanged: nothing is written.
        Changed and valid: atomic replacement. Anything else: quarantine (raised as a refusal). A copy with
        an unsettled dependent container is not settled at all (a refusal; the entry stays issued)."""
        pending = self._unsettled_dependents(entry)
        if pending:
            raise IsolationError("codex_credential_dependent_unsettled",
                                 json.dumps({"run_id": entry["run_id"], "dependents": pending}, sort_keys=True))
        home = Path(entry["home"])
        try:
            data = read_credential_file(home / "auth.json")
        except IsolationError as exc:
            self._quarantine(entry, "per_run_" + exc.reason_code)
            raise IsolationError("codex_credential_quarantined", "per_run_" + exc.reason_code) from exc
        state = "unchanged"
        if hashlib.sha256(data).hexdigest() != entry["issued_sha256"]:
            try:
                shape = credential_shape(data)
            except IsolationError as exc:
                self._quarantine(entry, "refreshed_" + exc.reason_code)
                raise IsolationError("codex_credential_quarantined", "refreshed_" + exc.reason_code) from exc
            if shape != {key: entry["shape"][key] for key in ("keys", "token_keys", "account_id", "auth_mode")}:
                reason = ("identity_changed" if shape["account_id"] != entry["shape"]["account_id"]
                          else "structure_changed")
                self._quarantine(entry, reason)
                raise IsolationError("codex_credential_quarantined", reason)
            try:
                current, _ = self.read_store()
            except IsolationError as exc:
                self._quarantine(entry, "store_" + exc.reason_code)
                raise IsolationError("codex_credential_quarantined", "store_" + exc.reason_code) from exc
            if hashlib.sha256(current).hexdigest() != entry["store_sha256"]:
                self._quarantine(entry, "store_changed_during_run")
                raise IsolationError("codex_credential_quarantined", "store_changed_during_run")
            self._replace(data)
            state = "written_back"
        entry.update(state=state, settled_at=self.clock())
        self._write_entry(entry)
        return {"run_id": entry["run_id"], "state": state}

    def _replace(self, data: bytes) -> None:
        """Temp file in the store, fsync, rename over auth.json, directory fsync."""
        temporary = self.store / (".auth.json." + uuid4().hex + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, self.auth)
        _fsync_directory(self.store)


class Admission:
    """One admitted Codex credential user; the lock is held until `release`."""

    def __init__(self, broker: CodexCredentialBroker, descriptor: int, data: bytes, shape: dict):
        self.broker, self.descriptor, self.data, self.shape = broker, descriptor, data, shape
        self.entry = None

    def issue(self, run_id: str, record_path, home: Path) -> dict:
        """The per-run copy (0600, in a fresh 0700 home) and its ledger entry, durable before any
        container can exist."""
        home = Path(home)
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(home, 0o700)
        target = home / "auth.json"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(descriptor, self.data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        sha = hashlib.sha256(self.data).hexdigest()
        self.entry = {"run_id": run_id, "record": str(record_path), "home": str(home), "issued_sha256": sha,
                      "store_sha256": sha, "shape": dict(self.shape), "state": "issued",
                      "issued_at": self.broker.clock()}
        self.broker._write_entry(self.entry)
        return {"account_sha256": hashlib.sha256(self.shape["account_id"].encode("utf-8")).hexdigest(),
                "issued": True}

    def bind_dependent(self, record_path) -> None:
        """Durably bind another container's run record to this issued copy BEFORE that container can exist
        (S3b hook discovery shares the copy): settlement and reconcile then wait until that record proves
        its container gone (fix F1)."""
        require(self.entry is not None and self.entry.get("state") == "issued", "Nothing issued to bind a dependent to")
        self.entry.setdefault("dependents", []).append(str(record_path))
        self.broker._write_entry(self.entry)

    def settle(self) -> dict:
        require(self.entry is not None, "Nothing was issued")
        return self.broker.settle(self.entry)

    def release(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None
