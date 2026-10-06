"""The in-process store: a deep-copied draft per unit, committed by replacing the whole state.

Layer: adapters
Context: storage
Owns: the in-memory emulation of `documents` and the knowledge graph tables (tests, fixtures)
Does not own: record meaning
Entry points: MemoryStore.transaction, MemoryTransaction, MemoryGraph

The unit is the `with` block: the draft becomes the state only when the block exits without an
exception, so a failure anywhere in the unit leaves no write behind (§2.9). The re-entrant lock
admits a nested `transaction()` in the same thread; its draft commits first and the outer draft then
replaces it, so the inner writes are lost. That is M7 behaviour, kept, and one reason §2.9 forbids
nested units.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock


class MemoryTransaction:
    def __init__(self, data: dict):
        self.data = data

    def get(self, bucket: str, key: str) -> dict | None:
        return deepcopy(self.data.get((bucket, key)))

    def put(self, bucket: str, key: str, body: dict) -> None:
        self.data[bucket, key] = deepcopy(body)

    def scan(self, bucket: str) -> list[dict]:
        return [deepcopy(v) for (b, _), v in sorted(self.data.items()) if b == bucket]

    def records(self) -> list[dict]:
        return [{"bucket": bucket, "id": key, "body": deepcopy(value)}
                for (bucket, key), value in sorted(self.data.items())]

    def entries(self, bucket: str, after: str = "", limit: int = 100) -> list[dict]:
        return [{"id": key, "body": deepcopy(value)}
                for (name, key), value in sorted(self.data.items()) if name == bucket and key > after][:limit]

    def graph(self):
        """Graph-write port (INV-AUTONOMOUS-001): nodes and edges live in the same draft as documents."""
        return MemoryGraph(self)


class MemoryGraph:
    def __init__(self, tx):
        self.tx = tx

    def put_node(self, node: dict) -> None:
        self.tx.put("knowledge_nodes", node["id"], node)

    def put_edge(self, source: str, target: str, kind: str) -> None:
        self.tx.put("knowledge_edges", source + "->" + target + ":" + kind, {"source": source, "target": target, "kind": kind})


class MemoryStore:
    def __init__(self):
        self.data: dict = {}
        self.lock = RLock()

    @contextmanager
    def transaction(self, fail_fast: bool = False):
        # `fail_fast` only shortens lock waits in the PostgreSQL store; an in-process lock has nothing to shorten.
        with self.lock:
            draft = deepcopy(self.data)
            yield MemoryTransaction(draft)
            self.data = draft
