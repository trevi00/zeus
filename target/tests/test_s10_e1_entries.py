"""S10 unit E1: the permanent `codex_harness.cli` shim, the `zeus` package, the console scripts and the two in-container entries (R-e1).

The shims import only ENTRY; `--help` through `python -m codex_harness.cli` and `python -m zeus` equals the entry parser's help;
`container_main` is retired (U6(b), USER-APPROVED-U6-20261006); `serve` runs over in-memory pipes with a fake runtime factory.
"""
import ast
import importlib.util
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
from codex_harness.execution.domain.container_spec import ENTRY_MODULE, EVIDENCE, PROTOCOL, WORKSPACE

TARGET = Path(__file__).resolve().parents[1]
SRC = TARGET / "src"
SHIM_FILES = {
    "codex_harness.cli": SRC / "codex_harness" / "cli.py",
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
    """Provenance: the `[project.scripts]` set and its order are M7's (SOURCE e38aa722 pyproject.toml), kept as the
    declared compatibility record of the public entry names; no contract makes the order observable. Each script target
    also resolves to a callable (behavioural)."""
    document = tomllib.loads((TARGET / "pyproject.toml").read_text("utf-8"))
    # int39 (owner): E3 and E2a add M7's supervisor and monitor scripts; the set AND the order are M7's
    # (SOURCE e38aa722 pyproject.toml [project.scripts]).
    assert list(document["project"]["scripts"].items()) == [
        ("zeus", "codex_harness.cli:main"), ("zeus-supervisor", "codex_harness.supervisor:main"),
        ("zeus-monitor", "codex_harness.monitor:main"), ("harness", "codex_harness.cli:main"),
        ("harness-supervisor", "codex_harness.supervisor:main")]
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


def test_container_main_is_retired_from_the_target():
    """U6(b) (USER-APPROVED-U6-20261006; DESIGN-s11 §20.1): the legacy Compose agent entry is gone from the target."""
    for module in ("codex_harness.container_main", "codex_harness.entry.processes.container_main"):
        assert importlib.util.find_spec(module) is None, module
    done = subprocess.run([sys.executable, "-m", "codex_harness.container_main", "--agent", "role:lead", "paths"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and "No module named" in done.stderr, (done.returncode, done.stderr[-200:])


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
