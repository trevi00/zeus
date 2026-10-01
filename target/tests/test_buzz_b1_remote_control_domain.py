"""Buzz B1: the remote-control domain (§4.3 command schema, §6.2 freshness/owner, §4.4 disposition machine)."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from codex_harness.coordination.domain import remote_control as rc
from codex_harness.kernel.errors import ContractError

CREATED = 1_800_000_000
CMD_ID = "3f0c5f0e-8a3e-4b9a-9d0e-5b1f0c2d7a41"
OWNER = "ab" * 32


def _iso(offset: float = 0.0) -> str:
    return datetime.fromtimestamp(CREATED + offset, timezone.utc).isoformat()


def _cmd(**over):
    base = {"schema": "urn:zeus:buzz-command:1", "command_id": CMD_ID, "op": "cancel_task", "task_id": "t1",
            "expected_generation": 3, "expected_control": None, "reason": "stop", "desk": None,
            "issued_at": _iso()}
    base.update(over)
    return base


def _content(command, *, before="", after=""):
    return f"{before}```zeus:command\n{json.dumps(command)}\n```{after}"


def _parse(command=None, **kw):
    return rc.parse_command(_content(command if command is not None else _cmd()), created_at=CREATED, **kw)


def _pause(op="pause_fleet", **over):
    return _cmd(op=op, task_id=None, expected_generation=None, expected_control={"paused": False, "version": 2},
                **over)


def _desk(op, **fields):
    desk = {"session_id": "s1", "title": "Desk", "intent": None, "text": None}
    desk.update(fields)
    return _cmd(op=op, task_id=None, expected_generation=None, desk=desk)


def _code(result):
    assert isinstance(result, rc.Refusal), result
    return result.code


# --- positive shapes -------------------------------------------------------------------------------------------

def test_cancel_resume_pause_and_desk_commands_parse():
    for command in (_cmd(), _pause(), _pause("resume_fleet"), _desk("desk_open"),
                    _desk("desk_turn", intent="consult", text="hi"), _desk("desk_turn", intent="request", text="x")):
        assert _parse(command) == command


def test_the_fence_may_sit_inside_other_text_and_crlf():
    command = _cmd()
    content = "hello\n```zeus:command\r\n" + json.dumps(command) + "\r\n```\ntrailing"
    assert rc.parse_command(content, created_at=CREATED) == command


def test_issued_at_accepts_z_suffix_and_fractions():
    zulu = datetime.fromtimestamp(CREATED, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _parse(_cmd(issued_at=zulu)) == _cmd(issued_at=zulu)
    stamp = datetime.fromtimestamp(CREATED, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.250Z")
    assert _parse(_cmd(issued_at=stamp)) == _cmd(issued_at=stamp)


def test_unknown_extra_keys_are_kept():
    command = _cmd(note="minor addition")
    assert _parse(command) == command


# --- refusals --------------------------------------------------------------------------------------------------

def test_missing_expected_generation_is_invalid_example_1():
    command = _cmd()
    del command["expected_generation"]
    assert _code(_parse(command)) == rc.INVALID_COMMAND
    assert _code(_parse(_cmd(expected_generation=None))) == rc.INVALID_COMMAND


@pytest.mark.parametrize("over", [
    {"task_id": None}, {"task_id": ""}, {"task_id": 7}, {"expected_generation": -1},
    {"expected_generation": True}, {"expected_generation": "3"}, {"expected_generation": 1.5},
    {"expected_control": {"paused": True, "version": 1}}, {"desk": {"session_id": "s"}},
])
def test_cancel_field_refusals(over):
    assert _code(_parse(_cmd(**over))) == rc.INVALID_COMMAND


@pytest.mark.parametrize("control", [
    None, {}, {"paused": True}, {"version": 1}, {"paused": "yes", "version": 1}, {"paused": True, "version": -1},
    {"paused": True, "version": True}, {"paused": True, "version": 1, "x": 1}, [True, 1],
])
@pytest.mark.parametrize("op", ["pause_fleet", "resume_fleet"])
def test_pause_resume_need_a_valid_expected_control(op, control):
    command = _pause(op)
    command["expected_control"] = control
    assert _code(_parse(command)) == rc.INVALID_COMMAND


def test_pause_refuses_cross_op_fields():
    for key, value in (("task_id", "t1"), ("expected_generation", 1), ("desk", {})):
        command = _pause()
        command[key] = value
        assert _code(_parse(command)) == rc.INVALID_COMMAND


@pytest.mark.parametrize("desk", [
    None, {}, {"session_id": "s1"}, {"session_id": "", "title": None, "intent": None, "text": None},
    {"session_id": "s" * 129, "title": None, "intent": None, "text": None},
    {"session_id": "s1", "title": 5, "intent": None, "text": None},
    {"session_id": "s1", "title": None, "intent": "consult", "text": None},
    {"session_id": "s1", "title": None, "intent": None, "text": "hi"},
    {"session_id": "s1", "title": None, "intent": None, "text": None, "x": 1},
])
def test_desk_open_refusals(desk):
    command = _desk("desk_open")
    command["desk"] = desk
    assert _code(_parse(command)) == rc.INVALID_COMMAND


@pytest.mark.parametrize("fields", [
    {"intent": None, "text": "hi"}, {"intent": "other", "text": "hi"}, {"intent": "consult", "text": None},
    {"intent": "consult", "text": ""}, {"intent": "consult", "text": 4},
])
def test_desk_turn_refusals(fields):
    assert _code(_parse(_desk("desk_turn", **fields))) == rc.INVALID_COMMAND


def test_desk_ops_refuse_other_op_fields():
    command = _desk("desk_open")
    command["task_id"] = "t1"
    assert _code(_parse(command)) == rc.INVALID_COMMAND


@pytest.mark.parametrize("schema", [None, 1, "", "urn:zeus:buzz-command:", "urn:zeus:buzz-command:x",
                                    "urn:zeus:buzz-command:1.1", "urn:zeus:buzz-command:01", "urn:zeus:buzz-receipt:1", "urn:zeus:buzz-command:-1"])
def test_malformed_schema_is_invalid(schema):
    assert _code(_parse(_cmd(schema=schema))) == rc.INVALID_COMMAND


@pytest.mark.parametrize("major", ["0", "2", "10"])
def test_unknown_major_is_unsupported_version(major):
    assert _code(_parse(_cmd(schema=f"urn:zeus:buzz-command:{major}"))) == rc.UNSUPPORTED_VERSION


@pytest.mark.parametrize("command_id", [
    None, 5, "", "not-a-uuid", str(uuid.uuid1()), str(uuid.uuid5(uuid.NAMESPACE_DNS, "x")),
    CMD_ID.upper(), CMD_ID.replace("-", ""), "{" + CMD_ID + "}", "00000000-0000-0000-0000-000000000000",
])
def test_command_id_must_be_a_canonical_uuid_v4(command_id):
    assert _code(_parse(_cmd(command_id=command_id))) == rc.INVALID_COMMAND


@pytest.mark.parametrize("op", [None, 3, "", "cancel", "CANCEL_TASK", "pause", "desk_close"])
def test_unknown_op_is_invalid(op):
    assert _code(_parse(_cmd(op=op))) == rc.INVALID_COMMAND


def test_reason_limit_500_characters():
    assert _parse(_cmd(reason="x" * 500)) is not None
    assert _parse(_cmd(reason="é" * 500)) is not None  # characters, not bytes
    assert _code(_parse(_cmd(reason="x" * 501))) == rc.INVALID_COMMAND
    assert _code(_parse(_cmd(reason=None))) == rc.INVALID_COMMAND
    command = _cmd()
    del command["reason"]
    assert _code(_parse(command)) == rc.INVALID_COMMAND


def test_issued_at_boundary_is_plus_minus_five_seconds():
    for offset in (-5, 0, 5):
        assert not isinstance(_parse(_cmd(issued_at=_iso(offset))), rc.Refusal)
    for offset in (-5.001, 5.001, 6, -6, 600):
        assert _code(_parse(_cmd(issued_at=_iso(offset)))) == rc.INVALID_COMMAND


@pytest.mark.parametrize("issued", [None, 5, "", "yesterday", "2027-01-15T08:00:00", "2027-01-15"])
def test_issued_at_must_be_a_zoned_iso_time(issued):
    assert _code(_parse(_cmd(issued_at=issued))) == rc.INVALID_COMMAND


def test_issued_at_in_another_zone_offset_compares_in_utc():
    local = datetime.fromtimestamp(CREATED + 3, timezone.utc).astimezone(timezone(timedelta(hours=9)))
    assert not isinstance(_parse(_cmd(issued_at=local.isoformat())), rc.Refusal)


@pytest.mark.parametrize("content", [
    "", "no fence", "```zeus:command\n{not json}\n```", "```zeus:command\n[1]\n```", "```zeus:command\n\"x\"\n```",
    "```zeus:command\n" + json.dumps(_cmd()),  # unterminated
    '```zeus:command\n{"a":1,"a":2}\n```',  # duplicate key
    '```zeus:command\n{"a":NaN}\n```',
    '```zeus:command\n{"reason":"\\ud800"}\n```',  # lone surrogate: no UTF-8 form
    "```json\n" + json.dumps(_cmd()) + "\n```",
    "```zeus:task-root\n" + json.dumps(_cmd()) + "\n```",
])
def test_malformed_content_is_invalid(content):
    assert _code(rc.parse_command(content, created_at=CREATED)) == rc.INVALID_COMMAND


def test_two_fences_are_refused_not_picked():
    one = _content(_cmd())
    assert _code(rc.parse_command(one + "\n" + one, created_at=CREATED)) == rc.INVALID_COMMAND


def test_content_size_is_bounded():
    big = _content(_cmd(note="x" * rc.MAX_COMMAND_CONTENT_BYTES))
    assert _code(rc.parse_command(big, created_at=CREATED)) == rc.INVALID_COMMAND
    assert _code(rc.parse_command(None, created_at=CREATED)) == rc.INVALID_COMMAND


@pytest.mark.parametrize("bad", [-1, True, "1", 1.0, None])
def test_created_at_must_be_an_integer(bad):
    with pytest.raises(ContractError):
        rc.parse_command(_content(_cmd()), created_at=bad)


def test_refusal_codes_are_the_declared_set():
    assert rc.REFUSAL_CODES == {
        "stale_generation", "stale_control", "activation_hold_present", "command_expired", "command_conflict",
        "invalid_command", "unsupported_version", "task_unknown", "role_unknown", "session_conflict",
        "request_conflict", "session_busy", "session_unknown", "not_applied", "desk_not_migrated"}
    for name in rc.REFUSAL_CODES:
        assert getattr(rc, name.upper()) == name
    assert rc.IGNORED_NOT_OWNER == "ignored_not_owner"
    assert rc.OPS == ("cancel_task", "pause_fleet", "resume_fleet", "desk_open", "desk_turn")


# --- digest ----------------------------------------------------------------------------------------------------

def test_digest_ignores_key_order_and_whitespace():
    command = _cmd()
    reordered = dict(reversed(list(command.items())))
    pretty = "```zeus:command\n" + json.dumps(command, indent=4, sort_keys=False) + "\n```"
    compact = "```zeus:command\n" + json.dumps(reordered, separators=(",", ":")) + "\n```"
    a = rc.parse_command(pretty, created_at=CREATED)
    b = rc.parse_command(compact, created_at=CREATED)
    assert rc.command_digest(a) == rc.command_digest(b) == rc.command_digest(command)
    assert len(rc.command_digest(a)) == 64


def test_digest_pinned_vector_and_sensitivity():
    assert rc.command_digest({"b": 1, "a": "é"}) == (
        "aa58fba8483623bed37c1b02edfccbdd9a53123837c20bfa4cb4049993a2872e")  # sha256 of {"a":"é","b":1}
    assert rc.command_digest(_cmd()) != rc.command_digest(_cmd(reason="other"))
    assert rc.command_digest(_cmd()) != rc.command_digest(_cmd(task_id="t2"))
    nested_a = _pause()
    nested_b = _pause()
    nested_b["expected_control"] = {"version": 2, "paused": False}
    assert rc.command_digest(nested_a) == rc.command_digest(nested_b)


def test_digest_refuses_non_json():
    with pytest.raises(ContractError):
        rc.command_digest({"a": float("nan")})
    with pytest.raises(ContractError):
        rc.command_digest({"a": object()})


# --- owner and freshness ---------------------------------------------------------------------------------------

def test_owner_allowed():
    assert rc.owner_allowed(OWNER, [OWNER]) is True
    assert rc.owner_allowed(OWNER, {"cd" * 32, OWNER}) is True
    assert rc.owner_allowed(OWNER, []) is False
    assert rc.owner_allowed(OWNER, ["cd" * 32]) is False
    assert rc.owner_allowed(OWNER.upper(), [OWNER]) is False
    assert rc.owner_allowed("ab" * 31, ["ab" * 31]) is False
    assert rc.owner_allowed(None, [OWNER]) is False
    assert rc.owner_allowed(OWNER, [None, 5]) is False


def test_freshness_boundary_is_exactly_600_seconds():
    assert rc.COMMAND_TTL == 600
    assert rc.fresh_for_admission(CREATED + 600, CREATED) is True
    assert rc.fresh_for_admission(CREATED + 601, CREATED) is False
    assert rc.fresh_for_admission(CREATED - 600, CREATED) is True
    assert rc.fresh_for_admission(CREATED - 601, CREATED) is False
    assert rc.fresh_for_admission(CREATED, CREATED) is True
    assert rc.fresh_for_admission(CREATED + 60, CREATED, ttl=60) is True
    assert rc.fresh_for_admission(CREATED + 61, CREATED, ttl=60) is False


@pytest.mark.parametrize("args", [(True, 1), (1, "1"), (-1, 1), (1.0, 1)])
def test_freshness_refuses_non_integers(args):
    with pytest.raises(ContractError):
        rc.fresh_for_admission(*args)


# --- the disposition machine -----------------------------------------------------------------------------------

ALLOWED = {
    ("received", "accepted"), ("received", "refused"), ("received", "effect_done"), ("received", "effect_unknown"),
    ("accepted", "effect_done"), ("accepted", "refused"), ("accepted", "effect_unknown"),
    ("effect_unknown", "effect_done"), ("effect_unknown", "refused"),
}


@pytest.mark.parametrize("current", rc.DISPOSITIONS)
@pytest.mark.parametrize("target", rc.DISPOSITIONS)
def test_every_pair_of_the_machine(current, target):
    assert rc.next_transition(current, target) is ((current, target) in ALLOWED)


def test_terminal_states_and_examples():
    assert rc.TERMINAL == {"effect_done", "refused"}
    assert rc.next_transition("effect_done", "refused") is False  # example 2
    assert rc.next_transition("refused", "effect_done") is False
    assert rc.next_transition("accepted", "received") is False  # forward-only
    assert rc.next_transition("effect_unknown", "accepted") is False
    for state in rc.TERMINAL:
        assert not any(rc.next_transition(state, t) for t in rc.DISPOSITIONS)


def test_unknown_dispositions_raise():
    with pytest.raises(ContractError):
        rc.next_transition("done", "refused")
    with pytest.raises(ContractError):
        rc.next_transition("received", "nope")


def test_work_vocabulary():
    assert rc.WORK_STATES == ("queued", "claimed", "running", "completed", "refused", "unknown")
    assert rc.WORK_RESULTS == ("answered", "needs_spec")
    assert rc.DISPOSITIONS == ("received", "accepted", "refused", "effect_done", "effect_unknown")
