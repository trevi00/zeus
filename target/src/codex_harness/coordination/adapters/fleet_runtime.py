"""The lane connection string, the lane environment, the receipt read, the lane launcher and the pre-spawn lane schema check (INV-FLEET-001).

Layer: adapters
Context: coordination
Owns: `lane_dsn` (the host DSN with the lane schema as the only search path), `verify_lane_schema` (the lane connection selects exactly the lane schema and the schema is already provisioned), `lane_environment` (the inherited host settings plus the lane overrides under both prefixes), `read_receipt` (the exact durable lane receipt row, or why it could not be read) and `LaneLauncher` (the lane child process and its outcome) (M7 `adapters/fleet_runtime.py`)
Does not own: the bindings of the isolation loader, the call budget and the spawn (`composition.fleet`)
Entry points: lane_dsn, verify_lane_schema, lane_environment, read_receipt, LaneLauncher
Contracts: INV-FLEET-001

`lane_dsn` and `verify_lane_schema` moved ahead of their slice from M7 `adapters/fleet_runtime.py` (SOURCE e38aa722) through named rules (A/evidence/rebuild/s7/fleet-recovery-move/move_aheads.py, DESIGN-s7 adapters-move §14); the rest moved by rule R-c16 (S10 unit C8a, GAP #3): every body is M7's except three owner-named injections, each refused before any effect while unwired: the isolation loader (`load_isolation`), the call budget (`budget`; M7's `CallBudget()` default is composition's) and the spawn (`popen`; M7's `subprocess.Popen(..., **no_console_kwargs(process_group=True))`). `LaunchRefused` is `coordination.domain.fleet`'s. `DEFAULT_ARGV` is M7's `(sys.executable, "-m", "codex_harness.cli")`: the `codex_harness.cli` console shim is unit E's.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from codex_harness.coordination.domain.fleet import LaunchRefused, classify_outcome
from codex_harness.kernel.errors import IsolationError, require
from codex_harness.kernel.ids import canonical
from codex_harness.kernel.usage import exhausted

LANE_KEYS = ("REPOSITORY", "RUNTIME_DIR", "REDIS_NAMESPACE", "DATABASE_URL")
DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")
POLL_SECONDS = 0.2


def lane_dsn(host_dsn: str, schema: str) -> str:
    """The lane connection string: the host DSN with the lane schema as the only search path."""
    if not isinstance(host_dsn, str) or not host_dsn.strip():
        raise LaunchRefused("database_url_missing")
    return make_conninfo(host_dsn, options="-c search_path=" + schema)


def lane_environment(lane: dict, host_settings: dict, base=None, *, load_isolation=None) -> dict:
    """Inherited host settings (Docker isolation, executable, token names) plus the lane overrides
    under both prefixes. Returned values are for the child process only, never for display."""
    require(load_isolation is not None, "Lane isolation is not wired")  # R-c16 R-l1: the loader is injected
    isolation = load_isolation(host_settings)
    if isolation is None:
        raise LaunchRefused("isolation_required")
    env = {**(os.environ if base is None else base), **host_settings}
    values = {"REPOSITORY": lane["repository"], "RUNTIME_DIR": lane["runtime"],
              "REDIS_NAMESPACE": lane["redis_namespace"],
              "DATABASE_URL": lane_dsn(host_settings.get("HARNESS_DATABASE_URL"), lane["schema"])}
    for key in LANE_KEYS:
        env["ZEUS_" + key] = env["HARNESS_" + key] = values[key]
    return env


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


def read_receipt(dsn: str, schema: str, operation_id: str, connect=psycopg.connect) -> tuple:
    """(row, error_type): the exact `operations` row from the lane schema, or why it could not be
    read. A read failure is uncertainty, never an empty result."""
    try:
        with connect(dsn, connect_timeout=5) as conn:
            current = conn.execute("SELECT current_schema()").fetchone()[0]
            if current != schema:
                return None, "SchemaMismatch"
            row = conn.execute("SELECT body FROM documents WHERE bucket='operations' AND id=%s",
                               (operation_id,)).fetchone()
            return (row[0] if row else None), None
    except Exception as exc:
        return None, type(exc).__name__


class LaneLauncher:
    def __init__(self, config: dict, host_settings: dict, *, argv=DEFAULT_ARGV, connect=psycopg.connect,
                 budget=None, environ=None, load_isolation=None, popen=None):
        self.config, self.host, self.argv, self.connect = config, host_settings, tuple(argv), connect
        self.budget, self.environ = budget, environ  # R-c16 R-l2: M7's `CallBudget()` default is composition's
        self.load_isolation, self.popen = load_isolation, popen  # R-l1, R-l3: injected, refused while unwired
        self.lanes = {lane["id"]: lane for lane in config["lanes"]}

    def budget_exhausted(self, budget: dict) -> bool:
        """Counts only, under the shared usage policy (finite ceilings, or subscription: readable
        ledger only): the ledger is reserved by the child's operation, immediately before its
        actual provider start, never here."""
        require(self.budget is not None, "Call budget is not wired")
        return exhausted(budget, self.budget.counts())

    def launch(self, job: dict) -> dict:
        require(self.popen is not None, "Lane spawn is not wired")  # R-c16 R-l3: before any effect
        lane = self.lanes[job["lane"]]
        try:
            env = lane_environment(lane, self.host, self.environ, load_isolation=self.load_isolation)
        except IsolationError as exc:
            raise LaunchRefused(exc.reason_code) from exc
        verify_lane_schema(env["ZEUS_DATABASE_URL"], lane["schema"], self.connect)
        directory = Path(lane["runtime"]) / "fleet" / job["id"]
        try:
            directory.mkdir(parents=True, exist_ok=True)
            manifest = directory / "operation.json"
            manifest.write_text(canonical(job["manifest"]) + "\n", encoding="utf-8", newline="\n")
            stdout = open(directory / "stdout.log", "ab")
            stderr = open(directory / "stderr.log", "ab")
        except OSError as exc:
            raise LaunchRefused("runtime_unwritable") from exc
        argv = [*self.argv, "--repository", lane["repository"], "operate", "run", "--file", str(manifest)]
        try:
            process = self.popen(argv, cwd=lane["repository"], env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr)
        except OSError as exc:
            stdout.close(), stderr.close()
            raise LaunchRefused("spawn_failed") from exc
        return {"job_id": job["id"], "process": process, "files": (stdout, stderr), "lane": lane["id"],
                "dsn": env["ZEUS_DATABASE_URL"], "schema": lane["schema"], "directory": directory}

    @staticmethod
    def wait(handles: list, seconds: float) -> list:
        """Finished handles, polling for up to `seconds`; no transaction is open while waiting."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            finished = [h for h in handles if h["process"].poll() is not None]
            if finished or time.monotonic() >= deadline:
                return finished
            time.sleep(POLL_SECONDS)

    def outcome(self, handle: dict, job: dict) -> dict:
        for stream in handle["files"]:
            stream.close()
        exit_code = handle["process"].returncode
        receipt, error = read_receipt(handle["dsn"], handle["schema"], job["operation_id"], self.connect)
        outcome = classify_outcome(exit_code, receipt, job, error)
        # INV-OPERATION-001: the lane operation's own durable owner handoff travels up as it was
        # written. The classification above is untouched by it; `Fleet.finalize` projects it safely.
        handoff = receipt.get("owner_handoff") if isinstance(receipt, dict) else None
        return outcome if handoff is None else {**outcome, "owner_handoff": handoff}
