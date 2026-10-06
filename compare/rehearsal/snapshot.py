"""Guard-free snapshot helpers for the volatile/stable file roots (RH-1b), moved verbatim out of `copies`.

`copies` exec-loads `compare/run.py`, which installs the provider guard; the production Phase P path must never import
that (RH-2c), so the scan/snapshot code lives here. Standard library plus `Refused` only; nothing here installs the guard.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
from pathlib import Path

from . import Refused


def _rel_parts(rel: str) -> tuple[str, ...]:
    parts = tuple(p for p in rel.split("/") if p)
    if not parts or ".." in parts or rel.startswith("/"):
        raise Refused("volatile_path_bad", rel)
    return parts


# Critique #5: the live roots are written continuously, so a sealed whole-tree copy would refuse; these paths are copied
# as point-in-time single-file snapshots instead. RH-1b: the list is `volatile.json`, derived from the WRITERS of the five
# R0 releases (each entry cites `file:line` at the revisions that write it) and from two read-only name/mtime listings of
# the live roots, and it is CLOSED: a path under `SCAN_ROOTS` that changes during the snapshot and is neither listed nor
# excluded refuses `volatile_undeclared` (RH-8 review: "RH integration must supply the actual paths ...").
VOLATILE_FILE = Path(__file__).with_name("volatile.json")
SCAN_ROOTS = ("runtime", "managed-fleet")  # the production roots the closed list covers, relative to the staged source


def load_volatile(path: Path = VOLATILE_FILE) -> dict:
    """The volatile document, validated: every entry is a safe relative path with at least one writer citation."""
    import json

    document = json.loads(Path(path).read_text(encoding="utf-8"))
    for entry in document["volatile"]:
        _rel_parts(entry["path"])
        if entry["kind"] not in ("file", "dir") or not entry["writers"]:
            raise Refused("volatile_entry_bad", entry["path"])
        for writer in entry["writers"]:
            if not (writer["rev"] in document["r0_revisions"] and writer["line"] >= 1 and writer["file"] and writer["text"]):
                raise Refused("volatile_entry_bad", entry["path"])
    for entry in document["excluded"]:
        _rel_parts(entry["path"])
        if not entry["reason"]:
            raise Refused("volatile_entry_bad", entry["path"])
    return document


_VOLATILE = load_volatile()
VOLATILE_PATHS = tuple(entry["path"] for entry in _VOLATILE["volatile"])
EXCLUDED_PATHS = tuple(entry["path"] for entry in _VOLATILE["excluded"])  # runtime/tokobs: not Zeus state


def scan_tree(source: Path, roots=SCAN_ROOTS, excluded=EXCLUDED_PATHS) -> dict[str, tuple[int, int]]:
    """`{relative path: (mtime_ns, size)}` of every non-directory entry under `roots` (lstat only: names, sizes and
    mtimes, never a content read; excluded subtrees are pruned). A directory's own mtime is a consequence of its entries
    and is not recorded."""
    source = Path(source)
    excl = [_rel_parts(e) for e in excluded]
    found: dict[str, tuple[int, int]] = {}
    pending = [source.joinpath(*_rel_parts(r)) for r in roots]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except FileNotFoundError:
            continue
        for entry in entries:
            rel = Path(entry.path).relative_to(source).as_posix()
            if any(tuple(rel.split("/"))[: len(e)] == e for e in excl):
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
            else:
                found[rel] = (info.st_mtime_ns, info.st_size)
    return found


def _covered(rel: str, listed) -> bool:
    parts = tuple(rel.split("/"))
    return any(parts[: len(p)] == p for p in map(_rel_parts, listed))


def undeclared_changes(before: dict, after: dict, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS) -> list[str]:
    """The paths that appeared, vanished or changed (mtime or size) between two scans and are neither volatile nor excluded."""
    changed = sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel))
    return [rel for rel in changed if not _covered(rel, volatile) and not _covered(rel, excluded)]


def stable_sha256(scan: dict, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS) -> str:
    """One digest over the (path, mtime_ns, size) of every stable file of a scan: what `verify-staged` must see unchanged."""
    lines = [f"{rel} {m} {n}\n" for rel, (m, n) in sorted(scan.items())
             if not _covered(rel, volatile) and not _covered(rel, excluded)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def _read_once(path, label: str):
    """Read `path` through ONE file descriptor (RH-2 P5b-1, D6): open `O_NOFOLLOW|O_NONBLOCK` (a FIFO opens without a
    writer and is refused below, never waited on), `fstat` that descriptor, then read it, so the recorded mtime, mode,
    size and bytes all describe one inode even when a writer rename-replaces the path (rename(2): stat-by-path then
    read-by-path can see two inodes). Returns `(data, info)`, or None when the path does not exist. `label` is the
    source-relative name used in refusals, never an absolute path."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise Refused("volatile_symlink", label) from None
        if error.errno == errno.ENXIO:  # a socket
            raise Refused("volatile_not_regular", label) from None
        raise Refused("volatile_unreadable", label) from None
    try:
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise Refused("volatile_not_regular", label)
            chunks = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:  # the descriptor's metadata or content cannot be read: a named refusal, never a bare OSError
            raise Refused("volatile_unreadable", label) from None
    finally:
        try:
            os.close(fd)
        except OSError:
            raise Refused("volatile_unreadable", label) from None
    return b"".join(chunks), info


