"""Buzz Batch B4: `BuzzProjection` (plan, replan, regenerate) over MemoryStore, the real coordination read functions
and labelled doubles for org/tasks.

Contracts: Buzz DESIGN v3 §4.1-§4.5, §6.1, §6.3; DESIGN-B §7 readings Q1-Q7. Test names carry the design §9 row-B
matrix number (m1..m8).
"""
import ast
import json
import re
import uuid
from pathlib import Path

import pytest

from codex_harness.coordination.domain import remote_control as rc

SRC = Path(__file__).resolve().parents[1] / "src" / "codex_harness"


# ---- item 4: the id rule has one owner (the coordination domain) -------------------------------------------------
def cid(n=1):
    return str(uuid.UUID(int=(n << 8) | (4 << 76) | (2 << 62)))


def fence(command):
    return "```zeus:command\n" + json.dumps(command) + "\n```"


@pytest.mark.parametrize("content,expected", [
    (fence({"command_id": cid(1), "op": "nope"}), cid(1)),  # the schema is not this function's business
    (fence({"command_id": cid(1)}) + "\n", cid(1)),
    ("no fence", None),
    (fence({"command_id": cid(1)}) + fence({"command_id": cid(2)}), None),
    (fence({"command_id": "not-a-uuid"}), None),
    (fence({"command_id": cid(10).upper()}), None),  # one spelling per id
    (fence({"command_id": str(uuid.UUID(int=1 << 64 | 1))}), None),  # not version 4
    ("```zeus:command\n{\"command_id\": \"%s\", \"command_id\": \"%s\"}\n```" % (cid(1), cid(2)), None),
    ("```zeus:command\n{\"command_id\": \"%s\", \"x\": NaN}\n```" % cid(1), None),
    ("```zeus:command\n[1]\n```", None),
    ("```zeus:command\n{broken\n```", None),
    (None, None)])
def test_m0_extract_command_id_uses_the_domains_own_rules(content, expected):
    assert rc.extract_command_id(content) == expected


def test_m0_extract_command_id_honours_the_content_bound():
    padding = "x" * rc.MAX_COMMAND_CONTENT_BYTES
    assert rc.extract_command_id(fence({"command_id": cid(1), "p": padding})) is None


def test_m0_the_application_compiles_no_regex_and_defines_no_fence():
    text = (SRC / "coordination/application/remote_control.py").read_text()
    tree = ast.parse(text)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {"re", "json", "uuid"} & imported
    code = [n for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute, ast.Constant))]
    names = {n.id for n in code if isinstance(n, ast.Name)} | {n.attr for n in code if isinstance(n, ast.Attribute)}
    assert not {"re", "_FENCE", "compile", "findall", "fullmatch", "json", "uuid"} & names
    assert "```" not in "".join(n.value for n in code if isinstance(n, ast.Constant) and isinstance(n.value, str)
                                and n.value is not ast.get_docstring(tree, clean=False))
    assert not re.search(r"^\s*_?[A-Z_]*FENCE\w*\s*=", text, re.M)
