"""Role key custody for the Buzz bridge, TEST custody only: throwaway keys, 0600 files, BIP-340 event signing.

Layer: adapters
Context: credentials
Owns: `TestRoleKeys` (create/load a role's key in a directory, its x-only public key, signing a Nostr event;
    the structural `EventSigner` implementation) and the private NIP-01 id serialization it signs over
Does not own: the BIP-340 arithmetic (`credentials.domain.bip340_sign`), event shape validation and
    verification (observation), the production signer (a Batch D entry condition)
Entry points: TestRoleKeys
Contracts: NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md (the id signed);
    BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki; RESEARCH-A A3/A4

credentials is a DAG root (it may import only the kernel), so the id preimage is serialized here with the same
exact NIP-01 escape table as `observation.domain.nostr_event`; a test pins the two together.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from pathlib import Path

from codex_harness.credentials.domain import bip340_sign
from codex_harness.kernel.errors import ContractError

_ROLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_ESCAPES = {"\n": "\\n", '"': '\\"', "\\": "\\\\", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ContractError("role keys: expected a string")
    return '"' + "".join(_ESCAPES.get(ch, ch) for ch in value) + '"'


def _count(value: object, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"role keys: {name} must be a non-negative integer")
    return str(value)


def _event_id(pubkey: str, unsigned: dict) -> str:
    tags = unsigned["tags"]
    if not isinstance(tags, list) or any(not isinstance(tag, list) for tag in tags):
        raise ContractError("role keys: tags must be a list of lists")
    tag_text = "[" + ",".join("[" + ",".join(_string(item) for item in tag) + "]" for tag in tags) + "]"
    text = "[0," + ",".join((_string(pubkey), _count(unsigned["created_at"], "created_at"),
                             _count(unsigned["kind"], "kind"), tag_text, _string(unsigned["content"]))) + "]"
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ContractError("role keys: text is not valid Unicode") from exc


class TestRoleKeys:
    """TEST custody: non-constant-time pure-Python signing; never production (DESIGN-A, RESEARCH A3/A4; the
    production signer is a Batch D entry condition).

    One 32-byte key file `<role>.key` (mode 0600) per role under `directory`. The secret is never returned,
    exported or logged: callers get the public key and signed events only.
    """

    __test__ = False  # not a pytest class, despite the name

    def __init__(self, directory: str | os.PathLike):
        self._directory = Path(directory)

    def __repr__(self) -> str:
        return f"TestRoleKeys(directory={str(self._directory)!r})"

    __str__ = __repr__

    def _path(self, role: str) -> Path:
        if not isinstance(role, str) or not _ROLE.fullmatch(role):
            raise ContractError("role keys: a role id is 1-64 characters of [a-z0-9_-]")
        return self._directory / f"{role}.key"

    def create(self, role: str) -> None:
        """Write a fresh random key (O_EXCL, 0600); an existing key is refused, never replaced."""
        path = self._path(role)
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        secret = secrets.token_bytes(32)
        while not bip340_sign.valid_secret(secret):
            secret = secrets.token_bytes(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError as exc:
            raise ContractError(f"role keys: a key already exists for {role}") from exc
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, secret)
        finally:
            os.close(fd)

    def _secret(self, role: str) -> bytes:
        path = self._path(role)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError as exc:
            raise ContractError(f"role keys: no key for {role}") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ContractError(f"role keys: the key file of {role} must be a regular file with mode 0600")
            secret = os.read(fd, 33)
        finally:
            os.close(fd)
        if not bip340_sign.valid_secret(secret):
            raise ContractError(f"role keys: the key file of {role} is not a valid 32-byte key")
        return secret

    def pubkey(self, role: str) -> str:
        """The x-only public key as 64 lowercase hex characters."""
        return bip340_sign.xonly_pubkey(self._secret(role)).hex()

    def sign(self, role: str, unsigned_event: dict) -> dict:
        """Set pubkey, id and sig on an event that has kind, created_at, tags and content."""
        if not isinstance(unsigned_event, dict) or not {"kind", "created_at", "tags", "content"} <= set(
                unsigned_event) or set(unsigned_event) - {"kind", "created_at", "tags", "content", "pubkey"}:
            raise ContractError("role keys: an unsigned event has kind, created_at, tags and content "
                                "(and optionally this role's pubkey)")
        secret = self._secret(role)
        pubkey = bip340_sign.xonly_pubkey(secret).hex()
        if unsigned_event.get("pubkey", pubkey) != pubkey:
            raise ContractError("role keys: the event names another pubkey")
        ident = _event_id(pubkey, unsigned_event)
        sig = bip340_sign.sign(secret, bytes.fromhex(ident)).hex()
        return {"id": ident, "pubkey": pubkey, "created_at": unsigned_event["created_at"],
                "kind": unsigned_event["kind"], "tags": [list(tag) for tag in unsigned_event["tags"]],
                "content": unsigned_event["content"], "sig": sig}
