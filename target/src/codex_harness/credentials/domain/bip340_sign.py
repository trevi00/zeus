"""BIP-340 Schnorr signing for TEST custody keys: non-constant-time pure Python, never production.

Layer: domain
Context: credentials
Owns: `sign` and `sign_with_aux` (the BIP-340 sign algorithm), `xonly_pubkey`, `valid_secret`, and the secp256k1
    arithmetic and tagged hashes they need (this arithmetic is custody's, not observation's)
Does not own: key files and role names (`credentials.adapters.role_keys`), verification (observation:
    `observation.domain.bip340`), the Nostr event id
Entry points: sign, sign_with_aux, xonly_pubkey, valid_secret
Contracts: BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki (RESEARCH-A A3/A4: the
    reference algorithm is "naive, highly inefficient, and non-constant time"; the production signer is a
    Batch D entry condition)

Secret-dependent branches and variable-time modular arithmetic make this unfit for a real key: it exists so the
bridge can be tested end to end with throwaway keys. `sign_with_aux` takes the aux randomness explicitly so the
official vectors can be reproduced exactly; `sign` draws fresh 32 bytes from `secrets`.
"""

from __future__ import annotations

import hashlib
import secrets

from codex_harness.kernel.errors import ContractError

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)
_Point = tuple[int, int] | None


def _tagged_hash(tag: str, data: bytes) -> bytes:
    digest = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(digest + digest + data).digest()


def _add(a: _Point, b: _Point) -> _Point:
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and a[1] != b[1]:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, _P) % _P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, _P) % _P
    x = (lam * lam - a[0] - b[0]) % _P
    return x, (lam * (a[0] - x) - a[1]) % _P


def _mul(point: _Point, scalar: int) -> _Point:
    result: _Point = None
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def valid_secret(secret: bytes) -> bool:
    """A 32-byte big-endian scalar in [1, n-1]."""
    return len(secret) == 32 and 1 <= int.from_bytes(secret, "big") < _N


def _keypair(secret: bytes) -> tuple[int, bytes]:
    if not valid_secret(secret):
        raise ContractError("bip340: the secret key is not a valid 32-byte scalar")
    point = _mul(_G, int.from_bytes(secret, "big"))
    assert point is not None  # d is in [1, n-1], so d*G is finite
    d = int.from_bytes(secret, "big")
    return (d if point[1] % 2 == 0 else _N - d), point[0].to_bytes(32, "big")


def xonly_pubkey(secret: bytes) -> bytes:
    return _keypair(secret)[1]


def sign_with_aux(secret: bytes, msg: bytes, aux_rand: bytes) -> bytes:
    """The BIP-340 signing algorithm with explicit 32-byte aux randomness (test vectors fix it)."""
    if len(aux_rand) != 32:
        raise ContractError("bip340: aux_rand must be 32 bytes")
    d, pub = _keypair(secret)
    t = (d ^ int.from_bytes(_tagged_hash("BIP0340/aux", aux_rand), "big")).to_bytes(32, "big")
    k = int.from_bytes(_tagged_hash("BIP0340/nonce", t + pub + msg), "big") % _N
    if k == 0:
        raise ContractError("bip340: derived nonce is zero; retry with other aux randomness")
    point = _mul(_G, k)
    assert point is not None
    if point[1] % 2 != 0:
        k = _N - k
    r = point[0].to_bytes(32, "big")
    e = int.from_bytes(_tagged_hash("BIP0340/challenge", r + pub + msg), "big") % _N
    return r + ((k + e * d) % _N).to_bytes(32, "big")


def sign(secret: bytes, msg: bytes) -> bytes:
    """Sign with fresh 32-byte aux randomness from `secrets`."""
    return sign_with_aux(secret, msg, secrets.token_bytes(32))
