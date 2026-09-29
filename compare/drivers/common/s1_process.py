"""Scenario body `host_os.process` (REBUILD-DESIGN-v2 §5.3 S1: process groups/trees, the spawn path,
timeouts and cleanup outcomes, scratch removal, pure host diagnostics).

Layer: harness (never shipped). `api` provides the side's host_os pieces: no_console_kwargs,
python_channel_environment, run_process, run_logged_process, observe_spawns, ProcessCancelled,
ProcessTree, Scratch, publication, narrow, parse_service_args, exit_facts, safe_scalar,
ContractError. Children are this side's own Python interpreter running fixed one-line programs;
no provider, Docker or network is involved. OS pids and process-group ids are projected out of every
result (they are not injectable); what remains are exit codes, flags, methods, reasons and
receipt field names.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from s1_common import outcome, relative

PY = sys.executable
PIDISH = {"pid", "group", "pgid", "process_id", "leader"}


def project(value):
    if isinstance(value, dict):
        return {k: ("<pid>" if k in PIDISH and isinstance(v, int) else project(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [project(v) for v in value]
    return value


def spawns(api, root: Path) -> dict:
    out: dict = {}
    out["no_console_kwargs"] = [
        api.no_console_kwargs(platform="posix"), api.no_console_kwargs(process_group=True, platform="posix"),
        api.no_console_kwargs(platform="nt"), api.no_console_kwargs(process_group=True, platform="nt"),
        api.no_console_kwargs(process_group=True, creationflags=0x4, platform="nt"),
        api.no_console_kwargs(process_group=True)]
    env = api.python_channel_environment({"A": "1", "PYTHONIOENCODING": "latin-1"})
    out["python_channel_environment"] = env
    child_env = api.python_channel_environment()
    done = api.run_process([PY, "-c", "import sys; print('é ok'); print('err', file=sys.stderr)"],
                           env=child_env)
    out["run_process"] = {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
                          "type": type(done).__name__, "args_kept": done.args[0] == PY}
    echoed = api.run_process([PY, "-c", "import sys; data = sys.stdin.read(); print(data.upper()); sys.exit(3)"],
                             input_text="input é", env=child_env, cwd=str(root))
    out["run_process_input"] = [echoed.returncode, echoed.stdout]
    out["run_process_timeout"] = outcome(lambda: api.run_process(
        [PY, "-c", "import time; time.sleep(30)"], timeout=1, env=child_env))
    out["run_process_timeout"].pop("message", None)
    seen = []
    with api.observe_spawns(seen.append):
        api.run_process([PY, "-c", "pass"], env=child_env)
    out["observed_spawns"] = len(seen)

    def refusing(pid):
        raise RuntimeError("record not written")

    marker = root / "marker"
    with api.observe_spawns(refusing):
        out["observer_refusal"] = outcome(lambda: api.run_process(
            [PY, "-c", f"import time; time.sleep(2); open({str(marker)!r}, 'w').write('ran')"], env=child_env))
    out["observer_refusal_child_ran"] = marker.exists()

    logged = root / "logged"
    logged.mkdir()
    ok = api.run_logged_process([PY, "-c", "print('out'); import sys; print('err', file=sys.stderr)"],
                                stdout_path=logged / "a.out", stderr_path=logged / "a.err", env=child_env)
    out["logged_ok"] = {"observation": ok, "stdout": (logged / "a.out").read_text(),
                        "stderr": (logged / "a.err").read_text()}
    timed = api.run_logged_process([PY, "-c", "import time; print('started', flush=True); time.sleep(30)"],
                                   stdout_path=logged / "b.out", stderr_path=logged / "b.err", timeout=2,
                                   env=child_env)
    out["logged_timeout"] = {"observation": project(timed), "stdout": (logged / "b.out").read_text()}
    stray = api.run_logged_process(
        [PY, "-c", "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])"],
        stdout_path=logged / "c.out", stderr_path=logged / "c.err", timeout=20, env=child_env)
    out["logged_stray_descendants"] = project(stray)
    return out


def trees(api, root: Path) -> dict:
    out: dict = {}
    child_env = api.python_channel_environment()
    tree = api.ProcessTree.spawn([PY, "-c", "import time; time.sleep(30)"], env=child_env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out["boundary"] = project(tree.boundary)
    receipt = tree.terminate("fixture stop", timeout=5, settle=5)
    out["receipt"] = project(receipt)
    out["receipt_kept"] = project(tree.receipt) == out["receipt"]
    tree.close()
    family = api.ProcessTree.spawn(
        [PY, "-c", "import subprocess, sys, time; "
                   "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); time.sleep(30)"],
        env=child_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import time as _time
    _time.sleep(0.5)
    out["family_receipt"] = project(family.terminate("fixture stop with a grandchild", timeout=5, settle=5))
    family.close()
    exited = api.ProcessTree.spawn([PY, "-c", "pass"], env=child_env)
    exited.process.wait(10)
    out["already_exited_receipt"] = project(exited.terminate("already gone", timeout=5, settle=5))
    exited.close()
    return out


def scratch(api, root: Path) -> dict:
    out: dict = {}
    base = root / "scratch-root"
    base.mkdir()
    box = api.Scratch(base)
    (base / "sub").mkdir()
    (base / "sub" / "file.txt").write_text("x", encoding="utf-8")
    readonly = base / "sub" / "readonly.txt"
    readonly.write_text("y", encoding="utf-8")
    readonly.chmod(0o444)
    (base / "sub").chmod(0o555)
    outside = root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    os.symlink(outside, base / "link-out")
    out["within"] = [box.within(base / "sub"), box.within(outside), box.within(base / "link-out")]
    out["refused_root"] = relative(outcome(lambda: api.Scratch(root / "missing")), {"ROOT": str(root)})
    report = box.remove(timeout=10)
    report.pop("seconds", None)
    # Directory iteration order is the filesystem's (tmpfs under bwrap, a disk elsewhere): the lists
    # are compared as sets of rows.
    for key in ("refusals", "blocking_refusals", "remaining", "cleared_read_only", "links_removed"):
        if isinstance(report.get(key), list):
            report[key] = sorted(report[key], key=lambda row: json.dumps(row, sort_keys=True))
    out["remove"] = relative(report, {"ROOT": str(root)})
    out["outside_kept"] = (outside / "keep.txt").exists()
    out["root_gone"] = not base.exists()
    return out


def pure(api) -> dict:
    return {
        "publication": [api.publication(24001, 5432), api.publication(None, 6379)],
        "narrow": [api.narrow({}),
                   api.narrow({"container": {"reachable": False}, "windows": {"reachable": True},
                               "wsl": {"reachable": True}}),
                   api.narrow({"container": {"reachable": True}, "windows": {"reachable": False},
                               "wsl": {"reachable": True}}),
                   api.narrow({"container": {"reachable": True}, "windows": {"reachable": True},
                               "wsl": {"reachable": False}}),
                   api.narrow({"container": {"reachable": True}, "windows": {"reachable": True},
                               "wsl": {"reachable": True}}),
                   api.narrow({"container": {"reachable": True}, "windows": {"reachable": None},
                               "wsl": {"reachable": True}})],
        "service_args": [api.parse_service_args(a) for a in (
            ["--journal", "j.jsonl", "--", "fleet", "run"], ["--journal=j.jsonl", "--", "x"], ["--journal", "j"],
            ["--journal"], ["--journal=", "--", "x"], ["--journal", "j", "fleet"], [], ["fleet"])],
        "exit_facts": [api.exit_facts(SystemExit(c))[0] for c in (None, 0, 3, True, False, "text", (1,))],
        "exit_reasons": [api.exit_facts(SystemExit(c))[1].get("reason") for c in (None, 0, 3, "text")],
        "safe_scalar": [api.safe_scalar(v) for v in (1, "x", None, True, 1.5, [1], {"a": 1}, b"x")],
    }


def run(api, root: Path) -> dict:
    return {"spawns": spawns(api, root), "trees": trees(api, root), "scratch": scratch(api, root),
            "pure": pure(api)}
