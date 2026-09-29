"""INV-ROLE-CONTAINER-001 / INV-CODEX-CREDENTIAL-001: fixed, host-brokered role containers.

The host isolated-worker launcher is the one broker for every product model invocation once isolation
is selected. The existing routing result `(provider, action, read_only)` maps to exactly one fixed
profile; any other shape, or a profile this host has not enabled, refuses before anything is spawned,
and there is never a host fallback:

    (claude, implement, rw) -> claude-impl-rw   the existing writable Claude worker, unchanged
    (codex,  implement, rw) -> codex-impl-rw    same task-scoped staging/evidence policy, Codex credential
    (claude, *,         ro) -> claude-role-ro   review checkout read-only, own result dir writable
    (codex,  *,         ro) -> codex-role-ro    review checkout read-only, own result dir writable

Every profile reuses the existing hardening, ownership and cleanup (`container_args`, `OwnedContainer`,
`hold`, `retire`, `run.json`); agents never choose a docker argv and role names grant nothing.

Codex credentials (D3 v3). A configured store directory holds exactly one file, the dedicated login's
`auth.json`. Each Codex run gets a fresh per-run CODEX_HOME holding a 0600 copy of it and the broker's
pinned `config.toml`, digest-checked and bind-mounted read-only; every other file the CLI creates is
task state, discarded (or kept for the SAME task and writable profile only, never for a reviewer). An
exclusive flock covers the whole run; admission also requires the ledger to show no unsettled prior
run whose container is not proven gone. After the container is confirmed stopped, the per-run
`auth.json` alone may flow back: validated as untrusted input (regular 0600 file, bounded, the store's
exact shape, the same account identity, the store itself unchanged since issue) and atomically
replaced. Any anomaly quarantines the store: no write-back, no next admission, no retry and never the
operator's `~/.codex`.

Pinned-CLI mechanism (I1 step 1, codex-cli 0.156.1, dummy auth, network none): with
`cli_auth_credentials_store = "file"` the CLI reads `$CODEX_HOME/auth.json` (keyring mode ignores the
same file); its file-store writer rewrites `auth.json` IN PLACE (open/modify/close_write, same inode,
mode 0600, no temporary file or rename); logout unlinks it; the App Server creates sqlite state,
`installation_id`, `skills/`, `tmp/arg0` links and `log/` under CODEX_HOME. The per-run home is a
writable directory because of that CLI state. A real token refresh was not exercised (it needs the
provider), so refresh persistence is verified only by the first authorized run, with a hold on any
anomaly; an in-place write interrupted mid-way is caught here as an unparseable file.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters import isolated_worker as iw
from codex_harness.adapters.app_server import AppServer
from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.domain.model import ContractError, canonical, digest, require

IsolationError = iw.IsolationError

# ---- profiles -----------------------------------------------------------------------------------
CLAUDE_IMPL_RW, CLAUDE_ROLE_RO = "claude-impl-rw", "claude-role-ro"
CODEX_ROLE_RO, CODEX_IMPL_RW = "codex-role-ro", "codex-impl-rw"
RESULT = "/result"
PROFILES = {
    CLAUDE_IMPL_RW: {"provider": "claude", "transport": "claude_cli", "read_only": False, "workspace": "staging_rw",
                     "writable": (iw.WORKSPACE, iw.EVIDENCE), "credential": "CLAUDE_CODE_OAUTH_TOKEN by name"},
    CLAUDE_ROLE_RO: {"provider": "claude", "transport": "claude_cli", "read_only": True, "workspace": "checkout_ro",
                     "writable": (iw.EVIDENCE,), "credential": "CLAUDE_CODE_OAUTH_TOKEN by name"},
    CODEX_ROLE_RO: {"provider": "codex", "transport": "app_server", "read_only": True, "workspace": "checkout_ro",
                    "writable": (RESULT, "/codex-home"), "credential": "per-run CODEX_HOME copy of the store auth.json"},
    CODEX_IMPL_RW: {"provider": "codex", "transport": "app_server", "read_only": False, "workspace": "staging_rw",
                    "writable": (iw.WORKSPACE, iw.EVIDENCE, "/codex-home"),
                    "credential": "per-run CODEX_HOME copy of the store auth.json"},
}
# The profiles whose prompts name container paths for the artifact reader (the existing worker is unchanged).
ROLE_PROFILES = (CLAUDE_ROLE_RO, CODEX_ROLE_RO, CODEX_IMPL_RW)
# The writers whose settled evidence is handed off to the content-addressed store (D4).
WRITABLE_PROFILES = (CLAUDE_IMPL_RW, CODEX_IMPL_RW)


def select_profile(provider, transport, action, read_only, *, codex_enabled: bool) -> str:
    """The one mapping from the routing result to a profile; everything else refuses before spawn."""
    if type(read_only) is bool:
        if provider == "claude" and transport == "claude_cli":
            if read_only:
                return CLAUDE_ROLE_RO
            if action == "implement":
                return CLAUDE_IMPL_RW
        elif provider == "codex" and transport == "app_server":
            if not codex_enabled:
                raise IsolationError("codex_profile_disabled",
                                     "isolation is selected and no Codex credential store is configured; "
                                     "the host App Server is never the fallback")
            if read_only:
                return CODEX_ROLE_RO
            if action == "implement":
                return CODEX_IMPL_RW
    raise IsolationError("role_profile_refused", f"{provider}/{transport}/{action}/{'ro' if read_only else 'rw'}")


# ---- the pinned Codex CLI and its broker-generated configuration ----------------------------------
CODEX_CLI_VERSION = "0.156.1"
# sha256 of the npm @openai/codex@0.156.1 linux-x64 musl `codex` binary, checked by the image build.
CODEX_CLI_SHA256 = "0b2e9301d6100dddda3b9d5c80ebaeaa3a2f1962388f2f36f6b96a9f08b1f33f"
CODEX_EXECUTABLE = "/usr/local/bin/codex"
CODEX_HOME = "/codex-home"
CODEX_CONFIG = ('# zeus-codex-role-config-v1: generated by the Zeus broker, mounted read-only.\n'
                'cli_auth_credentials_store = "file"\n'
                'check_for_update_on_startup = false\n')
CODEX_CONFIG_SHA256 = hashlib.sha256(CODEX_CONFIG.encode("utf-8")).hexdigest()
MAX_AUTH_BYTES = 64 * 1024
TOKEN_FIELDS = ("id_token", "access_token", "refresh_token")


# ---- evidence hand-off (D4) ---------------------------------------------------------------------
HANDOFF_KIND = "zeus-evidence-handoff-v1"
MAX_HANDOFF_REFS, MAX_HANDOFF_BYTES, MAX_MANIFEST_BYTES = 512, 256 * 1024 * 1024, 8 * 1024 * 1024
REF = re.compile(r"sha256:([0-9a-f]{64})")
# A hand-off named inside a referenced receipt (the writer's execution receipt carries its isolation block).
NAMED_HANDOFF = re.compile(r'"evidence_handoff":\s*\{[^{}]*?"manifest":\s*"sha256:([0-9a-f]{64})"')


def retain_evidence_handoff(artifacts, evidence_dir, run_id: str) -> dict:
    """Copy a settled writer's evidence (its `/evidence` tree and retained inner result) into the
    content-addressed store and return the manifest reference. Links, special files, hardlinks and
    oversize refuse by name (recorded, never raised: the writer's imported result stands)."""
    evidence_dir = Path(evidence_dir)
    try:
        tree = iw.scan_tree(evidence_dir, skip_top_git=False)
        sources = {name: evidence_dir.joinpath(*name.split("/")) for name in tree}
        inner = evidence_dir.parent / "inner_result.json"
        if inner.is_file() and not inner.is_symlink():
            sources["result/inner_result.json"] = inner
        files, total = {}, 0
        for name in sorted(sources):
            data = sources[name].read_bytes()
            if name in tree and hashlib.sha256(data).hexdigest() != tree[name]:
                raise IsolationError("handoff_changed_after_scan", repr(name)[:200])
            try:
                text, encoding = data.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                text, encoding = base64.b64encode(data).decode("ascii"), "base64"
            receipt = artifacts.put(text, "isolated-evidence:" + run_id + ":" + name)
            files[name] = {"ref": receipt["ref"], "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                           "encoding": encoding}
            total += len(data)
        manifest = {"kind": HANDOFF_KIND, "run_id": run_id, "files": files}
        receipt = artifacts.put(canonical(manifest), "isolated-evidence-handoff:" + run_id)
    except IsolationError as exc:
        return {"manifest": None, "refused": exc.reason_code}
    except Exception as exc:  # the writer's imported result stands; a failed copy is named, never raised
        return {"manifest": None, "refused": "handoff_" + type(exc).__name__}
    return {"manifest": receipt["ref"], "files": len(files), "bytes": total}


def handoff_refs(root, texts) -> list:
    """The artifact refs a container turn may read: every `sha256:<hex>` or `<root>/<hex>.txt` named
    in the host-assembled texts that exists in the store, plus each named hand-off manifest's files."""
    root = Path(root)
    found = set()
    path_pattern = re.compile(re.escape(str(root)) + r"[/\\]([0-9a-f]{64})\.txt")
    for text in texts:
        found.update(REF.findall(text))
        found.update(path_pattern.findall(text))
    present = {key for key in found if (root / (key + ".txt")).is_file()}

    def text_of(key):
        path = root / (key + ".txt")
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_bytes().decode("utf-8", errors="replace")
    manifests = set()
    for key in sorted(present):
        text = text_of(key)
        if text is not None:
            manifests.update(name for name in NAMED_HANDOFF.findall(text) if (root / (name + ".txt")).is_file())
            manifests.add(key)
    for key in sorted(manifests):
        try:
            body = json.loads(text_of(key) or "null")
        except ValueError:
            continue
        if isinstance(body, dict) and body.get("kind") == HANDOFF_KIND and isinstance(body.get("files"), dict):
            present.add(key)
            for entry in body["files"].values():
                match = REF.fullmatch(str(entry.get("ref") if isinstance(entry, dict) else ""))
                if match and (root / (match.group(1) + ".txt")).is_file():
                    present.add(match.group(1))
    return ["sha256:" + key for key in sorted(present)]


def materialize_handoff(handoff: dict | None, destination: Path) -> dict | None:
    """A per-run, verified, read-only copy of exactly the handed-off artifacts, laid out like the
    store so the same absolute paths and the artifact reader work inside the container. Never the
    live store, never a link; a digest mismatch or an oversize set refuses before any container."""
    if not handoff or not handoff.get("refs"):
        return None
    root = Path(handoff["root"])
    require(root.is_absolute() and "," not in str(root), "The hand-off root must be an absolute path")
    refs = list(handoff["refs"])
    if len(refs) > MAX_HANDOFF_REFS:
        raise IsolationError("handoff_too_large", str(len(refs)) + " refs")
    destination = Path(destination)
    destination.mkdir(parents=True)
    total = 0
    for ref in refs:
        match = REF.fullmatch(str(ref))
        if match is None:
            raise IsolationError("handoff_ref_invalid", repr(ref)[:100])
        source = root / (match.group(1) + ".txt")
        info = os.lstat(source)
        if not stat.S_ISREG(info.st_mode):
            raise IsolationError("handoff_source_not_regular", match.group(1))
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != match.group(1):
            raise IsolationError("handoff_integrity_failed", match.group(1))
        total += len(data)
        if total > MAX_HANDOFF_BYTES:
            raise IsolationError("handoff_too_large", str(total) + " bytes")
        target = destination / (match.group(1) + ".txt")
        target.write_bytes(data)
        target.chmod(0o444)
    destination.chmod(0o555)
    return {"source": str(destination.resolve()), "target": str(root),
            "summary": {"refs": len(refs), "bytes": total, "refs_sha256": digest(sorted(refs))}}


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


# ---- the Codex credential broker ----------------------------------------------------------------
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


def credential_shape(data: bytes) -> dict:
    """The non-secret structure of a Codex file-store credential: key sets, the account identity and
    the auth mode. A token value is only checked for presence, never returned."""
    try:
        body = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise IsolationError("credential_unparseable") from exc
    if not isinstance(body, dict) or not isinstance(body.get("tokens"), dict):
        raise IsolationError("credential_shape_invalid")
    tokens = body["tokens"]
    if not all(isinstance(tokens.get(name), str) and tokens[name] for name in TOKEN_FIELDS):
        raise IsolationError("credential_tokens_missing")
    if not isinstance(tokens.get("account_id"), str) or not tokens["account_id"]:
        raise IsolationError("credential_identity_missing")
    if body.get("OPENAI_API_KEY") not in (None, ""):
        # An API key is new billing, never authorized for product roles (D3 rejected alternatives).
        raise IsolationError("credential_api_key_refused")
    return {"keys": sorted(body), "token_keys": sorted(tokens), "account_id": tokens["account_id"],
            "auth_mode": body.get("auth_mode")}


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
    ledger of issued per-run copies, so every broker root sharing a store shares one serialization."""

    def __init__(self, store):
        self.store = Path(store)
        require(self.store.is_absolute(), "The Codex credential store must be an absolute path")
        self.auth = self.store / "auth.json"
        self.lock_path = self.store.parent / (self.store.name + ".lock")
        self.quarantine_path = self.store.parent / (self.store.name + ".quarantine")
        self.ledger = self.store.parent / (self.store.name + ".ledger")

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
                                                  "record": entry.get("record"), "at": time.time()})
        entry.update(state="quarantined", reason=reason, settled_at=time.time())
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
    def admit(self, *, wait_seconds: float, on_tick=None) -> "Admission":
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
        prior run is unsettled or unknown. Called only under the lock."""
        settled = []
        for entry in self.entries():
            if entry.get("state") != "issued":
                continue
            try:
                record = json.loads(Path(entry["record"]).read_text("utf-8"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise IsolationError("codex_credential_prior_run_unknown", str(entry.get("run_id"))) from exc
            if record.get("state") not in iw.RESOLVED:
                raise IsolationError("codex_credential_prior_run_unsettled",
                                     json.dumps({"run_id": entry["run_id"], "state": record.get("state"),
                                                 "record": entry["record"]}, sort_keys=True))
            settled.append(self.settle(entry))
            discard_tree(entry["home"])  # the settled copy's home: its task state never flows anywhere
        return settled

    def settle(self, entry: dict) -> dict:
        """Credential-only write-back of one stopped run's per-run copy. Unchanged: nothing is written.
        Changed and valid: atomic replacement. Anything else: quarantine (raised as a refusal)."""
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
        entry.update(state=state, settled_at=time.time())
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
                      "store_sha256": sha, "shape": dict(self.shape), "state": "issued", "issued_at": time.time()}
        self.broker._write_entry(self.entry)
        return {"account_sha256": hashlib.sha256(self.shape["account_id"].encode("utf-8")).hexdigest(),
                "issued": True}

    def settle(self) -> dict:
        require(self.entry is not None, "Nothing was issued")
        return self.broker.settle(self.entry)

    def release(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


# ---- the Codex App Server inside a role container -----------------------------------------------
def codex_environment() -> dict:
    """The fixed, value-free environment of every Codex profile container: no provider token of any
    kind; the credential is the per-run CODEX_HOME copy only."""
    return {"HOME": iw.CONTAINER_HOME, "CODEX_HOME": CODEX_HOME, "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": iw.WORKSPACE}


class _TextProcess:
    """The attached docker client's binary pipes, as the text streams the protocol code reads."""

    def __init__(self, process):
        self.raw, self.pid = process, process.pid
        self.stdin = io.TextIOWrapper(process.stdin, encoding="utf-8", write_through=True)
        self.stdout = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="replace")
        self.stderr = io.TextIOWrapper(process.stderr, encoding="utf-8", errors="replace")

    def poll(self):
        return self.raw.poll()


class AttachedAppServer(AppServer):
    """The unchanged JSON-RPC client over the stdio of `docker start --attach --interactive`. The
    container and the client tree are owned by `hold`; this closes only its own input on exit."""

    def __init__(self, process, cwd_target: str):
        super().__init__(executable=CODEX_EXECUTABLE)
        self.attached, self.cwd_target = _TextProcess(process), cwd_target

    def _spawn(self, argv):
        return self.attached

    def thread_cwd(self, cwd) -> str:
        return self.cwd_target

    def __exit__(self, *_):
        try:
            self.attached.stdin.close()
        except (OSError, ValueError):
            pass


class IsolatedCodexRuntime:
    """The executor's transport contract (context manager, `run`, `enters_on_open`) for codex-role-ro
    and codex-impl-rw. The protocol, schema, usage and turn semantics are the App Server client's."""

    enters_on_open = False

    def __init__(self, config: dict, root, *, profile: str, broker: CodexCredentialBroker, docker: str = "docker",
                 environment: dict | None = None, watch: tuple = (), context_window=None, handoff=None,
                 state_root=None, lock_wait_seconds: float = 60.0, network: str = "bridge"):
        require(isinstance(config, dict) and config.get("mode") == iw.MODE and iw.IMAGE.fullmatch(str(config.get("image"))),
                "Isolated runtime requires a validated isolation configuration")
        require(profile in (CODEX_ROLE_RO, CODEX_IMPL_RW), "Unsupported Codex container profile: " + str(profile))
        self.config, self.root, self.role_profile, self.broker, self.docker = config, Path(root), profile, broker, docker
        self.environment_source, self.watch = environment, tuple(Path(other) for other in watch)
        # `network` is the profile's worker network; only a no-provider fixture ever passes "none".
        self.context_window, self.handoff, self.network = context_window, handoff, network
        self.state_root = None if state_root is None else Path(state_root)
        self.lock_wait_seconds = lock_wait_seconds
        self.container, self.tree, self.record, self.record_path = None, None, None, None
        self.used = False

    def __enter__(self):
        # No Claude token is required or forwarded: a Codex container holds exactly one provider credential.
        self.preflight = iw.preflight(self.config, self.docker, self.environment_source, token=False)
        return self

    def __exit__(self, *_):
        if self.tree is not None:
            self.tree.terminate("context_exit")
            self.tree.close()
            self.tree = None

    def _advance(self, state: str, **detail) -> None:
        iw.advance(self.record, state, **detail)

    def _end_client(self) -> dict:
        if self.tree is None:
            return {"confirmed": True}
        ended = self.tree.terminate("container_stopped")
        self.tree.close()
        self.tree = None
        return ended

    def _state_directory(self, state_key) -> Path:
        return self.state_root / digest({"state_key": state_key, "profile": self.role_profile})

    def run(self, prompt: str, cwd: str, schema: dict, timeout: int = 240, *, on_event=None, read_only: bool = False,
            on_tick=None, model: str | None = None, on_enter=None, thread_id: str | None = None,
            state_key: str | None = None) -> dict:
        require(type(timeout) in (int, float) and 0 < timeout < float("inf"), "Execution timeout must be finite and positive")
        require(type(prompt) is str and bool(prompt), "Codex execution requires a prompt")
        require(read_only is (self.role_profile == CODEX_ROLE_RO),
                "A codex-role-ro container runs only read-only turns" if not read_only else
                "A codex-impl-rw container is not assigned reviews")
        # Task-scoped CLI state is reused only by the SAME task on the writable profile; a reviewer
        # always starts from a fresh home (D3 v3 item 2).
        require(state_key is None or (not read_only and self.state_root is not None),
                "Retained Codex state belongs to one writable task only")
        require(not self.used, "This transport object already ran; every attempt builds its own")
        self.used = True
        workspace = str(Path(cwd).resolve())
        pending = [row for root in (self.root, *self.watch) for row in iw.unresolved_runs(root, workspace)]
        if pending:
            raise IsolationError("isolation_unresolved_run", json.dumps(pending, sort_keys=True))
        admission = self.broker.admit(wait_seconds=min(self.lock_wait_seconds, float(timeout)), on_tick=on_tick)
        try:
            return self._admitted(admission, prompt, workspace, schema, timeout, on_event=on_event,
                                  read_only=read_only, on_tick=on_tick, model=model, on_enter=on_enter,
                                  thread_id=thread_id, state_key=state_key)
        finally:
            admission.release()

    def _prepare(self, admission, workspace, run_directory, read_only, state_key, on_tick) -> dict:
        # Published before anything is created, so a refusal part-way still discards what exists.
        prepared = self.prepared = {"handoff": None, "source": None, "staging_git": None,
                                    "home": run_directory / "codex-home", "handoff_path": run_directory / "handoff"}
        revision = subprocess.run(["git", "-C", workspace, "rev-parse", "HEAD"], capture_output=True, text=True,
                                  timeout=60, **no_console_kwargs())
        if revision.returncode != 0:
            raise IsolationError("source_revision_unavailable")
        dirty = subprocess.run(["git", "-C", workspace, "status", "--porcelain"], capture_output=True, text=True,
                               timeout=120, **no_console_kwargs())
        if dirty.returncode != 0 or dirty.stdout.strip():
            raise IsolationError("source_candidate_dirty")
        home, config = run_directory / "codex-home", run_directory / "codex-config.toml"
        if read_only:
            result = run_directory / "result"
            result.mkdir()
            prepared.update(source={"revision": revision.stdout.strip(), "mode": "read_only_checkout"}, result=result)
            mounts = [(workspace, iw.WORKSPACE, True), (str(result.resolve()), RESULT)]
            expected = {iw.WORKSPACE: False, RESULT: True}
        else:
            staging, evidence = run_directory / "workspace", run_directory / "evidence"
            evidence.mkdir()
            source = iw.stage_source(workspace, revision.stdout.strip(), staging, on_progress=on_tick)
            prepared.update(source=source, staging=staging, evidence=evidence,
                            staging_git=iw.init_standalone_git(staging))
            mounts = [(str(staging.resolve()), iw.WORKSPACE), (str(evidence.resolve()), iw.EVIDENCE)]
            expected = {iw.WORKSPACE: True, iw.EVIDENCE: True}
        handoff = materialize_handoff(self.handoff, run_directory / "handoff")
        if handoff is not None:
            mounts.append((handoff["source"], handoff["target"], True))
            expected[handoff["target"]] = False
        prepared["handoff"] = handoff
        home.mkdir(mode=0o700)
        if state_key is not None and self._state_directory(state_key).is_dir():
            shutil.copytree(self._state_directory(state_key), home, symlinks=True, dirs_exist_ok=True)
        config.write_text(CODEX_CONFIG, encoding="utf-8")
        config.chmod(0o444)
        if hashlib.sha256(config.read_bytes()).hexdigest() != CODEX_CONFIG_SHA256:
            raise IsolationError("codex_config_digest_mismatch", "before start")
        prepared["credential"] = admission.issue(self.container.run_id, self.record_path, home)
        mounts += [(str(home.resolve()), CODEX_HOME), (str(config.resolve()), CODEX_HOME + "/config.toml", True)]
        expected.update({CODEX_HOME: True, CODEX_HOME + "/config.toml": False})
        prepared.update(home=home, config=config, mounts=mounts, expected=expected)
        return prepared

    def _admitted(self, admission, prompt, workspace, schema, timeout, *, on_event, read_only, on_tick, model,
                  on_enter, thread_id, state_key) -> dict:
        run_id = uuid4().hex
        run_directory = self.root / run_id
        run_directory.mkdir(parents=True)
        self.record_path = run_directory / "run.json"
        self.container = iw.OwnedContainer(self.config, self.docker, run_id, "codex")
        self.record = iw.new_record(run_directory, role="codex", workspace=workspace, config=self.config,
                                    container=self.container, profile=self.role_profile)
        self.prepared = None
        try:
            prepared = self._prepare(admission, workspace, run_directory, read_only, state_key, on_tick)
            self._advance("prepared", profile=self.role_profile, config_sha256=CODEX_CONFIG_SHA256,
                          source={key: prepared["source"][key] for key in ("revision",)},
                          handoff=None if prepared["handoff"] is None else prepared["handoff"]["summary"],
                          credential={"store": "per-run copy issued", "ledger": "issued"})
            probe = AppServer(executable=CODEX_EXECUTABLE, context_window=self.context_window)
            entry = [CODEX_EXECUTABLE, *probe.server_arguments()]
            args = iw.container_args(self.config, name=self.container.name, run_id=run_id, role="codex",
                                     network=self.network, mounts=prepared["mounts"], environment=codex_environment(),
                                     pass_names=(), entry=entry, workdir=iw.WORKSPACE)
            try:
                container_id = self.container.create(args, iw.docker_environment(self.environment_source))
            except IsolationError:
                self._advance("refused", reason="container_create_failed")
                raise
            self.record["container"] = container_id
            try:
                self._advance("created", container=container_id)
                controls = self.container.verify(prepared["expected"], self.network)
            except IsolationError as exc:
                removal = self.container.remove()
                self._advance("refused" if removal["removed"] else "created", reason=exc.reason_code)
                raise
        except BaseException:
            if self.record["state"] is None:
                try:
                    self._advance("refused", reason="before_container")
                except IsolationError:
                    pass
            self._settle_quietly(admission)
            self._discard(self.prepared)
            raise
        started = time.monotonic()

        def converse():
            if on_enter is not None:
                on_enter()
            self.tree = iw.ProcessTree.spawn([self.docker, "start", "--attach", "--interactive", self.container.id],
                                             env=iw.docker_environment(self.environment_source),
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._advance("running", client_pid=self.tree.process.pid)
            server = AttachedAppServer(self.tree.process, iw.WORKSPACE)
            with server:
                return server.run(prompt, workspace, schema, timeout, thread_id=thread_id, on_event=on_event,
                                  read_only=read_only, on_tick=on_tick, model=model)
        try:
            value, stopped = iw.hold(self.container, self.record, converse, client=self._end_client, detail=lambda v: {
                "turn": {"interrupted": v.get("interrupted"), "failure": (v.get("failure") or {}).get("cause")}})
        except BaseException:
            # However the turn ended, the credential copy is settled only when the stop was confirmed;
            # an unconfirmed stop keeps the copy and its ledger entry for the next admission's reconcile.
            if iw.cleanup_debt(self.record) is None:
                try:
                    self._after_stop(admission, prepared)
                    self._discard(prepared)
                except IsolationError:
                    pass  # quarantined: the marker holds every next admission; the home stays as evidence
            raise
        if not stopped["confirmed"]:
            raise ContractError("Codex role container termination could not be confirmed; the outcome is unknown and "
                                "its credential copy stays unsettled; recovery record " + str(self.record_path))
        try:
            settlement = self._after_stop(admission, prepared)
        except IsolationError as exc:
            # Hold: the store is quarantined; the stopped container is still retired by the one rule,
            # and the per-run home stays as the owner's evidence.
            iw.retire(self.container, self.record, {"credential_hold": exc.reason_code, "detail": str(exc)},
                      "credential_hold")
            raise
        isolation = {**iw.summary(self.config), "profile": self.role_profile, "run_id": run_id,
                     "container": {"id": self.container.id, "name": self.container.name, "controls": controls,
                                   "stop": stopped},
                     "source": {key: prepared["source"][key] for key in ("revision", "files", "bytes", "manifest_sha256", "mode")
                                if key in prepared["source"]},
                     "staging_git": prepared["staging_git"], "preflight": self.preflight, "record": str(self.record_path),
                     "handoff": None if prepared["handoff"] is None else prepared["handoff"]["summary"],
                     "credential": {"transport": "per-run CODEX_HOME copy; credential-only write-back under the lock",
                                    "settlement": settlement["state"], "account_sha256": prepared["credential"]["account_sha256"]},
                     "cli": {"pinned_version": CODEX_CLI_VERSION, "pinned_sha256": CODEX_CLI_SHA256,
                             "config_sha256": CODEX_CONFIG_SHA256},
                     "elapsed_seconds": time.monotonic() - started}
        failure = None
        if not read_only:
            try:
                plan = iw.plan_import(prepared["source"]["manifest"], prepared["staging"])
                self._advance("validated", changes={key: len(plan[key]) for key in ("added", "modified", "deleted")})
                isolation["import"] = iw.apply_import(plan, prepared["staging"], Path(workspace))
                self._advance("imported")
            except IsolationError as exc:
                failure = exc
            except OSError as exc:
                failure = IsolationError("import_failed", type(exc).__name__)
        else:
            try:
                isolation["result_files"] = iw.scan_tree(prepared["result"], skip_top_git=False)
            except IsolationError as exc:
                isolation["result_files"] = {"refused": exc.reason_code}
        isolation["outcome"] = ("reviewed" if read_only else "imported") if failure is None else failure.reason_code
        retained = {key: value.get(key) for key in ("answer", "thread_id", "usage", "interrupted", "failure",
                                                     "inspection_blocked", "requested_model")}
        removal = iw.retire(self.container, self.record, {"isolation": isolation}, isolation["outcome"],
                            files={"codex_result.json": retained},
                            removed={"staging_retained": failure is not None})
        isolation["cleanup"] = removal
        if not removal["evidence_written"]:
            raise ContractError("Codex role container evidence could not be written; the stopped container is "
                                "retained; recovery record " + str(self.record_path))
        if failure is not None:
            raise ContractError(str(failure) + "; staging preserved; recovery record " + str(self.record_path)) from failure
        if not read_only and removal["removed"]:
            shutil.rmtree(prepared["staging"], ignore_errors=True)
        if state_key is not None:
            target = self._state_directory(state_key)
            discard_tree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(prepared["home"], target, symlinks=True,
                            ignore=lambda directory, names: [name for name in names if Path(directory) == prepared["home"]
                                                             and name in ("auth.json", "config.toml")])
            isolation["task_state"] = "retained_for_same_task"
        else:
            isolation["task_state"] = "discarded"
        self._discard(prepared)
        return {**value, "isolation": isolation}

    def _after_stop(self, admission, prepared) -> dict:
        """After a confirmed stop and before removal: the read-only configuration must be byte-for-byte
        what was mounted, then the credential copy is settled. Either anomaly is a hold."""
        config = prepared["config"]
        try:
            observed = hashlib.sha256(config.read_bytes()).hexdigest()
        except OSError:
            observed = None
        if observed != CODEX_CONFIG_SHA256:
            admission.broker._quarantine(admission.entry, "config_digest_changed")
            raise IsolationError("codex_credential_quarantined", "config_digest_changed")
        return admission.settle()

    def _settle_quietly(self, admission) -> None:
        """A refusal before any container started: the untouched copy settles as unchanged."""
        if admission.entry is None or admission.entry.get("state") != "issued":
            return
        try:
            admission.settle()
        except IsolationError:
            pass

    @staticmethod
    def _discard(prepared) -> None:
        """This run's own home (with its credential copy) and hand-off copy; records stay."""
        if not prepared:
            return
        for key in ("home", "handoff_path"):
            if prepared.get(key) is not None:
                discard_tree(prepared[key])
