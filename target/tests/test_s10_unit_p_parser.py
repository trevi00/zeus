"""S10 unit P: the M7 CLI parser moved into `codex_harness.entry.cli` (one module per root, no handler).

The byte-level parity (152 nodes, every `--help` digest) is the `cli.parser` compare family; these tests bind the
module shape, the root order, the import homes and the two argparse exits the golden does not record."""

import ast
import contextlib
import importlib
import io
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "target" / "src" / "codex_harness" / "entry" / "cli"
GOLDEN = ROOT / "compare" / "goldens" / "reference" / "cli.parser.json"
SOURCE = "e38aa722"


def golden_roots():
    return [n["command"].split(" ", 1)[1] for n in json.loads(GOLDEN.read_text(encoding="utf-8"))["nodes"] if n["root"]]


def parser_roots(parser):
    action = next(a for a in parser._actions if a.dest == "command")
    return list(action.choices)


def test_the_51_root_modules_each_define_add_parser_and_at_most_run():
    roots = golden_roots()
    assert len(roots) == 51
    for root in roots:
        path = PACKAGE / (root.replace("-", "_") + ".py")
        assert path.is_file(), root
        tree = ast.parse(path.read_text(encoding="utf-8"))
        public = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and not n.name.startswith("_")]
        assert "add_parser" in public and set(public) <= {"add_parser", "run"}, (root, public)
    # operation: entry.cli.operation, the M7 operation_cli helpers (C7a), not a root
    # entry.cli.threshold_proposals, threshold_replay, observed_assets: the M7 argparse mains (V27 argparse mains, not roots)
    assert {p.stem for p in PACKAGE.glob("*.py")} == {r.replace("-", "_") for r in roots} | {"__init__", "output", "operation", "threshold_proposals",
                                                                                           "threshold_replay", "observed_assets",
                                                                                           "research_package",
                                                                                           "dlq"}  # G20-D6: a declared target addition (RF-RT)
    # S10 A5-1b: dlq, a declared target addition (DESIGN-s10 §17a)


def test_parser_root_order_equals_the_golden_root_order():
    from codex_harness.entry import cli

    # G20-D6: a declared target addition (RF-RT): `research-package` follows the M7 roots.
    assert parser_roots(cli.parser()) == golden_roots() + ["research-package", "dlq"]  # S10 A5-1b: dlq, a declared target addition (DESIGN-s10 §17a)


def m7_assignment(path, name):
    """The value of a module-level `name = ...` in SOURCE (tuples of literals, names and `*name`)."""
    text = subprocess.run(["git", "-C", str(ROOT), "show", f"{SOURCE}:{path}"], capture_output=True, text=True,
                          check=True).stdout
    assigns = {}
    for n in ast.parse(text).body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigns[t.id] = n.value
                elif isinstance(t, ast.Tuple):  # `FINITE, SUBSCRIPTION = "finite", "subscription"`
                    assigns.update({e.id: v for e, v in zip(t.elts, n.value.elts)})

    def value(node):
        if isinstance(node, ast.Name):
            return value(assigns[node.id])
        if isinstance(node, ast.Tuple):
            out = []
            for element in node.elts:
                if isinstance(element, ast.Starred):
                    out.extend(value(element.value))
                else:
                    out.append(value(element))
            return tuple(out)
        return ast.literal_eval(node)

    return value(assigns[name])


@pytest.mark.parametrize("module, name, m7_path", [
    ("codex_harness.kernel.usage", "MODES", "src/codex_harness/domain/usage_policy.py"),
    ("codex_harness.delivery.domain.host_delivery", "WITHDRAW_REASONS", "src/codex_harness/domain/host_delivery.py"),
    ("codex_harness.research.domain.discovery_pressure", "INTENTS", "src/codex_harness/domain/discovery_pressure.py"),
])
def test_import_homes_are_the_target_symbols_with_m7_values(module, name, m7_path):
    source = (PACKAGE / {"MODES": "fleet", "WITHDRAW_REASONS": "host_delivery", "INTENTS": "research_program"}[name]
              ).with_suffix(".py").read_text(encoding="utf-8")
    assert f"from {module} import {name}" in source
    target = getattr(importlib.import_module(module), name)
    try:
        expected = m7_assignment(m7_path, name)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"git or SOURCE {SOURCE} is unavailable")
    assert tuple(target) == expected


@pytest.mark.parametrize("root", golden_roots())
def test_every_root_help_exits_zero(root):
    from codex_harness.entry import cli

    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exit_info:
        cli.parser().parse_args([root, "--help"])
    assert exit_info.value.code == 0
    assert out.getvalue().startswith(f"usage: zeus {root}")


def test_a_missing_command_is_an_argparse_usage_error():
    from codex_harness.entry import cli

    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as exit_info:
        cli.parser().parse_args([])
    assert exit_info.value.code == 2
