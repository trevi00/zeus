"""Buzz A1: BIP-340 verify and the test-custody sign against every row of the official test-vectors.csv.

Vectors: tests/fixtures/bip340/test-vectors.csv (unchanged copy, provenance beside it); BIP-340 cited in the modules.
"""

import csv
import hashlib
from pathlib import Path

import pytest

from codex_harness.credentials.domain import bip340_sign
from codex_harness.observation.domain import bip340

VECTORS = Path(__file__).parent / "fixtures" / "bip340" / "test-vectors.csv"
ROWS = list(csv.DictReader(VECTORS.open()))
PROVENANCE_SHA256 = "34c9d1d9c3a88d524bc80778540dc43f8306ec249a7485293063c376db851c2d"


def _b(hex_text: str) -> bytes:
    return bytes.fromhex(hex_text)


def test_vector_file_is_the_unchanged_official_copy():
    assert hashlib.sha256(VECTORS.read_bytes()).hexdigest() == PROVENANCE_SHA256


def test_vector_file_has_all_rows():
    assert len(ROWS) == 19 and [int(r["index"]) for r in ROWS] == list(range(19))
    assert sum(1 for r in ROWS if r["secret key"]) == 8


@pytest.mark.parametrize("row", ROWS, ids=lambda r: f"row{r['index']}")
def test_verify_matches_every_row(row):
    expected = {"TRUE": True, "FALSE": False}[row["verification result"]]
    assert bip340.verify(_b(row["public key"]), _b(row["message"]), _b(row["signature"])) is expected


@pytest.mark.parametrize("row", [r for r in ROWS if r["secret key"]], ids=lambda r: f"row{r['index']}")
def test_sign_with_aux_reproduces_the_row_signature(row):
    secret, msg = _b(row["secret key"]), _b(row["message"])
    assert bip340_sign.xonly_pubkey(secret) == _b(row["public key"])
    assert bip340_sign.sign_with_aux(secret, msg, _b(row["aux_rand"])) == _b(row["signature"])


def test_sign_round_trip_and_fresh_randomness():
    secret = bytes(31) + b"\x07"
    pub = bip340_sign.xonly_pubkey(secret)
    for msg in (b"", b"a", bytes(range(32)), b"x" * 100):
        one, two = bip340_sign.sign(secret, msg), bip340_sign.sign(secret, msg)
        assert one != two and bip340.verify(pub, msg, one) and bip340.verify(pub, msg, two)


def test_verify_never_raises_on_bad_lengths_and_tampering():
    row = ROWS[0]
    pub, msg, sig = _b(row["public key"]), _b(row["message"]), _b(row["signature"])
    assert bip340.verify(pub[:31], msg, sig) is False and bip340.verify(pub, msg, sig[:63]) is False
    assert bip340.verify(pub, b"x" + msg, sig) is False
    assert bip340.verify(pub, msg, sig[:-1] + bytes([sig[-1] ^ 1])) is False


def test_sign_refuses_invalid_secret():
    from codex_harness.kernel.errors import ContractError
    for bad in (bytes(32), b"\xff" * 32, b"\x01" * 31):
        with pytest.raises(ContractError):
            bip340_sign.sign(bad, b"m")
    with pytest.raises(ContractError):
        bip340_sign.sign_with_aux(bytes(31) + b"\x01", b"m", b"short")
