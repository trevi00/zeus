"""Session transcript bytes for durable Claude task sessions (INV-WORKER-SESSION-001).

Three file boundaries, one rule each:

- `export_session` runs where the CLI ran (the trusted container entry, or a test home). It copies
  ONLY the exact session's transcript and the regular files under that session's own directory,
  bounded, by an allowlist; credentials, settings, dot-files, other sessions and other projects are
  never read into the export, and a symlink or special file anywhere on the path refuses the export.
- `read_export` runs on the host after the container is confirmed stopped. It trusts nothing the
  container wrote about itself: every listed file is re-hashed, contained, regular and not a link,
  and an unlisted file refuses the whole export.
- `SessionArchives` is a restricted content-addressed store (its own root, never the general
  artifact tree a model can read through the artifact reader). A put is deterministic and verified
  by reading it back, so a lost response is replayed to the same reference. Nothing here deletes an
  archive: retention past closure is the owner's decision, never a side effect of cleanup.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.domain.model import ContractError, canonical, require
from codex_harness.domain.worker_sessions import (
    ARCHIVE_SCHEMA,
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_DEPTH,
    MAX_ARCHIVE_FILE_BYTES,
    MAX_ARCHIVE_FILES,
    WorkerSessionRefused,
    allowed_path,
    project_key,
    refuse,
    transcript_entry,
    transcript_path,
    validate_manifest,
)

EXPORT_DIRECTORY = "session-export"
RESTORE_DIRECTORY = "session-restore"
MANIFEST = "manifest.json"
MAX_MANIFEST_BYTES = 256 * 1024
ARCHIVE_TEXT_LIMIT = 4 * MAX_ARCHIVE_BYTES // 3 + 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _regular(path: Path) -> os.stat_result:
    """lstat, never follow: a link or special file is refused rather than read through."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise WorkerSessionRefused("archive_file_missing", path.name) from None
    refuse(not stat.S_ISLNK(info.st_mode), "archive_link_refused", path.name)
    refuse(stat.S_ISREG(info.st_mode), "archive_special_file_refused", path.name)
    return info


def _no_links_between(root: Path, relative: str) -> Path:
    """The path of `relative` under `root`, with every intermediate directory checked not to be a link."""
    current = root
    parts = relative.split("/")
    for part in parts[:-1]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise WorkerSessionRefused("archive_file_missing", part) from None
        refuse(not stat.S_ISLNK(info.st_mode) and stat.S_ISDIR(info.st_mode), "archive_link_refused", part)
    target = current / parts[-1]
    refuse(os.path.commonpath([os.path.abspath(root), os.path.abspath(target)]) == os.path.abspath(root),
           "archive_path_refused", "escapes its root")
    return target


def _walk(directory: Path, relative: str, depth: int, found: list) -> None:
    refuse(depth <= MAX_ARCHIVE_DEPTH, "archive_bounds", "depth")
    for entry in sorted(os.scandir(directory), key=lambda item: item.name):
        info = entry.stat(follow_symlinks=False)
        refuse(not stat.S_ISLNK(info.st_mode), "archive_link_refused", entry.name)
        child = relative + "/" + entry.name
        if stat.S_ISDIR(info.st_mode):
            _walk(Path(entry.path), child, depth + 1, found)
        else:
            refuse(stat.S_ISREG(info.st_mode), "archive_special_file_refused", entry.name)
            found.append(child)
        refuse(len(found) <= 4 * MAX_ARCHIVE_FILES, "archive_bounds", "file count")


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


