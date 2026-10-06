"""docs/zeus/operations/service-ownership-001/SPEC.md: the background owner ends what it started.

Every tree here is a real one: a child process that takes an OS file lock, starts a grandchild that
takes a second lock, and then either exits or stays. Locks are the evidence, because a released
lock is a fact about a process that no longer exists, while a pid may be reused and `os.kill(pid, 0)`
is not even a liveness question on Windows. An unrelated sentinel process runs beside every one of
these trees and has to be alive at the end.

Three kinds of evidence, kept apart:

* real runs on this host: exit codes preserved, a grandchild that outlived its parent reclaimed,
  the journal's contents, a start that never happened;
* labelled fault injection for the paths an OS will not produce on demand - an unconfirmed or
  failing `terminate`, a leaked spawn, a journal stream that stops accepting writes, an interrupt;
* native platform behaviour: real POSIX signals - at the spawn handoff, during an ordinary wait and
  during cleanup - plus SIGTERM and the documented SIGKILL limit against a real owner process, and
  the Windows abrupt-owner stop. Each skips with a reason elsewhere and is never read as a pass.

The signal tests deliver an actual SIGTERM with `os.kill`; only the moment of delivery is chosen,
and each of them refuses to signal at all unless the owner's own handler is installed.

The Windows tests below were not executed by the worker that wrote them (Linux host); they are the
owner's native checks.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

import codex_harness
from codex_harness.adapters import background_service
from codex_harness.adapters.background_service import run_owned
from codex_harness.adapters.commands import no_console_kwargs, python_channel_environment
from codex_harness.adapters.process_tree import ProcessTree, TreeOwnershipLeak

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt",
                                  reason="job-object kill-on-close is a Windows fact")
POSIX_ONLY = pytest.mark.skipif(os.name == "nt",
                                reason="SIGTERM to an owner and process groups are POSIX facts")

PACKAGE_ROOT = Path(codex_harness.__file__).resolve().parents[1]

# argv: lock, ready, grandchild script, grandchild lock, grandchild ready, mode, exit code
CHILD = """
import os, subprocess, sys, time
from filelock import FileLock

lock_path, ready, script, grandchild_lock, grandchild_ready, mode, code = sys.argv[1:8]
lock = FileLock(lock_path, is_singleton=False)
lock.acquire(timeout=30)
subprocess.Popen([sys.executable, script, grandchild_lock, grandchild_ready])
deadline = time.monotonic() + 60
while not os.path.exists(grandchild_ready) and time.monotonic() < deadline:
    time.sleep(0.05)
open(ready, 'w').close()
if mode == 'stay':
    time.sleep(600)
sys.exit(int(code))
"""

GRANDCHILD = """
import sys, time
from filelock import FileLock

lock = FileLock(sys.argv[1], is_singleton=False)
lock.acquire(timeout=30)
open(sys.argv[2], 'w').close()
time.sleep(600)
"""

OWNER = """
import sys
from codex_harness.adapters.background_service import run_owned

