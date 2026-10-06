"""Backend lane of docs/zeus/operations/report-background-001/SPEC.md: silent host children.

A console child started from a process without a console (the hidden PowerShell launchers) gets a
console window of its own unless it is created with CREATE_NO_WINDOW; a captured pipe is not a
visibility policy. `commands.no_console_kwargs` is the one helper, and every piped host child on the
listed paths spawns through it.

Three kinds of evidence, kept apart:

* the helper's own policy, asked with an injected platform (no process is started);
* wiring, with the platform injected into the helper and `subprocess.Popen`/`subprocess.run`
  replaced by a recorder that refuses to start anything: what each listed path would hand to
  Windows, observed on any host, plus a source audit that no listed spawn bypasses the helper;
* a real Windows child asked `GetConsoleWindow()` from inside, with UTF-8 output and its exit
  status kept. Those tests skip on other platforms and say so; nothing here reads a skip as a pass.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters import (
    app_server,
    audit_runner,
    commands,
    fleet_runtime,
    isolated_worker,
    operation_cli,
    port_diagnosis,
    process_tree,
    published_ports,
    source_execution,
    source_verification,
)
from codex_harness.adapters.commands import (
    CREATE_NEW_PROCESS_GROUP,
    CREATE_NO_WINDOW,
    no_console_kwargs,
    python_channel_environment,
    run_process,
)

# Win32 values (Microsoft process-creation-flags): either of these makes CREATE_NO_WINDOW ignored.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
CREATE_SUSPENDED = process_tree.CREATE_SUSPENDED if os.name == "nt" else 0x00000004

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="a real console handle is a Windows fact")

# The child asks Windows for its own console window and prints the answer first, then a UTF-8 line
# that the console code page (cp949 on the owner's host) could not carry, then exits 3.
CONSOLE_PROBE = ("import ctypes, sys\n"
                 "print(ctypes.WinDLL('kernel32').GetConsoleWindow())\n"
                 "print('한글 출력')\n"
                 "sys.exit(3)\n")

LISTED = ("commands", "fleet_runtime", "app_server", "isolated_worker", "operation_cli",
          "source_verification", "source_execution", "process_tree", "published_ports",
          "port_diagnosis", "audit_runner")


# ---- the helper's policy ------------------------------------------------------------------------

def test_windows_policy_is_no_window_without_the_flags_that_cancel_it():
    plain = no_console_kwargs(platform="nt")
    assert plain == {"creationflags": CREATE_NO_WINDOW}
    grouped = no_console_kwargs(process_group=True, platform="nt")["creationflags"]
    assert grouped & CREATE_NO_WINDOW and grouped & CREATE_NEW_PROCESS_GROUP
    suspended = no_console_kwargs(process_group=True, creationflags=CREATE_SUSPENDED,
                                  platform="nt")["creationflags"]
    assert suspended == CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED
    for flags in (plain["creationflags"], grouped, suspended):
        assert not flags & CREATE_NEW_CONSOLE and not flags & DETACHED_PROCESS
    assert "start_new_session" not in plain and "start_new_session" not in no_console_kwargs(
        process_group=True, platform="nt")


def test_posix_policy_carries_no_windows_keyword():
    assert no_console_kwargs(platform="posix") == {}
    assert no_console_kwargs(process_group=True, platform="posix") == {"start_new_session": True}
    assert no_console_kwargs(process_group=True, creationflags=CREATE_SUSPENDED,
                             platform="posix") == {"start_new_session": True}
    if os.name != "nt":
        assert no_console_kwargs() == {} and no_console_kwargs(process_group=True) == {"start_new_session": True}


def test_a_real_child_keeps_utf8_output_and_exit_status_on_this_host(tmp_path):
    """The default policy on the running host, with a real child: output and exit are unchanged."""
    done = run_process([sys.executable, "-c", "import sys; print('한글 출력'); sys.exit(3)"],
                       cwd=str(tmp_path), env=python_channel_environment(), timeout=60)
    assert done.returncode == 3 and done.stdout.strip() == "한글 출력"


# ---- wiring, with the platform injected and nothing started -----------------------------------

class Spawned(Exception):
    """The recorder's refusal: carries what would have been handed to the platform."""

    def __init__(self, argv, kwargs):
        super().__init__(argv[0])
        self.argv, self.kwargs = list(argv), dict(kwargs)


