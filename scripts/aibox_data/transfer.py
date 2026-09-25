"""Restartable, hash-verified staged copy of one manifest root (SPEC §8 artifacts, A3).

Layout: the staging root holds only the copied tree, byte-for-byte with the source names. All
in-flight state lives in a separate migration-owned work directory on the same filesystem:
`journal.json` and `partials/<sha256(root id, path)>.part`. Partial names therefore never collide
with, hide or exclude a real source file such as `log.part`.

The journal is bound to (migration_id, manifest digest, root id): a rerun with the same binding
resumes, a different digest is refused, and a staged file already verified is never copied again.
A partial is re-verified against the source prefix before appending, hashed, fsynced and renamed
into place. The source is re-hashed while copying, so a change after the seal is refused. Existing
staged bytes that disagree with the manifest are refused, never overwritten.

Path ownership: before any write, every destination ancestor below the staging root is checked with
lstat and must be a real directory (missing ones are created one level at a time); a symlink or
non-directory ancestor is refused, as are symlinked source ancestors, partials and journal files.
Files are opened with O_NOFOLLOW. These are check-then-use steps against an operator-owned staging
area: they stop pre-existing or accidental links, but they do NOT protect against an adversary who
swaps a directory for a link concurrently between the check and the write.

Source blocking findings (unreadable subtrees, special files, links escaping the root) make the
stage result `blocked` and the staged comparison fail; an unreadable subtree is never empty.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from .inventory import (
    CHUNK,
    blocking_findings,
    compare_roots,
    scan_root,
    validate_entry_path,
    verify_manifest_digest,
)

JOURNAL_SCHEMA = "zeus.aibox-stage-journal/2"
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
# Windows opens os.open() descriptors in TEXT mode unless O_BINARY is set (CRLF translation and
# Ctrl-Z end of file on read), which would hash and copy different bytes; POSIX has no such flag.
BINARY = getattr(os, "O_BINARY", 0)


class TransferRefused(Exception):
    def __init__(self, reason: str, path: str | None = None):
        super().__init__(reason if path is None else f"{reason}: {path}")
        self.reason, self.path = reason, path


def _lstat(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _real_dir(path: Path, create: bool, reason: str, label: str) -> bool:
    """True if `path` is a real directory (created if allowed); refuse links/non-directories."""
    info = _lstat(path)
    if info is None:
        if not create:
            return False
        try:
            os.mkdir(path)
        except FileExistsError:
            pass
        info = _lstat(path)
    if info is None or stat.S_ISLNK(info.st_mode):
        raise TransferRefused(f"{reason}_symlink", label)
    if not stat.S_ISDIR(info.st_mode):
        raise TransferRefused(f"{reason}_not_directory", label)
    return True


def _ancestors(root: Path, relative: str, create: bool, reason: str) -> bool:
    """Check (and optionally create) every ancestor of `relative` below `root`."""
    current = root
    for part in relative.split("/")[:-1]:
        current = current / part
        if not _real_dir(current, create, reason, relative):
            return False
    return True


def _open_regular(path: Path, flags: int, reason: str, label: str, mode: int = 0o666) -> int:
    try:
        handle = os.open(path, flags | NOFOLLOW | BINARY, mode)
    except OSError as exc:
        raise TransferRefused(reason, label) from exc
    if not stat.S_ISREG(os.fstat(handle).st_mode):
        os.close(handle)
        raise TransferRefused(reason, label)
    return handle


def _sha(path: Path, reason: str, label: str, limit: int | None = None) -> str:
    digest, remaining = hashlib.sha256(), limit
    with os.fdopen(_open_regular(path, os.O_RDONLY, reason, label), "rb") as stream:
        while remaining is None or remaining > 0:
            block = stream.read(CHUNK if remaining is None else min(CHUNK, remaining))
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    if hasattr(os, "O_DIRECTORY"):
        handle = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


class _Work:
    """The migration-owned work directory: journal plus hash-named partials."""

    def __init__(self, path: Path, staging: Path, binding: dict):
        self.path, self.binding = path, binding
        fresh = _lstat(path) is None
        _real_dir(path, True, "work_dir", str(path))
        self.journal_file, self.partials = path / "journal.json", path / "partials"
        journal_info = _lstat(self.journal_file)
        if journal_info is None:
            foreign = [name for name in os.listdir(path) if name not in {"partials", "journal.json.tmp"}]
            if foreign or (not fresh and _lstat(self.partials) is not None and os.listdir(self.partials)):
                raise TransferRefused("work_dir_not_migration_owned", str(path))
            self.journal = {"schema": JOURNAL_SCHEMA, **binding, "completed": {}, "events": []}
        else:
            if not stat.S_ISREG(journal_info.st_mode):
                raise TransferRefused("journal_not_regular", str(self.journal_file))
            with os.fdopen(_open_regular(self.journal_file, os.O_RDONLY, "journal_not_regular",
                                         str(self.journal_file)), encoding="utf-8") as stream:
                self.journal = json.load(stream)
            if {k: self.journal.get(k) for k in binding} != binding:
                raise TransferRefused("journal_binding_mismatch", str(self.journal_file))
        _real_dir(self.partials, True, "partials_dir", str(self.partials))
        if os.stat(path).st_dev != os.stat(staging).st_dev:
            raise TransferRefused("work_dir_other_filesystem", str(path))

    def partial(self, relative: str) -> Path:
        key = hashlib.sha256(f"{self.binding['root_id']}\0{relative}".encode()).hexdigest()
        return self.partials / f"{key}.part"

    def save(self) -> None:
        temporary = self.path / "journal.json.tmp"
        handle = _open_regular(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, "journal_not_regular",
                               str(temporary), 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(self.journal, stream, sort_keys=True, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.journal_file)
        _fsync_dir(self.path)


def _copy_file(source: Path, part: Path, destination: Path, staging: Path, entry: dict,
               limit_bytes: int | None) -> dict:
    """Copy one file through its work-dir partial. Raises on refusal or injected stop."""
    label = entry["path"]
    resumed = 0
    info = _lstat(part)
    if info is not None:
        if not stat.S_ISREG(info.st_mode):
            raise TransferRefused("partial_not_regular", label)
        resumed = info.st_size
        if (resumed > entry["bytes"] or _sha(part, "partial_not_regular", label)
                != _sha(source, "source_not_regular", label, resumed)):
            raise TransferRefused("partial_diverged", label)
    digest, written = hashlib.sha256(), 0
    reader = os.fdopen(_open_regular(source, os.O_RDONLY, "source_not_regular", label), "rb")
    writer = os.fdopen(_open_regular(part, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                                     "partial_not_regular", label), "ab")
    with reader, writer:
        digest.update(reader.read(resumed))
        while True:
            block = reader.read(CHUNK)
            if not block:
                break
            if limit_bytes is not None and written + len(block) > limit_bytes:
                writer.write(block[:max(0, limit_bytes - written)])
                writer.flush()
                os.fsync(writer.fileno())
                raise TransferRefused("interrupted", label)
            digest.update(block)
            writer.write(block)
            written += len(block)
        writer.flush()
        os.fsync(writer.fileno())
    if digest.hexdigest() != entry["sha256"] or os.lstat(part).st_size != entry["bytes"]:
        # The partial keeps the source's current bytes as evidence; the source changed after the seal.
        raise TransferRefused("source_changed_after_seal", label)
    if _sha(part, "partial_not_regular", label) != entry["sha256"]:
        raise TransferRefused("staged_hash_mismatch", label)
    # Re-check ownership immediately before the rename (check-then-use; see module docstring).
    _ancestors(staging, label, False, "staging_ancestor")
    if _lstat(destination) is not None:
        raise TransferRefused("staged_conflict", label)
    os.replace(part, destination)
    _fsync_dir(destination.parent)
    return {"path": label, "action": "copied", "resumed_from_bytes": resumed, "bytes": entry["bytes"]}


def _roots(source_root, staging_root, work_dir) -> tuple[Path, Path, Path]:
    source, staging, work = (Path(p).absolute() for p in (source_root, staging_root, work_dir))
    if not _real_dir(source, False, "source_root", str(source)):
        raise TransferRefused("source_root_missing", str(source))
    if _lstat(staging.parent) is None:
        raise TransferRefused("staging_parent_missing", str(staging))
    _real_dir(staging, True, "staging_root", str(staging))
    real = {name: Path(os.path.realpath(p)) for name, p in
            (("source", source), ("staging", staging), ("work", work))}
    if _inside(real["staging"], real["source"]) or _inside(real["source"], real["staging"]):
        raise TransferRefused("staging_overlaps_source")
    if any(_inside(real["work"], real[n]) or _inside(real[n], real["work"]) for n in ("source", "staging")):
        raise TransferRefused("work_dir_overlaps")
    return source, staging, work


def stage_root(manifest: dict, root_id: str, source_root: str | Path, staging_root: str | Path,
               work_dir: str | Path, limit_bytes: int | None = None) -> dict:
    """Copy one sealed manifest root into staging. `limit_bytes` is a test/throttle hook that stops
    after that many newly written bytes, leaving a resumable partial (reported as interrupted)."""
    if not verify_manifest_digest(manifest):
        raise TransferRefused("manifest_digest_invalid")
    if root_id not in manifest["roots"]:
        raise TransferRefused("unknown_root", root_id)
    root = manifest["roots"][root_id]
    for entry in root["entries"]:
        try:
            validate_entry_path(entry["path"])
        except ValueError as exc:
            raise TransferRefused("unsafe_manifest_path", str(entry["path"])) from exc
    source, staging, work_path = _roots(source_root, staging_root, work_dir)
    work = _Work(work_path, staging, {"migration_id": manifest["migration_id"],
                                      "manifest_digest": manifest["digest"], "root_id": root_id})
    blocking = blocking_findings(root)
    events, remaining = [], limit_bytes
    for entry in root["entries"]:
        relative = entry["path"]
        destination = staging / relative
        if entry["kind"] == "symlink" and entry["escapes_root"]:
            events.append({"path": relative, "action": "external_symlink_not_created"})
            continue
        if entry["kind"] not in {"file", "symlink"}:
            events.append({"path": relative, "action": "special_not_copied"})
            continue
        exists = _ancestors(staging, relative, False, "staging_ancestor")
        current = _lstat(destination) if exists else None
        if entry["kind"] == "symlink":
            if current is not None:
                if not (stat.S_ISLNK(current.st_mode) and os.readlink(destination) == entry["link_target"]):
                    raise TransferRefused("staged_conflict", relative)
                events.append({"path": relative, "action": "verified_existing"})
                continue
            _ancestors(staging, relative, True, "staging_ancestor")
            os.symlink(entry["link_target"], destination)
            events.append({"path": relative, "action": "symlink_created"})
            continue
        if current is not None:
            if (not stat.S_ISREG(current.st_mode)
                    or _sha(destination, "staged_conflict", relative) != entry["sha256"]):
                raise TransferRefused("staged_conflict", relative)
            work.journal["completed"][relative] = entry["sha256"]
            events.append({"path": relative, "action": "verified_existing"})
            continue
        if not _ancestors(source, relative, False, "source_ancestor"):
            raise TransferRefused("source_changed_after_seal", relative)
        _ancestors(staging, relative, True, "staging_ancestor")
        try:
            event = _copy_file(source / relative, work.partial(relative), destination, staging,
                               entry, remaining)
        except TransferRefused as exc:
            if exc.reason == "interrupted":
                work.journal["events"].append({"path": relative, "action": "interrupted"})
                work.save()
                return {"status": "interrupted", "blocking": blocking,
                        "events": events + [{"path": relative, "action": "interrupted"}]}
            raise
        if remaining is not None:
            remaining -= entry["bytes"] - event["resumed_from_bytes"]
        work.journal["completed"][relative] = entry["sha256"]
        work.journal["events"].append(event)
        work.save()
        events.append(event)
    work.save()
    status = "blocked" if any(blocking.values()) else "complete"
    return {"status": status, "blocking": blocking, "events": events,
            "journal": str(work.journal_file)}


def verify_staged(manifest: dict, root_id: str, staging_root: str | Path,
                  work_dir: str | Path | None = None) -> dict:
    """Re-scan the staged tree and compare every entry, under its real name, with the sealed
    manifest. Source blocking findings and leftover work-dir partials fail the comparison."""
    if not verify_manifest_digest(manifest):
        return {"match": False, "problems": ["manifest_digest_invalid"]}
    staging = Path(staging_root).absolute()
    info = _lstat(staging)
    if info is None or not stat.S_ISDIR(info.st_mode):
        return {"match": False, "problems": ["staging_root_not_real_directory"]}
    result = compare_roots(manifest["roots"][root_id], scan_root(staging))
    partials = []
    if work_dir is not None and _lstat(Path(work_dir) / "partials") is not None:
        partials = sorted(os.listdir(Path(work_dir) / "partials"))
    result["partials"] = partials
    result["match"] = result["match"] and not partials
    return result