sys.exit(run_owned(sys.argv[2:], journal=sys.argv[1]))
"""


class Service:
    """The scripts, locks, readiness files and journal of one owned tree, all inside tmp_path."""

    def __init__(self, root: Path):
        self.root = root
        self.child_script = root / "child.py"
        self.grandchild_script = root / "grandchild.py"
        self.owner_script = root / "owner.py"
        self.child_script.write_text(CHILD, encoding="utf-8")
        self.grandchild_script.write_text(GRANDCHILD, encoding="utf-8")
        self.owner_script.write_text(OWNER, encoding="utf-8")
        self.child_lock = root / "child.lock"
        self.grandchild_lock = root / "grandchild.lock"
        self.child_ready = root / "child.ready"
        self.grandchild_ready = root / "grandchild.ready"
        self.journal = root / "owner.jsonl"

    def argv(self, mode: str = "exit", code: int = 0) -> list[str]:
        return [sys.executable, str(self.child_script), str(self.child_lock),
                str(self.child_ready), str(self.grandchild_script), str(self.grandchild_lock),
                str(self.grandchild_ready), mode, str(code)]

    def wait_ready(self, timeout: float = 60.0) -> bool:
        """True once the grandchild holds its lock, so no test races the tree it is judging."""
        deadline = time.monotonic() + timeout
        while not self.grandchild_ready.exists():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True

    def clear_ready(self) -> None:
        for marker in (self.child_ready, self.grandchild_ready):
            marker.unlink(missing_ok=True)

    def free(self, path: Path, timeout: float = 20.0) -> bool:
        """True when this process can take the lock: the holder is gone, not merely unresponsive."""
        probe = FileLock(str(path), is_singleton=False)
        deadline = time.monotonic() + timeout
        while True:
            try:
                probe.acquire(timeout=0)
            except Timeout:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)
                continue
            probe.release()
            return True

    def text(self) -> str:
        return self.journal.read_text(encoding="utf-8") if self.journal.exists() else ""

    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.text().splitlines() if line.strip()]

    def events(self) -> list[str]:
        return [entry["event"] for entry in self.entries()]

    def last(self, event: str) -> dict:
        found = [entry for entry in self.entries() if entry["event"] == event]
        assert found, (event, self.events())
        return found[-1]


@pytest.fixture
def service(tmp_path):
    return Service(tmp_path)


@pytest.fixture
def sentinel():
    """An unrelated process beside the owned tree; every cleanup here has to leave it alone."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **no_console_kwargs())
    try:
        yield process
    finally:
        process.kill()
        process.wait(timeout=60)


def owner_environment() -> dict:
    env = python_channel_environment()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + ((os.pathsep + existing) if existing else "")
    return env


