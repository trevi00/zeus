"""S10 unit E1: the permanent `codex_harness.cli` shim, the `zeus` package, the console scripts and the two in-container entries (R-e1).

The shims import only ENTRY; `--help` through `python -m codex_harness.cli` and `python -m zeus` equals the entry parser's help;
`container_main.main` runs with its two host paths (`/runtime/agents`, `/run/secrets/codex-auth`) redirected under `tmp_path` by replacing
the module's `Path` name (M7's statements are unchanged); `serve` runs over in-memory pipes with a fake runtime factory.
"""
import ast
import io
import json
import os
import subprocess
import sys
import tomllib
from importlib import import_module
from pathlib import Path

import import_rules
import pytest

from codex_harness.composition import isolated_worker_entry as worker
from codex_harness.entry.cli import parser
from codex_harness.entry.processes import container_main
from codex_harness.execution.domain.container_spec import ENTRY_MODULE, EVIDENCE, PROTOCOL, WORKSPACE

TARGET = Path(__file__).resolve().parents[1]
SRC = TARGET / "src"
SHIM_FILES = {
    "codex_harness.cli": SRC / "codex_harness" / "cli.py",
    "codex_harness.container_main": SRC / "codex_harness" / "container_main.py",
    "codex_harness.adapters.isolated_worker_entry": SRC / "codex_harness" / "adapters" / "isolated_worker_entry.py",
    "zeus": SRC / "zeus" / "__init__.py",
    "zeus.__main__": SRC / "zeus" / "__main__.py",
}


def imported_modules(path):
    found = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found += [node.module + "." + alias.name for alias in node.names]
            found.append(node.module)
    return found


@pytest.mark.parametrize("module", sorted(SHIM_FILES))
def test_each_shim_imports_only_entry(module):
    assert import_rules.classify(module)[0] == "SHIM"
    for target in imported_modules(SHIM_FILES[module]):
        if target.startswith(("codex_harness", "zeus")) and not target.endswith((".main", ".parser", ".emit")):
            assert import_rules.classify(target)[0] == "ENTRY", (module, target)
        else:
            assert target.startswith("codex_harness.entry") or target.split(".")[0] != "codex_harness", (module, target)


@pytest.mark.parametrize("module", ["codex_harness.cli", "zeus"])
def test_help_through_the_shims_equals_the_entry_parser_help(module):
    environment = {key: value for key, value in os.environ.items() if key != "ZEUS_COMPOSITION_PROFILE"}
    done = subprocess.run([sys.executable, "-m", module, "--help"], capture_output=True, text=True, env=environment,
                          timeout=120, cwd=TARGET)
    assert done.returncode == 0, done.stderr
    expected = parser().format_help()
    assert done.stdout == expected
    assert done.stderr == ""


def test_the_cli_shim_reexports_the_entry_callables():
    from codex_harness import cli
    from codex_harness.entry import cli as entry

    assert (cli.main, cli.parser, cli.emit) == (entry.main, entry.parser, entry.emit)


def test_pyproject_scripts_and_packages_name_existing_modules():
    document = tomllib.loads((TARGET / "pyproject.toml").read_text("utf-8"))
    assert document["project"]["scripts"] == {"zeus": "codex_harness.cli:main", "harness": "codex_harness.cli:main"}
    for target in document["project"]["scripts"].values():
        module, _, name = target.partition(":")
        assert callable(getattr(import_module(module), name))
    packages = document["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/codex_harness", "src/zeus"]
    for package in packages:
        assert (TARGET / package / "__init__.py").is_file()


def test_the_isolated_worker_shim_sits_at_the_pinned_entry_module():
    assert ENTRY_MODULE == "codex_harness.adapters.isolated_worker_entry"
    assert SHIM_FILES[ENTRY_MODULE].is_file()


def redirect_paths(monkeypatch, tmp_path):
    def fake(*parts):
        text = os.path.join(*map(str, parts))
        if text.startswith("/runtime") or text.startswith("/run/secrets"):
            text = str(tmp_path) + text
        return Path(text)

    monkeypatch.setattr(container_main, "Path", fake)
    monkeypatch.setenv("CODEX_HOME", "unset")