class _Nt:
    """`os` as seen from one module, answering `name == "nt"`; everything else is the real module."""
    name = "nt"

    def __getattr__(self, attribute):
        return getattr(os, attribute)


@pytest.fixture
def recorder(monkeypatch):
    """The helper believes it is on Windows; Popen and run refuse to start and report their kwargs."""
    monkeypatch.setattr(commands, "os", _Nt())

    def refuse(argv, *args, **kwargs):
        raise Spawned(argv, kwargs)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    return refuse


def assert_silent(spawned: Spawned, *, group: bool, suspended: bool = False):
    flags = spawned.kwargs["creationflags"]
    assert flags & CREATE_NO_WINDOW, spawned.argv
    assert bool(flags & CREATE_NEW_PROCESS_GROUP) is group, spawned.argv
    assert bool(flags & CREATE_SUSPENDED) is suspended, spawned.argv
    assert not flags & CREATE_NEW_CONSOLE and not flags & DETACHED_PROCESS, spawned.argv
    assert "start_new_session" not in spawned.kwargs and not spawned.kwargs.get("shell")


def test_run_process_and_its_taskkill_are_silent(recorder, monkeypatch, tmp_path):
    with pytest.raises(Spawned) as raised:
        run_process(["child"], cwd=str(tmp_path))
    assert_silent(raised.value, group=True)
    assert raised.value.kwargs["stdin"] is subprocess.PIPE and raised.value.kwargs["stdout"] is subprocess.PIPE

    class Hung:
        pid = 4242

        def communicate(self, *args, **kwargs):
            raise subprocess.TimeoutExpired("child", 1)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: Hung())
    with pytest.raises(Spawned) as raised:
        run_process(["child"], timeout=1)
    assert raised.value.argv == ["taskkill", "/PID", "4242", "/T", "/F"]
    assert_silent(raised.value, group=False)
    assert raised.value.kwargs["timeout"] == 20 and raised.value.kwargs["capture_output"] is True


def test_fleet_lane_child_is_silent_in_its_own_group(recorder, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_runtime, "lane_environment", lambda lane, host, environ: {"ZEUS_DATABASE_URL": "dsn"})
    monkeypatch.setattr(fleet_runtime, "verify_lane_schema", lambda dsn, schema, connect: None)
    lane = {"id": "a", "repository": str(tmp_path), "schema": "lane_a", "runtime": str(tmp_path / "rt")}
    launcher = fleet_runtime.LaneLauncher({"lanes": [lane]}, {}, argv=("zeus",), connect=None,
                                          budget=SimpleNamespace(counts=lambda: {}), environ={})
    with pytest.raises(Spawned) as raised:
        launcher.launch({"id": "op-1", "lane": "a", "manifest": {}})
    assert raised.value.argv[:1] == ["zeus"] and raised.value.kwargs["stdin"] is subprocess.DEVNULL
    assert_silent(raised.value, group=True)
    assert raised.value.kwargs["cwd"] == str(tmp_path)


def test_codex_app_server_and_its_taskkill_are_silent(recorder, monkeypatch):
    server = app_server.AppServer(executable="codex-fixture")
    with pytest.raises(Spawned) as raised:
        server.__enter__()
    assert raised.value.argv == ["codex-fixture", "app-server"]
    assert_silent(raised.value, group=True)
    monkeypatch.setattr(app_server, "os", _Nt())
    server.process = SimpleNamespace(pid=77, poll=lambda: None)
    with pytest.raises(Spawned) as raised:
        server.__exit__(None, None, None)
    assert raised.value.argv == ["taskkill", "/PID", "77", "/T", "/F"]
    assert_silent(raised.value, group=False)