def start_owner(service: Service, mode: str = "stay", code: int = 0) -> subprocess.Popen:
    """`run_owned` in a real owner process, so the test can stop that owner the way an OS does."""
    with open(service.root / "owner.stderr", "wb") as errors:
        return subprocess.Popen([sys.executable, str(service.owner_script), str(service.journal),
                                 *service.argv(mode, code)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                                env=owner_environment(), **no_console_kwargs())


def owner_stderr(service: Service) -> str:
    path = service.root / "owner.stderr"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def alive(pid: int) -> bool:
    """POSIX only: `os.kill` on Windows terminates rather than asks."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---- real runs on this host ---------------------------------------------------------------------

@pytest.mark.parametrize("code", [0, 7])
def test_the_childs_own_exit_code_survives_and_its_grandchild_does_not(service, sentinel, code):
    """The child exits on its own with a grandchild still running; the owner reclaims the tree.

    This is the observed defect in miniature: the thing that outlives the process the harness
    started is the thing that kept holding the lock.
    """
    assert run_owned(service.argv("exit", code), journal=str(service.journal)) == code
    assert service.wait_ready(), "the grandchild never reached its lock"
    assert service.free(service.grandchild_lock), "the grandchild outlived the owner"
    assert service.free(service.child_lock)
    assert sentinel.poll() is None, "an unrelated process was caught by the cleanup"
    assert service.events() == ["starting", "startup", "child_exited", "cleanup", "shutdown"]
    assert service.last("child_exited")["child_exit_code"] == code
    assert service.last("shutdown") | {"timestamp": None} == {
        "timestamp": None, "event": "shutdown", "child_exit_code": code, "final_exit_code": code,
        "cleanup_confirmed": True, "error_type": None}


def test_the_journal_carries_facts_and_never_the_command_line_or_the_environment(service):
    """Visibility/privacy: a pid and exit codes, but nothing that could be a secret."""
    canary = "canary-6f3a9c2b-not-for-the-journal"
    env = python_channel_environment()
    env["ZEUS_TEST_CANARY"] = canary
    assert run_owned(service.argv("exit", 0), cwd=str(service.root), env=env,
                     journal=str(service.journal)) == 0
    text = service.text()
    assert canary not in text and "child.py" not in text and str(service.root) not in text
    assert sys.executable not in text
    allowed = {"timestamp", "event", "pid", "child_exit_code", "final_exit_code",
               "cleanup_confirmed", "error_type"}
    for entry in service.entries():
        assert set(entry) <= allowed, entry
    pid = service.last("startup")["pid"]
    assert isinstance(pid, int) and pid > 0


def test_a_journal_that_cannot_be_opened_starts_nothing(service, sentinel):
    """Startup logging failure: 125, and the child never ran, so nothing is left to reclaim."""
    unwritable = service.root / "no-such-directory" / "owner.jsonl"
    assert run_owned(service.argv("exit", 0), journal=str(unwritable)) == 125
    assert not service.child_ready.exists() and not service.grandchild_ready.exists()
    assert service.free(service.child_lock, timeout=1), "no child means no held lock"
    assert not unwritable.exists() and sentinel.poll() is None


def test_a_journal_that_opens_but_refuses_its_first_line_spawns_nothing(service, sentinel,
                                                                        monkeypatch):
    """Injection: the journal opens and then refuses every write, the way a full disk does.

    Opening a file is not writing to it, which is what the first submission assumed. The receipt
    that proves the journal works is taken before the spawn, so a refusal here leaves no process
    at all rather than an unaccounted service.
    """
    real_popen = subprocess.Popen
    attempts = []

    class Watched(real_popen):
        def __init__(self, argv, **kwargs):
            attempts.append(list(argv))
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Watched)
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("starting"))
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 125
    assert attempts == [], "a journal that cannot be written starts nothing"
    assert not service.child_ready.exists() and not service.grandchild_ready.exists()
    assert service.free(service.child_lock, timeout=1), "no child means no held lock"
    assert service.entries() == [] and sentinel.poll() is None


def test_the_starting_receipt_is_written_before_the_first_spawn(service, monkeypatch):
    """The other half of the same rule: the successful pre-spawn receipt, and ordinary events after.

    The journal is read at the moment the owner starts the process, so the order is observed
    rather than inferred from the finished file.
    """
    real_popen = subprocess.Popen
    at_spawn = []

    class Watched(real_popen):
        def __init__(self, argv, **kwargs):
            at_spawn.append(service.events())
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Watched)
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 0
    assert at_spawn == [["starting"]], "the journal proved itself writable before anything ran"
    assert service.events() == ["starting", "startup", "child_exited", "cleanup", "shutdown"]
    assert service.last("starting") | {"timestamp": None} == {"timestamp": None, "event": "starting"}
    assert service.last("startup")["pid"] > 0, "the pid-bearing record still follows ownership"


def test_a_missing_program_is_one_sanitized_failure_and_no_second_start(service, monkeypatch):
    """Start failure: no retry, no orphan, and the journal names the class, never the path."""
    real_popen = subprocess.Popen
    attempts = []

    class Watched(real_popen):
        def __init__(self, argv, **kwargs):
            attempts.append(list(argv))
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Watched)
    missing = str(service.root / "there-is-no-such-program")
    assert run_owned([missing], journal=str(service.journal)) == 125
    assert attempts == [[missing]], "a failed start must not be tried twice"
    assert service.events() == ["starting", "start_failed"]
    assert service.last("start_failed")["error_type"] in ("FileNotFoundError", "NotADirectoryError",
                                                          "PermissionError", "OSError")
    assert missing not in service.text()


def test_only_the_named_program_is_started_and_never_through_a_shell(service, monkeypatch):
    """Isolation/scope: one child, no process-name or pid sweep, no shell expansion."""
    real_popen = subprocess.Popen
    started = []

    class Watched(real_popen):
        def __init__(self, argv, **kwargs):
            started.append((list(argv), kwargs.get("shell", False), kwargs.get("stdout")))
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", Watched)
    argv = service.argv("exit", 0)
    assert run_owned(argv, journal=str(service.journal)) == 0
    assert [command for command, _, _ in started] == [argv]
    assert not any(shell for _, shell, _ in started)
    assert [stdout for _, _, stdout in started] == [subprocess.DEVNULL]


# ---- labelled fault injection: paths the OS will not produce on demand ---------------------------

def injected_terminate(monkeypatch, outcome, calls):
    """Injection, not an OS failure: the real cleanup still runs; only its answer is rewritten."""
    real_terminate, real_close = ProcessTree.terminate, ProcessTree.close

    def terminate(self, reason, *, timeout=20.0, settle=10.0):
        calls.append(("terminate", timeout, settle))
        receipt = real_terminate(self, reason, timeout=timeout, settle=settle)
        if outcome == "raises":
            raise RuntimeError("injected: the cleanup call itself failed")
        return {**receipt, "confirmed": False}

    def close(self):
        calls.append(("close", None, None))
        real_close(self)

    monkeypatch.setattr(ProcessTree, "terminate", terminate)
    monkeypatch.setattr(ProcessTree, "close", close)


@pytest.mark.parametrize("outcome", ["unconfirmed", "raises"])
def test_a_cleanup_that_is_not_confirmed_is_124_and_the_handle_is_still_closed(service, sentinel,
                                                                              monkeypatch, outcome):
    calls: list[tuple] = []
    injected_terminate(monkeypatch, outcome, calls)
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 124
    assert calls == [("terminate", 5.0, 5.0), ("close", None, None)], "bounded waits, then close"
    assert service.free(service.grandchild_lock), "the injected receipt did not stop the real kill"
    assert sentinel.poll() is None
    assert service.last("cleanup")["cleanup_confirmed"] is False
    assert service.last("shutdown")["final_exit_code"] == 124
    assert service.last("shutdown")["error_type"] == ("RuntimeError" if outcome == "raises"
                                                      else None)


def test_a_leaked_start_is_124_and_is_never_started_again(service, monkeypatch):
    """Injection: `spawn` reports it created a process it cannot prove gone. A retry would add a
    second one to whatever the first one is, so there is exactly one attempt."""
    attempts = []

    def leaking(argv, **kwargs):
        attempts.append(list(argv))
        raise TreeOwnershipLeak("injected leak", detail={"cleanup": {"left_running": True}})

    monkeypatch.setattr(ProcessTree, "spawn", leaking)
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 124
    assert len(attempts) == 1
    assert service.events() == ["starting", "start_leaked"]
    assert service.last("start_leaked") | {"timestamp": None} == {
        "timestamp": None, "event": "start_leaked", "cleanup_confirmed": False,
        "error_type": "TreeOwnershipLeak"}


class _Refuses:
    """A stream that accepts nothing, the way a full disk does."""

    def write(self, text):
        raise OSError("injected: the journal stream refuses writes")

    def flush(self):
        pass

    def close(self):
        pass

    def seek(self, *args):
        return 0

    def tell(self):
        return 0


def refusing_from(event: str):
    """Injection: from the named event on, journal writes fail. `logging` swallows such failures
    by default (it prints to stderr and carries on), which is exactly what must not happen."""

    class _RefusingHandler(RotatingFileHandler):
        def emit(self, record):
            if ('"event": "' + event + '"') in record.getMessage():
                self.stream = _Refuses()
            super().emit(record)

    return _RefusingHandler


def test_a_journal_failure_after_the_start_still_reclaims_the_tree_and_refuses_success(service,
                                                                                      sentinel,
                                                                                      monkeypatch):
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("child_exited"))
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 125
    assert service.free(service.grandchild_lock), "a broken journal must not skip the cleanup"
    assert service.free(service.child_lock) and sentinel.poll() is None
    assert service.events() == ["starting", "startup"], "nothing after the failure reached the file"


@pytest.mark.parametrize("code", [0, 7])
def test_a_final_entry_that_cannot_be_written_is_an_owner_error_whatever_the_child_said(service,
                                                                                        monkeypatch,
                                                                                        code):
    """The child exited and the tree is gone, but the owner cannot say so: 125, not 0 and not 7.

    A nonzero child is the case the first submission got wrong: it answered 7, which reads as the
    child's own, fully accounted run rather than as an owner whose last receipt never landed.
    """
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("shutdown"))
    assert run_owned(service.argv("exit", code), journal=str(service.journal)) == 125
    assert service.events() == ["starting", "startup", "child_exited", "cleanup"]
    assert service.last("child_exited")["child_exit_code"] == code
    assert service.last("cleanup")["cleanup_confirmed"] is True


def test_a_failed_final_entry_does_not_outrank_an_unproven_tree(service, sentinel, monkeypatch):
    """Control for the precedence above: 124 is still first when both faults are injected."""
    calls: list[tuple] = []
    injected_terminate(monkeypatch, "unconfirmed", calls)
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("shutdown"))
    assert run_owned(service.argv("exit", 7), journal=str(service.journal)) == 124
    assert service.last("cleanup")["cleanup_confirmed"] is False
    assert "shutdown" not in service.events()
    assert service.free(service.grandchild_lock) and sentinel.poll() is None


def test_a_failed_final_entry_does_not_outrank_a_deliberate_interruption(service, sentinel,
                                                                        monkeypatch):
    """Control for the precedence above: a stop stays 130 when the last receipt also fails."""
    interrupting_spawn(monkeypatch, service, KeyboardInterrupt)
    monkeypatch.setattr(background_service, "RotatingFileHandler", refusing_from("shutdown"))
    assert run_owned(service.argv("stay", 0), journal=str(service.journal)) == 130
    assert service.events() == ["starting", "startup", "cleanup"]
    assert service.free(service.child_lock) and service.free(service.grandchild_lock)
    assert sentinel.poll() is None


def interrupting_spawn(monkeypatch, service, failure):
    """Injection: the owner is interrupted while it waits, with the whole tree alive underneath."""
    real_spawn = ProcessTree.spawn

    def spawn(argv, **kwargs):
        tree = real_spawn(argv, **kwargs)
        real_wait = tree.process.wait

        def interrupted(*args, **kwargs):
            tree.process.wait = real_wait  # the owner's own cleanup uses the real one
            assert service.wait_ready(), "the tree was not up when the interrupt was injected"
            raise failure()

        tree.process.wait = interrupted
        return tree

    monkeypatch.setattr(ProcessTree, "spawn", spawn)


def test_an_interrupted_owner_is_130_after_the_tree_is_gone(service, sentinel, monkeypatch):
    interrupting_spawn(monkeypatch, service, KeyboardInterrupt)
    assert run_owned(service.argv("stay", 0), journal=str(service.journal)) == 130
    assert service.free(service.child_lock) and service.free(service.grandchild_lock)
    assert sentinel.poll() is None
    assert service.events() == ["starting", "startup", "cleanup", "shutdown"]
    assert service.last("shutdown")["error_type"] == "KeyboardInterrupt"
    assert service.last("shutdown")["cleanup_confirmed"] is True
    assert service.last("shutdown")["child_exit_code"] is None


# ---- the SIGTERM handler: POSIX, main thread, and put back ---------------------------------------

def test_the_sigterm_handler_is_restored_when_the_run_ends(service, monkeypatch):
    """The installed handler is also called here directly: it must record and return, never raise.

    That is the whole of the deferred stop. A handler that unwinds can do so anywhere the owner
    happens to be, including inside the spawn that is producing the tree it would have to reclaim.
    """
    real_spawn = ProcessTree.spawn
    seen = []

    def spawn(argv, **kwargs):
        seen.append(signal.getsignal(signal.SIGTERM))
        return real_spawn(argv, **kwargs)

    monkeypatch.setattr(ProcessTree, "spawn", spawn)
    before = signal.getsignal(signal.SIGTERM)
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 0
    assert signal.getsignal(signal.SIGTERM) is before
    if os.name == "nt":
        assert seen == [before], "no handler is installed on Windows"
    else:
        assert seen != [before] and callable(seen[0])
        assert seen[0](signal.SIGTERM, None) is None, "the handler records the stop; it never raises"


def test_a_run_off_the_main_thread_installs_no_handler_and_still_owns_its_tree(service):
    """`signal.signal` is main-thread only; the owner must not fail or leave the tree behind."""
    before = signal.getsignal(signal.SIGTERM)
    answer: list[int] = []
    worker = threading.Thread(target=lambda: answer.append(
        run_owned(service.argv("exit", 3), journal=str(service.journal))))
    worker.start()
    worker.join(timeout=180)
    assert not worker.is_alive() and answer == [3]
    assert signal.getsignal(signal.SIGTERM) is before
    assert service.free(service.grandchild_lock)


# ---- native POSIX: a real signal, delivered where it used to unwind ------------------------------

@POSIX_ONLY
def test_a_real_sigterm_at_the_spawn_handoff_is_143_only_after_the_tree_is_reclaimed(service,
                                                                                     sentinel,
                                                                                     monkeypatch):
    """The reproduced defect: the signal arrives while the owner is taking the tree.

    The signal is real - `os.kill` to this very process - and only the moment of delivery is
    chosen: the whole tree is up, the spawn has produced it, and the owner has not yet returned
    from the handoff. A handler that raised here unwound out with the processes already created,
    which is a 143 reported beside a live service. Recorded instead, the stop waits for the owner.
    """
    real_spawn = ProcessTree.spawn
    before = signal.getsignal(signal.SIGTERM)
    handed_over = []

    def spawn(argv, **kwargs):
        tree = real_spawn(argv, **kwargs)
        assert service.wait_ready(), "the tree was not up when the signal was delivered"
        assert signal.getsignal(signal.SIGTERM) is not before, "no owner handler is installed"
        os.kill(os.getpid(), signal.SIGTERM)
        handed_over.append(tree.process.pid)  # reached only because nothing unwound from the signal
        return tree

    monkeypatch.setattr(ProcessTree, "spawn", spawn)
    assert run_owned(service.argv("stay", 0), journal=str(service.journal)) == 143
    assert len(handed_over) == 1, "the handoff completed; the signal did not raise through it"
    assert service.free(service.child_lock) and service.free(service.grandchild_lock)
    assert not alive(handed_over[0]) and sentinel.poll() is None
    assert signal.getsignal(signal.SIGTERM) is before
    assert service.events() == ["starting", "startup", "cleanup", "shutdown"]
    assert service.last("shutdown")["final_exit_code"] == 143
    assert service.last("shutdown")["cleanup_confirmed"] is True
    assert service.last("shutdown")["child_exit_code"] is None


@POSIX_ONLY
def test_a_real_sigterm_during_an_ordinary_wait_is_answered_by_the_bounded_poll(service, sentinel,
                                                                                monkeypatch):
    """The sleeping service: the child sleeps for 600 seconds and the stop is answered in one step.

    The owner's wait is recorded, so "bounded" is asserted rather than assumed, and the previous
    SIGTERM handler is back when the run ends.
    """
    real_spawn = ProcessTree.spawn
    before = signal.getsignal(signal.SIGTERM)
    waits = []

    def spawn(argv, **kwargs):
        tree = real_spawn(argv, **kwargs)
        real_wait = tree.process.wait

        def watched(*args, **kwargs):
            waits.append(kwargs.get("timeout"))
            tree.process.wait = real_wait  # the cleanup's own waits are the real ones
            assert service.wait_ready(), "the tree was not up when the signal was sent"
            assert signal.getsignal(signal.SIGTERM) is not before, "no owner handler is installed"
            os.kill(os.getpid(), signal.SIGTERM)  # a real signal, into a real wait
            return real_wait(*args, **kwargs)

        tree.process.wait = watched
        return tree

    monkeypatch.setattr(ProcessTree, "spawn", spawn)
    started = time.monotonic()
    assert run_owned(service.argv("stay", 0), journal=str(service.journal)) == 143
    elapsed = time.monotonic() - started
    assert waits and waits[0] is not None and waits[0] <= 1.0, waits
    assert elapsed < 120, "the child sleeps for 600s; the stop was not waited out"
    assert signal.getsignal(signal.SIGTERM) is before
    assert service.free(service.child_lock) and service.free(service.grandchild_lock)
    assert sentinel.poll() is None
    assert service.last("shutdown")["final_exit_code"] == 143
    assert service.last("shutdown")["cleanup_confirmed"] is True


@POSIX_ONLY
def test_a_real_sigterm_during_cleanup_does_not_raise_through_it(service, sentinel, monkeypatch):
    """The stop arrives after the child's run was finished and recorded, while cleanup is running.

    Nothing may unwind out of the signal there either. The answer stays the child's own code: that
    run completed and was accounted for before the stop existed, and the tree is gone either way.
    """
    real_terminate = ProcessTree.terminate
    before = signal.getsignal(signal.SIGTERM)

    def terminate(self, reason, *, timeout=20.0, settle=10.0):
        assert signal.getsignal(signal.SIGTERM) is not before, "no owner handler is installed"
        os.kill(os.getpid(), signal.SIGTERM)
        return real_terminate(self, reason, timeout=timeout, settle=settle)

    monkeypatch.setattr(ProcessTree, "terminate", terminate)
    assert run_owned(service.argv("exit", 5), journal=str(service.journal)) == 5
    assert service.free(service.grandchild_lock) and sentinel.poll() is None
    assert signal.getsignal(signal.SIGTERM) is before
    assert service.last("shutdown")["final_exit_code"] == 5
    assert service.last("shutdown")["cleanup_confirmed"] is True


# ---- native POSIX: a real owner, a real signal ---------------------------------------------------

@POSIX_ONLY
def test_posix_sigterm_to_a_real_owner_ends_the_tree_and_answers_143(service, sentinel):
    owner = start_owner(service, mode="stay")
    try:
        assert service.wait_ready(), owner_stderr(service)
        os.kill(owner.pid, signal.SIGTERM)
        assert owner.wait(timeout=120) == 143, owner_stderr(service)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=60)
    assert service.free(service.child_lock) and service.free(service.grandchild_lock)
    assert sentinel.poll() is None
    assert service.last("shutdown")["final_exit_code"] == 143
    assert service.last("shutdown")["cleanup_confirmed"] is True
    assert not alive(service.last("startup")["pid"])


@POSIX_ONLY
def test_posix_sigkill_of_the_owner_leaves_the_tree_behind_which_is_the_documented_limit(service):
    """Explicitly excluded by the SPEC, and shown rather than assumed: with the owner killed
    outright there is nothing left on POSIX to signal the group, unlike a Windows job handle.

    The tree this test deliberately leaves alive is ended here, by its own process group.
    """
    owner = start_owner(service, mode="stay")
    child_pid = None
    try:
        assert service.wait_ready(), owner_stderr(service)
        owner.kill()
        assert owner.wait(timeout=120) == -signal.SIGKILL
        child_pid = service.last("startup")["pid"]
        assert alive(child_pid), "the owner's own child"
        assert not service.free(service.grandchild_lock, timeout=2), "the limit, not a cleanup"
        assert "shutdown" not in service.events(), "a killed owner writes no final receipt"
    finally:
        if child_pid is not None:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=60)
    assert service.free(service.grandchild_lock), "the group kill above did end the tree"


# ---- native Windows: the abrupt owner stop this fix exists for -----------------------------------

@WINDOWS_ONLY
def test_windows_abrupt_owner_stop_releases_children_and_the_lock(service, sentinel):
    """The scheduled-task Stop in miniature: the owner is terminated with no chance to clean up.

    Nothing on this side runs afterwards; the OS closes the last handle to the job and
    KILL_ON_JOB_CLOSE ends the child and the grandchild. The next owner then starts, which it can
    only do if the locks were really released.
    """
    owner = start_owner(service, mode="stay")
    try:
        assert service.wait_ready(), owner_stderr(service)
        owner.kill()  # TerminateProcess: no handler, no finally, no cleanup code of ours
        owner.wait(timeout=120)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=60)
    assert service.free(service.child_lock), "the child survived the owner"
    assert service.free(service.grandchild_lock), "the grandchild survived the owner"
    assert sentinel.poll() is None, "an unrelated process was caught by the job"
    assert "shutdown" not in service.events(), "a killed owner writes no final receipt"

    service.clear_ready()
    assert run_owned(service.argv("exit", 0), journal=str(service.journal)) == 0
    assert service.child_ready.exists(), "the next owner's child took the released lock"
    assert service.free(service.grandchild_lock)
