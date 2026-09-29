"""S4 `codex exec` transport (execution.adapters.providers.codex_exec.CodexRuntime) on the target.

Adapted from SOURCE M7 `tests/test_output_schema.py::test_all_outputs_reach_both_transport_boundaries` and
`::test_cli_preflight_blocks_before_process`: the M7 tests patched the module's `run_process`; the target
injects the host_os ProcessRunner, so the same fixture is passed as `runner`. No Codex process is started.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.execution.adapters.providers.codex_exec import CodexRuntime
from codex_harness.kernel.errors import ContractError

SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"summary": {"type": "string"}},
          "required": ["summary"]}


def test_the_schema_reaches_the_output_schema_file_and_the_prompt_travels_on_stdin(tmp_path):
    seen = []

    def run(argv, **kwargs):
        seen.append((json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text()), kwargs["input_text"]))
        return SimpleNamespace(returncode=1, stderr="fixture transport reached", stdout="")

    with pytest.raises(ContractError, match="fixture transport reached"):
        CodexRuntime("fixture", runner=run).run("the prompt", str(tmp_path), SCHEMA)
    assert seen == [(SCHEMA, "the prompt")]


@pytest.mark.parametrize("bad", [None, {"properties": {"version": {"const": 1}}},
                                 {"$defs": {"kind": {"const": "AdaptationProposal"}}}])
def test_preflight_blocks_before_any_process(bad, tmp_path):
    calls = []
    with pytest.raises(ContractError, match="sha256:"):
        CodexRuntime("fixture", runner=lambda *a, **kw: calls.append(a)).run("prompt", str(tmp_path), bad)
    assert not calls


def test_a_valid_answer_is_validated_and_events_parsed_a_timeout_is_a_contract_error(tmp_path):
    def answer(argv, **kwargs):
        Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps({"summary": "ok"}))
        return SimpleNamespace(returncode=0, stderr="", stdout='{"type":"x"}\nnot json\n')

    result = CodexRuntime("fixture", runner=answer).run("p", str(tmp_path), SCHEMA)
    assert result == {"answer": {"summary": "ok"}, "events": [{"type": "x"}]}

    def wrong(argv, **kwargs):
        Path(argv[argv.index("--output-last-message") + 1]).write_text(json.dumps({"other": 1}))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        CodexRuntime("fixture", runner=wrong).run("p", str(tmp_path), SCHEMA)

    def slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    with pytest.raises(ContractError, match="Codex invocation timed out"):
        CodexRuntime("fixture", runner=slow).run("p", str(tmp_path), SCHEMA)


def test_probe_reports_the_version_through_the_runner():
    runtime = CodexRuntime("fixture", runner=lambda argv, **kw: SimpleNamespace(returncode=0, stdout="codex 0.156.1\n",
                                                                                 stderr=""))
    assert runtime.probe() == {"passed": True, "version": "codex 0.156.1", "exit_code": 0}
