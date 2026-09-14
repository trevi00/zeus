"""A process this harness started, plus everything it starts, owned from the moment it is created.

The parent's absence is not the descendants' absence. A child can outlive its parent, and a kill
command that answers "no such process" after the parent has already exited has killed nothing; a
receipt built on either of those reads a surviving grandchild as a terminated tree.

So the tree is owned rather than hunted. On Windows the process is created suspended, assigned to
a job object that kills everything in it when the job closes, verified to be in that job, and only
then resumed: it never executes an instruction outside the boundary, every process it creates joins
the job, and after `TerminateJobObject` the job's own accounting says whether any member is left.
On POSIX it starts in a new session, so the process group is the boundary, the group id is captured
at spawn rather than read back from a process that may already be gone, and the group is polled
until it is empty whether or not the leader exited first.

Two receipts come out, never one: what happened to the process this harness started, and what
happened to the tree. Only the pair is a termination, and what cannot be proven stays unproven.

A boundary that fails owns what it has already made. The process exists before its membership is
proven, so ending a job that never accepted it ends nothing and the created process stays behind
suspended, holding a pid, once per attempt. The cleanup therefore kills through the handle this
module holds as well, and answers with the process's own exit status. With that status the failure
is a start that left nothing; without it the failure is a different thing entirely, and it says so
by name.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    JobObjectBasicAccountingInformation = 1
    # PROCESS_SET_QUOTA and PROCESS_TERMINATE to assign, QUERY_LIMITED_INFORMATION to ask whether
    # the assignment took: without the query right IsProcessInJob refuses and the boundary would be
    # assumed rather than verified.
    PROCESS_RIGHTS = 0x0100 | 0x0001 | 0x1000
    # Python's subprocess module exposes no CREATE_SUSPENDED; this is the Win32 creation flag.
    CREATE_SUSPENDED = 0x00000004
    THREAD_SUSPEND_RESUME = 0x0002
    TH32CS_SNAPTHREAD = 0x00000004
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [("TotalUserTime", wintypes.LARGE_INTEGER),
                    ("TotalKernelTime", wintypes.LARGE_INTEGER),
                    ("ThisPeriodTotalUserTime", wintypes.LARGE_INTEGER),
                    ("ThisPeriodTotalKernelTime", wintypes.LARGE_INTEGER),
                    ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                    ("tpBasePri", ctypes.c_long), ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD)]

    # Every prototype is declared. Without a restype ctypes hands back a C int, which truncates a
    # 64-bit handle to something that names nothing, and every call after it fails for a reason
    # that has nothing to do with the boundary being asked for.
    for _name, _restype, _argtypes in (
            ("CreateJobObjectW", wintypes.HANDLE, (wintypes.LPVOID, wintypes.LPCWSTR)),
            ("SetInformationJobObject", wintypes.BOOL,
             (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)),
            ("QueryInformationJobObject", wintypes.BOOL,
             (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD)),
            ("TerminateJobObject", wintypes.BOOL, (wintypes.HANDLE, wintypes.UINT)),
            ("AssignProcessToJobObject", wintypes.BOOL, (wintypes.HANDLE, wintypes.HANDLE)),
            ("IsProcessInJob", wintypes.BOOL,
             (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))),
            ("OpenProcess", wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
            ("OpenThread", wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
            ("ResumeThread", wintypes.DWORD, (wintypes.HANDLE,)),
            ("CreateToolhelp32Snapshot", wintypes.HANDLE, (wintypes.DWORD, wintypes.DWORD)),
            ("Thread32First", wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32))),
            ("Thread32Next", wintypes.BOOL, (wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32))),
            ("CloseHandle", wintypes.BOOL, (wintypes.HANDLE,))):
        _function = getattr(_kernel32, _name)
        _function.restype = _restype
        _function.argtypes = _argtypes


class TreeOwnershipError(RuntimeError):
    """The boundary could not be established, and nothing this harness created is still there."""


class TreeOwnershipLeak(TreeOwnershipError):
    """The boundary failed and a process this harness created could not be proven gone.

    This is deliberately a different answer from `TreeOwnershipError`. "Nothing started" may be
    retried; "something was created and I cannot say it is gone" may not, because a retry would add
    a second one to whatever the first one is. The detail says what was attempted and what the
    process's own exit status was, so the refusal names a thing an operator can go and look at.
    """

    def __init__(self, message: str, *, detail: dict):
        super().__init__(message)
        self.detail = detail


def _windows_job():
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise TreeOwnershipError("CreateJobObject failed: " + str(ctypes.get_last_error()))
    limits = _EXTENDED_LIMIT()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                             ctypes.byref(limits), ctypes.sizeof(limits)):
        _kernel32.CloseHandle(job)
        raise TreeOwnershipError("SetInformationJobObject failed: " + str(ctypes.get_last_error()))
    return job


def _assign(job, pid) -> bool:
    handle = _kernel32.OpenProcess(PROCESS_RIGHTS, False, pid)
    if not handle:
        return False
    try:
        if not _kernel32.AssignProcessToJobObject(job, handle):
            return False
        member = wintypes.BOOL()
        if not _kernel32.IsProcessInJob(handle, job, ctypes.byref(member)):
            return False
        return bool(member.value)
    finally:
        _kernel32.CloseHandle(handle)


def _resume(pid) -> bool:
    """Resume every thread of the suspended process; it has run nothing until this returns."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == INVALID_HANDLE:
        return False
    entry = _THREADENTRY32()
    entry.dwSize = ctypes.sizeof(_THREADENTRY32)
    resumed = 0
    try:
        found = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if thread:
                    try:
                        if _kernel32.ResumeThread(thread) != 0xFFFFFFFF:
                            resumed += 1
                    finally:
                        _kernel32.CloseHandle(thread)
            found = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return resumed > 0


