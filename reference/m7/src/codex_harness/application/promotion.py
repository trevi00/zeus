"""Evidence-bound knowledge promotion in one store transaction (INV-AUTONOMOUS-001).

The caller has already re-read the exact succeeded implementation task, the accepted independent
review decision and the all_checked inspection row inside the same transaction. This module writes
the bounded `verified:<run>` graph through the transaction's graph port and the promotion receipt
together: a failure anywhere rolls back both. An identical retry replays the receipt; a different
graph for the same run is refused. No SQL lives here; the port belongs to the store adapter.
"""
from __future__ import annotations

from codex_harness.domain.autonomous import PROMOTED_NAMESPACE
from codex_harness.domain.model import ContractError, digest, utcnow

BUCKET = "promotions"
RECEIPT_SCHEMA = "urn:zeus:promotion-receipt:1"


class PromotionRefused(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("promotion refused: " + reason_code)
        self.reason_code = reason_code


def promote(tx, run_id: str, graph: dict, evidence: dict) -> dict:
    """Write nodes, edges and the receipt in the caller's transaction. `evidence` holds the exact
    record identities the caller validated; it is stored beside the graph digest, never re-derived."""
    if graph.get("repository") != PROMOTED_NAMESPACE + run_id:
        raise PromotionRefused("promotion_namespace_mismatch")
    graph_sha256 = digest(graph)
    old = tx.get(BUCKET, run_id)
    if old is not None:
        if old["graph_sha256"] == graph_sha256:
            return {**old, "cached": True}
        raise PromotionRefused("promotion_conflict")
    port = getattr(tx, "graph", None)
    if port is None:
        raise PromotionRefused("graph_port_missing")
    writer = port()
    for node in graph["nodes"]:
        writer.put_node(node)
    for edge in graph["edges"]:
        writer.put_edge(edge["source"], edge["target"], edge["kind"])
    row = {"schema": RECEIPT_SCHEMA, "id": run_id, "repository": graph["repository"], "graph_sha256": graph_sha256,
           "nodes": [n["id"] for n in graph["nodes"]], "edges": len(graph["edges"]), "evidence": evidence,
           "authority": "verified execution/review provenance with explicit scope; not truth of prose, not merged code",
           "promoted_at": utcnow()}
    tx.put(BUCKET, run_id, row)
    return {**row, "cached": False}
