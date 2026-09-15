"""A temporary directory one run owns: what must be kept leaves first, then the scratch goes.

Two things were wrong with removing a run's scratch by calling `rmtree(ignore_errors=True)` five
times with a sleep between.

The first is that it treats every refusal as slowness. Measured on this machine (git 2.55.0.windows,
a throwaway repository with a linked worktree and packed objects), five attempts leave exactly the
same four files every time: `.git/objects/info/commit-graph` and the pack's `.idx`, `.pack` and
`.rev`. Git marks packed objects read-only, and on Windows the read-only attribute makes `DeleteFile`
answer ERROR_ACCESS_DENIED. Waiting cannot change an attribute. On Linux the same four files are
equally read-only and the same removal succeeds, because there unlinking depends on the *directory*
being writable. So the failure is a platform difference in what an attribute means, not a race. A
file somebody still has open is the other refusal, ERROR_SHARING_VIOLATION, and that one is real:
it goes away when the handle closes and never before.

The second is that it throws away the evidence. The scratch holds the execution artifact the
receipt points at, the diff the task produced and the log of the test run this runner performed.
Removing the directory first and recording `execution_ref` afterwards leaves a receipt whose
evidence cannot be opened. So preservation comes first, is verified by reading the copies back and
hashing them, and a failure to preserve keeps the scratch instead of tidying it away.

Everything here is confined to the root this object created. A path that resolves outside it is
refused rather than followed, and a link is removed as a link and never descended into, so nothing
on the other side of it is touched.
"""
from __future__ import annotations

import errno
import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path

from codex_harness.domain.model import ContractError, require

CAUSES = ("read_only_attribute", "in_use", "not_empty", "denied", "other")
# A directory that still holds something is not an obstacle of its own: it is the shape of the
# obstacle underneath it. Both are reported, and only the one underneath decides what to do next.
CONSEQUENTIAL = ("not_empty",)
REMOVAL_TIMEOUT = 60.0
REPORTED_REMAINING = 50


class ScratchEscape(ContractError):
    """A path under the scratch resolved outside it. Nothing is removed on the other side of that."""


class PreservationFailed(ContractError):
    """What had to be kept could not be verified on disk, so the scratch is kept as well."""


def file_digest(path: Path) -> str:
    reader = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            reader.update(block)
    return "sha256:" + reader.hexdigest()


def _cause(exc: OSError, writable: bool) -> str:
    """Name the refusal from what the operating system said, not from what we assume it meant."""
    if getattr(exc, "winerror", None) == 32 or exc.errno in (errno.EBUSY, errno.ETXTBSY):
        return "in_use"
    if exc.errno in (errno.ENOTEMPTY, errno.EEXIST) or getattr(exc, "winerror", None) == 145:
        return "not_empty"
    if not writable:
        return "read_only_attribute"
    if isinstance(exc, PermissionError):
        return "denied"
    return "other"


def _writable(path: Path) -> bool:
    try:
        return bool(path.lstat().st_mode & stat.S_IWRITE)
    except OSError:
        return True  # unknown; it is never reported as a read-only refusal on a guess


