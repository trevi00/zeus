"""Role key custody for the Buzz bridge, TEST custody only: throwaway keys, 0600 files, BIP-340 event signing.

Layer: adapters
Context: credentials
Owns: `TestRoleKeys` (create/load a role's key in a directory, its x-only public key, BIP-340 signing of a
    32-byte event id)
Does not own: the BIP-340 arithmetic (`credentials.domain.bip340_sign`), the NIP-01 id serialization, event
    shape validation and verification (observation; `observation.adapters.event_signer` computes the id and
    calls `sign_id`), the production signer (a Batch D entry condition)
Entry points: TestRoleKeys
Contracts: BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki; RESEARCH-A A3/A4

Custody signs an event ID (design §5): it never sees or serializes an event.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from pathlib import Path

from codex_harness.credentials.domain import bip340_sign
from codex_harness.kernel.errors import ContractError

_ROLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


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

    def sign_id(self, role: str, event_id_hex: str) -> str:
        """BIP-340 signature (128 lowercase hex characters) over the 32-byte event id."""
        if not isinstance(event_id_hex, str) or not _HEX64.fullmatch(event_id_hex):
            raise ContractError("role keys: an event id is 64 lowercase hex characters")
        return bip340_sign.sign(self._secret(role), bytes.fromhex(event_id_hex)).hex()
