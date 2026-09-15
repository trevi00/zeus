"""Disposable PostgreSQL/Redis for incumbent and candidate release tests."""
import json
import os
import re
import secrets
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import python_channel_environment, run_process
from codex_harness.domain.model import ContractError, canonical, digest, require, utcnow

ENVIRONMENT_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "UV_CACHE_DIR",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "ALLUSERSPROFILE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}


def verification_environment(endpoints, environ=None):
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key.upper() in ENVIRONMENT_KEYS}
    # INV-RELEASE-001: old incumbent tests mutate HARNESS_*; remove inherited Zeus aliases.
    env.update(HARNESS_INTEGRATION="1", HARNESS_DATABASE_URL=endpoints["database_url"],
               HARNESS_REDIS_URL=endpoints["redis_url"], HARNESS_REDIS_NAMESPACE="zeus-verification")
    # INV-ENCODING-001: release pytest is a Python child; the allowlist above already dropped
    # any inherited PYTHONIOENCODING/PYTHONUTF8, so the channel is bound here explicitly.
    return python_channel_environment(env)


class VerificationServices:
    def __init__(self, root, artifacts):
        self.root = Path(root).resolve()
        self.artifacts = artifacts
        self.project = "zeus-verify-" + uuid4().hex
        self.directory = self.root / self.project
        self.password = secrets.token_hex(24)

    def _command(self, *args):
        env = {key: value for key, value in os.environ.items()
               if key.upper() in ENVIRONMENT_KEYS or key in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"}}
        env["ZEUS_VERIFY_PASSWORD"] = self.password
        result = run_process(["docker", "compose", "--project-name", self.project,
                              "--file", str(self.directory / "compose.json"), *args],
                             cwd=str(self.directory), env=env, timeout=150)
        if result.returncode:
            raise RuntimeError("Isolated verification services unavailable: " + args[0])
        return result.stdout.strip()

    def __enter__(self):
        self.directory.mkdir(parents=True)
        spec = {"services": {
            "postgres": {"image": "pgvector/pgvector:pg17", "environment": {
                "POSTGRES_USER": "zeus", "POSTGRES_DB": "zeus", "POSTGRES_PASSWORD": "${ZEUS_VERIFY_PASSWORD}"},
                "ports": ["127.0.0.1::5432"], "volumes": ["database:/var/lib/postgresql/data"],
                "mem_limit": "512m", "cpus": 1,
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U zeus -d zeus"],
                                "interval": "1s", "timeout": "3s", "retries": 60}},
            "redis": {"image": "redis:7.4-alpine", "ports": ["127.0.0.1::6379"],
                "command": ["redis-server", "--appendonly", "no"], "mem_limit": "128m", "cpus": 0.5,
                "healthcheck": {"test": ["CMD", "redis-cli", "ping"],
                                "interval": "1s", "timeout": "3s", "retries": 60}}},
            "volumes": {"database": {}}}
        (self.directory / "compose.json").write_text(canonical(spec), encoding="utf-8")
        (self.directory / "manifest.json").write_text(canonical({"project": self.project,
            "created_at": utcnow(), "definition_hash": digest(spec)}), encoding="utf-8")
        try:
            self._command("up", "-d", "--wait")
            ports = {}
            for service, port in (("postgres", "5432"), ("redis", "6379")):
                value = self._command("port", service, port)
                match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", value)
                require(match is not None and 0 < int(match[1]) < 65536, "Unknown verification endpoint")
                ports[service] = int(match[1])
            # `up --wait` reports the container healthchecks, and a healthcheck is not the same claim
            # as "this service can answer me". Measured over 24 stacks on two hosts (the probe and
            # its records are in docs/zeus/evidence/readiness-004): every single start has a window
            # where the published port already accepts TCP and PostgreSQL still refuses the session,
            # and on WSL the healthcheck went green *inside* that window in 3 of 12 starts. So ready
            # is neither "healthy" nor "the socket opened": it is this service answering a real
            # request, and being the service this project started.
            readiness = {service: self._await_service(service, port) for service, port in ports.items()}
            self.artifacts.put(canonical({"project": self.project, "ports": ports,
                "ready_after_seconds": {name: row["ready_after"] for name, row in readiness.items()},
                "readiness": readiness, "status": "services_ready",
                "definition_hash": digest(spec)}), "verification-services")
            return {"database_url": f'postgresql://zeus:{self.password}@127.0.0.1:{ports["postgres"]}/zeus',
                    "redis_url": f'redis://127.0.0.1:{ports["redis"]}/0'}
        except BaseException:
            self._cleanup_observed()
            raise

    @staticmethod
    def _refusal_kind(error):
        """Name a refusal without carrying the text that produced it; no credential travels here."""
        message = str(error).lower()
        if "starting up" in message:
            return "starting_up"          # the server took the session and said it cannot serve yet
        if "closed the connection" in message or "connection reset" in message:
            return "closed_unexpectedly"  # the session was accepted and then dropped
        if "refused" in message:
            return "refused"              # nothing is listening on the published port yet
        if "timeout" in message or "timed out" in message:
            return "timed_out"
        return "other"

    def _await_tcp(self, port, deadline, refusals):
        """The socket opening. Necessary, and on its own not evidence of anything else."""
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                    return True
            except OSError as exc:
                refusals[self._refusal_kind(exc)] = refusals.get(self._refusal_kind(exc), 0) + 1
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)

    def _answer(self, service, port):
        """One real request, and the service's own identity in the reply. Raises on any refusal."""
        if service == "postgres":
            import psycopg

            dsn = f"postgresql://zeus:{self.password}@127.0.0.1:{port}/zeus"
            with psycopg.connect(dsn, connect_timeout=3) as connection:
                identity = connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
            return str(identity)
        import redis

        client = redis.Redis(host="127.0.0.1", port=port, socket_timeout=3)
        try:
            client.ping()
            return str(client.info("server").get("run_id"))
        finally:
            client.close()

    def _container_identity(self, service):
        """The same identity asked of the container this project started, over docker rather than TCP.

        The published port is chosen by the daemon and ports get reused. Asking both sides and
        requiring the same answer is what makes "the service is up" mean "our service is up".
        """
        if service == "postgres":
            value = self._command("exec", "-T", "postgres", "psql", "-U", "zeus", "-d", "zeus",
                                  "-tAc", "select system_identifier from pg_control_system()")
            return value.strip()
        info = self._command("exec", "-T", "redis", "redis-cli", "info", "server")
        for line in info.splitlines():
            if line.startswith("run_id:"):
                return line.split(":", 1)[1].strip()
        return ""

    def _await_service(self, service, port, deadline_seconds=30.0):
        """Ready means this service answered us, and it is the one this project started.

        The bound is unchanged. What is bounded is stronger: a stack that opens a port and then
        cannot serve inside the deadline is a failure with a named reason, not a stack that is
        called ready because a socket connected.
        """
        started = time.monotonic()
        deadline = started + deadline_seconds
        refusals = {}
        tcp_after = None
        if not self._await_tcp(port, deadline, refusals):
            raise ContractError(f"Verification endpoint 127.0.0.1:{port} for {service} never accepted a "
                                f"connection within {deadline_seconds}s; refusals: {canonical(refusals)}")
        tcp_after = round(time.monotonic() - started, 2)
        while True:
            try:
                identity = self._answer(service, port)
                break
            except Exception as exc:
                kind = self._refusal_kind(exc)
                refusals[kind] = refusals.get(kind, 0) + 1
                if time.monotonic() >= deadline:
                    raise ContractError(
                        f"Verification service {service} on 127.0.0.1:{port} accepted a connection but did "
                        f"not answer within {deadline_seconds}s; refusals: {canonical(refusals)}") from exc
                time.sleep(0.1)
        expected = self._container_identity(service)
        require(bool(identity) and identity == expected,
                f"The service answering 127.0.0.1:{port} is not this project's {service}")
        return {"tcp_after": tcp_after, "ready_after": round(time.monotonic() - started, 2),
                "identity": identity, "refusals_during_startup": refusals,
                "note": "ready is a real answer from the container this project started, not an open socket"}

    def _cleanup(self):
        self._command("down", "--volumes", "--remove-orphans", "--timeout", "10")
        self.artifacts.put(canonical({"project": self.project, "status": "services_removed"}), "verification-cleanup")
        # Only this generated directory's two known files are removed. No recursive path deletion.
        require(self.directory.resolve().parent == self.root and not self.directory.is_symlink(),
                "Verification directory escaped managed root")
        for name in ("compose.json", "manifest.json"):
            (self.directory / name).unlink()
        self.directory.rmdir()

    def __exit__(self, *args):
        self._cleanup_observed()

    def _cleanup_observed(self):
        try:
            self._cleanup()
            return None
        except Exception as exc:
            # INV-VERIFICATION-001: preserve the primary outcome and leave the manifest for retry.
            failure = {"project": self.project, "status": "cleanup_failed", "error_type": type(exc).__name__}
            self.artifacts.put(canonical(failure), "verification-cleanup")
            return failure

    @classmethod
    def collect_stale(cls, root, artifacts, max_age=7200):
        root = Path(root).resolve()
        removed, failures = [], []
        for path in root.glob("zeus-verify-*/manifest.json"):
            if path.is_symlink() or path.parent.is_symlink():
                continue
            try:
                metadata = json.loads(path.read_text("utf-8"))
                project = path.parent.name
                require(re.fullmatch(r"zeus-verify-[0-9a-f]{32}", project)
                        and metadata["project"] == project, "Unknown verification stack")
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(metadata["created_at"])).total_seconds()
                if age < max_age:
                    continue
                definition = path.parent / "compose.json"
                require(not definition.is_symlink() and digest(json.loads(definition.read_text("utf-8")))
                        == metadata["definition_hash"], "Verification definition changed")
                service = cls(root, artifacts)
                service.project, service.directory = project, path.parent
                failure = service._cleanup_observed()
                if failure:
                    failures.append(failure)
                else:
                    removed.append(project)
            except Exception as exc:
                failure = {"project": path.parent.name, "status": "cleanup_blocked", "error_type": type(exc).__name__}
                artifacts.put(canonical(failure), "verification-cleanup")
                failures.append(failure)
        return {"removed": removed, **({"failures": failures} if failures else {})}
