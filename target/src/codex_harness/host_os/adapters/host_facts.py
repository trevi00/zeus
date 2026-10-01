"""What `/proc` and the cgroup v2 tree say about processes (INV-HOST-DELIVERY-VERIFY-001).

Layer: adapters
Context: host_os
Owns: HostFacts (pid presence and start ticks, boot id, cgroup path and members, the owner identity) and the PRESENT/ABSENT/UNKNOWN answers (M7 `adapters/release_verifier.py`, moved ahead of S8)
Does not own: the release verifier and its attempt reconcile (S8), the signals and the kill of a process (process_groups, process_tree)
Entry points: HostFacts, PRESENT, ABSENT, UNKNOWN
Contracts: INV-HOST-DELIVERY-VERIFY-001

Moved ahead of its slice from M7 `adapters/release_verifier.py` (SOURCE e38aa722) through named rules (DESIGN-s7 adapters-move, A/evidence/rebuild/s7/host-facts/transcribe.py); the only changes are this header and the imports; every body is otherwise M7's. Pure `/proc` and cgroup reads: it imports the standard library only.
"""
from __future__ import annotations

import os
from pathlib import Path

PRESENT, ABSENT, UNKNOWN = "present", "absent", "unknown"


class HostFacts:
    """What `/proc` and the cgroup v2 tree say about processes.

    An unreadable fact is None (unknown). Absence is reported only where it is proven
    (INV-HOST-DELIVERY-VERIFY-001): a failed or unparseable observation is never read as "gone".
    A process fact or boot id is an observation only under a proc root that shows this process as
    itself; under any other root every one of them is unknown.
    """

    def __init__(self, proc="/proc", cgroup_root="/sys/fs/cgroup"):
        self.proc, self.cgroup_root = Path(proc), Path(cgroup_root)

    def boot_id(self):
        """None when unreadable, or read under a root that is not observable for this process: such
        a boot id is never taken for another boot (INV-HOST-DELIVERY-VERIFY-001)."""
        try:
            boot = (self.proc / "sys" / "kernel" / "random" / "boot_id").read_text("ascii").strip() or None
        except (OSError, ValueError):
            return None
        return boot if boot and self._observable() else None

    def _ticks(self, name: str, pid: int) -> int:
        """Field 22 of `/proc/<name>/stat`, whose first field must be `pid`. Raises OSError when it
        cannot be read and ValueError when it is not a whole stat line of that pid."""
        text = (self.proc / name / "stat").read_text("utf-8", errors="replace")
        fields = text[text.rindex(")") + 1:].split()
        if text.split(" (", 1)[0] != str(pid) or len(fields) < 20 or not (
                fields[19].isascii() and fields[19].isdigit()):
            raise ValueError("unparseable stat")
        return int(fields[19])

    def _observable(self) -> bool:
        """This proc root shows THIS process as itself (same mount, same pid namespace)."""
        try:
            self._ticks("self", os.getpid())
        except (OSError, ValueError):
            return False
        return True

    def process(self, pid):
        """`(PRESENT, start_ticks)`, `(ABSENT, None)` or `(UNKNOWN, None)` for one pid.

        INV-HOST-DELIVERY-VERIFY-001: ABSENT is confirmed only when `/proc/<pid>` does not exist
        (ENOENT/ESRCH), and PRESENT only when its whole stat names that pid - both under a proc
        root that is observable for this very process: under any other root (another pid
        namespace's mount, no `self`) a pid names nothing recorded here, so neither its absence nor
        its start time proves anything. EACCES, EIO or any other read error, an unparseable or
        truncated stat, a stat of another pid, an unobservable proc root or a pid that is not a
        positive int is UNKNOWN - never absence, never another start time.
        """
        if type(pid) is not int or pid <= 0:
            return UNKNOWN, None
        try:
            answer = PRESENT, self._ticks(str(pid), pid)
        except (FileNotFoundError, ProcessLookupError):
            answer = self._missing(pid)
        except (OSError, ValueError):
            return UNKNOWN, None
        return answer if answer[0] != UNKNOWN and self._observable() else (UNKNOWN, None)

    def _missing(self, pid: int):
        """After ENOENT/ESRCH on its stat: ABSENT only if `/proc/<pid>` itself is gone too."""
        try:
            os.lstat(self.proc / str(pid))
        except (FileNotFoundError, ProcessLookupError):
            return ABSENT, None
        except OSError:
            return UNKNOWN, None
        return UNKNOWN, None  # its directory is still there without a readable stat: no proof

    def start_ticks(self, pid):
        """Field 22 of `/proc/<pid>/stat`: the start time that makes a pid a process identity.
        None when absent OR unknown; `process` is what tells the two apart."""
        return self.process(pid)[1]

    def cgroup(self, pid="self"):
        try:
            lines = (self.proc / str(pid) / "cgroup").read_text("utf-8").splitlines()
        except (OSError, ValueError):
            return None
        paths = [line[3:] for line in lines if line.startswith("0::")]
        return paths[0] if len(paths) == 1 and paths[0].startswith("/") else None

    def members(self, cgroup):
        """The pids of one cgroup: [] only when it provably no longer exists, None when unknown.

        INV-HOST-DELIVERY-VERIFY-001: a missing directory is absence (a unit's cgroup is removed
        when it is empty) only under an observable cgroup v2 root - its `cgroup.controllers` is
        readable. A missing or unmounted root, a hybrid layout, an unreadable path or a directory
        without its member list is unknown, never an empty cgroup.
        """
        if not (isinstance(cgroup, str) and cgroup.startswith("/") and ".." not in cgroup.split("/")):
            return None
        try:
            (self.cgroup_root / "cgroup.controllers").read_text("ascii")
        except (OSError, ValueError):
            return None
        directory = self.cgroup_root / cgroup.lstrip("/")
        try:
            return [int(value) for value in (directory / "cgroup.procs").read_text("ascii").split()]
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            return None
        try:
            os.lstat(directory)
        except FileNotFoundError:
            return []
        except OSError:
            return None
        return None

    def owner(self):
        """This process's identity, or None when it is not observable here: an attempt never
        records an identity read under a foreign or unobservable proc root."""
        pid = os.getpid()
        owner = {"pid": pid, "start_ticks": self.start_ticks(pid), "boot_id": self.boot_id(),
                 "cgroup": self.cgroup()}
        return owner if owner["start_ticks"] is not None and owner["boot_id"] else None