def _abandon_windows_spawn(job, process, *, timeout: float = 10.0) -> dict:
    """End what was created when the boundary failed, and say plainly what is left.

    Terminating the job kills the job's members, and a process whose assignment failed is not one:
    the job is empty and the process outlives it, suspended, holding a pid. The handle `Popen` owns
    is the one thing that is certainly ours, so the kill goes through that as well. What answers is
    the process's own exit status, never the return value of a call that asked for the kill.
    """
    record = {"pid": process.pid, "job_terminated": bool(_kernel32.TerminateJobObject(job, 1)),
              "killed_by_own_handle": None}
    if process.poll() is None:
        try:
            process.kill()  # TerminateProcess through our handle; a suspended process dies too
            record["killed_by_own_handle"] = True
        except OSError as exc:
            record["killed_by_own_handle"] = type(exc).__name__
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        record["waited_out"] = True
    record["exit_code"] = process.returncode
    record["left_running"] = process.poll() is None
    return record


def _close_pipes(process) -> None:
    """Give back the pipe ends of a process that never ran; nothing is going to read them."""
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _active_in_job(job):
    accounting = _BASIC_ACCOUNTING()
    if not _kernel32.QueryInformationJobObject(job, JobObjectBasicAccountingInformation,
                                               ctypes.byref(accounting), ctypes.sizeof(accounting), None):
        return None
    return int(accounting.ActiveProcesses)


