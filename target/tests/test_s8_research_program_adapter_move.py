"""S8 pilot 74: the M7 `adapters/research_program.py` moved into research, VERBATIM through named rules
(A/evidence/rebuild/s8/research-program-adapter-move/transcribe.py; DESIGN-s8 §6 V11, §8 V13).

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named
`codex_harness`). Behaviour is checked on the TARGET only, against literals; the recorded comparison is the
`research.capture` golden.
"""
import ast
import importlib
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "target" / "src" / "codex_harness"
SOURCE = "e38aa722"
MOD = "codex_harness.research.adapters.research_program"
M7_PATH = "src/codex_harness/adapters/research_program.py"


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:{M7_PATH}"], check=True, capture_output=True,
                          text=True).stdout


def target_text():
    return Path(importlib.import_module(MOD).__file__).read_text()


def defined(node):
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.Assign):
        return tuple(n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return ()


def statements(src):
    out = {}
    for i, node in enumerate(ast.parse(src).body):
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            continue
        key = defined(node) or ("expr", i)
        assert key not in out
        out[key] = node
    return out


def methods(src, name):
    klass = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in klass.body if isinstance(n, ast.FunctionDef)}


def test_adapter_is_m7_in_m7_order_and_only_the_named_statements_differ():
    ref, ours = statements(m7_text()), statements(target_text())
    keys = list(ref)
    assert len(keys) == 14 and len(ours) == 15
    expected = []
    for key in keys:
        if key == ("CAPTURE_AUTHOR",):
            expected.append(("RUNS",))
        expected.append(key)
    assert list(ours) == expected
    changed = [key[0] for key, node in ref.items() if ast.dump(ours[key]) != ast.dump(node)]
    assert sorted(changed) == ["GitCapture", "collect_local"]
    theirs, mine = methods(m7_text(), "GitCapture"), methods(target_text(), "GitCapture")
    assert list(mine) == list(theirs) == ["__init__", "_git", "capture", "_hash_blob"]
    assert [k for k in theirs if ast.dump(mine[k]) != ast.dump(theirs[k])] == ["__init__", "_git", "capture"]


def test_r_q2_ports_are_keyword_only_with_one_require_at_each_first_use():
    text, m7 = target_text(), m7_text()
    new, old = methods(text, "GitCapture")["__init__"].args, methods(m7, "GitCapture")["__init__"].args
    assert [a.arg for a in new.args] == [a.arg for a in old.args] == ["self", "repository", "timeout"]
    assert old.kwonlyargs == [] and [a.arg for a in new.kwonlyargs] == ["run_process", "git_source"]
    assert all(isinstance(d, ast.Constant) and d.value is None for d in new.kw_defaults)
    assert m7.count("run_process(") == 1 and text.count("self.run_process(") == 1
    assert m7.count("GitSource(") == 1 and text.count("self.git_source(self.repository).blob(") == 1
    for old_name in ("GitSource(", "commands", "operation_cli", "dge_cli"):
        assert old_name not in text.replace("self.git_source(", "")
    assert "= run_process(" not in text
    for port, message, first_use in (("run_process", "run_process is not wired", "self.run_process("),
                                     ("git_source", "git_source is not wired", "self.git_source(self.repository)")):
        require = f"require(self.{port} is not None, '{message}')"
        assert text.count(require) == 1, port
        assert text.index(require) < text.index(first_use), port


def test_r_q3_verify_sources_is_a_keyword_only_port_checked_before_the_try():
    text = target_text()
    fn = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "collect_local")
    assert [a.arg for a in fn.args.args] == ["config", "source"]
    assert [a.arg for a in fn.args.kwonlyargs] == ["verify_sources"] and fn.args.kw_defaults[0].value is None
    require = "require(verify_sources is not None, 'verify_sources is not wired')"
    assert text.count(require) == 1
    # before the try: its `except Exception` would otherwise turn the refusal into an "unavailable" status
    assert text.index(require) < text.index("        bound = verify_sources(")
    assert text.index(require) < text.index("    try:\n        bound = verify_sources(")


def test_r_q1_runs_is_a_local_constant_equal_to_the_coordination_owner():
    from codex_harness.coordination.application import autonomous

    module = importlib.import_module(MOD)
    assert module.RUNS == autonomous.BUCKET == "autonomous_runs"
    assert 'RUNS = "autonomous_runs"' in target_text()
    assert "application.autonomous" not in target_text()


def test_imports_are_only_kernel_and_research_homes_and_no_host_os():
    tree = ast.parse(target_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module.startswith("codex_harness.")}
    assert mods == {"codex_harness.kernel.errors", "codex_harness.kernel.ids",
                    "codex_harness.research.application.research_program", "codex_harness.research.domain.audit_progress",
                    "codex_harness.research.domain.autonomous", "codex_harness.research.domain.dge",
                    "codex_harness.research.domain.discovery_pressure", "codex_harness.research.domain.research_attempt_scope",
                    "codex_harness.research.domain.research_investigations", "codex_harness.research.domain.research_program"}
    assert not [m for m in mods if m.startswith(("codex_harness.domain", "codex_harness.application", "codex_harness.adapters"))]
    for path in (SRC / "research").rglob("*.py"):  # V11: research never imports host_os; composition injects it
        assert not [n for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ImportFrom)
                    and (n.module or "").startswith("codex_harness.host_os")], path


def test_composition_wires_the_host_os_ports_and_the_s10_verifier_is_bound_by_the_caller(tmp_path):
    from codex_harness.composition import research_program_adapters as composition
    from codex_harness.host_os.adapters import git_source, process_groups

    capture = composition.git_capture(tmp_path)
    assert (capture.run_process, capture.git_source) == (process_groups.run_process, git_source.GitSource)
    assert capture.timeout == 60
    calls = []
    bound = composition.local_collector(lambda packet, source: calls.append((packet, source)) or [])
    assert bound({"local_candidates": [], "base_revision": "b"}, "src")[1] == [] and calls == []


def test_an_unwired_capture_refuses_at_its_first_git_use_with_the_added_require():
    from codex_harness.kernel.errors import ContractError

    module = importlib.import_module(MOD)
    capture = module.GitCapture("/nonexistent")
    assert (capture.run_process, capture.git_source) == (None, None)
    path, ref = "docs/zeus/research-captures/rp/001.json", "refs/zeus/research/rp/001"
    with pytest.raises(module.CaptureError):  # the pure checks still run first, in M7's order
        capture.capture("b" * 40, "bad", "{}", ref)
    with pytest.raises(ContractError) as info:
        capture.capture("b" * 40, path, "{}", ref)
    assert str(info.value) == "run_process is not wired"


def test_an_unwired_verify_sources_refuses_instead_of_marking_the_source_unavailable():
    from codex_harness.kernel.errors import ContractError

    module = importlib.import_module(MOD)
    config = {"local_candidates": [{"id": "x"}], "base_revision": "b"}
    with pytest.raises(ContractError) as info:
        module.collect_local(config, object())
    assert str(info.value) == "verify_sources is not wired"
    assert module.collect_local({"local_candidates": [], "base_revision": "b"}, object())[0]["status"] == "ok"


def test_the_wired_collect_local_keeps_m7_unavailable_mapping():
    module = importlib.import_module(MOD)

    def refuse(packet, source):
        raise module.DgeRefused("source_digest_mismatch")
    status, items = module.collect_local({"local_candidates": [{"id": "x"}], "base_revision": "b"}, object(),
                                         verify_sources=refuse)
    assert (status["status"], status["code"], items) == ("unavailable", "source_digest_mismatch", [])