def test_process_tree_keeps_suspended_start_and_group_and_adds_no_window(recorder, monkeypatch):
    """Injected: the Windows branch of `spawn` runs here with the job object faked (no kernel32)."""
    monkeypatch.setattr(process_tree, "os", _Nt())
    monkeypatch.setattr(process_tree, "_windows_job", lambda: 1)
    # The Win32 constant lives in the module's Windows-only block; on other hosts it is supplied.
    monkeypatch.setattr(process_tree, "CREATE_SUSPENDED", CREATE_SUSPENDED, raising=False)
    closed = []
    monkeypatch.setattr(process_tree, "_kernel32", SimpleNamespace(CloseHandle=closed.append), raising=False)
    with pytest.raises(Spawned) as raised:
        process_tree.ProcessTree.spawn(["child"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
    assert_silent(raised.value, group=True, suspended=True)
    assert closed == [1], "the job handle of a failed spawn is released"


@pytest.mark.parametrize("path", ["operation_cli", "source_verification", "audit_runner",
                                  "published_ports", "port_diagnosis", "source_execution",
                                  "isolated_worker.list_revision", "isolated_worker.init_standalone_git",
                                  "isolated_worker.stage_source"])
def test_piped_git_docker_and_probe_children_are_silent(recorder, monkeypatch, tmp_path, path):
    if path == "operation_cli":
        call = lambda: operation_cli.GitSource(tmp_path).commit_exists("a" * 40)  # noqa: E731
    elif path == "source_verification":
        call = lambda: source_verification.GitSourceVerifier(tmp_path, None).git("rev-parse", "HEAD")  # noqa: E731
    elif path == "audit_runner":
        runner = audit_runner.AuditRunner(tmp_path / "audit", None)
        call = lambda: runner.acquire("https://github.com/org/repo", "b" * 40)  # noqa: E731
    elif path == "published_ports":
        call = lambda: published_ports._run(["docker", "ps"], 1.0)  # noqa: E731
    elif path == "port_diagnosis":
        call = lambda: port_diagnosis._run(["wsl.exe", "-e", "true"], 1.0)  # noqa: E731
    elif path == "source_execution":
        call = lambda: source_execution.bounded_command(["docker", "run"], 1)  # noqa: E731
    elif path == "isolated_worker.list_revision":
        call = lambda: isolated_worker.list_revision(tmp_path, "HEAD")  # noqa: E731
    elif path == "isolated_worker.init_standalone_git":
        call = lambda: isolated_worker.init_standalone_git(tmp_path)  # noqa: E731
    else:
        monkeypatch.setattr(isolated_worker, "list_revision", lambda repository, revision: [])
        call = lambda: isolated_worker.stage_source(tmp_path, "HEAD", tmp_path / "stage")  # noqa: E731
    with pytest.raises(Spawned) as raised:
        call()
    assert_silent(raised.value, group=False)
    assert raised.value.argv[0] in ("git", "docker", "wsl.exe")


def test_every_listed_spawn_goes_through_the_helper():
    """Source audit of the eleven listed modules: no `subprocess.run`/`Popen` without the helper,
    and no `shell=True`, `CREATE_NEW_CONSOLE` or `DETACHED_PROCESS` in their code (docstrings
    may name the cancelling flags; code may not)."""
    root = Path(commands.__file__).parent
    found, cancelling = {}, []
    for name in LISTED:
        module = ast.parse((root / (name + ".py")).read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Name) and node.id in ("CREATE_NEW_CONSOLE", "DETACHED_PROCESS"):
                cancelling.append(name + ":" + str(node.lineno))
            if isinstance(node, ast.Attribute) and node.attr in ("CREATE_NEW_CONSOLE", "DETACHED_PROCESS"):
                cancelling.append(name + ":" + str(node.lineno))
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            target = node.func
            if not (isinstance(target.value, ast.Name) and target.value.id == "subprocess"
                    and target.attr in ("run", "Popen", "call", "check_call", "check_output")):
                continue
            routed = any(keyword.arg is None and isinstance(keyword.value, ast.Call)
                         and isinstance(keyword.value.func, ast.Name)
                         and keyword.value.func.id == "no_console_kwargs" for keyword in node.keywords)
            shelled = any(keyword.arg == "shell" for keyword in node.keywords)
            # A spawn written with the POSIX-only keyword sits in a branch Windows never reaches;
            # the SPEC leaves POSIX policy unchanged, so it is classified, not routed.
            posix_only = any(keyword.arg == "start_new_session" for keyword in node.keywords)
            found[name + ":" + str(node.lineno)] = (target.attr, routed, shelled, posix_only)
    assert cancelling == [], cancelling
    assert found, "the audit found no spawn at all, which cannot be right"
    unrouted = sorted(site for site, (_, routed, _, posix_only) in found.items()
                      if not routed and not posix_only)
    assert unrouted == [], unrouted
    posix = sorted(site.split(":")[0] for site, (_, _, _, posix_only) in found.items() if posix_only)
    assert posix == ["process_tree"], posix  # the one POSIX branch of ProcessTree.spawn
    assert not [site for site, (_, _, shelled, _) in found.items() if shelled]
    # The complete listed paths, by module: every one has at least one audited spawn.
    assert {site.split(":")[0] for site in found} == set(LISTED)


# ---- native Windows: the child's own answer -----------------------------------------------------

def _console_probe(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(CONSOLE_PROBE, encoding="utf-8")
    return [sys.executable, str(script)]


@WINDOWS_ONLY
def test_windows_run_process_child_reports_no_console_window_and_keeps_utf8_and_exit(tmp_path):
    import ctypes
    done = run_process(_console_probe(tmp_path), cwd=str(tmp_path), env=python_channel_environment(),
                       timeout=60)
    assert done.returncode == 3, done.stderr
    handle, text = done.stdout.splitlines()[:2]
    assert handle == "0", "the child had a console window: " + handle
    assert text == "한글 출력"
    # Control, labelled: the same child without the policy inherits this process's console. It can
    # only discriminate when the test itself has a console; otherwise it is recorded as not asked.
    if ctypes.WinDLL("kernel32").GetConsoleWindow():
        plain = subprocess.run(_console_probe(tmp_path), cwd=str(tmp_path), capture_output=True,
                               text=True, encoding="utf-8", env=python_channel_environment(), timeout=60)
        assert plain.stdout.splitlines()[0] != "0", "the control shows the probe cannot discriminate"


@WINDOWS_ONLY
def test_windows_process_tree_child_reports_no_console_window_inside_its_job(tmp_path):
    tree = process_tree.ProcessTree.spawn(_console_probe(tmp_path), cwd=str(tmp_path),
                                          env=python_channel_environment(), stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, _ = tree.process.communicate(timeout=60)
        assert tree.process.returncode == 3
        assert out.decode("utf-8").splitlines()[:2] == ["0", "한글 출력"]
        assert tree.boundary["kind"] == "job_object" and tree.boundary["created_suspended"] is True
        receipt = tree.terminate("probe finished")
        assert receipt["confirmed"] is True and receipt["parent"]["exit_code"] == 3
    finally:
        tree.close()


@WINDOWS_ONLY
def test_windows_timeout_taskkill_runs_without_a_console_window(tmp_path, monkeypatch):
    seen = []
    real_run = subprocess.run

    def watched(argv, *args, **kwargs):
        seen.append((list(argv), dict(kwargs)))
        return real_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", watched)
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(tmp_path), timeout=1)
    kills = [(argv, kwargs) for argv, kwargs in seen if argv[0] == "taskkill"]
    assert len(kills) == 1 and kills[0][1]["creationflags"] & CREATE_NO_WINDOW
