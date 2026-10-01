"""Buzz A1: the NIP-01 codec (escape table, id, shape, frames, prefixes). NIP-01 / NIP-42 cited in the module."""

import hashlib
import json

import pytest

from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain import nostr_event as ne

PK = "ab" * 32
ID = "cd" * 32
SIG = "ef" * 64


def _event(**over):
    base = {"id": ID, "pubkey": PK, "created_at": 1, "kind": 1, "tags": [["t", "x"]], "content": "hi", "sig": SIG}
    base.update(over)
    return base


@pytest.mark.parametrize("content,escaped", [
    ("\n", b"\\n"), ('"', b'\\"'), ("\\", b"\\\\"), ("\r", b"\\r"), ("\t", b"\\t"), ("\b", b"\\b"),
    ("\f", b"\\f"),
    ("\u0001", b"\x01"), ("\u001f", b"\x1f"), ("\u0000", b"\x00"), ("\u007f", b"\x7f"),
    ("/", b"/"), ("é", "é".encode()), ("😀", "😀".encode()),
])
def test_escape_table(content, escaped):
    out = ne.serialize_for_id(PK, 1, 1, [], content)
    assert out == b'[0,"' + PK.encode() + b'",1,1,[],"' + escaped + b'"]'


def test_other_control_characters_are_verbatim_and_differ_from_json_dumps():
    out = ne.serialize_for_id(PK, 1, 1, [["t", "a\u0001b"]], "a\u0001b")
    assert out.count(b"\x01") == 2 and b"\\u0001" not in out
    assert out != json.dumps([0, PK, 1, 1, [["t", "a\u0001b"]], "a\u0001b"], ensure_ascii=False,
                             separators=(",", ":")).encode()


def test_event_id_of_a_hand_computed_event():
    # Hand derivation: the array text is exactly
    #   [0,"<64 x 'a'>",1700000000,1,[["t","x"]],"hi\n\"q\""]
    # the content hi<LF>"q" escapes to  hi\n\"q\"  (backslash n, backslash quote), nothing else changes.
    pub = "a" * 64
    preimage = '[0,"' + pub + '",1700000000,1,[["t","x"]],"hi\\n\\"q\\""]'
    assert ne.serialize_for_id(pub, 1700000000, 1, [["t", "x"]], 'hi\n"q"') == preimage.encode()
    # Independent digest of that exact preimage (printf ... | sha256sum).
    expected = "b44aa8b8875e502bd2c03aa077885bea4f55c49ece8f8c128eb0e7a8bf022a51"
    assert hashlib.sha256(preimage.encode()).hexdigest() == expected
    assert ne.event_id(pub, 1700000000, 1, [["t", "x"]], 'hi\n"q"') == expected


def test_serialize_refuses_bad_inputs():
    for args in [(PK, True, 1, [], ""), (PK, -1, 1, [], ""), (PK, 1, 1.0, [], ""), (PK, 1, 1, "x", ""),
                 (PK, 1, 1, [["a", 1]], ""), (PK, 1, 1, [], b"x"), (PK, 1, 1, [], "\ud800")]:
        with pytest.raises(ContractError):
            ne.serialize_for_id(*args)


def test_validate_event_accepts_and_copies():
    event = _event()
    assert ne.validate_event(event) == event and ne.validate_event(event) is not event


@pytest.mark.parametrize("over", [
    {"id": "AB" * 32}, {"id": "ab" * 31}, {"pubkey": "g" * 64}, {"pubkey": PK.upper()}, {"sig": "ab" * 63},
    {"sig": SIG.upper()}, {"created_at": True}, {"created_at": -1}, {"created_at": 1.5}, {"kind": "1"},
    {"kind": -2}, {"kind": False}, {"tags": "x"}, {"tags": ["x"]}, {"tags": [["a", 1]]}, {"content": 1},
    {"content": "x" * (ne.MAX_EVENT_BYTES + 1)},
])
def test_validate_event_refuses(over):
    with pytest.raises(ContractError):
        ne.validate_event(_event(**over))


