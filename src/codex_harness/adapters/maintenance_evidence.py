"""Evidence ports of active-generation maintenance, restart phase (INV-HOST-DELIVERY-MAINTENANCE-001).

The use case (`application.host_delivery.HostDelivery.maintain`) decides; this module only reads,
and each port refuses with one fixed code and one allowlisted field, never a value:

* `trusted_authority_reader` - the bytes of the recorded user directive a maintenance document names
  (`authority`), from the control runtime's content-addressed artifact store (DN-1), read without
  following a final link and verified by sha256. It never creates a directory.
* `LazyArtifacts` - the same `FileArtifacts` store, constructed only on the first `put`, so a read-only
  path (every `--check`) creates nothing.
* `control_action_reader` - one read of the control store's owner-action row
  (INV-OWNER-ACTIONS-001); nothing is written.

ALL-PRIMARY-20260930: this release carries the restart phase only. The arm-phase ports (the pinned
credential observation helper, the one-job canary executor and the qualification deadline) are the named
remainder of PR-3; the new generation's PRIMARY booleans are observed by the operator's pinned helper and
bound to the invocation and instance this restart records.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from codex_harness.adapters.host_migration_evidence import HostReader
from codex_harness.application.owner_actions import BUCKET_ACTIONS
from codex_harness.domain.host_delivery import DeliveryRefused

AUTHORITY_MAX_BYTES = 262144
EVIDENCE_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def trusted_authority_reader(root: Path):
    """`(ref) -> bytes` over the content-addressed artifact store at `root` (`<hex>.txt`), read only.

    The ref must be `sha256:<64 hex>`; the file must be a regular file (a final link is not followed) of
    1..`AUTHORITY_MAX_BYTES` bytes whose sha256 is exactly that hex. Anything else refuses
    `maintenance_authority_unverified` naming `authority`. Nothing is created, and the bytes are only
    returned to the caller, which verifies and never stores or prints them."""
    root = Path(root)

    def read(ref) -> bytes:
        if not (type(ref) is str and EVIDENCE_REF.fullmatch(ref)):
            raise DeliveryRefused("maintenance_authority_unverified", "authority")
        key = ref.partition(":")[2]
        try:
            data = HostReader.file(root / (key + ".txt"), AUTHORITY_MAX_BYTES)
        except Exception as exc:
            raise DeliveryRefused("maintenance_authority_unverified", "authority") from exc
        if not data or hashlib.sha256(data).hexdigest() != key:
            raise DeliveryRefused("maintenance_authority_unverified", "authority")
        return data

    return read


class LazyArtifacts:
    """`FileArtifacts` at `root`, constructed (and its directory created) on the first `put` only."""

    def __init__(self, root):
        self.root, self._store = Path(root), None

    def put(self, body: str, source: str) -> dict:
        if self._store is None:
            from codex_harness.adapters.artifacts import FileArtifacts

            self._store = FileArtifacts(str(self.root))
        return self._store.put(body, source)


def control_action_reader(store):
    """`(action_id) -> row | None`: one read transaction of the control store's owner-action row."""

    def read(action_id):
        if not (type(action_id) is str and HEX64.fullmatch(action_id)):
            return None
        with store.transaction() as tx:
            return tx.get(BUCKET_ACTIONS, action_id)

    return read


__all__ = ["AUTHORITY_MAX_BYTES", "LazyArtifacts", "control_action_reader", "trusted_authority_reader"]