class Scratch:
    """The throwaway directory a run works in. Create it here so its exact root is known."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve(strict=True)
        require(self.root.is_dir(), "A scratch root must be a directory")

    @classmethod
    def create(cls, prefix: str) -> "Scratch":
        return cls(tempfile.mkdtemp(prefix=prefix))

    # ---- containment -----------------------------------------------------------------------------
    def within(self, path: Path) -> bool:
        """Whether a path's final resolved location is inside the exact root this run created."""
        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        return resolved == self.root or self.root in resolved.parents

    def _require_within(self, path: Path, report: dict) -> None:
        if self.within(path):
            return
        record = {"path": str(path), "resolves_to": str(Path(path).resolve(strict=False))}
        report["escapes"].append(record)
        raise ScratchEscape("A path under the scratch resolves outside it: " + str(path))

    # ---- keeping what matters --------------------------------------------------------------------
    def preserve(self, destination: Path, entries: list) -> dict:
        """Copy the evidence out and prove it arrived, before anything is removed.

        Each entry is `{"name": ..., "source": <path inside this scratch>}` or
        `{"name": ..., "text": ...}`. The copy is read back from disk and hashed: a receipt that
        points at evidence has to point at bytes somebody can still open.
        """
        destination = Path(destination)
        kept, failures = [], []
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Not being able to make the destination is a preservation failure like any other, and
            # the caller needs it as a result rather than as an exception thrown past its reporting.
            return {"destination": str(destination), "kept": [], "complete": False,
                    "failures": [{"name": str(destination), "error": type(exc).__name__,
                                  "message": str(exc)[:400]}],
                    "note": "the destination directory could not be created; nothing was copied"}
        for entry in entries:
            name = str(entry["name"])
            target = destination / name
            try:
                if "source" in entry:
                    source = Path(entry["source"])
                    if not self.within(source):
                        raise ScratchEscape("Refusing to preserve a path outside the scratch: " + str(source))
                    payload = source.read_bytes()
                    origin = str(source)
                else:
                    payload = str(entry["text"]).encode("utf-8")
                    origin = "produced by the runner"
                target.parent.mkdir(parents=True, exist_ok=True)
                # Exclusive: evidence already on disk belongs to a run that already finished, and
                # its receipt still names that file's digest. A second run writes beside it or
                # fails; it never writes through it, not even partially.
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                expected = "sha256:" + hashlib.sha256(payload).hexdigest()
                observed = file_digest(target)  # read back: the copy is the thing being claimed
                if observed != expected or target.stat().st_size != len(payload):
                    raise PreservationFailed("The preserved copy does not match what was written")
                kept.append({"name": name, "path": str(target), "bytes": len(payload),
                             "sha256": observed, "origin": origin, "verified": True})
            except (OSError, ValueError, ContractError) as exc:
                failures.append({"name": name, "error": type(exc).__name__, "message": str(exc)[:400]})
        return {"destination": str(destination), "kept": kept, "failures": failures,
                "complete": not failures,
                "note": "each copy was read back from disk and hashed; nothing here is assumed"}

    # ---- giving the space back -------------------------------------------------------------------
    def remove(self, *, timeout: float = REMOVAL_TIMEOUT) -> dict:
        """Remove the scratch and say exactly what refused, one cause at a time.

        A read-only file inside this root is this run's own leftover, so the attribute is cleared and
        the removal retried. A file somebody still holds open is a bounded failure: it is reported
        with its path and cause and left where it is, because forcing it would mean reaching outside
        this process's business.
        """
        report = {"root": str(self.root), "removed": False, "cleared_read_only": [],
                  "links_removed": [], "refusals": [], "escapes": [], "timed_out": False,
                  "seconds": 0.0}
        started = time.monotonic()
        deadline = started + float(timeout)
        try:
            if self.root.exists():
                self._purge(self.root, report, deadline)
                self._rmdir(self.root, report)
        except ScratchEscape as exc:
            report["aborted"] = {"reason": "path_escaped_the_scratch", "detail": str(exc)[:400]}
        report["seconds"] = round(time.monotonic() - started, 3)
        report["removed"] = not self.root.exists()
        remaining = self._remaining()
        report["remaining"] = remaining[:REPORTED_REMAINING]
        report["remaining_count"] = len(remaining)
        blocking = [refusal for refusal in report["refusals"]
                    if refusal["cause"] not in CONSEQUENTIAL]
        report["blocking_refusals"] = blocking
        report["recleanable"] = bool(blocking) and not report["escapes"] and all(
            refusal["cause"] == "in_use" for refusal in blocking)
        report["note"] = ("a read-only file inside this root is cleared and removed; an open file is "
                          "reported and left; nothing outside this root is touched")
        return report

    def _purge(self, directory: Path, report: dict, deadline: float) -> None:
        try:
            with os.scandir(directory) as entries:
                children = list(entries)
        except FileNotFoundError:
            return
        except OSError as exc:
            report["refusals"].append({"path": self._relative(directory), "cause": _cause(exc, True),
                                       "errno": errno.errorcode.get(exc.errno, exc.errno),
                                       "winerror": getattr(exc, "winerror", None),
                                       "operation": "scandir"})
            return
        for entry in children:
            if time.monotonic() >= deadline:
                report["timed_out"] = True
                return
            path = Path(entry.path)
            # A link is removed as a link. Descending into one would leave this root, and what is on
            # the other side belongs to somebody else.
            if entry.is_symlink() or entry.is_junction():
                self._drop_link(path, entry, report)
                continue
            self._require_within(path, report)
            if entry.is_dir(follow_symlinks=False):
                self._purge(path, report, deadline)
                self._rmdir(path, report)
            else:
                self._unlink(path, report)

    def _drop_link(self, path: Path, entry, report: dict) -> None:
        target = None
        try:
            target = os.readlink(path)
        except OSError:
            target = "unreadable"
        record = {"path": self._relative(path), "target": str(target),
                  "kind": "junction" if entry.is_junction() else "symlink",
                  "target_inside_scratch": self.within(path),
                  "note": "removed as a link; never followed"}
        try:
            if entry.is_dir(follow_symlinks=False) or entry.is_junction():
                os.rmdir(path)
            else:
                path.unlink()
            record["removed"] = True
        except OSError as exc:
            record["removed"] = False
            report["refusals"].append({"path": self._relative(path), "cause": _cause(exc, True),
                                       "errno": errno.errorcode.get(exc.errno, exc.errno),
                                       "winerror": getattr(exc, "winerror", None),
                                       "operation": "unlink_link"})
        report["links_removed"].append(record)

    def _unlink(self, path: Path, report: dict) -> None:
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            failure = exc
        writable = _writable(path)
        if not writable:
            # The attribute belongs to a file this run's own git made. Clearing it is the fix that
            # retrying never was, and it happens only for a path proven to be inside this root.
            self._require_within(path, report)
            try:
                os.chmod(path, stat.S_IWRITE)
                path.unlink()
                report["cleared_read_only"].append(self._relative(path))
                return
            except OSError as exc:
                failure = exc
                writable = _writable(path)
        report["refusals"].append({"path": self._relative(path), "cause": _cause(failure, writable),
                                   "errno": errno.errorcode.get(failure.errno, failure.errno),
                                   "winerror": getattr(failure, "winerror", None),
                                   "read_only_attribute": not writable, "operation": "unlink"})

    def _rmdir(self, path: Path, report: dict) -> None:
        try:
            os.rmdir(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            report["refusals"].append({"path": self._relative(path), "cause": _cause(exc, True),
                                       "errno": errno.errorcode.get(exc.errno, exc.errno),
                                       "winerror": getattr(exc, "winerror", None),
                                       "operation": "rmdir"})

    def _relative(self, path: Path) -> str:
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            return str(path)

    def _remaining(self) -> list:
        if not self.root.exists():
            return []
        found = []
        for current, directories, files in os.walk(self.root):
            for name in files + directories:
                found.append(self._relative(Path(current) / name))
        return sorted(found)
