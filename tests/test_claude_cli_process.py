"""U002 C02, C03, C06: the Claude Code CLI transport's process, stream and termination boundaries.

Every run here drives `tests/claude_protocol_child.py`, a fault injector that speaks the CLI's
stream shape. It proves how the adapter behaves against a hostile or broken child; it proves
nothing about a model, and the adapter records the fixture launcher with every run so a receipt
made this way can never be read as a provider measurement (C10 is the real call).
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from codex_harness.adapters.claude_cli import ClaudeCodeRuntime, child_environment, claude_settings
from codex_harness.domain.invocation import classify_result, parse_request, usage_record
from codex_harness.domain.model import ContractError

CHILD = Path(__file__).resolve().parent / "claude_protocol_child.py"
RUNTIME = {"output_format": "stream-json", "input_format": "text", "verbose": True,
           "permission_mode": "acceptEdits", "permission_prompts": "none", "setting_sources": "",
           "strict_mcp_config": True, "tools": ["Bash", "Read", "Edit"],
           "allowed_tools": ["Read", "Edit", "Bash(python -m pytest *)"],
           "disallowed_tools": ["Task", "WebFetch"]}
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"summary": {"type": "string"}, "tests": {"type": "array", "items": {"type": "string"}}},
          "required": ["summary", "tests"]}


def transport(scenario: str, **kwargs) -> ClaudeCodeRuntime:
    return ClaudeCodeRuntime(model="claude-stub-" + scenario, runtime=RUNTIME, executable=str(CHILD),
                             launcher=[sys.executable], max_budget_usd=1.0,
                             settings_document=claude_settings(RUNTIME), **kwargs)


def execute(scenario, workspace, prompt="지시문: fixture prompt", timeout=90, **kwargs):
    limits = kwargs.pop("limits", None)
    events, ticks = [], []
    runtime = transport(scenario, **({"limits": limits} if limits else {}), **kwargs)
    with runtime as opened:
        result = opened.run(prompt, str(workspace), SCHEMA, timeout=timeout, on_event=events.append,
                            on_tick=lambda: ticks.append(1))
    return result, events, ticks, runtime


def observation(workspace):
    return json.loads((Path(workspace) / "stub-observation.json").read_text("utf-8"))


# ---- C02: the prompt reaches the child over stdin, through a path with spaces and Hangul ---------

def test_c02_prompt_is_delivered_over_stdin_and_never_appears_in_a_command(tmp_path):
    workspace = tmp_path / "작업 공간 with spaces"
    workspace.mkdir()
    prompt = "지시문: 한글과 공백이 섞인 프롬프트\n" + "본문 라인 " * 200
    result, events, ticks, runtime = execute("normal", workspace, prompt=prompt)
    seen = observation(workspace)
    assert seen["stdin"]["sha256"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert seen["stdin"]["bytes"] == len(prompt.encode("utf-8"))
    # The child echoes the digest of what it read back through its structured output.
    assert result["answer"]["summary"] == seen["stdin"]["sha256"]
    assert seen["cwd"] == str(workspace.resolve()), "the workspace path survived spaces and Hangul"
    for element in seen["argv"]:
        assert prompt not in element and "지시문" not in element
    for element in result["command"]["argv"]:
        assert prompt not in str(element)
    assert result["command"]["prompt_transport"] == "stdin"
    assert result["stream"]["stdin"]["state"] == "written"
    assert result["stream"]["bytes"]["stderr"] > 0, "stderr was drained alongside stdout"
    assert ticks, "the tick ran while the child was alive"
    assert result["process"]["confirmed"] and result["process"]["exit_code"] == 0


def test_c02_schema_and_settings_travel_as_values_but_never_into_the_recorded_command(tmp_path):
    result, _, _, _ = execute("normal", tmp_path)
    seen = observation(tmp_path)
    assert json.loads(seen["schema"]) == SCHEMA, "the child received the schema itself"
    assert json.loads(seen["settings"])["permissions"]["allow"] == RUNTIME["allowed_tools"]
    recorded = " ".join(str(part) for part in result["command"]["argv"])
    assert "additionalProperties" not in recorded and "Bash(python -m pytest *)" not in recorded
    assert result["command"]["schema_sha256"] and result["command"]["settings_sha256"]
    assert result["command"]["launcher"] == [sys.executable]
    assert "not a provider measurement" in result["command"]["measurement"]


def test_c02_the_child_environment_carries_no_zeus_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://harness:secret@127.0.0.1:55432/harness")
    monkeypatch.setenv("ZEUS_REDIS_URL", "redis://127.0.0.1:56379/0")
    monkeypatch.setenv("POSTGRES_PASSWORD", "fixture-password")
    environment, report = child_environment()
    assert not [name for name in environment if name.startswith(("ZEUS_", "HARNESS_", "POSTGRES_"))]
    assert {"HARNESS_DATABASE_URL", "ZEUS_REDIS_URL", "POSTGRES_PASSWORD"} <= set(report["withheld_zeus_names"])
    assert all("secret" not in str(value) for value in report.values() if not isinstance(value, list))
    result, _, _, _ = execute("normal", tmp_path)
    seen = observation(tmp_path)
    assert not [name for name in seen["environment_names"] if name.startswith(("ZEUS_", "HARNESS_", "POSTGRES_"))]
    assert "PATH" in seen["environment_names"], "the child still has what it needs to start"
    assert result["command"]["environment"]["withheld_zeus_names"]


# ---- C03: what the run produced, named from what was observed ------------------------------------

@pytest.mark.parametrize("scenario,outcome,cause", [
    ("normal", "accepted", None),
    ("empty", "empty_answer", None),
    ("toolonly", "tool_only", None),
    ("malformed", "accepted", None),
    ("redelivered", "accepted", None),
    ("noterminal", "provider_failure", "claude-provider-missing-terminal"),
    ("conflict", "provider_failure", "claude-provider-conflicting-terminal"),
    ("badschema", "invalid_output", "claude-output-schema-mismatch"),
    ("error", "provider_failure", "claude-provider-error-result"),
    ("budget", "provider_failure", "claude-provider-budget-exhausted"),
    ("maxturns", "provider_failure", "claude-provider-max-turns"),
])
def test_c03_each_observed_ending_gets_its_own_name(tmp_path, scenario, outcome, cause):
    result, events, _, _ = execute(scenario, tmp_path)
    assert classify_result(result) == outcome
    assert (result.get("failure") or {}).get("cause") == cause
    assert result["provider"] == "claude-code-cli" and result["transport"] == "claude_cli"
    # The raw provider line is kept beside the normalized one and never renamed into another protocol.
    for event in events:
        assert event["provider"] == "claude-code-cli"
        assert "method" not in event and "params" not in event
    assert result["interrupted"] is False and result["rotate"] is False


def test_c03_a_clean_exit_with_no_output_is_not_an_answer(tmp_path):
    result, _, _, _ = execute("empty", tmp_path)
    assert result["process"]["exit_code"] == 0 and result["terminal"]["subtype"] == "success"
    assert result["answer"] is None and classify_result(result) != "accepted"
    assert result["structural"]["checks"]["text"] == "failed"


def test_c03_tool_activity_without_an_answer_is_tool_only_and_observed_by_the_runner(tmp_path):
    result, _, _, _ = execute("toolonly", tmp_path)
    assert classify_result(result) == "tool_only" and result["answer"] is None
    assert result["tool_items"] == 1
    assert result["tool_usage_observed"]["completed"] == ["toolu_fixture_1"]
    assert result["tool_usage_observed"]["started"] == ["toolu_fixture_1"]


def test_c03_malformed_lines_are_counted_and_never_stop_a_valid_terminal(tmp_path):
    result, events, _, _ = execute("malformed", tmp_path)
    assert result["stream"]["malformed_lines"] == 3
    assert classify_result(result) == "accepted"
    defects = [event["defect"] for event in events if event["type"] == "malformed"]
    assert len(defects) == 3 and all(defects)


def test_c03_an_identical_repeat_is_a_redelivery_and_a_different_one_is_a_conflict(tmp_path):
    same, _, _, _ = execute("redelivered", tmp_path)
    assert same["terminal"]["redelivered"] == 1 and same["terminal"]["conflicting"] is False
    different, _, _, _ = execute("conflict", tmp_path)
    assert different["terminal"]["conflicting"] is True
    assert different["failure"]["cause"] == "claude-provider-conflicting-terminal"


def test_c03_the_schema_is_checked_here_not_taken_on_the_providers_word(tmp_path):
    result, _, _, _ = execute("badschema", tmp_path)
    assert result["answer"] is None
    assert result["failure"]["cause"] == "claude-output-schema-mismatch"
    assert result["failure"]["owner"] == "agent_output"
    assert result["structural"]["checks"]["schema"] == "failed"
    assert result["answer_source"] == "structured_output"


def test_c03_a_refused_permission_is_recorded_and_is_not_an_answer(tmp_path):
    result, events, _, _ = execute("denied", tmp_path)
    assert [event["type"] for event in events if event["type"] == "permission_denied"] == ["permission_denied"]
    assert result["stream"]["permission_denials"] == [{"id": "denial-1", "status": "denied"}]
    assert classify_result(result) != "accepted"


# ---- C04 at the transport: usage is read once, from the terminal message -------------------------

def test_c04_usage_comes_only_from_the_terminal_message_and_names_its_parts(tmp_path):
    result, _, _, _ = execute("redelivered", tmp_path)
    record = usage_record({**result, "requested_model": result["requested_model"]}, "claude_cli")
    assert record["source"] == "claude/result.usage"
    assert record["parts"] == {"input_tokens": 120, "output_tokens": 30,
                               "cache_creation_input_tokens": 5, "cache_read_input_tokens": 7}
    # 120 + 30 + 5 + 7 counted once, although two identical result messages arrived.
    assert record["total_tokens"] == 162 and record["basis"] == "result_total_including_cache"
    assert record["confirmed_model"] == "stub-reported-model"
    assert record["requested_model"] == "claude-stub-redelivered"
    assert record["reported_cost_usd"] == 0.0123 and record["cost_source"] == "provider_estimate"
    assert "never a billed amount" in record["cost_note"]


# ---- C06: bounded endings, with the tree actually gone -------------------------------------------

def test_c06_a_silent_child_ends_at_the_deadline_with_its_tree_confirmed_gone(tmp_path):
    started = time.monotonic()
    result, _, ticks, runtime = execute("silent", tmp_path, timeout=4)
    assert 3 <= time.monotonic() - started < 40
    assert result["failure"]["cause"] == "claude-provider-timeout"
    assert result["process"]["confirmed"] and result["process"]["stop_reason"] == "deadline"
    assert runtime.process.poll() is not None
    assert len(ticks) > 1, "the tick kept running while nothing arrived"


def test_c06_a_child_that_never_reads_stdin_does_not_deadlock_the_runner(tmp_path):
    result, _, _, runtime = execute("nostdin", tmp_path, prompt="x" * 200000, timeout=4)
    assert result["failure"]["cause"] == "claude-provider-timeout"
    assert result["process"]["confirmed"] and runtime.process.poll() is not None
    assert result["stream"]["stdin"]["state"] in {"pending", "written", "failed", "written_close_failed"}


def test_c06_a_flooding_child_is_bounded_and_says_so(tmp_path):
    result, events, _, _ = execute("flood", tmp_path, limits={"stream_bytes": 200_000, "retained_events": 20})
    assert result["stream"]["truncated"] is True
    assert result["failure"]["cause"] == "claude-provider-stream-truncated"
    # Past the limit nothing more is kept, so the retained events stay few, while the byte counter
    # shows the reader went on to the end of the pipe rather than leaving the child blocked on it.
    assert len(events) <= 20
    assert result["stream"]["bytes_total"] > 3_000_000 and result["process"]["exit_code"] == 0


def test_c06_an_oversized_line_is_skipped_and_recorded_without_losing_the_run(tmp_path):
    result, events, _, _ = execute("longline", tmp_path, limits={"line_bytes": 100_000})
    assert result["stream"]["counts"]["oversized_line"] == 1
    assert any(event["raw_type"] == "oversized" for event in events)
    assert classify_result(result) == "accepted", "the terminal result after the oversized line still counted"


def test_c06_a_lost_lease_stops_the_tree_before_the_failure_is_raised(tmp_path):
    calls = {"count": 0}

    def tick():
        calls["count"] += 1
        if calls["count"] > 3:
            raise ContractError("Execution lease lost")

    runtime = transport("silent")
    with runtime as opened:
        with pytest.raises(ContractError, match="lease lost"):
            opened.run("prompt", str(tmp_path), SCHEMA, timeout=60, on_tick=tick)
    assert runtime.process.poll() is not None
    assert runtime._termination["confirmed"] is True


def test_c06_cancelling_ends_the_run_without_waiting_for_the_deadline(tmp_path):
    checks = {"count": 0}

    def cancel():
        checks["count"] += 1
        return checks["count"] > 3

    runtime = transport("silent")
    started = time.monotonic()
    with runtime as opened:
        result = opened.run("prompt", str(tmp_path), SCHEMA, timeout=300, cancel=cancel)
    assert time.monotonic() - started < 60
    assert result["failure"]["cause"] == "claude-provider-cancelled"
    assert result["process"]["confirmed"] and runtime.process.poll() is not None


def test_c06_the_descendants_of_the_child_are_killed_with_it(tmp_path):
    result, _, _, runtime = execute("tree", tmp_path, timeout=5)
    assert result["process"]["confirmed"], "the adapter proved the process it started is gone"
    assert result["process"]["exit_code"] is not None, "the exit is proven by an exit code"
    descendants = result["process"]["descendants"]
    if os.name != "nt":
        assert result["process"]["group_empty"] is True and descendants["confirmed"] is True
    else:
        # Windows has no group to poll, so the tree kill's result is recorded beside the proven
        # parent exit rather than being allowed to turn that exit into an unknown outcome.
        assert descendants["method"] == "taskkill /T /F" and "result" in descendants
    marker = Path(observation(tmp_path)["grandchild_marker"])
    assert marker.exists(), "the grandchild was alive and writing before the kill"
    time.sleep(1.5)
    settled = marker.read_bytes()
    time.sleep(1.5)
    assert marker.read_bytes() == settled, "the grandchild stopped writing when its parent tree died"


def test_c06_an_unconfirmed_termination_is_unknown_and_raises_rather_than_returning(tmp_path, monkeypatch):
    runtime = transport("silent")
    with runtime as opened:
        monkeypatch.setattr(opened, "_terminate",
                            lambda reason: {"reason": reason, "method": "fixture", "confirmed": False,
                                            "exit_code": None, "escalated": True, "group_empty": False,
                                            "signal_result": None})
        with pytest.raises(ContractError, match="termination could not be confirmed"):
            opened.run("prompt", str(tmp_path), SCHEMA, timeout=3)
    assert runtime.process.poll() is not None or runtime.process.kill() is None


# ---- the transport's declared support matrix is enforced before anything starts -------------------

def test_the_request_matrix_refuses_what_this_transport_cannot_prove(tmp_path):
    accepted = parse_request("claude_cli", {"model": "claude-fable-5-1", "timeout": 30,
                                            "output_schema": SCHEMA, "read_only": False,
                                            "max_budget_usd": 1.0, "permission_mode": "acceptEdits"})
    assert accepted["options"]["max_budget_usd"] == 1.0
    assert accepted["unconfirmed"] == ["read_only"]
    assert set(accepted["unsupported"]) == {"session_resume", "system", "temperature",
                                            "max_output_tokens", "response_format"}
    with pytest.raises(ContractError, match="cannot prove it applies"):
        parse_request("claude_cli", {"model": "claude-fable-5-1", "read_only": True})
    with pytest.raises(ContractError, match="not supported by claude_cli"):
        parse_request("claude_cli", {"model": "claude-fable-5-1", "session_resume": True})
    with pytest.raises(ContractError, match="read-only"):
        transport("normal").run("p", str(tmp_path), SCHEMA, timeout=10, read_only=True)
    with pytest.raises(ContractError, match="differs from the configured"):
        transport("normal").run("p", str(tmp_path), SCHEMA, timeout=10, model="claude-other")


def test_an_installed_cli_without_a_required_option_is_refused_before_entry(tmp_path, monkeypatch):
    runtime = transport("normal")
    monkeypatch.setattr(runtime, "_read_capabilities", lambda: ("--print", "--model"))
    with pytest.raises(ContractError, match="lacks required options"):
        runtime.__enter__()
    assert runtime.process is None, "nothing was started"


def test_a_missing_cli_is_a_refusal_that_never_starts_anything():
    runtime = ClaudeCodeRuntime(model="claude-fable-5-1", executable=None, max_budget_usd=1.0)
    runtime.executable = None
    with pytest.raises(ContractError, match="not installed"):
        runtime.__enter__()
    assert runtime.process is None
