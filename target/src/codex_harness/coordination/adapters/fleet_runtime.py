"""The lane connection string and the pre-spawn lane schema check (INV-FLEET-001).

Layer: adapters
Context: coordination
Owns: `lane_dsn` (the host DSN with the lane schema as the only search path) and `verify_lane_schema` (the lane connection selects exactly the lane schema and the schema is already provisioned) (M7 `adapters/fleet_runtime.py`, moved ahead of S5/S6)
Does not own: the lane launcher, the lane environment and the receipt read (S5/S6)
Entry points: lane_dsn, verify_lane_schema
Contracts: INV-FLEET-001

Moved ahead of its slice from M7 `adapters/fleet_runtime.py` (SOURCE e38aa722) through named rules (A/evidence/rebuild/s7/fleet-recovery-move/move_aheads.py, DESIGN-s7 adapters-move §14); the only change is the home of `LaunchRefused` (coordination.domain.fleet); both bodies are otherwise M7's. The host-migration collectors call both (`delivery.restore.pg` runs the real `verify_lane_schema`).
"""
from __future__ import annotations

import psycopg
from psycopg.conninfo import make_conninfo

from codex_harness.coordination.domain.fleet import LaunchRefused


def lane_dsn(host_dsn: str, schema: str) -> str:
    """The lane connection string: the host DSN with the lane schema as the only search path."""
    if not isinstance(host_dsn, str) or not host_dsn.strip():
        raise LaunchRefused("database_url_missing")
    return make_conninfo(host_dsn, options="-c search_path=" + schema)


def verify_lane_schema(dsn: str, schema: str, connect=psycopg.connect) -> None:
    """Pre-spawn: the lane connection must select exactly the lane schema (never public) and the
    schema must already be provisioned; nothing is created here."""
    try:
        with connect(dsn, connect_timeout=5) as conn:
            current = conn.execute("SELECT current_schema()").fetchone()[0]
            if current != schema:
                raise LaunchRefused("lane_schema_mismatch")
            exists = conn.execute("SELECT to_regclass(%s)", (schema + ".documents",)).fetchone()[0]
            if exists is None:
                raise LaunchRefused("lane_schema_unprovisioned")
    except LaunchRefused:
        raise
    except Exception as exc:
        raise LaunchRefused("lane_unavailable") from exc
