"""BIP-340 Schnorr signature verification over secp256k1 (public data only; not used for signing).

Layer: domain
Context: observation
Owns: `verify` (x-only public key, message of any length, 64-byte signature), with the field/curve arithmetic,
    `lift_x` and the `BIP0340/challenge` tagged hash it needs
Does not own: signing or any secret-key arithmetic (credentials custody: `credentials.domain.bip340_sign`),
    the Nostr event id (`nostr_event`) and the id recomputation (`observation.adapters.nostr_verify`)
Entry points: verify
Contracts: BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki (RESEARCH-A A4)

Public data only: the public key, the message and the signature are public, so the non-constant-time pure-Python
arithmetic leaks nothing secret. It is not used for signing and must not be extended to handle a secret key.
Verified against every row of the official `test-vectors.csv`.
"""

from __future__ import annotations

import hashlib

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)
_Point = tuple[int, int] | None  # None is the point at infinity


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


def _lift_x(x: int) -> _Point:
    """The curve point with this x and an even y, or None when x is not a valid coordinate."""
    if x >= _P:
        return None
    square = (pow(x, 3, _P) + 7) % _P
    y = pow(square, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != square:
        return None
    return x, y if y % 2 == 0 else _P - y


def verify(pubkey_xonly: bytes, msg: bytes, sig: bytes) -> bool:
    """BIP-340 verification; False for every invalid input, including a wrong length, never an exception."""
    if len(pubkey_xonly) != 32 or len(sig) != 64:
        return False
    point = _lift_x(int.from_bytes(pubkey_xonly, "big"))
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if point is None or r >= _P or s >= _N:
        return False
    e = int.from_bytes(_tagged_hash("BIP0340/challenge", sig[:32] + pubkey_xonly + msg), "big") % _N
    result = _add(_mul(_G, s), _mul(point, _N - e))
    return result is not None and result[1] % 2 == 0 and result[0] == r
