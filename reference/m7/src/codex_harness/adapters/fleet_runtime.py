"""Lane launcher for the fleet runner (INV-FLEET-001): the existing `zeus operate run` as a child
process in a lane environment, and the exact durable lane receipt read back afterwards.

The child receives both `ZEUS_`/`HARNESS_` aliases of the lane repository, runtime root, Redis
namespace and lane DSN (host DSN plus `search_path=<schema>` through psycopg.conninfo, never string
concatenation). Docker isolation must be selected by the host settings; there is no host fallback.
Process output goes to files under the lane runtime, never into the store. The machine CallBudget
ledger stays at its default home path and is only counted here, never reserved.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from codex_harness.adapters.call_budget import CallBudget
from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.adapters.isolated_worker import IsolationError, load_isolation
from codex_harness.application.fleet import LaunchRefused
from codex_harness.domain.fleet import classify_outcome
from codex_harness.domain.model import canonical
from codex_harness.domain.usage_policy import exhausted

LANE_KEYS = ("REPOSITORY", "RUNTIME_DIR", "REDIS_NAMESPACE", "DATABASE_URL")
DEFAULT_ARGV = (sys.executable, "-m", "codex_harness.cli")
POLL_SECONDS = 0.2


def lane_dsn(host_dsn: str, schema: str) -> str:
    """The lane connection string: the host DSN with the lane schema as the only search path."""
    if not isinstance(host_dsn, str) or not host_dsn.strip():
        raise LaunchRefused("database_url_missing")
    return make_conninfo(host_dsn, options="-c search_path=" + schema)


def lane_environment(lane: dict, host_settings: dict, base=None) -> dict:
    """Inherited host settings (Docker isolation, executable, token names) plus the lane overrides
    under both prefixes. Returned values are for the child process only, never for display."""
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
                 budget=None, environ=None):
        self.config, self.host, self.argv, self.connect = config, host_settings, tuple(argv), connect
        self.budget, self.environ = budget if budget is not None else CallBudget(), environ
        self.lanes = {lane["id"]: lane for lane in config["lanes"]}

    def budget_exhausted(self, budget: dict) -> bool:
        """Counts only, under the shared usage policy (finite ceilings, or subscription: readable
        ledger only): the ledger is reserved by the child's operation, immediately before its
        actual provider start, never here."""
        return exhausted(budget, self.budget.counts())

    def launch(self, job: dict) -> dict:
        lane = self.lanes[job["lane"]]
        try:
            env = lane_environment(lane, self.host, self.environ)
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
            process = subprocess.Popen(argv, cwd=lane["repository"], env=env, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, **no_console_kwargs(process_group=True))
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
