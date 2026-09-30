"""Delivery ports: the buckets delivery owns and the Protocols its use cases call (REBUILD-DESIGN-v2 §2.7; DESIGN-s7 V4).

Layer: ports
Context: delivery
Owns: OWNED_BUCKETS of the delivery context (the host delivery and host migration buckets); the consumer-declared Protocols HostDelivery's objects call on review's
    release owner. Each has at most 6 methods; the implementations (review's Releases and ReleaseQueue) are
    structural and never import this module; composition wires them
Does not own: the release rows (review), the host targets, GitHub and canary adapters (S7 adapter step)
Entry points: OWNED_BUCKETS, ReleaseAuthority, ReleaseClaims, ReleaseSettlement
Contracts: INV-HOST-DELIVERY-001, INV-RELEASE-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("host_delivery_targets", "host_delivery_plans", "host_delivery_intents",
                 "host_delivery_descriptors", "host_delivery_migrations", "images", "host_migrations",
                 "host_migration_transitions", "host_migration_checkpoints")


class ReleaseAuthority(Protocol):
    """review: the release verdict, promotion and migration requests, each joining the caller's unit (S7 V4, V5)."""

    def verify(self, release_id, revision, policy_hash, checks, *, transaction=None) -> dict: ...

    def promote(self, release_id, expected_active, *, transaction=None) -> dict: ...

    def rollback(self, expected_active, reason) -> dict: ...

    def request_evaluator_migration(self, release_id, actor, *, expected_revision, expected_policy_hash, approval,
                                    resolved_pin, now=None, transaction=None) -> dict: ...

    def request_environment_reverification(self, release_id, actor, *, expected_revision, expected_policy_hash,
                                           approval, resolved_pin, resolved_controller, now=None,
                                           transaction=None) -> dict: ...

    def record_superseded(self, release_id, reason, *, transaction=None) -> dict: ...


class ReleaseClaims(Protocol):
    """review: the single-controller release queue claim and its lease (S7 V4)."""

    def enqueue(self, release_id, reason, *, transaction=None): ...

    def claim(self, now=None, eligible=None): ...

    def owned(self, tx, claim, now=None): ...

    def heartbeat(self, claim, now=None): ...

    def retry(self, release_id, reason, *, transaction=None): ...


class ReleaseSettlement(Protocol):
    """review: the end of one claimed tick, an external wait or a finished attempt (S7 V4)."""

    def defer(self, claim, result, *, resume_after_seconds=0, now=None): ...

    def finish(self, claim, result, now=None): ...
