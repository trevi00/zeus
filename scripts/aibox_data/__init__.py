"""Offline data-transfer tooling for the aibox migration (SPEC aibox-migration-001 §6-§8, §10, gate C).

Everything here is read-only against the source: it scans files, verifies exported inventories and
stages copies into a separate staging root. It never connects to PostgreSQL or Redis, never reads
credentials and never changes admission, registry or ledger state; the migration coordinator owns
state transitions and consumes these reports as evidence.
"""

SCHEMA_VERSION = 1
