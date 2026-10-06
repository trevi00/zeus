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

Layer: adapters
Context: host_os
Owns: one owned process tree from spawn to its two-part termination receipt
Does not own: the Windows job-object primitives (host_os.adapters.windows.job_objects), process
creation itself (host_os.adapters.process_groups.popen, the one spawn chokepoint)
Entry points: ProcessTree.spawn, ProcessTree.terminate, ProcessTree.close, TreeOwnershipError (defined in
host_os.ports, S8 V26 E-4a; imported here, so `process_tree.TreeOwnershipError is ports.TreeOwnershipError`),
TreeOwnershipLeak
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

from codex_harness.host_os.adapters.process_groups import no_console_kwargs, popen
from codex_harness.host_os.ports import TreeOwnershipError

if os.name == "nt":  # pragma: no cover - exercised on Windows hosts
    from codex_harness.host_os.adapters.windows import job_objects


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
    job, failure = job_objects.create_job()
    if job is None:
        raise TreeOwnershipError(failure)
    return job


def _close_pipes(process) -> None:
    """Give back the pipe ends of a process that never ran; nothing is going to read them."""
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


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
            process = popen(argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout,
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
            # Suspended, in its own group, and without a console window; the boundary and the
            # resume order are unchanged by the console policy.
            process = popen(
                argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                **no_console_kwargs(process_group=True, creationflags=job_objects.CREATE_SUSPENDED))
            if not job_objects.assign(job, process.pid):
                raise TreeOwnershipError("the process could not be placed in its job object")
            if not job_objects.resume(process.pid):
                raise TreeOwnershipError("the process could not be resumed inside its job object")
        except BaseException as exc:
            # The process was created before the boundary was proven, so the cleanup cannot assume
            # the job owns it. It kills through our own handle as well and then reads the exit
            # status. Only an exit status lets this stay a start that left nothing behind.
            cleanup = None
            if process is not None:
                cleanup = job_objects.abandon_spawn(job, process)
                _close_pipes(process)
            job_objects.close(job)
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
                record["signalled"] = job_objects.terminate(self._job, 1)
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
            job_objects.terminate(self._job, 1)
            active = job_objects.active_in_job(self._job)
            while active not in (0, None) and time.monotonic() < deadline:
                time.sleep(0.1)
                active = job_objects.active_in_job(self._job)
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
            job_objects.close(self._job)  # kill-on-close: nothing survives this
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
