"""Restartable, hash-verified staged copy of one manifest root (SPEC §8 artifacts, A3).

The journal is bound to (migration_id, manifest digest, root id): a rerun with the same binding
resumes, a rerun with a different digest is refused, and a staged file already verified is never
copied again. Each file is written to `<name>.part`, its prefix re-verified against the source
before appending, hashed, fsynced and renamed into place. The source is re-hashed while copying,
so a change after the seal is refused instead of staged. Existing staged bytes that disagree with
the manifest are refused, never overwritten. Internal symlinks are recreated literally; links that
escape the root are reported and not created.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .inventory import CHUNK, compare_roots, scan_root, sha256_file, verify_manifest_digest

JOURNAL_SCHEMA = "zeus.aibox-stage-journal/1"


class TransferRefused(Exception):
    def __init__(self, reason: str, path: str | None = None):
        super().__init__(reason if path is None else f"{reason}: {path}")
        self.reason, self.path = reason, path


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=1)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_dir(path.parent)


def _fsync_dir(path: Path) -> None:
    if hasattr(os, "O_DIRECTORY"):
        handle = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def _load_journal(path: Path, binding: dict) -> dict:
    if path.exists():
        journal = json.loads(path.read_text("utf-8"))
        if {k: journal.get(k) for k in binding} != binding:
            raise TransferRefused("journal_binding_mismatch", str(path))
        return journal
    return {"schema": JOURNAL_SCHEMA, **binding, "completed": {}, "events": []}


def _copy_file(source: Path, destination: Path, entry: dict, limit_bytes: int | None) -> dict:
    """Copy one file through `.part`. Returns the event; raises on refusal or injected stop."""
    part = destination.with_name(destination.name + ".part")
    resumed = 0
    if part.exists():
        resumed = part.stat().st_size
        if resumed > entry["bytes"] or sha256_file(part) != sha256_file(source, resumed):
            raise TransferRefused("partial_diverged", entry["path"])
    digest = hashlib.sha256()
    written = 0
    with open(source, "rb") as reader, open(part, "ab") as writer:
        prefix = reader.read(resumed)
        digest.update(prefix)
        while True:
            block = reader.read(CHUNK)
            if not block:
                break
            if limit_bytes is not None and written + len(block) > limit_bytes:
                block = block[:max(0, limit_bytes - written)]
                writer.write(block)
                writer.flush()
                os.fsync(writer.fileno())
                raise TransferRefused("interrupted", entry["path"])
            digest.update(block)
            writer.write(block)
            written += len(block)
        writer.flush()
        os.fsync(writer.fileno())
    if digest.hexdigest() != entry["sha256"] or part.stat().st_size != entry["bytes"]:
        # The part keeps the source's current bytes as evidence; the source changed after the seal.
        raise TransferRefused("source_changed_after_seal", entry["path"])
    if sha256_file(part) != entry["sha256"]:
        raise TransferRefused("staged_hash_mismatch", entry["path"])
    os.replace(part, destination)
    _fsync_dir(destination.parent)
    return {"path": entry["path"], "action": "copied", "resumed_from_bytes": resumed,
            "bytes": entry["bytes"]}


def stage_root(manifest: dict, root_id: str, source_root: str | Path, staging_root: str | Path,
               journal_path: str | Path, limit_bytes: int | None = None) -> dict:
    """Copy one sealed manifest root into staging. `limit_bytes` is a test/throttle hook that stops
    after that many newly written bytes, leaving a resumable `.part` (reported as interrupted)."""
    if not verify_manifest_digest(manifest):
        raise TransferRefused("manifest_digest_invalid")
    if root_id not in manifest["roots"]:
        raise TransferRefused("unknown_root", root_id)
    source, staging, journal_file = Path(source_root), Path(staging_root), Path(journal_path)
    if source.resolve() == staging.resolve():
        raise TransferRefused("staging_is_source")
    if journal_file.absolute().is_relative_to(staging.absolute()):
        raise TransferRefused("journal_inside_staging")
    staging.mkdir(parents=True, exist_ok=True)
    binding = {"migration_id": manifest["migration_id"], "manifest_digest": manifest["digest"],
               "root_id": root_id}
    journal = _load_journal(journal_file, binding)
    events, remaining = [], limit_bytes
    status = "complete"
    for entry in manifest["roots"][root_id]["entries"]:
        destination = staging / entry["path"]
        if entry["kind"] == "symlink":
            if entry["escapes_root"]:
                events.append({"path": entry["path"], "action": "external_symlink_not_created"})
                status = "needs_decision"
            elif destination.is_symlink() and os.readlink(destination) == entry["link_target"]:
                events.append({"path": entry["path"], "action": "verified_existing"})
            elif os.path.lexists(destination):
                raise TransferRefused("staged_conflict", entry["path"])
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(entry["link_target"], destination)
                events.append({"path": entry["path"], "action": "symlink_created"})
            continue
        if entry["kind"] != "file":
            events.append({"path": entry["path"], "action": "special_not_copied"})
            status = "needs_decision"
            continue
        if os.path.lexists(destination):
            if destination.is_symlink() or not destination.is_file() or sha256_file(destination) != entry["sha256"]:
                raise TransferRefused("staged_conflict", entry["path"])
            journal["completed"][entry["path"]] = entry["sha256"]
            events.append({"path": entry["path"], "action": "verified_existing"})
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            event = _copy_file(source / entry["path"], destination, entry, remaining)
        except TransferRefused as exc:
            if exc.reason == "interrupted":
                journal["events"].append({"path": entry["path"], "action": "interrupted"})
                _write_json_atomic(journal_file, journal)
                return {"status": "interrupted", "events": events + [{"path": entry["path"],
                                                                      "action": "interrupted"}]}
            raise
        if remaining is not None:
            remaining -= entry["bytes"] - event["resumed_from_bytes"]
        journal["completed"][entry["path"]] = entry["sha256"]
        journal["events"].append(event)
        _write_json_atomic(journal_file, journal)
        events.append(event)
    _write_json_atomic(journal_file, journal)
    return {"status": status, "events": events, "journal": str(journal_file)}


def verify_staged(manifest: dict, root_id: str, staging_root: str | Path) -> dict:
    """Re-scan the staged tree and compare every entry with the sealed manifest."""
    if not verify_manifest_digest(manifest):
        return {"match": False, "problems": ["manifest_digest_invalid"]}
    staged = scan_root(staging_root)
    staged["entries"] = [e for e in staged["entries"] if not e["path"].endswith(".part")]
    result = compare_roots(manifest["roots"][root_id], staged)
    leftovers = [e["path"] for e in scan_root(staging_root)["entries"] if e["path"].endswith(".part")]
    result["partials"] = leftovers
    result["match"] = result["match"] and not leftovers
    return result
