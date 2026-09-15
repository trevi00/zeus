"""Disposable PostgreSQL/Redis for incumbent and candidate release tests."""
import json
import os
import re
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import python_channel_environment, run_process
from codex_harness.domain.model import ContractError, canonical, digest, require, utcnow

# A deadline that has already been missed gets one more bounded chance to take the attempt back.
# It is not part of the readiness deadline and never extends it; it only bounds the taking back.
RECLAIM_SECONDS = 5.0
# How many attempts this object may still own without having reclaimed them before it refuses to
# start more. Repetition must not be able to grow threads and sockets without limit.
UNRECLAIMED_LIMIT = 3

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
        # Attempts this object started, could not take back, and therefore still owns.
        self.unreclaimed = []

    def _command(self, *args, timeout=150):
        env = {key: value for key, value in os.environ.items()
               if key.upper() in ENVIRONMENT_KEYS or key in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG"}}
        env["ZEUS_VERIFY_PASSWORD"] = self.password
        result = run_process(["docker", "compose", "--project-name", self.project,
                              "--file", str(self.directory / "compose.json"), *args],
                             cwd=str(self.directory), env=env, timeout=max(1, int(timeout)))
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
            # where the published port already accepts TCP and PostgreSQL still refuses the session.
            # In 3 of 12 WSL starts the healthcheck was *observed* green before the first observed
            # answer; the probe polls health and then requests in turn, so that ordering does not
            # establish that the server could not have answered at the health moment. What it does
            # establish is that an open socket is not an answer. So ready is neither "healthy" nor
            # "the socket opened": it is this service answering a real request, inside the deadline,
            # and being the service this project started.
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
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=min(2.0, remaining)):
                    return True
            except OSError as exc:
                kind = self._refusal_kind(exc)
                refusals[kind] = refusals.get(kind, 0) + 1
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)

    def _bounded(self, work, seconds):
        """Run one attempt, come back inside `seconds`, and take back what the attempt opened.

        Coming back is not the same as letting go. A worker thread cannot be cancelled from outside,
        and `daemon=True` only says it will not hold the interpreter open at exit - it does not end a
        thread sitting in `recv`. Abandoning it leaves a thread and a live socket behind, and a
        deadline that is hit repeatedly leaves one of each every time.

        So the attempt registers what it opens as it opens it, and when the deadline passes this
        closes those things. Closing the socket is what actually ends the blocked call, and the
        thread then finishes on its own. That is checked here rather than assumed: the worker is
        joined again inside a separate, named reclaim window.

        What cannot be reclaimed is not forgotten. It is counted, described, and it limits how many
        further attempts may be started, so repetition cannot grow this without bound.
        """
        resources, outcome = [], {}

        def attempt():
            try:
                outcome["value"] = work(resources.append)
            except BaseException as exc:  # carried as a value, never re-raised into the caller
                outcome["error"] = exc

        if len(self.unreclaimed) >= UNRECLAIMED_LIMIT:
            raise ContractError(
                f"{len(self.unreclaimed)} earlier attempts for project {self.project} could not be "
                f"reclaimed; refusing to start another. Recover by ending this process; the stack "
                f"itself is removed by the usual teardown.")
        worker = threading.Thread(target=attempt, daemon=True,
                                  name=f"verification-attempt-{self.project[-8:]}")
        worker.start()
        worker.join(max(0.0, seconds))
        if not worker.is_alive():
            if "error" in outcome:
                raise outcome["error"]
            return outcome["value"]

        closed = self._close_all(resources)
        worker.join(RECLAIM_SECONDS)
        if worker.is_alive():
            # Still holding on. Ownership stays here as a recorded fact with a recovery path, and
            # the count is what stops a repeated deadline from piling these up silently.
            self.unreclaimed.append({"thread": worker.name, "resources": len(resources),
                                     "closed": closed, "reclaim_seconds": RECLAIM_SECONDS,
                                     "recovery": "ends when this process ends; the stack is removed "
                                                 "by teardown independently of it"})
        raise TimeoutError("the attempt did not finish within its share of the deadline")

    @staticmethod
    def _close_all(resources):
        """Close what the attempt opened, in the order most likely to release a blocked call."""
        closed = 0
        for resource in list(resources):
            for name in ("cancel", "close", "terminate", "kill"):
                action = getattr(resource, name, None)
                if action is None:
                    continue
                try:
                    action()
                    closed += 1
                except Exception:
                    continue
                if name in ("close", "terminate", "kill"):
                    break
        return closed

    def _answer(self, service, port, seconds, register=None):
        """One real request, and the service's own identity in the reply. Raises on any refusal.

        Whatever is opened is handed to `register` the moment it exists, so a deadline elsewhere can
        close it. A connection this call never registers is a connection nobody can take back.
        """
        register = register if register is not None else (lambda resource: None)
        if service == "postgres":
            import psycopg

            dsn = f"postgresql://zeus:{self.password}@127.0.0.1:{port}/zeus"
            bound = max(1, int(seconds * 1000))
            connection = psycopg.connect(dsn, connect_timeout=max(1, int(seconds)),
                                         options=f"-c statement_timeout={bound}")
            register(connection)
            try:
                identity = connection.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
            finally:
                connection.close()
            return str(identity)
        import redis

        client = redis.Redis(host="127.0.0.1", port=port, socket_timeout=max(0.5, seconds),
                             socket_connect_timeout=max(0.5, seconds))
        register(client)
        try:
            client.ping()
            return str(client.info("server").get("run_id"))
        finally:
            client.close()

    def _container_identity(self, service, seconds):
        """The same identity asked of the container this project started, over docker rather than TCP.

        The published port is chosen by the daemon and ports get reused. Asking both sides and
        requiring the same answer is what makes "the service is up" mean "our service is up". This
        lookup spends the deadline it shares with everything else; it does not get one of its own.
        """
        if service == "postgres":
            value = self._command("exec", "-T", "postgres", "psql", "-U", "zeus", "-d", "zeus",
                                  "-tAc", "select system_identifier from pg_control_system()",
                                  timeout=seconds)
            return value.strip()
        info = self._command("exec", "-T", "redis", "redis-cli", "info", "server", timeout=seconds)
        for line in info.splitlines():
            if line.startswith("run_id:"):
                return line.split(":", 1)[1].strip()
        return ""

    def _refuse(self, summary, refusals):
        """The only thing that leaves here: a summary, and counts by kind.

        `raise ... from exc` would keep the original on the exception chain, and a traceback prints
        the chain. The provider's own words - which is where a credential would be if one ever got
        into one - stay out of it, so the refusal is built from the classification alone and the
        chain is suppressed.
        """
        raise ContractError(f"{summary}; refusals: {canonical(refusals)}") from None

    def _await_service(self, service, port, deadline_seconds=30.0):
        """Ready means this service answered us inside the deadline, and it is the one we started.

        One deadline covers every stage - the socket, the authentication, the query, receiving the
        result, and asking the container the same question over docker. No stage gets a fresh bound,
        and an answer that arrives after the deadline is not a ready that arrived late: it is a
        failure with a named reason.
        """
        started = time.monotonic()
        deadline = started + deadline_seconds
        refusals = {}
        if not self._await_tcp(port, deadline, refusals):
            self._refuse(f"Verification endpoint 127.0.0.1:{port} for {service} never accepted a "
                         f"connection within {deadline_seconds}s", refusals)
        tcp_after = round(time.monotonic() - started, 2)
        identity = None
        while identity is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._refuse(f"Verification service {service} on 127.0.0.1:{port} accepted a connection "
                             f"but did not answer within {deadline_seconds}s", refusals)
            try:
                identity = self._bounded(
                    lambda register: self._answer(service, port, remaining, register), remaining)
            except BaseException as exc:
                kind = self._refusal_kind(exc)
                refusals[kind] = refusals.get(kind, 0) + 1
                if time.monotonic() >= deadline:
                    self._refuse(f"Verification service {service} on 127.0.0.1:{port} accepted a connection "
                                 f"but did not answer within {deadline_seconds}s", refusals)
                time.sleep(0.1)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # The answer itself was late. Ready is about being usable in time, not about eventually.
            self._refuse(f"Verification service {service} on 127.0.0.1:{port} answered after its "
                         f"{deadline_seconds}s deadline had passed", refusals)
        try:
            # `run_process` bounds and kills its own child, so this attempt has nothing of its own
            # to register; the thread ends when the subprocess does.
            expected = self._bounded(lambda register: self._container_identity(service, remaining),
                                     remaining)
        except BaseException as exc:
            kind = self._refusal_kind(exc)
            refusals[kind] = refusals.get(kind, 0) + 1
            self._refuse(f"The container identity for {service} could not be read within the "
                         f"{deadline_seconds}s deadline", refusals)
        if not identity or identity != expected:
            self._refuse(f"The service answering 127.0.0.1:{port} is not this project's {service}",
                         refusals)
        return {"tcp_after": tcp_after, "ready_after": round(time.monotonic() - started, 2),
                "identity": identity, "refusals_during_startup": refusals,
                "readiness_deadline_seconds": deadline_seconds,
                "reclaim_deadline_seconds": RECLAIM_SECONDS,
                "unreclaimed_attempts": list(self.unreclaimed),
                "note": "ready is a real answer from the container this project started, inside one "
                        "readiness deadline covering every stage; the reclaim deadline is separate "
                        "and only bounds taking back an attempt that already missed the first one"}

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
