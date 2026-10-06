"""The Python-graph index revision record (S10 E3).

Layer: application
Context: knowledge
Owns: bucket graph_index (single writer)
Does not own: the index itself (adapters, PostgresKnowledge.index_python) and the decision when to re-index (composition.supervisor)
Entry points: GraphIndexState
Contracts: INV-GRAPH-001
Moved from SOURCE M7 `supervisor.py` maintain_views `graph` (the only reader and writer of this bucket); the two statements are M7's.
"""


class GraphIndexState:
    """Stateless owner operations; each joins the caller's transaction."""

    def indexed(self, tx):
        return tx.get("graph_index", "main")

    def record(self, tx, revision, index) -> None:
        tx.put("graph_index", "main", {"id": "main", "revision": revision, **index})
