"""The d0a/d0b restored-catalog bracket (RH-1b; rehearsal design "2. PHASE P" verdicts and RH-8's review).

Phase P dumps production twice around the Redis copy (d0a before it, d0b after). Each dump is restored into its own
disposable copy (`S` for d0a, `seal-b` for d0b, removed after use) and `bracket()` compares the two over the product's
own `pg_catalog` / `catalog_digest` (the same function on both sides):

- equal catalog sha256 -> `quiescent: true`: production did not move across the Redis copy;
- unequal -> `quiescent: false`, `D0 := d0a`, the differing relations (names and row counts only, never a row) and
  `cross_store_skew: true` (the Redis copy happened between the dumps); the PEL-owner checks become informational.

The facts are stored in `d0.json` under `facts.bracket` (`d0.record_d0(..., bracket=...)`). Nothing here writes to a copy.
"""

from __future__ import annotations

from .copies import pg_dsn


def relation_facts(catalog: dict) -> dict[str, tuple[int, str]]:
    """`{"schema.relation": (row count, rows sha256)}` of every relation of a product catalog."""
    return {f"{schema}.{name}": (relation["rows"], relation["rows_sha256"])
            for schema, body in sorted(catalog["schemas"].items()) for name, relation in sorted(body["relations"].items())}


def compare_catalogs(first: dict, second: dict) -> dict:
    """The bracket verdict of two product catalogs (`first` = d0a, `second` = d0b); names and counts only."""
    from codex_harness.delivery.adapters.host_migration import catalog_digest

    a, b = relation_facts(first), relation_facts(second)
    differing = sorted(name for name in a.keys() | b.keys() if a.get(name) != b.get(name))
    digests = {"d0a": catalog_digest(first), "d0b": catalog_digest(second)}
    quiescent = digests["d0a"] == digests["d0b"]
    facts = {"quiescent": quiescent, "d0": "d0a", "catalog_sha256": digests, "relations_compared": len(a.keys() | b.keys()),
             "differing": differing,
             "differing_counts": {name: {"d0a": a[name][0] if name in a else None, "d0b": b[name][0] if name in b else None}
                                  for name in differing},
             "cross_store_skew": not quiescent,
             "pel_owner_checks": "enforced" if quiescent else "informational"}
    if not quiescent:
        facts["catalog_only_difference"] = not differing  # a difference outside the row digests (ACL, column, ...)
    return facts


def bracket(d0a_copy, d0b_copy, database: str) -> dict:
    """Compare the catalogs of the two restored Phase-P dumps (`copies.Copy` handles, restored under `database`)."""
    from codex_harness.delivery.adapters.host_migration import pg_catalog

    catalogs = [pg_catalog(pg_dsn(copy.pg_socket, database), database) for copy in (d0a_copy, d0b_copy)]
    return compare_catalogs(*catalogs)


__all__ = ["bracket", "compare_catalogs", "relation_facts"]
