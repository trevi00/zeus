"""S8 pilot 99 (DESIGN-s8 §13 V18): M7 `adapters/canary.py` moves to `review.adapters.canary` with the hook rule and the Codex probe injected.

M7 is read only as text through `git show e38aa722:...` and compared by AST (never imported: both packages are named `codex_harness`). Behaviour is
compared by the recorded `review.canary` golden; the head refusal has no M7 counterpart and is pinned here."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.research.domain.recurrence import hook_apply
from codex_harness.review.adapters import canary as module
from codex_harness.review.adapters.canary import executable_canary

REPO = Path(__file__).resolve().parents[2]
SOURCE = "e38aa722"
HOMES = {"__future__": ["annotations"], "subprocess": [], "codex_harness.kernel.errors": ["require"]}
REQUIRE = "require(hook_apply is not None and probe is not None, 'canary needs the hook rule and the Codex probe')"
ALIAS = {"kind": "executable_alias", "match": "codex.ps1", "replacement": "codex.cmd", "platform": "windows"}


def m7_text():
    return subprocess.run(["git", "-C", str(REPO), "show", f"{SOURCE}:src/codex_harness/adapters/canary.py"], check=True,
                          capture_output=True, text=True).stdout


def target_text():
    return Path(module.__file__).read_text()


def function(src):
    return next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "executable_canary")


def test_the_module_is_one_function_and_nothing_else_moved_or_was_added():
    ref, ours = ast.parse(m7_text()).body, ast.parse(target_text()).body
    assert [n.name for n in ref if isinstance(n, ast.FunctionDef)] == [n.name for n in ours if isinstance(n, ast.FunctionDef)] == ["executable_canary"]
    assert [type(n).__name__ for n in ours if not isinstance(n, (ast.Import, ast.ImportFrom, ast.Expr))] == ["FunctionDef"]


def test_r_cn1_signature_gains_two_keyword_only_callables_defaulting_to_none():
    ref, ours = function(m7_text()), function(target_text())
    assert [a.arg for a in ours.args.args] == [a.arg for a in ref.args.args] == ["spec"]
    assert [a.arg for a in ours.args.kwonlyargs] == ["hook_apply", "probe"]
    assert [ast.unparse(d) for d in ours.args.kw_defaults] == ["None", "None"]
    assert ast.unparse(ours.returns) == ast.unparse(ref.returns) == "dict" and ours.args.defaults == []


def test_r_cn1_one_require_follows_the_docstring_and_the_rest_is_m7s_modulo_the_probe_call():
    ref, ours = function(m7_text()), function(target_text())
    assert ast.unparse(ours.body[0]) == ast.unparse(ref.body[0]) and ast.get_docstring(ours) == ast.get_docstring(ref)
    assert ast.unparse(ours.body[1]) == REQUIRE
    assert ast.unparse(ours.body[2:]) == "\n".join(ast.unparse(n) for n in ref.body[1:]).replace("CodexRuntime().probe()", "probe()")
    requires = [n for n in ast.walk(ast.parse(target_text())) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "require"]
    assert len(requires) == 1


def test_the_except_clause_is_unchanged_and_hook_apply_is_the_parameter():
    ours = function(target_text())
    handlers = [n for n in ast.walk(ours) if isinstance(n, ast.ExceptHandler)]
    assert [ast.unparse(h.type) for h in handlers] == ["(OSError, subprocess.SubprocessError, ValueError)"]
    assert not any(isinstance(n, ast.Name) and n.id == "CodexRuntime" for n in ast.walk(ast.parse(target_text())))


def test_imports_are_only_the_v18_homes():
    found = {}
    for n in ast.parse(target_text()).body:
        if isinstance(n, ast.ImportFrom):
            found[n.module] = sorted(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            found.update({a.name: [] for a in n.names})
    assert found == {k: sorted(v) for k, v in HOMES.items()}


def test_header_names_context_layer_the_move_and_the_rules():
    header = target_text().split('"""')[1]
    for needle in ("Layer: adapters", "Context: review", "Owns:", "Does not own:", "Entry points:", "Contracts:",
                   "Moved from M7 `adapters/canary.py`", "SOURCE e38aa722", "V18", "A/evidence/rebuild/s8/canary-move/transcribe.py",
                   "R-cn0", "R-cn1"):
        assert needle in header, needle


@pytest.mark.parametrize("kwargs", [{}, {"hook_apply": hook_apply}, {"probe": lambda: {"passed": True}}])
def test_a_missing_collaborator_is_refused_before_either_runs(kwargs):
    calls = []
    wired = {k: (lambda *a, **kw: calls.append(k) or {"passed": True}) if k == "probe" else v for k, v in kwargs.items()}
    with pytest.raises(ContractError, match="canary needs the hook rule and the Codex probe"):
        executable_canary(ALIAS, **wired)
    assert calls == []


def test_the_wired_function_reproduces_the_incident_and_probes_once():
    calls = []

    def probe():
        calls.append(1)
        return {"passed": True, "version": "v", "exit_code": 0}

    result = executable_canary(ALIAS, hook_apply=hook_apply, probe=probe)
    assert result["checks"] == {"reproduction": True, "normal_case": True, "cli_start": True} and calls == [1]
    assert result["scope"] == "bootstrap-command-hook; not a release deployment canary"


def test_an_unavailable_probe_is_a_failed_start_not_an_error():
    def probe():
        raise OSError("no codex")

    result = executable_canary(ALIAS, hook_apply=hook_apply, probe=probe)
    assert result["probe"] == {"passed": False, "version": "unavailable"} and result["checks"]["cli_start"] is False
