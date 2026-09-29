"""Reference driver: the CLI parser golden (REBUILD-DESIGN-v2 §5.2a, first row).

Scenario family `cli.parser`. Builds M7 `codex_harness.cli.parser()` in-process under R-P and walks
every sub-parser: the 152 nodes / 51 roots with their arguments (dest, option strings, choices,
nargs, required) and the sha256 and byte length of each node's `--help` output (COLUMNS=100). No
handler runs: `--help` exits inside argparse before dispatch.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness"))

import driver  # noqa: E402

driver.start("reference")

import argparse  # noqa: E402
import contextlib  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402

from codex_harness import cli  # noqa: E402


def literal(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(v, (bool, int, float, str)) for v in value):
        return list(value)
    return "<" + type(value).__name__ + ">"


def arguments(parser):
    out = []
    for action in parser._actions:
        if isinstance(action, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        out.append({"dest": action.dest, "options": list(action.option_strings),
                    "choices": sorted(map(str, action.choices)) if action.choices else None,
                    "nargs": literal(action.nargs), "required": bool(action.required),
                    "default": literal(action.default), "action": type(action).__name__})
    return out


def help_of(root, path):
    stream = io.StringIO()
    code = None
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(io.StringIO()):
        try:
            root.parse_args([*path, "--help"])
        except SystemExit as exc:
            code = exc.code
    text = stream.getvalue()
    return {"help_exit": code, "help_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "help_bytes": len(text.encode()), "usage": text.splitlines()[0] if text else ""}


def main() -> None:
    root = cli.parser()
    nodes = []

    def walk(parser, path):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    here = [*path, name]
                    nodes.append({"command": " ".join(["zeus", *here]), "root": len(here) == 1,
                                  "arguments": arguments(child), **help_of(root, here)})
                    walk(child, here)

    walk(root, [])
    top = {"command": "zeus", "arguments": arguments(root), **help_of(root, [])}
    driver.finish("reference", "cli.parser", {
        "node_count": len(nodes), "root_count": sum(n["root"] for n in nodes),
        "top": top, "nodes": nodes})


if __name__ == "__main__":
    main()