# ---- export (where the CLI ran) ------------------------------------------------------------------
def export_session(home, cwd: str, session_id: str, destination) -> dict:
    """Copy the exact session's allowlisted files from the CLI home into an empty `destination`."""
    home, destination = Path(home), Path(destination)
    project = project_key(cwd)
    transcript = transcript_path(project, session_id)
    base = _no_links_between(home, transcript)
    _regular(base)
    candidates = [transcript]
    session_directory = home / "projects" / project / session_id
    try:
        info = os.lstat(session_directory)
    except FileNotFoundError:
        info = None
    if info is not None:
        refuse(not stat.S_ISLNK(info.st_mode) and stat.S_ISDIR(info.st_mode), "archive_link_refused", session_id)
        _walk(session_directory, f"projects/{project}/{session_id}", 1, candidates)
    refuse(not destination.exists() or not any(destination.iterdir()), "archive_destination_not_empty")
    files, contents, excluded, total = [], {}, 0, 0
    for relative in candidates:
        if not allowed_path(relative, project, session_id):
            excluded += 1  # dot-files and unsafe names are never exported, and never read
            continue
        source = _no_links_between(home, relative)
        size = _regular(source).st_size
        refuse(size <= MAX_ARCHIVE_FILE_BYTES, "archive_bounds", "file bytes")
        total += size
        refuse(total <= MAX_ARCHIVE_BYTES and len(files) < MAX_ARCHIVE_FILES, "archive_bounds", "total")
        data = source.read_bytes()
        refuse(len(data) == size, "archive_file_changed", relative)
        files.append({"path": relative, "bytes": len(data), "sha256": _sha(data)})
        contents[relative] = data
    manifest = validate_manifest({"schema": ARCHIVE_SCHEMA, "session_id": session_id, "project": project,
                                  "files": files}, session_id=session_id)
    for relative, data in contents.items():
        _write_new(destination / relative, data)
    _write_new(destination / MANIFEST, canonical(manifest).encode("utf-8"))
    return {**manifest, "excluded": excluded}


# ---- host-side verification ----------------------------------------------------------------------
def read_export(directory, *, session_id: str) -> dict:
    """Re-verify an exported (or staged) session directory completely; returns manifest and bytes."""
    directory = Path(directory)
    manifest_path = directory / MANIFEST
    size = _regular(manifest_path).st_size
    refuse(size <= MAX_MANIFEST_BYTES, "archive_bounds", "manifest bytes")
    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WorkerSessionRefused("archive_malformed", "manifest") from None
    manifest = validate_manifest(manifest, session_id=session_id)
    listed = {entry["path"] for entry in manifest["files"]}
    present = []
    for entry in sorted(os.scandir(directory), key=lambda item: item.name):
        info = entry.stat(follow_symlinks=False)
        refuse(not stat.S_ISLNK(info.st_mode), "archive_link_refused", entry.name)
        if entry.name == MANIFEST:
            continue
        if stat.S_ISDIR(info.st_mode):
            _walk(Path(entry.path), entry.name, 1, present)
        else:
            present.append(entry.name)
    refuse(set(present) == listed, "archive_unlisted_file" if set(present) - listed else "archive_file_missing")
    files = {}
    for entry in manifest["files"]:
        path = _no_links_between(directory, entry["path"])
        refuse(_regular(path).st_size == entry["bytes"], "archive_corrupt", entry["path"])
        data = path.read_bytes()
        refuse(len(data) == entry["bytes"] and _sha(data) == entry["sha256"], "archive_corrupt", entry["path"])
        files[entry["path"]] = data
    return {"manifest": manifest, "files": files}


def restore_session(source, home, *, session_id: str, expected_manifest: dict) -> dict:
    """Place a verified staged archive into a fresh CLI home. The manifest must be exactly the one
    the host named; an existing different file is refused, never overwritten."""
    staged = read_export(source, session_id=session_id)
    refuse(staged["manifest"] == validate_manifest(expected_manifest, session_id=session_id), "archive_manifest_mismatch")
    home = Path(home)
    for relative, data in staged["files"].items():
        target = home / relative
        refuse(os.path.commonpath([os.path.abspath(home), os.path.abspath(target)]) == os.path.abspath(home),
               "archive_path_refused", relative)
        if os.path.lexists(target):
            _regular(target)
            refuse(target.read_bytes() == data, "archive_restore_conflict", relative)
            continue
        _write_new(target, data)
    return staged["manifest"]


