"""Observation ports: the buckets observation owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: observation
Owns: OWNED_BUCKETS of the observation context; SpoolFull and ObservationSpool (M7 `ports.py`, moved ahead in S4
    unchanged: the append-only record store the Observer writes through)
Also owns (Buzz A1/A2, additive): the EventSigner, EventVerifier and RelayClient signatures (no implementation)
Also owns (Buzz A3a/A3b, additive): the RemoteInboxPort and BridgeLeasePort signatures, which coordination's owner
    operations implement structurally (no import from observation to coordination)
Does not own: ObservationDirectory (9 methods, above the port-size limit: S9) and the other observation Protocols
    (PostgresFacts, RedisFacts, ...: S9)
Entry points: OWNED_BUCKETS, SpoolFull, ObservationSpool, EventSigner, EventVerifier, RelayClient, RemoteInboxPort,
    BridgeLeasePort
Contracts: INV-OBSERVATION-001; NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

OWNED_BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts",
                 "observation_collections", "observation_terminations", "health",
                 # Buzz A3a (design §6.2 steps 4 and 6): the per-channel cursor and the persisted reconciliation passes.
                 "buzz_cursors", "buzz_passes",
                 # Buzz A3b (design §6.1): the signed outbound ops, the per-class deferral watermarks, one alert row.
                 "buzz_outbox", "buzz_outbox_watermarks", "buzz_alerts")


class SpoolFull(RuntimeError):
    """The bounded observation spool cannot take another record; the caller counts and reports."""


class ObservationSpool(Protocol):
    """One process run's append-only durable record store (INV-OBSERVATION-001)."""
    process_run_id: str

    def append(self, kind: str, event: dict) -> int: ...
    def close(self) -> None: ...


class EventSigner(Protocol):
    """Signs a Nostr event for a role (custody; TEST custody until the Batch D production signer)."""

    def pubkey(self, role: str) -> str: ...
    def sign(self, role: str, unsigned: dict) -> dict: ...


class EventVerifier(Protocol):
    """True only for a well-formed event whose id matches its fields and whose BIP-340 signature holds."""

    def verify(self, event: dict) -> bool: ...


class RelayClient(Protocol):
    """A Nostr relay connection: publish a signed event, query (one request or the whole keyset), subscribe, close."""

    def publish(self, event: dict) -> dict: ...
    def query(self, filters: list[dict]) -> dict: ...
    def query_all(self, filter: dict, *, until: int | None = None) -> dict: ...
    def subscribe(self, sub_id: str, filters: list[dict]) -> Iterator[dict]: ...
    def close(self) -> None: ...


class RemoteInboxPort(Protocol):
    """Coordination's `remote_inbox` owner operations, each inside the CALLER's transaction (design §5, §6.2 step 2)."""

    def insert_pending(self, tx, meta: dict) -> str: ...
    def mark_processed(self, tx, event_id: str, outcome: str) -> dict: ...
    def pending(self, tx) -> list[dict]: ...
    def compact(self, tx, older_than: int) -> int: ...


class BridgeLeasePort(Protocol):
    """The single active bridge's generation-fenced lease (design §6.5)."""

    def acquire(self, tx, owner_id: str, now: float, ttl_seconds: float) -> int | None: ...
    def renew(self, tx, owner_id: str, generation: int, now: float, ttl_seconds: float) -> float: ...
    def require_current(self, tx, generation: int) -> None: ...
