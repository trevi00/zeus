"""Nostr event codec: the NIP-01 id serialization, event shape, relay/client frames and refusal prefixes.

Layer: domain
Context: observation
Owns: `serialize_for_id` (the exact NIP-01 escape table), `event_id`, `validate_event`, the client frame
    builders (`req`, `close`, `event_frame`, `auth_frame`), `parse_relay_frame` / `RelayFrame`, `classify`
    (the NIP-01/NIP-42 machine-readable prefixes) and `auth_event_template` (the unsigned kind 22242)
Does not own: BIP-340 verification (`bip340`, `observation.adapters.nostr_verify`), signing (credentials custody),
    the WebSocket transport and the retry policy (the relay client)
Entry points: serialize_for_id, event_id, validate_event, req, close, event_frame, auth_frame,
    parse_relay_frame, classify, auth_event_template, RelayFrame, PREFIXES, MAX_EVENT_BYTES
Contracts: NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md;
    NIP-42 https://github.com/nostr-protocol/nips/blob/master/42.md;
    BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki (the signature over the id)

The id is SHA-256 of the UTF-8 array `[0,pubkey,created_at,kind,tags,content]` with no whitespace. NIP-01 escapes
only `\\n`, `\\"`, `\\\\`, `\\r`, `\\t`, `\\b` and `\\f`; every other character is included verbatim, which
`json.dumps` does not do (it writes the other control characters as `\\u00XX`), so strings are escaped here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from codex_harness.kernel.errors import ContractError

MAX_EVENT_BYTES = 262144  # declared bound on the id serialization of one accepted event
MAX_SUB_ID_CHARS = 64  # NIP-01: a subscription id is a non-empty string of at most 64 characters
AUTH_KIND = 22242  # NIP-42
PREFIXES = ("duplicate", "pow", "blocked", "rate-limited", "invalid", "restricted", "mute", "error",
            "auth-required")
_EVENT_KEYS = frozenset({"id", "pubkey", "created_at", "kind", "tags", "content", "sig"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX128 = re.compile(r"[0-9a-f]{128}")
_ESCAPES = {"\n": "\\n", '"': '\\"', "\\": "\\\\", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _string(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("nostr: expected a string")
    return '"' + "".join(_ESCAPES.get(ch, ch) for ch in value) + '"'


def _integer(value: int, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"nostr: {name} must be a non-negative integer")
    return str(value)


def serialize_for_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> bytes:
    """The NIP-01 id preimage: `[0,pubkey,created_at,kind,tags,content]`, UTF-8, no whitespace."""
    if not isinstance(tags, list) or any(not isinstance(tag, list) for tag in tags):
        raise ContractError("nostr: tags must be a list of lists")
    tag_text = "[" + ",".join("[" + ",".join(_string(item) for item in tag) + "]" for tag in tags) + "]"
    text = "[0," + ",".join((_string(pubkey), _integer(created_at, "created_at"), _integer(kind, "kind"),
                             tag_text, _string(content))) + "]"
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:  # a lone surrogate has no UTF-8 form
        raise ContractError("nostr: text is not valid Unicode") from exc


def event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    return hashlib.sha256(serialize_for_id(pubkey, created_at, kind, tags, content)).hexdigest()


def validate_event(obj: object) -> dict:
    """The shape of a signed event (NIP-01); returns a new dict of exactly the seven fields."""
    if not isinstance(obj, dict) or set(obj) != _EVENT_KEYS:
        raise ContractError("nostr: an event is an object with exactly id, pubkey, created_at, kind, tags, "
                            "content and sig")
    for name, pattern in (("id", _HEX64), ("pubkey", _HEX64), ("sig", _HEX128)):
        value = obj[name]
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ContractError(f"nostr: {name} must be lowercase hex of the declared length")
    for name in ("created_at", "kind"):
        _integer(obj[name], name)
    tags, content = obj["tags"], obj["content"]
    if not isinstance(tags, list) or any(
            not isinstance(tag, list) or any(not isinstance(item, str) for item in tag) for tag in tags):
        raise ContractError("nostr: tags must be a list of lists of strings")
    if not isinstance(content, str):
        raise ContractError("nostr: content must be a string")
    if len(serialize_for_id(obj["pubkey"], obj["created_at"], obj["kind"], tags, content)) > MAX_EVENT_BYTES:
        raise ContractError(f"nostr: event exceeds {MAX_EVENT_BYTES} bytes")
    return {key: obj[key] for key in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")}


def _frame(*items: object) -> str:
    return json.dumps(list(items), ensure_ascii=False, separators=(",", ":"))


def _sub_id(sub_id: str) -> str:
    if not isinstance(sub_id, str) or not 1 <= len(sub_id) <= MAX_SUB_ID_CHARS:
        raise ContractError("nostr: a subscription id is 1 to 64 characters")
    return sub_id


def req(sub_id: str, *filters: dict) -> str:
    if any(not isinstance(item, dict) for item in filters):
        raise ContractError("nostr: a filter is an object")
    return _frame("REQ", _sub_id(sub_id), *filters)


def close(sub_id: str) -> str:
    return _frame("CLOSE", _sub_id(sub_id))


def event_frame(event: dict) -> str:
    return _frame("EVENT", validate_event(event))


def auth_frame(event: dict) -> str:
    """NIP-42 client answer `["AUTH", <signed kind 22242 event>]`."""
    checked = validate_event(event)
    if checked["kind"] != AUTH_KIND:
        raise ContractError("nostr: an AUTH answer is a kind 22242 event")
    return _frame("AUTH", checked)


def auth_event_template(relay_url: str, challenge: str, created_at: int) -> dict:
    """The unsigned NIP-42 event: kind 22242, the `relay` and `challenge` tags, empty content."""
    for name, value in (("relay_url", relay_url), ("challenge", challenge)):
        if not isinstance(value, str) or not value:
            raise ContractError(f"nostr: {name} must be a non-empty string")
    _integer(created_at, "created_at")
    return {"kind": AUTH_KIND, "created_at": created_at,
            "tags": [["relay", relay_url], ["challenge", challenge]], "content": ""}


@dataclass(frozen=True)
class RelayFrame:
    """One relay-to-client frame; only the fields of its `kind` are set."""
    kind: str
    sub_id: str | None = None
    event: dict | None = None
    event_id: str | None = None
    accepted: bool | None = None
    message: str | None = None
    challenge: str | None = None


def _arity(items: list, count: int, kind: str) -> None:
    if len(items) != count:
        raise ContractError(f"nostr: a {kind} frame has {count - 1} fields")


def _text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"nostr: {what} must be a string")
    return value


def parse_relay_frame(text: str) -> RelayFrame:
    """Parse `EVENT`, `OK`, `EOSE`, `CLOSED`, `NOTICE` or `AUTH`; anything else is a ContractError."""
    try:
        items = json.loads(text)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("nostr: the frame is not JSON") from exc
    if not isinstance(items, list) or not items or not isinstance(items[0], str):
        raise ContractError("nostr: a frame is a non-empty array that starts with its type")
    kind = items[0]
    if kind == "EVENT":
        _arity(items, 3, kind)
        return RelayFrame(kind, sub_id=_sub_id(items[1]), event=validate_event(items[2]))
    if kind == "OK":
        _arity(items, 4, kind)
        ident = items[1]
        if not isinstance(ident, str) or not _HEX64.fullmatch(ident):
            raise ContractError("nostr: OK carries a 64-hex event id")
        if not isinstance(items[2], bool):
            raise ContractError("nostr: OK carries a boolean")
        return RelayFrame(kind, event_id=ident, accepted=items[2], message=_text(items[3], "OK message"))
    if kind == "EOSE":
        _arity(items, 2, kind)
        return RelayFrame(kind, sub_id=_sub_id(items[1]))
    if kind == "CLOSED":
        _arity(items, 3, kind)
        return RelayFrame(kind, sub_id=_sub_id(items[1]), message=_text(items[2], "CLOSED message"))
    if kind == "NOTICE":
        _arity(items, 2, kind)
        return RelayFrame(kind, message=_text(items[1], "NOTICE message"))
    if kind == "AUTH":
        _arity(items, 2, kind)
        return RelayFrame(kind, challenge=_text(items[1], "AUTH challenge"))
    raise ContractError("nostr: unknown relay frame type")


def classify(message: str) -> str:
    """The NIP-01/NIP-42 machine-readable prefix (`prefix: text`) of an OK/CLOSED message, else `none`."""
    head, sep, _ = message.partition(":")
    return head if sep and head in PREFIXES else "none"
