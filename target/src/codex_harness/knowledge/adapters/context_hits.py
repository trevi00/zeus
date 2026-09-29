"""Knowledge hits for a composition: the hybrid graph/vector query behind context.ports.KnowledgeHits.

Layer: adapters
Context: knowledge
Owns: constructing the lazy encoder per query and releasing it afterwards, as M7 did
Does not own: which hits are delivered (context verifies revisions and budgets)
Entry points: KnowledgeHits.hits
Contracts: INV-GRAPH-001
"""

from __future__ import annotations

from codex_harness.knowledge.adapters.embeddings import LocalEmbeddings


class KnowledgeHits:
    def __init__(self, knowledge, models_dir: str):
        self.knowledge, self.models_dir = knowledge, models_dir

    def hits(self, text: str, limit: int) -> list[dict]:
        encoder = LocalEmbeddings(self.models_dir)
        hits = self.knowledge.hybrid_query(text, encoder, limit=limit)
        del encoder
        return hits
