"""Read-only PostgreSQL snapshot port for the council (INV-COUNCIL-001).

One `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` transaction with bounded connection and
statement timeouts reads exactly the selected `documents` rows in one statement and the database,
schema and server version for the endpoint identity digest. PostgreSQL 18 transaction-iso: Repeatable
Read sees one snapshot for the whole transaction; READ ONLY makes any write fail server-side. The
domain reduces the rows to per-key found/missing/unknown, canonical-row SHA-256 and the whitelisted
status fields; no body, DSN, error text or credential leaves this module. Any connection or read
failure is `snapshot_unavailable`, never an empty observation. `connect` is injectable so unit tests
drive a fake connection; the integration lane uses real PostgreSQL. This port never writes and is
not `Store.transaction` (which serializes writers behind an advisory lock).
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg

from codex_harness.domain.council import snapshot_envelope, snapshot_records, validate_current_state
from codex_harness.domain.model import ContractError, digest, utcnow

BEGIN = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
IDENTITY = "SELECT current_database(), current_schema(), current_setting('server_version')"
SELECT = ("SELECT s.bucket, s.id, d.body FROM unnest(%s::text[], %s::text[]) AS s(bucket, id) "
          "JOIN documents d ON d.bucket = s.bucket AND d.id = s.id")


class SnapshotUnavailable(ContractError):
    def __init__(self, reason_code: str):
        super().__init__("council snapshot " + reason_code)
        self.reason_code = reason_code


class ReadOnlySnapshot:
    def __init__(self, dsn: str, *, connect=None, clock=utcnow, connect_timeout: int = 5, statement_timeout_ms: int = 5000):
        if type(connect_timeout) is not int or connect_timeout <= 0 or type(statement_timeout_ms) is not int or statement_timeout_ms <= 0:
            raise ContractError("Snapshot timeouts must be positive integers")
        self.dsn, self.connect, self.clock = dsn, connect or psycopg.connect, clock
        self.connect_timeout, self.statement_timeout_ms = connect_timeout, statement_timeout_ms

    @contextmanager
    def _session(self):
        """The read-only repeatable-read transaction; always rolled back, never committed."""
        try:
            conn = self.connect(self.dsn, connect_timeout=self.connect_timeout, autocommit=True)
        except Exception as exc:
            raise SnapshotUnavailable("snapshot_unavailable") from exc
        with conn:
            conn.execute(BEGIN)
            try:
                conn.execute("SET LOCAL statement_timeout = '%dms'" % self.statement_timeout_ms)
                yield conn
            finally:
                conn.execute("ROLLBACK")

    def observe(self, selection: list, *, topic: str, run_id: str, base_revision: str, max_age_seconds: int) -> dict:
        records = validate_current_state({"records": selection, "max_age_seconds": max_age_seconds})["records"]
        try:
            with self._session() as conn:
                identity = conn.execute(IDENTITY).fetchone()
                rows = conn.execute(SELECT, ([r["bucket"] for r in records], [r["id"] for r in records])).fetchall()
                observed_at = self.clock()
        except SnapshotUnavailable:
            raise
        except Exception as exc:
            raise SnapshotUnavailable("snapshot_unavailable") from exc
        if not (isinstance(identity, (tuple, list)) and len(identity) == 3 and all(isinstance(v, str) for v in identity)):
            raise SnapshotUnavailable("snapshot_unavailable")
        bodies = {(bucket, key): body for bucket, key, body in rows}
        endpoint = digest({"database": identity[0], "schema": identity[1], "server_version": identity[2]})
        return snapshot_envelope(topic=topic, run_id=run_id, base_revision=base_revision, selection=records,
                                 records=snapshot_records(records, bodies), database_identity=endpoint,
                                 observed_at=observed_at, max_age_seconds=max_age_seconds)


__all__ = ["BEGIN", "ReadOnlySnapshot", "SnapshotUnavailable"]