def test_validate_event_refuses_missing_extra_and_non_object():
    missing = _event()
    del missing["sig"]
    for bad in (missing, _event(extra=1), [], None, "x"):
        with pytest.raises(ContractError):
            ne.validate_event(bad)


def test_client_frames():
    flt = {"kinds": [1], "limit": 0}
    assert json.loads(ne.req("s1", flt, {"ids": [ID]})) == ["REQ", "s1", flt, {"ids": [ID]}]
    assert ne.req("s1") == '["REQ","s1"]'
    assert ne.close("s1") == '["CLOSE","s1"]'
    assert json.loads(ne.event_frame(_event())) == ["EVENT", _event()]
    auth = _event(kind=22242, tags=[["relay", "wss://r"], ["challenge", "c"]], content="")
    assert json.loads(ne.auth_frame(auth)) == ["AUTH", auth]
    for bad in (lambda: ne.req(""), lambda: ne.req("x" * 65), lambda: ne.req("s", "notadict"),
                lambda: ne.close(1), lambda: ne.event_frame({}), lambda: ne.auth_frame(_event())):
        with pytest.raises(ContractError):
            bad()


def test_auth_event_template():
    assert ne.auth_event_template("wss://relay.example", "chal", 5) == {
        "kind": 22242, "created_at": 5, "content": "",
        "tags": [["relay", "wss://relay.example"], ["challenge", "chal"]]}
    for args in [("", "c", 1), ("wss://r", "", 1), ("wss://r", "c", -1), ("wss://r", "c", True)]:
        with pytest.raises(ContractError):
            ne.auth_event_template(*args)


def test_parse_every_relay_frame_kind():
    got = ne.parse_relay_frame(json.dumps(["EVENT", "s", _event()]))
    assert (got.kind, got.sub_id, got.event) == ("EVENT", "s", _event())
    got = ne.parse_relay_frame(json.dumps(["OK", ID, True, ""]))
    assert (got.kind, got.event_id, got.accepted, got.message) == ("OK", ID, True, "")
    assert ne.parse_relay_frame('["EOSE","s"]') == ne.RelayFrame("EOSE", sub_id="s")
    assert ne.parse_relay_frame('["CLOSED","s","restricted: no"]') == ne.RelayFrame(
        "CLOSED", sub_id="s", message="restricted: no")
    assert ne.parse_relay_frame('["NOTICE","hello"]') == ne.RelayFrame("NOTICE", message="hello")
    assert ne.parse_relay_frame('["AUTH","chal"]') == ne.RelayFrame("AUTH", challenge="chal")


@pytest.mark.parametrize("text", [
    "", "not json", "{}", "[]", "[1]", '["WAT"]', '["EOSE"]', '["EOSE","s","x"]', '["EOSE",1]', '["EOSE",""]',
    '["OK","zz",true,""]', json.dumps(["OK", ID, "true", ""]), json.dumps(["OK", ID, 1, ""]),
    json.dumps(["OK", ID, True]), json.dumps(["OK", ID, True, 5]), '["CLOSED","s"]', '["CLOSED","s",1]',
    '["NOTICE"]', '["NOTICE",1]', '["AUTH"]', '["AUTH",1]', '["EVENT","s"]', '["EVENT","s",{}]', None,
])
def test_malformed_frames_refused(text):
    with pytest.raises(ContractError):
        ne.parse_relay_frame(text)


@pytest.mark.parametrize("prefix", ne.PREFIXES)
def test_classify_every_prefix(prefix):
    assert ne.classify(f"{prefix}: because") == prefix


def test_classify_none_and_example():
    frame = ne.parse_relay_frame(json.dumps(["OK", ID, False, "auth-required: we only accept members"]))
    assert ne.classify(frame.message) == "auth-required"
    for message in ("", "hello", "unknown: x", "duplicate", "Duplicate: x", " duplicate: x", "a:duplicate: x"):
        assert ne.classify(message) == "none"
