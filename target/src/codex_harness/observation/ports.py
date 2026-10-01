"""Observation ports: the buckets observation owns (single writer, REBUILD-DESIGN-v2 §2.7).

Layer: ports
Context: observation
Owns: OWNED_BUCKETS of the observation context; SpoolFull and ObservationSpool (M7 `ports.py`, moved ahead in S4
    unchanged: the append-only record store the Observer writes through)
Also owns (Buzz A1, additive): the EventSigner, EventVerifier and RelayClient signatures (no implementation)
Does not own: ObservationDirectory (9 methods, above the port-size limit: S9) and the other observation Protocols
    (PostgresFacts, RedisFacts, ...: S9)
Entry points: OWNED_BUCKETS, SpoolFull, ObservationSpool, EventSigner, EventVerifier, RelayClient
Contracts: INV-OBSERVATION-001; NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

OWNED_BUCKETS = ("observation_audit", "observations", "observation_quarantine", "observation_alerts",
                 "observation_collections", "observation_terminations", "health")


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
    """A Nostr relay connection: publish a signed event, query once, subscribe, close."""

    def publish(self, event: dict) -> dict: ...
    def query(self, filters: list[dict]) -> list[dict]: ...
    def subscribe(self, sub_id: str, filters: list[dict]) -> Iterator[dict]: ...
    def close(self) -> None: ...
