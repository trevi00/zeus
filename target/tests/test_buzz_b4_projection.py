"""Buzz Batch B4: `BuzzProjection` (plan, replan, regenerate) over MemoryStore, the real coordination read functions
and labelled doubles for org/tasks.

Contracts: Buzz DESIGN v3 §4.1-§4.5, §6.1, §6.3; DESIGN-B §7 readings Q1-Q7. Test names carry the design §9 row-B
matrix number (m1..m8).
"""
import ast
import re
import uuid
from pathlib import Path

import pytest

from codex_harness.coordination.domain import remote_control as rc

SRC = Path(__file__).resolve().parents[1] / "src" / "codex_harness"


# ---- item 4: the id rule has one owner (the coordination domain) -------------------------------------------------
from test_buzz_b3_remote_control import NOW, OWNER, World, cid, command, fence, inbox_row  # noqa: E402


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


# ---- Q2: the coordination read functions the projection plans from ------------------------------------------------
from codex_harness.coordination.application.fleet import state  # noqa: E402
from codex_harness.coordination.application.remote_control import transitions_after  # noqa: E402
from codex_harness.coordination.application.remote_inbox import RemoteInbox  # noqa: E402


def read(w, fn, *args):
    with w.store.transaction() as tx:
        return fn(tx, *args)


def admit_via_inbox(w, row):
    """The bridge's path: the inbox row is retained with its event, then admitted."""
    with w.store.transaction() as tx:
        RemoteInbox().insert_pending(tx, {name: row[name] for name in ("event_id", "author", "created_at", "received_at",
                                                                         "channel", "event")})
    return w.admit(row)


def test_q2_transitions_after_is_oldest_first_inclusive_and_enriched(tmp_path):
    w = World(tmp_path)
    admit_via_inbox(w, inbox_row(fence(w.cancel_cmd(1)), 1, received_at=NOW))
    w.now = NOW + 3
    pause = command("pause_fleet", 2, created_at=NOW + 3, expected_control={"paused": False, "version": 0})
    admit_via_inbox(w, inbox_row(fence(pause), 2, created_at=NOW + 3, received_at=NOW + 3))
    rows = read(w, transitions_after, None, 10)
    assert [(r["command_id"], r["at"], r["op"], r["command_author"], r["channel"]) for r in rows] == [
        (cid(1), NOW, "cancel_task", OWNER, "c1"), (cid(2), NOW + 3, "pause_fleet", OWNER, "c1")]
    assert [r["command_id"] for r in read(w, transitions_after, NOW + 3, 10)] == [cid(2)]  # inclusive bound
    assert [r["command_id"] for r in read(w, transitions_after, NOW + 1, 10)] == [cid(2)]
    assert [r["command_id"] for r in read(w, transitions_after, None, 1)] == [cid(1)]
    before = w.snapshot()
    read(w, transitions_after, None, 10)
    assert w.snapshot() == before  # read-only
    for bad in ((-1, 1), (None, 0), (True, 1), (None, True)):
        with pytest.raises(Exception, match="remote control"):
            read(w, transitions_after, *bad)


def test_q2_a_missing_inbox_row_or_binding_enriches_with_none(tmp_path):
    w = World(tmp_path)
    w.admit(inbox_row(fence(w.cancel_cmd(1)), 1))
    row = read(w, transitions_after, None, 1)[0]
    assert row["op"] == "cancel_task"
    with w.store.transaction() as tx:  # the unit of the test only: drop the binding and the inbox row from view
        row = {**tx.get("remote_command_transitions", f"{cid(1)}:1"), "command_event_id": "f" * 64}
        tx.put("remote_command_transitions", f"{cid(1)}:1", row)
    enriched = read(w, transitions_after, None, 1)[0]
    assert enriched["command_author"] is None and enriched["channel"] is None


def test_q2_fleet_view_reads_the_pause_row_hold_and_version(tmp_path):
    w = World(tmp_path)
    assert read(w, state.fleet_view) == {"paused": False, "activation_hold": False, "control_version": 0}
    w.pause.pause()
    assert read(w, state.fleet_view) == {"paused": True, "activation_hold": False, "control_version": 1}
    w.pause.resume()
    w.pause.activation_gate("target-1", "d" * 64)
    assert read(w, state.fleet_view) == {"paused": True, "activation_hold": True, "control_version": 3}