def copy_once(path, target, *, label: str | None = None) -> dict | None:
    """Read `path` once (see `_read_once`) and write the bytes to a NEW file `target` (0600, exclusive, no symlink
    following), creating its parents. Returns `{size, mtime_ns, mode, read_at_ns, sha256}` describing exactly the bytes
    written, or None when `path` is gone. Refusals: `volatile_symlink`, `volatile_not_regular`, `volatile_unreadable`
    (read side); `seal_write_failed` for any write-side OSError, an existing target included."""
    label = label if label is not None else Path(path).name
    got = _read_once(path, label)
    if got is None:
        return None
    data, info = got
    read_at = time.time_ns()
    target = Path(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        finally:
            os.close(fd)
    except OSError:
        raise Refused("seal_write_failed", label) from None
    return {"size": len(data), "mtime_ns": info.st_mtime_ns, "mode": stat.S_IMODE(info.st_mode), "read_at_ns": read_at,
            "sha256": hashlib.sha256(data).hexdigest()}


def snapshot_volatile(source: Path, dest: Path, volatile=VOLATILE_PATHS, excluded=EXCLUDED_PATHS, *,
                      scan_roots=SCAN_ROOTS, during=None, admit=None) -> dict:
    """Copy each declared volatile file (or the regular files of a declared directory) from `source` to `dest` once,
    reading it a single time so the recorded size/mtime/mode/sha256 describe exactly the bytes written; the copy is a new
    inode, so a later change on either side never reaches the other. Symlinks and excluded paths are refused/skipped;
    every refusal names a source-relative path or a name.

    `admit`, when given, is called once with the sorted relative paths about to be read, before the first read.

    Fail closed (RH-1b): `scan_roots` are listed (names, sizes, mtimes) before the reads and again after `during()` (the
    staging of the stable subtrees in the real flow, a writer in tests); any other path that changed refuses
    `volatile_undeclared` (the error's `paths` lists them all); the stable files' digest before and after is recorded
    (`stable`)."""
    source, dest = Path(source), Path(dest)
    before = scan_tree(source, scan_roots, excluded) if scan_roots else {}
    excl = [_rel_parts(e) for e in excluded]
    files, skipped = [], []
    for rel in volatile:
        parts = _rel_parts(rel)
        if any(parts[: len(e)] == e or e[: len(parts)] == parts for e in excl):
            raise Refused("volatile_excluded", rel)
        base = source.joinpath(*parts)
        if any(source.joinpath(*parts[: i + 1]).is_symlink() for i in range(len(parts))):
            raise Refused("volatile_symlink", rel)
        try:
            kind = os.lstat(base).st_mode  # one classification per declared path
        except FileNotFoundError:
            skipped.append(rel)
            continue
        if stat.S_ISLNK(kind):
            raise Refused("volatile_symlink", rel)
        if stat.S_ISDIR(kind):
            files += [(rel_file, f) for rel_file, f in _walk(source, base)]
        elif stat.S_ISREG(kind):
            files.append((rel, base))
        else:
            raise Refused("volatile_not_regular", rel)
    reads = []
    for rel, path in sorted(files):
        if any(tuple(rel.split("/"))[: len(e)] == e for e in excl):
            skipped.append(rel)
        else:
            reads.append((rel, path))
    if admit is not None:
        admit([rel for rel, _path in reads])
    entries = []
    for rel, path in reads:
        done = copy_once(path, dest.joinpath(*rel.split("/")), label=rel)
        if done is None:
            skipped.append(rel)
            continue
        entries.append({"path": rel, **done})
    if during is not None:
        during()
    reads = [e["read_at_ns"] for e in entries]
    manifest = {"files": entries, "skipped": sorted(set(skipped)), "excluded": list(excluded),
                "skew_ns": (max(reads) - min(reads)) if reads else 0}
    if scan_roots:
        after = scan_tree(source, scan_roots, excluded)
        undeclared = undeclared_changes(before, after, volatile, excluded)
        if undeclared:
            error = Refused("volatile_undeclared", f"{len(undeclared)} path(s) changed outside the closed list: "
                            + ", ".join(undeclared[:5]))
            error.paths = undeclared
            raise error
        manifest["stable"] = {"files": sum(1 for r in before if not _covered(r, volatile) and not _covered(r, excluded)),
                              "sha256": stable_sha256(before, volatile, excluded),
                              "sha256_after": stable_sha256(after, volatile, excluded), "unchanged": True}
    return manifest


def _walk(source: Path, base: Path):
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink():
                raise Refused("volatile_symlink", name)
            yield full.relative_to(source).as_posix(), full
