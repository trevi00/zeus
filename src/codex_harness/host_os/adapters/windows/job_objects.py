"""Windows job objects: the kill-on-close boundary of an owned process tree (W-B, §5.5).

Layer: adapters
Context: host_os
Owns: the kernel32 prototypes, job creation, membership checks, thread resume, job accounting
Does not own: the tree receipt (host_os.adapters.process_tree), process creation (the one spawn
chokepoint in host_os.adapters.process_groups)
Entry points: create_job, assign, resume, abandon_spawn, active_in_job, terminate, close,
CREATE_SUSPENDED

Moved verbatim out of the M7 `adapters/process_tree.py` Windows branch (design §5.5 W-B: Windows
execution branches live in an `adapters/windows/` subpackage, not constructible in the Linux
production composition; retirement is U6a). Importing this module on POSIX defines the functions
but loads no Windows library; `process_tree` imports it only when `os.name == "nt"`.
"""
from __future__ import annotations

import os
import subprocess

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


def create_job():
    """`(job, None)` for a new KILL_ON_JOB_CLOSE job, or `(None, reason)`; the caller raises."""
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, "CreateJobObject failed: " + str(ctypes.get_last_error())
    limits = _EXTENDED_LIMIT()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                             ctypes.byref(limits), ctypes.sizeof(limits)):
        _kernel32.CloseHandle(job)
        return None, "SetInformationJobObject failed: " + str(ctypes.get_last_error())
    return job, None


def assign(job, pid) -> bool:
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


def resume(pid) -> bool:
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


def abandon_spawn(job, process, *, timeout: float = 10.0) -> dict:
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


def active_in_job(job):
    accounting = _BASIC_ACCOUNTING()
    if not _kernel32.QueryInformationJobObject(job, JobObjectBasicAccountingInformation,
                                               ctypes.byref(accounting), ctypes.sizeof(accounting), None):
        return None
    return int(accounting.ActiveProcesses)


def terminate(job, exit_code: int = 1) -> bool:
    return bool(_kernel32.TerminateJobObject(job, exit_code))


def close(handle) -> None:
    _kernel32.CloseHandle(handle)
