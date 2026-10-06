"""Measure when a disposable stack is actually usable, on one time axis, for a fixed set of runs.

`VerificationServices` calls a stack ready when a TCP connection to the published port is accepted.
Three failures have been recorded against that:

* on WSL the port is not connectable at all inside the 30s bound (ConnectionRefusedError),
* in CI a connection was accepted and then answered `FATAL: the database system is starting up`,
* in CI a connection was accepted and then `server closed the connection unexpectedly`.

The first is about the host port forward. The other two are about the server behind it, and TCP
cannot see them at all. Whether they share a root cause is the question, not the premise.

So this records, against one clock started at `compose up`:

  container health transitions · published port appearing · host TCP accept ·
  a real PostgreSQL query answering · a real Redis PING answering · each service's own identity ·
  and, for the runs that follow one, the teardown of the previous project

It changes nothing. It starts its own compose projects, removes them, and touches nothing else. The
repetition plan is fixed here rather than chosen while reading results, and every attempt is kept,
including the ones that pass.

usage: uv run python scripts/readiness_probe.py --label windows-11 --out docs/zeus/evidence/readiness-004
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from codex_harness.adapters.commands import run_process  # noqa: E402

# ---- the plan, fixed before anything runs ---------------------------------------------------------
CYCLES_PER_CONDITION = 6
CONDITIONS = ("standalone", "after_teardown")
PROBE_DEADLINE = 90.0          # generous on purpose: this measures when things happen, not whether
POLL_SECONDS = 0.05
COMPOSE_TIMEOUT = 180


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compose(project: str, directory: Path, *args, timeout: int = COMPOSE_TIMEOUT):
    import os

    env = {**os.environ, "ZEUS_VERIFY_PASSWORD": "probe-" + secrets.token_hex(8)}
    return run_process(["docker", "compose", "--project-name", project, "--file",
                        str(directory / "compose.json"), *args],
                       cwd=str(directory), env=env, timeout=timeout)


SPEC = {
    "services": {
        "postgres": {"image": "pgvector/pgvector:pg17",
                     "environment": {"POSTGRES_USER": "zeus", "POSTGRES_DB": "zeus",
                                     "POSTGRES_PASSWORD": "${ZEUS_VERIFY_PASSWORD}"},
                     "ports": ["127.0.0.1::5432"], "volumes": ["database:/var/lib/postgresql/data"],
                     "mem_limit": "512m", "cpus": 1,
                     "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U zeus -d zeus"],
                                     "interval": "1s", "timeout": "3s", "retries": 60}},
        "redis": {"image": "redis:7.4-alpine", "ports": ["127.0.0.1::6379"],
                  "command": ["redis-server", "--appendonly", "no"], "mem_limit": "128m", "cpus": 0.5,
                  "healthcheck": {"test": ["CMD", "redis-cli", "ping"],
                                  "interval": "1s", "timeout": "3s", "retries": 60}}},
    "volumes": {"database": {}},
}


class Cycle:
    """One stack: brought up, measured until everything answers or the deadline, then removed."""

    def __init__(self, root: Path, condition: str, index: int):
        self.project = "zeus-probe-" + uuid4().hex[:12]
        self.directory = root / self.project
        self.condition = condition
        self.index = index
        self.password = "probe-" + secrets.token_hex(8)
        self.record: dict = {"project": self.project, "condition": condition, "cycle": index,
                             "started_at": now(), "timeline": [], "services": {}}

    # ---- the single clock ------------------------------------------------------------------------
    def mark(self, event: str, **detail) -> float:
        at = round(time.monotonic() - self.clock, 3)
        self.record["timeline"].append({"at": at, "event": event, **detail})
        return at

    def run(self) -> dict:
        """Bring the stack up and watch every measure advance on one clock, from the same moment.

        `up --wait` is deliberately not used. It blocks until the healthchecks pass, so a probe that
        starts afterwards can only ever see a window that has already closed. Here the health report
        is one of the things being timed, not the thing that gates the timing.

        What this is not: watching from the same instant the stack starts. The clock starts before
        `compose up`, but the watching begins after `up -d` returns, and health is polled before the
        service requests in each pass. So an observation of health preceding an observation of an
        answer is an ordering of observations, not evidence about what the server could have done in
        between.
        """
        import os

        self.directory.mkdir(parents=True)
        (self.directory / "compose.json").write_text(json.dumps(SPEC, indent=2), encoding="utf-8")
        env = {**os.environ, "ZEUS_VERIFY_PASSWORD": self.password}
        self.clock = time.monotonic()
        self.mark("compose_up_started")
        up = run_process(["docker", "compose", "--project-name", self.project, "--file",
                          str(self.directory / "compose.json"), "up", "-d"],
                         cwd=str(self.directory), env=env, timeout=COMPOSE_TIMEOUT)
        self.mark("compose_up_returned", exit_code=up.returncode)
        self.record["compose_up_ok"] = up.returncode == 0
        if up.returncode:
            self.record["compose_up_stderr_tail"] = up.stderr.strip().splitlines()[-4:]
            self.teardown()
            return self.record
        self.watch()
        self.teardown()
        return self.record

    def watch(self) -> None:
        """One loop, everything advancing together: health, port, TCP, and a real answer."""
        import psycopg
        import redis

        pending = {"postgres": {"port": None, "tcp": False, "answer": False, "healthy": False},
                   "redis": {"port": None, "tcp": False, "answer": False, "healthy": False}}
        refusals = {"postgres": [], "redis": []}
        next_docker_poll = 0.0
        deadline = time.monotonic() + PROBE_DEADLINE
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - self.clock
            if elapsed >= next_docker_poll:
                next_docker_poll = elapsed + 0.5
                for service in ("postgres", "redis"):
                    if not pending[service]["healthy"]:
                        status = self.health_of(service)
                        if status == "healthy":
                            pending[service]["healthy"] = True
                            self.mark("health_healthy", service=service)
                    if pending[service]["port"] is None:
                        port = self.published_port(service)
                        if port is not None:
                            pending[service]["port"] = port
                            self.record["services"].setdefault(service, {})["port"] = port
                            self.mark("port_published", service=service, port=port)
            for service in ("postgres", "redis"):
                port = pending[service]["port"]
                if port is None or pending[service]["answer"]:
                    continue
                if not pending[service]["tcp"]:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                            pending[service]["tcp"] = True
                            at = self.mark("tcp_accepted", service=service)
                            self.record["services"][service]["tcp"] = {"ok": True, "at": at}
                    except OSError:
                        continue
                # Past this line the existing readiness check is already satisfied. What follows is
                # the part it cannot see.
                try:
                    if service == "postgres":
                        dsn = f"postgresql://zeus:{self.password}@127.0.0.1:{port}/zeus"
                        with psycopg.connect(dsn, connect_timeout=3) as connection:
                            identity = connection.execute(
                                "SELECT system_identifier FROM pg_control_system()").fetchone()[0]
                        detail = {"system_identifier": str(identity)}
                    else:
                        client = redis.Redis(host="127.0.0.1", port=port, socket_timeout=3)
                        client.ping()
                        detail = {"run_id": client.info("server").get("run_id")}
                        client.close()
                except Exception as exc:
                    refusals[service].append({"at": round(time.monotonic() - self.clock, 3),
                                              "error": type(exc).__name__,
                                              "reason": re.sub(r"\s+", " ", str(exc)).strip()[:160]})
                    continue
                pending[service]["answer"] = True
                at = self.mark("service_answered", service=service)
                self.record["services"][service]["answer"] = {
                    "ok": True, "at": at, "refusals": refusals[service], **detail}
            if all(state["answer"] and state["healthy"] for state in pending.values()):
                break
            time.sleep(POLL_SECONDS)

        for service, state in pending.items():
            record = self.record["services"].setdefault(service, {})
            record.setdefault("health_healthy", state["healthy"])
            if not state["tcp"]:
                record["tcp"] = {"ok": False, "at": self.mark("tcp_never_accepted", service=service)}
            if not state["answer"]:
                record["answer"] = {"ok": False, "refusals": refusals[service],
                                    "at": self.mark("service_never_answered", service=service)}

    def health_of(self, service: str):
        container = self.container_of(service)
        if not container:
            return None
        inspected = run_process(["docker", "inspect", container, "--format",
                                 "{{json .State.Health}}"], timeout=60)
        try:
            health = json.loads(inspected.stdout or "null") or {}
        except ValueError:
            return None
        record = self.record["services"].setdefault(service, {})
        record["health"] = {"status": health.get("Status"),
                            "failing_streak": health.get("FailingStreak"),
                            "checks": len(health.get("Log") or [])}
        return health.get("Status")

    def container_of(self, service: str):
        record = self.record["services"].setdefault(service, {})
        if record.get("container"):
            return record["container"]
        found = run_process(["docker", "compose", "--project-name", self.project, "--file",
                             str(self.directory / "compose.json"), "ps", "-q", service],
                            cwd=str(self.directory), timeout=60).stdout.strip()
        if found:
            record["container"] = found
        return found or None

    def published_port(self, service: str):
        container_port = "5432" if service == "postgres" else "6379"
        result = run_process(["docker", "compose", "--project-name", self.project, "--file",
                              str(self.directory / "compose.json"), "port", service, container_port],
                             cwd=str(self.directory), timeout=60)
        match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", result.stdout.strip())
        return int(match[1]) if match else None

    # ---- and then it is gone ----------------------------------------------------------------------
    def teardown(self) -> None:
        self.mark("teardown_started")
        result = compose(self.project, self.directory, "down", "--volumes", "--remove-orphans",
                         "--timeout", "10")
        self.record["teardown_at"] = self.mark("teardown_returned", exit_code=result.returncode)
        self.record["teardown_ok"] = result.returncode == 0
        for name in ("compose.json",):
            (self.directory / name).unlink(missing_ok=True)
        try:
            self.directory.rmdir()
        except OSError:
            pass
        self.record["finished_at"] = now()


def summarise(cycles: list) -> dict:
    """What the runs say, counting every one of them."""
    summary = {"cycles": len(cycles), "by_condition": {}}
    for condition in CONDITIONS:
        rows = [row for row in cycles if row["condition"] == condition]
        gaps, health_gaps, refusal_kinds, tcp_failures, answer_failures = [], [], set(), 0, 0
        for row in rows:
            for service in ("postgres", "redis"):
                state = row["services"].get(service, {})
                tcp, answer = state.get("tcp") or {}, state.get("answer") or {}
                if tcp.get("ok") is False:
                    tcp_failures += 1
                if answer.get("ok") is False:
                    answer_failures += 1
                for refusal in answer.get("refusals", []):
                    refusal_kinds.add(f'{service}:{refusal["error"]}:{refusal["reason"][:70]}')
                if tcp.get("ok") and answer.get("ok"):
                    gaps.append({"service": service, "seconds": round(answer["at"] - tcp["at"], 3)})
            healthy = next((event["at"] for event in row["timeline"]
                            if event["event"] == "health_healthy" and event.get("service") == "postgres"), None)
            answered = (row["services"].get("postgres", {}).get("answer") or {}).get("at")
            if healthy is not None and answered is not None:
                health_gaps.append(round(answered - healthy, 3))
        summary["by_condition"][condition] = {
            "runs": len(rows),
            "tcp_never_accepted": tcp_failures,
            "never_answered": answer_failures,
            "tcp_to_answer_seconds": gaps,
            "healthy_to_answer_seconds": health_gaps,
            "refusal_kinds": sorted(refusal_kinds),
        }
    return summary


def through_harness(out: Path, label: str, runs: int) -> dict:
    """Bring real stacks up through `VerificationServices` and keep what its readiness reported.

    The cycles above measure the environment. This measures the change: on the same machine, how
    much of that window the readiness check now waits through, and what it names while waiting.
    """
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.verification import VerificationServices

    root = ROOT / ".probe-harness"
    root.mkdir(exist_ok=True)
    artifacts = FileArtifacts(str(root / "artifacts"))
    records = []
    for index in range(1, runs + 1):
        services = VerificationServices(root, artifacts)
        started = time.monotonic()
        record = {"run": index, "project": services.project, "started_at": now()}
        try:
            with services as endpoints:
                record["endpoints_opened"] = bool(endpoints.get("database_url"))
            record["ok"] = True
        except Exception as exc:
            record["ok"] = False
            record["error"] = type(exc).__name__ + ": " + re.sub(r"\s+", " ", str(exc))[:200]
        record["seconds"] = round(time.monotonic() - started, 2)
        record["finished_at"] = now()
        print(f"{label} harness {index}/{runs} ok={record['ok']}", flush=True)
        records.append(record)
    receipts = []
    for path in sorted(Path(artifacts.root).rglob("*.txt")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if body.get("status") == "services_ready":
            receipts.append({"project": body["project"], "readiness": body.get("readiness")})
    return {"runs": records, "readiness_receipts": receipts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cycles", type=int, default=CYCLES_PER_CONDITION,
                        help="runs per condition; the plan is fixed before the first run")
    parser.add_argument("--through-harness", type=int, default=0,
                        help="instead of raw cycles, bring this many stacks up through VerificationServices")
    args = parser.parse_args(argv)

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    if args.through_harness:
        report = {"label": args.label, "started_at": now(), "platform": sys.platform,
                  "plan": {"through_harness_runs": args.through_harness,
                           "note": "fixed before the first run; every run is recorded"},
                  **through_harness(out, args.label, args.through_harness)}
        report["finished_at"] = now()
        path = out / f"{args.label}-readiness-after-fix.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("written:", path)
        return 0
    root = Path(ROOT / ".probe")
    root.mkdir(exist_ok=True)

    report = {"label": args.label, "started_at": now(), "platform": sys.platform,
              "plan": {"cycles_per_condition": args.cycles, "conditions": list(CONDITIONS),
                       "note": "fixed before the first run; every attempt is recorded, including passes"},
              "docker": run_process(["docker", "version", "--format", "{{.Server.Version}}"],
                                    timeout=60).stdout.strip(),
              "cycles": []}
    try:
        for condition in CONDITIONS:
            for index in range(1, args.cycles + 1):
                if condition == "after_teardown" and report["cycles"]:
                    # No pause: this condition is "immediately after another project went down".
                    report["cycles"][-1]["followed_by_immediate_start"] = True
                cycle = Cycle(root, condition, index)
                print(f"{args.label} {condition} {index}/{args.cycles} {cycle.project}", flush=True)
                report["cycles"].append(cycle.run())
                if condition == "standalone":
                    time.sleep(3)  # let the previous project settle, so this condition is standalone
    finally:
        report["finished_at"] = now()
        report["summary"] = summarise(report["cycles"])
        path = out / f"{args.label}-readiness-probe.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            root.rmdir()
        except OSError:
            pass
        print(json.dumps(report["summary"], ensure_ascii=False))
        print("written:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
