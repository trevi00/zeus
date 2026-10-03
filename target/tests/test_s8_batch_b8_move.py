"""S8 batch B8 (DESIGN-s8 §31/§32): M7 `adapters/sdd.py` moves to `review.adapters.sdd` (R-sd1 `read_spec` takes `root` and `run_process`, R-sd2
`device_probe` takes `run_process`, R-sd0 the import homes) and M7 `domain/model.py::session_action` is added, verbatim, to
`coordination.application.sessions` (the cross-slice correction).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `review.sdd_adapter` golden (the wired module is target-equal to it); the unwired refusals have no M7 counterpart and are
pinned here.
"""

from __future__ import annotations

import ast
import difflib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.coordination.application import sessions
from codex_harness.kernel import strict_json
from codex_harness.kernel.errors import ContractError
from codex_harness.kernel.policy import POLICY
from codex_harness.review.adapters import sdd as module

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
BASE_HEAD = "14a66bdf6312c87db61717cde39469acd6c35780"
SDD_M7 = "src/codex_harness/adapters/sdd.py"
MODEL_M7 = "src/codex_harness/domain/model.py"
SESSIONS = "target/src/codex_harness/coordination/application/sessions.py"


def git_show(rev, path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True, text=True).stdout


def text_of(mod):
    return Path(mod.__file__).read_text()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        out[getattr(node, "name", None) or i] = node
    return out


def import_modules(src):
    return sorted({n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})


def function_lines(src, name):
    node = statements(src)[name]
    return ast.get_source_segment(src, node).splitlines()


def changed_lines(name):
    ours, theirs = function_lines(text_of(module), name), function_lines(git_show(SOURCE, SDD_M7), name)
    diff = [line for line in difflib.unified_diff(theirs, ours, lineterm="", n=0) if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    return diff


def sample_spec():
    path = REPO / "compare" / "drivers" / "common" / "s8_sdd.py"
    loaded = importlib.util.spec_from_file_location("s8_sdd_fixture", path)
    fixture = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(fixture)
    return fixture.spec()


# ----- the sdd adapter -----------------------------------------------------------------------------------------------------------------------
def test_sdd_is_m7s_modulo_r_sd0_r_sd1_r_sd2():
    ours, theirs = statements(text_of(module)), statements(git_show(SOURCE, SDD_M7))
    assert [k for k in theirs if k != "parse_json"] == list(ours)
    changed = {k for k in ours if ast.dump(ours[k]) != ast.dump(theirs[k])}
    assert changed == {"read_spec", "device_probe"}


def test_parse_json_is_the_kernels_and_stays_a_name_of_the_module():
    assert module.parse_json is strict_json.parse_json
    assert "parse_json" in statements(git_show(SOURCE, SDD_M7)) and "parse_json" not in statements(text_of(module))


def test_every_changed_line_is_an_r_sd1_or_r_sd2_line():
    assert changed_lines("read_spec") == [
        "-def read_spec(path, revision=None):",
        "-    path, root = Path(path).resolve(), repository_root()",
        "+def read_spec(path, revision=None, *, root=None, run_process=None):",
        '+    require(root is not None, "root is not wired")',
        "+    path = Path(path).resolve()",
        '+        require(run_process is not None, "run_process is not wired")']
    assert changed_lines("device_probe") == [
        "-def device_probe():",
        "+def device_probe(*, run_process=None):",
        '+    require(run_process is not None, "run_process is not wired")']


def test_the_run_process_require_sits_immediately_before_each_first_call():
    for name in ("read_spec", "device_probe"):
        lines = [line.strip() for line in function_lines(text_of(module), name)]
        guard = lines.index('require(run_process is not None, "run_process is not wired")')
        assert "run_process(" in lines[guard + 1]
        assert not any("run_process(" in line for line in lines[:guard])
    assert function_lines(text_of(module), "read_spec")[1].strip() == 'require(root is not None, "root is not wired")'


def test_the_sdd_import_homes_and_no_host_import():
    imports = import_modules(text_of(module))
    assert imports == ["codex_harness.kernel.errors", "codex_harness.kernel.ids", "codex_harness.kernel.strict_json",
                       "codex_harness.review.domain.sdd", "importlib.resources", "pathlib"]
    source = text_of(module)
    assert "subprocess" not in source and "adapters.commands" not in source and "configuration" not in source
    calls = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "run_process"]
    assert len(calls) == 4  # M7's four call sites (two in read_spec, two in device_probe), each of the injected parameter (the module binds no run_process name)
    assert "run_process" not in {a.asname or a.name for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}


# ----- R-sd1 / R-sd2: refused when unwired, before any spawn -----------------------------------------------------------------------------------
class Recorder:
    def __init__(self, stdout="", returncode=0):
        self.calls, self.stdout, self.returncode = [], stdout, returncode

    def __call__(self, argv, cwd=None, timeout=120, **kwargs):
        self.calls.append((list(argv), cwd))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


