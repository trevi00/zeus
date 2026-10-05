"""Storage ports: the transaction/store, read-only store, artifact and message-bus Protocols.

Layer: ports
Context: storage
Owns: buckets maintenance, migration_runs, knowledge_nodes, knowledge_edges (the in-process graph
tables); the PostgreSQL `documents`/`knowledge_*`/`schema_migrations` access itself
Does not own: the meaning of any record body; the `events` bucket (coordination's EventJournal)
Entry points: Transaction, Store, ReadTransaction, ReadOnlyStore, ArtifactStore, ArtifactReader,
MessageBus, EventJournal, MessageDeliveryError, TransportChanged, OWNED_BUCKETS
Contracts: INV-ARTIFACT-001, INV-MIGRATION-001, INV-MESSAGE-001

These are shared infrastructure ports (`SP` in the §3.6 table): every context's ports, application
and adapters may name them in signatures. The M7 signatures are kept exactly (§2.5). An operation
that can join an atomic unit takes the unit's `Transaction` and never opens its own (§2.9 rule 2).
"""

from __future__ import annotations

from typing import ContextManager, Protocol

# §2.7: the buckets this context writes; `tx.put("<bucket>"` for any of them outside storage is a
# single-writer violation (target/tests/import_rules.py).
OWNED_BUCKETS = ("maintenance", "migration_runs", "knowledge_nodes", "knowledge_edges")


class ReadTransaction(Protocol):
    def get(self, bucket: str, key: str) -> dict | None: ...
    def scan(self, bucket: str) -> list[dict]: ...
    def records(self) -> list[dict]: ...
    def entries(self, bucket: str, after: str = "", limit: int = 100) -> list[dict]: ...


class Transaction(Protocol):
    def get(self, bucket: str, key: str) -> dict | None: ...
    def put(self, bucket: str, key: str, body: dict) -> None: ...
    def scan(self, bucket: str) -> list[dict]: ...
    def records(self) -> list[dict]: ...
    def entries(self, bucket: str, after: str = "", limit: int = 100) -> list[dict]: ...


class Store(Protocol):
    # `fail_fast` (S2b): a display-only writer's short lock budget; stores without lock waits accept and ignore it.
    def transaction(self, fail_fast: bool = False) -> ContextManager[Transaction]: ...


class ReadOnlyStore(Protocol):
    """What a read-only consumer (the monitor collector) may hold: reads only, never a write."""

    def transaction(self) -> ContextManager[ReadTransaction]: ...


class EventJournal(Protocol):
    """The `events` bucket's owner operation, implemented by coordination (§2.7 `EventJournal`).

    `append` joins the caller's unit (`tx`) and writes `body` under `event_id` only when that id is
    absent, so a replay of the same fact never writes twice."""

    def append(self, tx: Transaction, event_id: str, body: dict) -> None: ...


class MessageDeliveryError(RuntimeError):
    """Transport failed; delivery may have happened before the response was lost."""


class TransportChanged(RuntimeError):
    """The publisher is not the transport committed for this attempt; it refused BEFORE any write,
    so nothing was handed to any transport by this call (research-dispatch-recovery-001)."""


class MessageBus(Protocol):
    """`transport()` is optional: a bus that has it returns its credential-free identity, which the
    outbox commits with the attempt BEFORE publishing and passes back as `publish(message,
    transport=...)`; the bus must refuse with `TransportChanged` before writing when it is not that
    transport. A bus without it still delivers, but its attempts carry no transport binding."""

    def validate(self, message: dict) -> dict: ...
    def publish(self, message: dict, transport: dict | None = None) -> str: ...


class ArtifactStore(Protocol):
    # `lock_timeout` (S2b): a display-only writer's short wait before it drops its record.
    # `redactions` (S11 XC-2b B3): the count of credential spans redacted from `body`, recorded in the receipt when given.
    def put(self, body: str, source: str, lock_timeout: float = 30, redactions: int | None = None) -> dict: ...
    def read(self, reference: str, start: int = 0, length: int = 8000) -> str: ...


class ArtifactReader(Protocol):
    """Integrity-checked mechanical reads (M7 `AuditArtifacts` beyond put/read), never model context."""

    def document(self, reference: str) -> dict: ...
    def inspect(self, reference: str) -> dict: ...
    def text(self, reference: str, max_bytes: int) -> str: ...
    def search(self, reference: str, needle: str, limit: int = 20) -> list[dict]: ...
