"""Buzz A1: TEST-custody role keys: O_EXCL create, 0600, sign -> verify_event, tampering, no key in repr/str."""

import os
import stat

import pytest

from codex_harness.credentials.adapters import role_keys
from codex_harness.credentials.adapters.role_keys import TestRoleKeys
from codex_harness.kernel.errors import ContractError
from codex_harness.observation.adapters.nostr_verify import verify_event
from codex_harness.observation.domain import nostr_event as ne
from codex_harness.observation.ports import EventSigner, EventVerifier, RelayClient

UNSIGNED = {"kind": 1, "created_at": 1700000000, "tags": [["t", "x"]], "content": "hello\n\u0001é😀"}


@pytest.fixture
def keys(tmp_path):
    store = TestRoleKeys(tmp_path / "keys")
    store.create("alice")
    return store


def test_create_is_exclusive_and_mode_0600(tmp_path):
    store = TestRoleKeys(tmp_path / "keys")
    store.create("alice")
    path = tmp_path / "keys" / "alice.key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_size == 32
    before = path.read_bytes()
    with pytest.raises(ContractError):
        store.create("alice")
    assert path.read_bytes() == before
    store.create("bob")
    assert (tmp_path / "keys" / "bob.key").read_bytes() != before


def test_role_ids_cannot_escape_the_directory(tmp_path):
    store = TestRoleKeys(tmp_path)
    for bad in ("", "../x", "a/b", "A", ".hidden", "x" * 65, None):
        with pytest.raises(ContractError):
            store.create(bad)


def test_missing_and_loose_keys_refused(keys, tmp_path):
    with pytest.raises(ContractError):
        keys.pubkey("nobody")
    path = tmp_path / "keys" / "alice.key"
    os.chmod(path, 0o644)
    with pytest.raises(ContractError):
        keys.pubkey("alice")
    os.chmod(path, 0o600)
    path.write_bytes(b"short")
    with pytest.raises(ContractError):
        keys.pubkey("alice")


def test_pubkey_is_xonly_hex(keys):
    pub = keys.pubkey("alice")
    assert len(pub) == 64 and pub == pub.lower() and bytes.fromhex(pub) and keys.pubkey("alice") == pub


def test_sign_then_verify_true_and_shape(keys):
    event = keys.sign("alice", UNSIGNED)
    assert ne.validate_event(event) == event and event["pubkey"] == keys.pubkey("alice")
    assert event["id"] == ne.event_id(event["pubkey"], 1700000000, 1, [["t", "x"]], UNSIGNED["content"])
    assert verify_event(event) is True
    assert keys.sign("alice", {**UNSIGNED, "pubkey": event["pubkey"]})["pubkey"] == event["pubkey"]
    assert "id" not in UNSIGNED and "sig" not in UNSIGNED  # the input is not mutated


def test_private_id_serializer_matches_the_observation_codec():
    contents = ["", "a\nb\"c\\d\re\tf\bg\fh", "\u0000\u0001\u001f\u007f", "é😀/"]
    for content in contents:
        unsigned = {"kind": 7, "created_at": 9, "tags": [["a", content], []], "content": content}
        assert role_keys._event_id("ab" * 32, unsigned) == ne.event_id("ab" * 32, 9, 7, unsigned["tags"], content)


@pytest.mark.parametrize("field,value", [
    ("content", "tampered"), ("id", "00" * 32), ("sig", "00" * 64), ("pubkey", "11" * 32),
    ("created_at", 1700000001), ("kind", 2), ("tags", [["t", "y"]]),
])
def test_tampering_gives_false(keys, field, value):
    event = keys.sign("alice", UNSIGNED)
    event[field] = value
    assert verify_event(event) is False


def test_other_roles_pubkey_and_resigned_id_with_old_sig_is_false(keys):
    keys.create("bob")
    event = keys.sign("alice", UNSIGNED)
    event["pubkey"] = keys.pubkey("bob")
    assert verify_event(event) is False
    event["id"] = ne.event_id(event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"])
    assert verify_event(event) is False  # the id fits the fields, the signature is alice's


def test_malformed_shape_raises_contract_error(keys):
    event = keys.sign("alice", UNSIGNED)
    for bad in ({**event, "sig": "zz"}, {**event, "tags": "x"}, {k: v for k, v in event.items() if k != "id"}):
        with pytest.raises(ContractError):
            verify_event(bad)


def test_sign_refuses_bad_unsigned_events(keys):
    for bad in ({}, {"kind": 1}, {**UNSIGNED, "sig": "x"}, {**UNSIGNED, "id": "x"}, {**UNSIGNED, "pubkey": "11" * 32},
                {**UNSIGNED, "created_at": True}, {**UNSIGNED, "content": 1}, "x"):
        with pytest.raises(ContractError):
            keys.sign("alice", bad)


def test_repr_and_str_carry_no_key_bytes_and_no_export(keys, tmp_path):
    secret = (tmp_path / "keys" / "alice.key").read_bytes()
    for text in (repr(keys), str(keys), f"{keys!r}{keys}"):
        assert secret.hex() not in text and str(secret) not in text
    assert not [n for n in dir(keys) if any(w in n.lower() for w in ("export", "secret_bytes", "private"))
                and not n.startswith("_")]
    assert "TEST custody: non-constant-time pure-Python signing; never production" in TestRoleKeys.__doc__
    assert TestRoleKeys.__test__ is False


def test_ports_are_structural_and_small():
    for port in (EventSigner, EventVerifier, RelayClient):
        methods = [n for n, v in vars(port).items() if callable(v) and not n.startswith("_")]
        assert 1 <= len(methods) <= 6
    assert {"publish", "query", "subscribe", "close"} <= set(vars(RelayClient))