def test_read_spec_git_mode_without_run_process_is_refused_before_any_spawn(tmp_path):
    with pytest.raises(ContractError, match="run_process is not wired"):
        module.read_spec(tmp_path / "spec.json", "HEAD", root=tmp_path)
    with pytest.raises(ContractError, match="run_process is not wired"):
        module.read_spec(tmp_path / "spec.json", "HEAD", root=tmp_path, run_process=None)


def test_read_spec_without_root_is_refused_first_in_either_mode(tmp_path):
    recorder = Recorder()
    for revision in (None, "", "HEAD"):
        with pytest.raises(ContractError, match="root is not wired"):
            module.read_spec(tmp_path / "does-not-exist.json", revision, run_process=recorder)
    assert recorder.calls == []


def test_read_spec_draft_mode_spawns_nothing_and_needs_no_run_process(tmp_path):
    (tmp_path / "spec.json").write_text(json.dumps(sample_spec()), encoding="utf-8")
    loaded, provenance = module.read_spec(tmp_path / "spec.json", root=tmp_path)
    assert loaded["id"] == "spec.alpha"
    assert provenance == {"mode": "working_tree_draft", "repository": str(tmp_path), "revision": None, "path": str(tmp_path / "spec.json")}


def test_read_spec_git_mode_runs_the_injected_process_in_the_injected_root(tmp_path):
    body = json.dumps(sample_spec())
    sha = "c" * 40

    def runner(argv, cwd=None, timeout=120, **kwargs):
        runner.calls.append((list(argv), cwd))
        return SimpleNamespace(returncode=0, stdout=sha + "\n" if argv[1] == "rev-parse" else body, stderr="")

    runner.calls = []
    loaded, provenance = module.read_spec(tmp_path / "docs" / "spec.json", "main", root=tmp_path, run_process=runner)
    assert runner.calls == [(["git", "rev-parse", "--verify", "main^{commit}"], str(tmp_path)), (["git", "show", sha + ":docs/spec.json"], str(tmp_path))]
    assert loaded["id"] == "spec.alpha"
    assert provenance == {"mode": "git", "repository": str(tmp_path), "revision": sha, "path": "docs/spec.json"}


def test_device_probe_without_run_process_is_refused_before_any_adb_spawn(tmp_path, monkeypatch):
    log = tmp_path / "adb.log"
    adb = tmp_path / "bin" / "adb"
    adb.parent.mkdir()
    adb.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n", encoding="utf-8")
    adb.chmod(0o755)
    monkeypatch.setenv("PATH", str(adb.parent))
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    with pytest.raises(ContractError, match="run_process is not wired"):
        module.device_probe()
    assert not log.exists()
    recorder = Recorder(stdout="List of devices attached\nR5CT1 offline\n")
    report = module.device_probe(run_process=recorder)
    assert recorder.calls == [([str(adb), "devices", "-l"], None)] and report["devices"][0]["state"] == "offline"


def test_device_probe_without_adb_spawns_nothing_and_needs_no_run_process(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    monkeypatch.delenv("ANDROID_SDK_ROOT", raising=False)
    report = module.device_probe()
    assert report["status"] == "blocked" and report["adb_available"] is False


# ----- session_action ------------------------------------------------------------------------------------------------------------------------
def test_session_action_is_m7s_function_and_the_rest_of_sessions_is_unchanged():
    theirs = statements(git_show(SOURCE, MODEL_M7))["session_action"]
    ours = statements(Path(REPO / SESSIONS).read_text())
    assert ast.dump(ours["session_action"]) == ast.dump(theirs)
    base = statements(git_show(BASE_HEAD, SESSIONS))
    assert [k for k in ours if k != "session_action"] == list(base)
    assert all(ast.dump(ours[k]) == ast.dump(base[k]) for k in base)
    assert import_modules(Path(REPO / SESSIONS).read_text()) == ["__future__", "codex_harness.kernel.errors", "codex_harness.kernel.ids",
                                                                   "codex_harness.kernel.policy"]
    assert sessions.POLICY is POLICY


def test_session_action_outcomes_under_the_packaged_policy():
    capacity = 100
    at = int(capacity * POLICY.context_checkpoint_fraction)
    assert sessions.session_action(at, capacity, 0, True) == "checkpoint_when_safe"
    assert sessions.session_action(at, capacity, 0, False) == "rotate"
    assert sessions.session_action(0, capacity, POLICY.idle_seconds, False) == "hibernate"
    assert sessions.session_action(0, capacity, POLICY.idle_seconds, True) == "continue"
    assert sessions.session_action(0, capacity, 0, False) == "continue"
    assert sessions.session_action(at - 1, capacity, POLICY.idle_seconds - 1, False) == "continue"


@pytest.mark.parametrize("used,capacity,idle", [(0, 0, 0), (0, -1, 0), (-1, 10, 0), (0, 10, -0.5)])
def test_session_action_refuses_invalid_telemetry(used, capacity, idle):
    with pytest.raises(ContractError, match="Invalid session telemetry"):
        sessions.session_action(used, capacity, idle, False)
