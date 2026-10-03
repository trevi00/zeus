"""The `zeus` CLI composition: the knowledge builders (the PREP-S10 composition.cli.knowledge builders).

Layer: composition
Owns: knowledge, embeddings
Does not own: any root's argument shape or body (entry.cli) and the store-backed builders of the other roots (S10 units C2a-C8)
Entry points: knowledge, embeddings
Contracts: none

Replaces the `PostgresKnowledge(database_url())` and `LocalEmbeddings(".runtime/models")` constructions of M7 `cli.py` (SOURCE e38aa722:874-889, 905-914).
Imports sit inside the functions, so importing this module stays light (no psycopg, no tree-sitter, no model).
"""


def knowledge():
    from codex_harness.composition import database_url
    from codex_harness.knowledge.adapters.postgres_knowledge import PostgresKnowledge
    return PostgresKnowledge(database_url())


def embeddings():
    from codex_harness.knowledge.adapters.embeddings import LocalEmbeddings
    return LocalEmbeddings(".runtime/models")
