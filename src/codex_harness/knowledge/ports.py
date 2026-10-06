"""Knowledge ports and owned buckets (§2.5, §2.7).

Layer: ports
Context: knowledge
Owns: OWNED_BUCKETS of the knowledge context; CodeIndex and KnowledgeQuery (the M7 `Knowledge` split)
Does not own: the graph tables (storage owns knowledge_nodes/knowledge_edges writes through the store graph port)
Entry points: CodeIndex.index_python, KnowledgeQuery.query, OWNED_BUCKETS
Contracts: INV-GRAPH-001
"""

from __future__ import annotations

from typing import Protocol

OWNED_BUCKETS = ("experience_claims", "profile_consents", "profile_runs", "promotions", "seam_comparisons",
                 "seam_ledger_imports", "seam_observations", "seam_views", "snapshot_imports",
                 "graph_index")  # S10 E3: GraphIndexState (M7 supervisor's graph index revision)


class CodeIndex(Protocol):
    def index_python(self, root: str) -> dict: ...


class KnowledgeQuery(Protocol):
    def query(self, text: str, depth: int = 1, limit: int = 12) -> list[dict]: ...