# ---- restricted content-addressed archive store -------------------------------------------------
class SessionArchives:
    """Verified archives in their own root. `put` is deterministic, idempotent and read back."""

    def __init__(self, root):
        self.store = FileArtifacts(str(root))

    @property
    def root(self) -> Path:
        return self.store.root

    @staticmethod
    def read_export(directory, *, session_id: str) -> dict:
        return read_export(directory, session_id=session_id)

    def put(self, export: dict) -> dict:
        manifest = validate_manifest(export["manifest"], session_id=export["manifest"]["session_id"])
        files = export["files"]
        require(set(files) == {entry["path"] for entry in manifest["files"]}, "Archive bytes do not match the manifest")
        document = {"schema": ARCHIVE_SCHEMA, "manifest": manifest,
                    "files": {path: base64.b64encode(files[path]).decode("ascii") for path in sorted(files)}}
        receipt = self.store.put(canonical(document), "worker-session:" + manifest["session_id"])
        loaded = self.load(receipt["ref"], session_id=manifest["session_id"])  # verified, not assumed
        return {"ref": receipt["ref"], "bytes": receipt["bytes"], "session_id": manifest["session_id"],
                "manifest_sha256": _sha(canonical(manifest).encode("utf-8")),
                "transcript_sha256": transcript_entry(loaded["manifest"])["sha256"],
                "files": len(manifest["files"])}

    def load(self, reference: str, *, session_id: str) -> dict:
        try:
            document = json.loads(self.store._body(reference, ARCHIVE_TEXT_LIMIT))
        except FileNotFoundError:
            raise WorkerSessionRefused("archive_missing", reference) from None
        except (ContractError, ValueError, UnicodeDecodeError, OSError) as exc:
            raise WorkerSessionRefused("archive_corrupt", type(exc).__name__) from None
        try:
            refuse(isinstance(document, dict) and document.get("schema") == ARCHIVE_SCHEMA, "archive_corrupt", "schema")
            manifest = validate_manifest(document.get("manifest"), session_id=session_id)
            encoded = document.get("files")
            refuse(isinstance(encoded, dict) and set(encoded) == {e["path"] for e in manifest["files"]},
                   "archive_corrupt", "file set")
            files = {}
            for entry in manifest["files"]:
                data = base64.b64decode(encoded[entry["path"]], validate=True)
                refuse(len(data) == entry["bytes"] and _sha(data) == entry["sha256"], "archive_corrupt", entry["path"])
                files[entry["path"]] = data
        except WorkerSessionRefused as exc:
            if exc.reason == "archive_foreign_session":
                raise
            raise WorkerSessionRefused("archive_corrupt", exc.reason) from None
        except (ValueError, TypeError):
            raise WorkerSessionRefused("archive_corrupt", "encoding") from None
        return {"manifest": manifest, "files": files}

    def stage(self, reference: str, destination, *, session_id: str) -> dict:
        """Write a verified archive in export layout into an empty restore directory."""
        loaded = self.load(reference, session_id=session_id)
        destination = Path(destination)
        refuse(not destination.exists() or not any(destination.iterdir()), "archive_destination_not_empty")
        for relative, data in loaded["files"].items():
            _write_new(destination / relative, data)
        _write_new(destination / MANIFEST, canonical(loaded["manifest"]).encode("utf-8"))
        return loaded["manifest"]

    def continuity(self, prior_reference: str, export: dict, *, session_id: str) -> str:
        """`prefix_verified` when the new transcript begins with the prior archive's exact transcript."""
        prior = self.load(prior_reference, session_id=session_id)
        old = prior["files"][transcript_entry(prior["manifest"])["path"]]
        new = export["files"][transcript_entry(export["manifest"])["path"]]
        return "prefix_verified" if len(new) > len(old) and new.startswith(old) else "unproven"


# ---- `zeus worker-session status|close` -----------------------------------------------------------
def archive_root():
    from codex_harness.adapters.configuration import runtime_dir
    return runtime_dir() / "worker-sessions"


def add_parser(commands) -> None:
    session = commands.add_parser("worker-session", help="Durable Claude task sessions: read-only status, explicit close")
    sub = session.add_subparsers(dest="worker_session_command", required=True)
    status = sub.add_parser("status", help="Bounded status; ids, hashes and states only (store read only)")
    status.add_argument("--task-id", default=None)
    close = sub.add_parser("close", help="Close an archival_pending session whose evidence promotion is recorded")
    close.add_argument("--task-id", required=True)


def execute(service, args, archives=None) -> dict:
    from codex_harness.application.worker_sessions import WorkerSessions
    owner = WorkerSessions(service.store, archives or SessionArchives(archive_root()))
    if args.worker_session_command == "status":
        return {**owner.status(args.task_id), "exit_code": 0}
    row = owner.close(args.task_id)
    return {"closed": row["state"] == "closed", "task_id": args.task_id, "state": row["state"],
            "archive_retained": (row.get("cleanup") or {}).get("archive_retained"), "exit_code": 0}


def refusal(exc) -> dict:
    """A code and a type; never a path, transcript text or a raw exception message."""
    return {"refused": True, "reason": getattr(exc, "reason", None) or "error", "error_type": type(exc).__name__,
            "exit_code": 1}
