"""The one spawn chokepoint (REBUILD-DESIGN-v2 §5.3 S1 host_os) and the Windows split (§5.5 W-B).

Every process the target creates goes through `host_os.adapters.process_groups.popen`/`run`; no other
target module calls a `subprocess` creator or an `os` exec/spawn function. The Windows primitives
live under `host_os/adapters/windows/` and are not even imported on POSIX by the process tree.
"""

import ast
import subprocess
import sys
from pathlib import Path

from _layout import TARGET

SRC = TARGET / "src"
CHOKEPOINT = SRC / "codex_harness" / "host_os" / "adapters" / "process_groups.py"
CREATORS = {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
OS_SPAWN = ("exec", "spawn", "posix_spawn", "system", "popen", "fork")


def spawn_sites(path: Path) -> list[str]:
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            found += [f"from subprocess import {a.name}" for a in node.names if a.name in CREATORS]
        # A call, or a creator passed around as a value; a type annotation is neither.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id == "subprocess" and func.attr in CREATORS:
                    found.append(f"subprocess.{func.attr}")
                if func.value.id == "os" and func.attr.startswith(OS_SPAWN):
                    found.append(f"os.{func.attr}")
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name) \
                        and arg.value.id == "subprocess" and arg.attr in CREATORS:
                    found.append(f"subprocess.{arg.attr} passed as a value")
    return found


def test_only_the_chokepoint_creates_processes():
    sites = {p.relative_to(SRC).as_posix(): spawn_sites(p) for p in SRC.rglob("*.py")}
    others = {k: v for k, v in sites.items() if v and Path(SRC / k) != CHOKEPOINT
              and not k.endswith("resources/worker_profile_hook.py")}
    assert others == {}, others
    assert sorted(sites[CHOKEPOINT.relative_to(SRC).as_posix()]) == ["subprocess.Popen", "subprocess.run"]


def test_no_target_code_passes_shell_or_a_console_cancelling_flag():
    """The rest of M7's retired spawn audit (`test_background_processes::test_every_listed_spawn_goes_through_the_helper`,
    SKIPPED-TEST-CLOSURE-20261004 C), generalized from its eleven M7 files to the whole target: no `shell=` keyword
    on any call, and no CREATE_NEW_CONSOLE or DETACHED_PROCESS in code (Windows ignores CREATE_NO_WINDOW next to
    either, so the chokepoint's no-console policy would be cancelled). Docstrings may name them; code may not."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                found.append(f"{path.relative_to(SRC)}:{node.value.lineno} shell=")
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if name in ("CREATE_NEW_CONSOLE", "DETACHED_PROCESS"):
                found.append(f"{path.relative_to(SRC)}:{node.lineno} {name}")
    assert found == []


def test_the_packaged_hook_resource_spawns_nothing_either():
    """Structural: the hook resource holds no spawn site, which the single-chokepoint rule above requires of every
    target file; the runtime property is covered by test_the_packaged_hook_runs_with_every_spawn_path_patched_to_raise."""
    assert spawn_sites(SRC / "codex_harness" / "resources" / "worker_profile_hook.py") == []


def test_the_packaged_hook_runs_with_every_spawn_path_patched_to_raise(tmp_path, monkeypatch, capsys):
    """Behaviour: the hook handles a session start and two failures of one tool (the second emits its research-required
    context) with the chokepoint, `subprocess` creators and the `os` exec/spawn/system/fork functions all raising, and
    writes its receipts."""
    import importlib.util
    import io
    import json
    import os
    from types import SimpleNamespace

    from codex_harness.host_os.adapters import process_groups

    def spawned(*args, **kwargs):
        raise AssertionError("the packaged hook spawned a process")

    for owner, names in ((process_groups, ("run", "popen")), (subprocess, tuple(CREATORS)),
                         (os, tuple(n for n in dir(os) if n.startswith(OS_SPAWN)))):
        for name in names:
            if hasattr(owner, name):
                monkeypatch.setattr(owner, name, spawned)
    spec = importlib.util.spec_from_file_location(
        "worker_profile_hook_under_test", SRC / "codex_harness" / "resources" / "worker_profile_hook.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    directory = tmp_path / "receipts"
    events = [{"hook_event_name": "SessionStart", "session_id": "s-1"}] + [
        {"hook_event_name": "PostToolUseFailure", "session_id": "s-1", "tool_name": "Bash", "tool_use_id": f"u-{i}",
         "error": "boom at line 7"} for i in (1, 2)]
    for body in events:
        monkeypatch.setattr(hook.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(body).encode())))
        assert hook.main(["--directory", str(directory), "--profile-digest", "d" * 64]) == 0
    assert len(list(directory.glob("*.json"))) == 3
    context = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(context) == 1 and "Two-strike rule: 2 distinct Bash failures" in context[0]["hookSpecificOutput"]["additionalContext"]


def test_the_chokepoint_passes_arguments_and_results_unchanged(tmp_path):
    from codex_harness.host_os.adapters import process_groups

    done = process_groups.run([sys.executable, "-c", "import sys; print(sys.argv[1])", "x y"],
                              capture_output=True, text=True, cwd=str(tmp_path))
    assert isinstance(done, subprocess.CompletedProcess) and done.stdout == "x y\n" and done.returncode == 0
    child = process_groups.popen([sys.executable, "-c", "pass"])
    assert isinstance(child, subprocess.Popen) and child.wait(10) == 0


def test_posix_process_tree_does_not_import_the_windows_primitives(child_env):
    code = ("import sys; import codex_harness.host_os.adapters.process_tree, "
            "codex_harness.host_os.adapters.background_service, codex_harness.host_os.adapters.service_entry; "
            "print(sorted(m for m in sys.modules if m.endswith('job_objects')))")
    env = dict(child_env, PYTHONPATH=child_env["PYTHONPATH"] + ":" + str(SRC))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_windows_modules_are_pure_on_posix():
    from codex_harness.host_os.adapters.windows import job_objects, no_console

    assert not hasattr(job_objects, "_kernel32"), "no Windows library is loaded on POSIX"
    assert no_console.taskkill_argv(7) == ["taskkill", "/PID", "7", "/T", "/F"]
    assert no_console.creation_kwargs(process_group=True) == {
        "creationflags": no_console.CREATE_NO_WINDOW | no_console.CREATE_NEW_PROCESS_GROUP}
