"""Ported SOURCE main b9d8f15 (S2R) suite `tests/test_maintenance_evidence.py` run against the target (G1-13 batch b).

Every assertion is S2R's, unchanged. Adaptations are import lines and one construction only: the adapter is
`delivery.adapters.maintenance_evidence`, `MemoryStore` / `FileArtifacts` / `DeliveryRefused` / `BUCKET_ACTIONS` come from their target homes,
and `LazyArtifacts(root)` is `LazyArtifacts(root, FileArtifacts)` (the store constructor is injected: an adapter may not import `storage.adapters`).

S2R docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001, evidence ports of the restart phase: the trusted authority reader, the lazy
artifact store and the owner-action reader (the arm-phase credential helper and canary executor are PR-3's
remainder, ALL-PRIMARY-20260930).

The authority store is a labelled content-addressed directory in `tmp_path`. No unit, store, model or provider is
touched.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
from codex_harness.delivery.adapters.maintenance_evidence import (
    AUTHORITY_MAX_BYTES,
    LazyArtifacts,
    control_action_reader,
    trusted_authority_reader,
)
from codex_harness.delivery.domain.host_delivery import DeliveryRefused
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

posix_only = pytest.mark.skipif(os.name == "nt", reason="the managed systemd maintenance is Linux-only (aibox)")


# ----- S2M-2: the authority is verified bytes from the trusted store, never created ------------------------------
def _put(root: Path, data: bytes, *, name=None) -> str:
    key = name or hashlib.sha256(data).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    (root / (key + ".txt")).write_bytes(data)
    return "sha256:" + key


def test_authority_reader_verifies_bytes_refuses_forged_modified_symlinked_or_oversized_and_creates_nothing(tmp_path):
    root = tmp_path / "runtime" / "artifacts"
    directive = "LABELLED recorded user directive: PRIMARY maintenance of managed-fleet\n".encode("utf-8")
    ref = _put(root, directive)
    read = trusted_authority_reader(root)
    assert read(ref) == directive
    refs = {"forged_syntax": "sha256:" + "A" * 64, "short": "sha256:" + "a" * 63, "not_a_ref": "latest",
            "not_a_string": None, "absent": "sha256:" + "0" * 64}
    modified = _put(root, b"other bytes", name=hashlib.sha256(b"original bytes").hexdigest())
    refs["modified"] = modified
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_bytes(b"linked directive")
    link_key = hashlib.sha256(b"linked directive").hexdigest()
    (root / (link_key + ".txt")).symlink_to(elsewhere)
    refs["symlinked"] = "sha256:" + link_key
    big = b"x" * (AUTHORITY_MAX_BYTES + 1)
    refs["oversized"] = _put(root, big)
    refs["empty"] = _put(root, b"")
    if hasattr(os, "mkfifo"):
        fifo_key = hashlib.sha256(b"fifo").hexdigest()
        os.mkfifo(root / (fifo_key + ".txt"))
        refs["fifo"] = "sha256:" + fifo_key
    for name, candidate in refs.items():
        with pytest.raises(DeliveryRefused) as refused:
            read(candidate)
        assert (refused.value.reason_code, refused.value.field) == ("maintenance_authority_unverified",
                                                                    "authority"), name
    # A store that does not exist is not created by reading it.
    missing = tmp_path / "no-runtime" / "artifacts"
    with pytest.raises(DeliveryRefused):
        trusted_authority_reader(missing)(ref)
    assert not missing.exists() and not missing.parent.exists()


# ----- S2M-17: the artifact store is created only by the first actual put -------------------------------------------
def test_lazy_artifacts_create_nothing_until_the_first_put(tmp_path):
    root = tmp_path / "runtime" / "artifacts"
    artifacts = LazyArtifacts(root, FileArtifacts)
    assert not root.exists() and not root.parent.exists()
    receipt = artifacts.put('{"typed":"copy"}', "host-delivery-maintenance:labelled:startup_receipt")
    key = hashlib.sha256(b'{"typed":"copy"}').hexdigest()
    assert receipt["ref"] == "sha256:" + key and (root / (key + ".txt")).read_bytes() == b'{"typed":"copy"}'
    # The same store serves later puts, and its bytes verify through the trusted reader.
    assert artifacts.put('{"typed":"copy"}', "again")["ref"] == receipt["ref"]
    assert trusted_authority_reader(root)(receipt["ref"]) == b'{"typed":"copy"}'


def test_the_owner_action_reader_reads_one_row_and_nothing_else():
    store = MemoryStore()
    action_id = "b" * 64
    with store.transaction() as tx:
        tx.put(BUCKET_ACTIONS, action_id, {"id": action_id, "state": "requested"})
    read = control_action_reader(store)
    assert read(action_id) == {"id": action_id, "state": "requested"}
    assert read("c" * 64) is None
    for invalid in ("B" * 64, "b" * 63, None, 7, "../" + "b" * 61):
        assert read(invalid) is None
    with store.transaction() as tx:
        assert tx.scan(BUCKET_ACTIONS) == [{"id": action_id, "state": "requested"}]