def test_container_main_without_agent_only_delegates_to_the_entry_cli(monkeypatch, tmp_path):
    redirect_paths(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr("codex_harness.entry.cli.main", lambda: calls.append("cli"))
    monkeypatch.setattr(sys, "argv", ["container_main", "paths"])
    container_main.main()
    assert calls == ["cli"] and os.environ["CODEX_HOME"] == "unset" and list(tmp_path.iterdir()) == []


def test_container_main_agent_sets_the_codex_home_copies_the_newer_auth_and_writes_the_config_once(monkeypatch, tmp_path):
    redirect_paths(monkeypatch, tmp_path)
    secret = tmp_path / "run" / "secrets" / "codex-auth"
    secret.parent.mkdir(parents=True)
    secret.write_text('{"fixture": 1}', encoding="utf-8")
    calls = []
    monkeypatch.setattr("codex_harness.entry.cli.main", lambda: calls.append("cli"))
    monkeypatch.setattr(sys, "argv", ["container_main", "--agent", "role:lead", "paths"])
    container_main.main()
    home = tmp_path / "runtime" / "agents" / "role-lead"
    assert calls == ["cli"] and os.environ["CODEX_HOME"] == str(home)
    assert (home / "auth.json").read_text("utf-8") == '{"fixture": 1}' and (home / "auth.json").stat().st_mode & 0o777 == 0o600
    config = (home / "config.toml").read_text("utf-8")
    assert config.startswith('approval_policy = "never"\n') and config.endswith('model_reasoning_effort = "medium"\n')
    (home / "config.toml").write_text("kept = true\n", encoding="utf-8")
    container_main.main()
    assert (home / "config.toml").read_text("utf-8") == "kept = true\n"


def request(**fields):
    return {"protocol": PROTOCOL, "prompt": "p", "schema": {"type": "object"}, "timeout": 5, "model": "fixture",
            "session_id": "s", "runtime": {}, "cwd": WORKSPACE, "evidence_root": EVIDENCE, **fields}


def lines(output):
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_serve_answers_one_fresh_request_with_entered_then_result():
    built, seen = [], []

    class Runtime:
        def __init__(self, **kwargs):
            built.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def run(self, prompt, cwd, schema, timeout, on_event, on_enter, session_id, **kwargs):
            on_enter()
            on_event({"type": "fixture"})
            seen.append((prompt, cwd, schema, timeout, session_id, kwargs))
            return {"answer": {"ok": True}, "events": [{"type": "fixture"}], "thread_id": "s"}

    output = io.BytesIO()
    assert worker.serve(io.BytesIO(json.dumps(request()).encode("utf-8")), output, Runtime) == 0
    assert seen == [("p", WORKSPACE, {"type": "object"}, 5, "s", {})]
    assert built == [{"model": "fixture", "runtime": {"profile_evidence_root": EVIDENCE}, "max_budget_usd": None,
                      "settings_document": None}]
    written = lines(output)
    assert [line["kind"] for line in written] == ["entered", "event", "result"]
    assert all(line["protocol"] == PROTOCOL for line in written)
    assert written[-1]["result"] == {"answer": {"ok": True}, "thread_id": "s"}


def test_serve_refuses_an_oversized_request_before_any_runtime_is_built(monkeypatch):
    monkeypatch.setattr(worker, "MAX_REQUEST_BYTES", 16)
    output = io.BytesIO()
    assert worker.serve(io.BytesIO(b"x" * 17), output, lambda **_: pytest.fail("runtime built")) == 1
    assert lines(output) == [{"protocol": PROTOCOL, "kind": "refused", "error_type": "ValueError",
                              "message": "request exceeds budget"}]


def test_serve_refuses_a_foreign_protocol_without_building_a_runtime():
    output = io.BytesIO()
    body = json.dumps(request(protocol="other")).encode("utf-8")
    assert worker.serve(io.BytesIO(body), output, lambda **_: pytest.fail("runtime built")) == 1
    assert lines(output)[0]["kind"] == "refused" and lines(output)[0]["message"] == "request is not " + PROTOCOL


def test_the_isolated_worker_entry_process_serves_stdin_and_stdout(monkeypatch):
    from codex_harness.entry.processes import isolated_worker

    class Stream:
        buffer = io.BytesIO(b"{}")

    class Out:
        buffer = io.BytesIO()

    monkeypatch.setattr(sys, "stdin", Stream)
    monkeypatch.setattr(sys, "stdout", Out)
    assert isolated_worker.main() == 1
    assert json.loads(Out.buffer.getvalue())["kind"] == "refused"