class ProcessTree:
    """One owned process tree. Construct with `spawn`, end with `terminate`."""

    def __init__(self, process, *, boundary: dict, job=None, group=None):
        self.process = process
        self.boundary = boundary
        self._job = job
        self._group = group
        self.receipt: dict | None = None

    @classmethod
    def spawn(cls, argv, *, cwd=None, env=None, stdin=None, stdout=None, stderr=None) -> "ProcessTree":
        if os.name != "nt":
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            # The group id is captured here, not read back later from a process that may be gone.
            try:
                group = os.getpgid(process.pid)
            except (ProcessLookupError, OSError):
                group = process.pid  # start_new_session makes the child its own group leader
            return cls(process, job=None, group=group,
                       boundary={"kind": "process_group", "owned_from_spawn": True, "group": group,
                                 "limit": "a descendant that calls setsid leaves this group and "
                                          "cannot be proven gone from here"})
        job = _windows_job()
        process = None
        try:
            process = subprocess.Popen(
                argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                creationflags=CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP)
            if not _assign(job, process.pid):
                raise TreeOwnershipError("the process could not be placed in its job object")
            if not _resume(process.pid):
                raise TreeOwnershipError("the process could not be resumed inside its job object")
        except BaseException as exc:
            # The process was created before the boundary was proven, so the cleanup cannot assume
            # the job owns it. It kills through our own handle as well and then reads the exit
            # status. Only an exit status lets this stay a start that left nothing behind.
            cleanup = None
            if process is not None:
                cleanup = _abandon_windows_spawn(job, process)
                _close_pipes(process)
            _kernel32.CloseHandle(job)
            if cleanup is not None and cleanup["left_running"]:
                raise TreeOwnershipLeak(
                    "the boundary failed and the process created for it could not be proven gone",
                    detail={"cause": type(exc).__name__ + ": " + str(exc), "cleanup": cleanup}) from exc
            raise
        return cls(process, job=job, group=None,
                   boundary={"kind": "job_object", "owned_from_spawn": True,
                             "created_suspended": True, "verified_member": True,
                             "limit": "a process created with CREATE_BREAKAWAY_FROM_JOB would "
                                      "leave this job; the child is resumed only after it is a member"})

    # ---- ending it -------------------------------------------------------------------------------
    def terminate(self, reason: str, *, timeout: float = 20.0, settle: float = 10.0) -> dict:
        """Stop the tree and report the parent and the tree separately; only both together end it."""
        parent = self._end_parent(reason, timeout)
        tree = self._end_tree(settle)
        receipt = {"reason": reason, "boundary": dict(self.boundary), "parent": parent, "tree": tree,
                   "confirmed": bool(parent["confirmed"]) and bool(tree["confirmed"]),
                   "note": "a terminated parent is not a terminated tree; acceptance needs both"}
        self.receipt = receipt
        return receipt

    def _end_parent(self, reason: str, timeout: float) -> dict:
        process = self.process
        record = {"pid": process.pid, "already_exited": process.poll() is not None,
                  "signalled": None, "escalated": False}
        if process.poll() is None:
            if os.name == "nt":
                record["signalled"] = bool(_kernel32.TerminateJobObject(self._job, 1))
            else:
                try:
                    os.killpg(self._group, signal.SIGTERM)
                    record["signalled"] = True
                except (ProcessLookupError, PermissionError, OSError) as exc:
                    record["signalled"] = type(exc).__name__
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["escalated"] = True
                try:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(self._group, signal.SIGKILL)
                    process.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError, OSError) as exc:
                    record["escalation_error"] = type(exc).__name__
        else:
            record["ended_on_its_own"] = True
        record["exit_code"] = process.returncode
        # An exit code in hand is the proof; nothing a kill command reports can withdraw it.
        record["confirmed"] = process.poll() is not None
        return record

    def _end_tree(self, settle: float) -> dict:
        """Every process in the boundary, including ones the parent left behind."""
        deadline = time.monotonic() + settle
        if os.name == "nt":
            _kernel32.TerminateJobObject(self._job, 1)
            active = _active_in_job(self._job)
            while active not in (0, None) and time.monotonic() < deadline:
                time.sleep(0.1)
                active = _active_in_job(self._job)
            record = {"method": "job_object", "active_processes": active,
                      "confirmed": active == 0,
                      "evidence": "the job's own accounting of how many of its processes are alive"}
            return record
        try:
            os.killpg(self._group, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        state = _group_state(self._group, deadline)
        return {"method": "process_group", "group": self._group, "group_empty": state,
                "confirmed": state is True,
                "evidence": "signal zero to the group until no member answers"}

    def close(self) -> None:
        if os.name == "nt" and self._job is not None:
            _kernel32.CloseHandle(self._job)  # kill-on-close: nothing survives this
            self._job = None


def _group_state(group: int, deadline: float):
    """True when the group is empty, False when it still has members, None when unknowable."""
    while True:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return None
        except OSError:
            return None
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
