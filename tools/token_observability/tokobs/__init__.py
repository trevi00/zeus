"""tokobs: the token-observability collector core (token-observability-001, W1).

Purpose: read existing worker receipt files, keep an append-only SQLite ledger, and render bounded
Prometheus exposition text. Layer: tooling (operator tooling, not Zeus product code).
Owns: the package namespace. Does-not-own: any deployment file, dashboard or source stream.
Stdlib only. DESIGN.md / ACCEPTANCE.md live in the artifact store (A/evidence/token-observability-001).
"""

__version__ = "1.0.0-w1b"
