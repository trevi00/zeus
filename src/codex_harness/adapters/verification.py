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
# It is not part of the readiness deadline and never extends it; it only bounds the taking back -
# and it covers the closing as well as the waiting, because a close can hang too.
RECLAIM_SECONDS = 5.0
# How many attempts may be owed across this whole process before another is refused. A stack is one
# object and a run makes many, so a per-object count would reset with every new stack and bound
# nothing; this is the number that has to hold.
UNRECLAIMED_LIMIT = 3


# What a resource's own state says. "I could not find out" is a third answer, and it is not closed.
CLOSED, OPEN, UNKNOWN = "closed", "open", "unknown"

# Where an attempt is. A reservation is not a finished attempt, and a running attempt is not a
# candidate for reclamation just because it has not finished yet.
RESERVED, RUNNING, WORKER_FINISHED = "reserved", "running", "worker_finished"
CANCELLED, RELEASED = "cancelled", "released"
RECLAIMABLE = (WORKER_FINISHED, CANCELLED)


class _RedisHandle:
    """A redis client wrapped so that closing it leaves a signal this code can actually read.

    `redis.Redis` has no attribute that says whether it is shut, so the fact being recorded here is
    a narrow and explicit one: this close path ran to completion for this type. It is not a general
    "assume closed when there is nothing to check" - a resource with nothing to check stays UNKNOWN.
    """

    def __init__(self, client):
        self.client = client
        self.closed = False

    def close(self):
        self.client.close()
        self.closed = True


def _state_of(resource):
    """CLOSED, OPEN, or UNKNOWN - asked of the resource, by type, with no fallback to optimism."""
    if isinstance(resource, socket.socket):
        try:
            return CLOSED if resource.fileno() == -1 else OPEN
        except Exception:
            return UNKNOWN          # the question failed; that is not an answer of "closed"
    flag = getattr(resource, "closed", None)
    if isinstance(flag, bool):
        return CLOSED if flag else OPEN
    if isinstance(flag, int):
        return CLOSED if flag else OPEN     # psycopg reports its connection state as a flag
    return UNKNOWN


class _Held:
    """One resource an attempt opened, and what its own state says about it.

    Calling `close` and having it return is not the same fact as the resource being shut, and a
    failure to ask is not the same as an answer. `attempts` counts what was tried; `state` carries
    what could be established.
    """

    def __init__(self, resource):
        self.resource = resource
        self.attempts = 0
        self.error = None
        self.state = _state_of(resource)

    @property
    def closed(self):
        return self.state == CLOSED

    def confirm(self):
        """Look again, without calling anything that could block."""
        if self.state != CLOSED:
            self.state = _state_of(self.resource)
        return self.closed

    def shut(self):
        """Try to close, then look. A failure or an unreadable state keeps the resource."""
        if self.closed:
            return True
        self.attempts += 1
        for name in ("cancel", "close", "terminate", "kill"):
            action = getattr(self.resource, name, None)
            if action is None:
                continue
            try:
                action()
            except Exception as exc:
                self.error = type(exc).__name__
                continue
            if name in ("close", "terminate", "kill"):
                break
        return self.confirm()

    def report(self):
        return {"state": self.state, "close_attempts": self.attempts, "error": self.error,
                "kind": type(self.resource).__name__}


class _Attempt:
    """One piece of work, the resources it opened, and where it is between reserved and released."""

    def __init__(self, identifier, name, work):
        self.id = identifier
        self.lock = threading.Lock()
        self.held = []
        self.state = RESERVED
        self.worker_done = False
        self.outcome = {}
        self.reclaimer = None
        self.thread = threading.Thread(target=self._run, args=(work,), daemon=True,
                                       name=f"verification-attempt-{name}-{identifier}")

    def _run(self, work):
        try:
            self.outcome["value"] = work(self.register)
        except BaseException as exc:  # carried as a value, never re-raised into the caller
            self.outcome["error"] = exc
        finally:
            # The worker says so itself. Nobody infers it from `is_alive`, which is also false for a
            # thread that has not started yet.
            with self.lock:
                self.worker_done = True
                if self.state == RUNNING:
                    self.state = WORKER_FINISHED

    # ---- moving between states ---------------------------------------------------------------------
    def running(self):
        with self.lock:
            if self.state == RESERVED:
                self.state = WORKER_FINISHED if self.worker_done else RUNNING

    def cancel(self):
        with self.lock:
            self.state = CANCELLED

    # ---- running and registering -----------------------------------------------------------------
    def register(self, resource):
        """Take ownership of something the attempt opened, whenever it opens it."""
        with self.lock:
            held = _Held(resource)
            self.held.append(held)
            cancelled = self.state == CANCELLED
        if cancelled:
            held.shut()   # it arrived to an attempt already being taken back; take it back now

    def wait(self, seconds):
        self.thread.join(max(0.0, seconds))
        with self.lock:
            return self.worker_done

    def result(self):
        if "error" in self.outcome:
            raise self.outcome["error"]
        return self.outcome.get("value")

    # ---- being taken back ------------------------------------------------------------------------
    def sweep(self):
        with self.lock:
            pending = [held for held in self.held if not held.closed]
        for held in pending:
            held.shut()

    def take_back(self, deadline):
        """Cancel, then keep sweeping while the worker lives, and once more after it ends."""
        self.cancel()
        while True:
            self.sweep()
            self.thread.join(0.05)
            with self.lock:
                done = self.worker_done
            if done:
                self.sweep()
                return
            if time.monotonic() >= deadline:
                return

    def begin_reclaim(self, seconds):
        """Start taking this attempt back, on a thread of its own. One live reclaimer per slot."""
        deadline = time.monotonic() + seconds
        self.reclaimer = threading.Thread(target=self.take_back, args=(deadline,), daemon=True,
                                          name=f"verification-reclaim-{self.id}")
        self.reclaimer.start()
        return self.reclaimer

    # ---- what is still owed ------------------------------------------------------------------------
    def reclaimable(self):
        """Only an attempt whose worker is done, or one that was cancelled, may be swept."""
        with self.lock:
            return self.state in RECLAIMABLE

    def settled(self):
        """Released only from a state that allows it, and only when nothing is still owed.

        A reservation is never settled: its thread has not started, so `is_alive` is false for a
        reason that has nothing to do with being finished. A running attempt is never settled
        either; it is simply not finished.
        """
        with self.lock:
            if self.state in (RESERVED, RUNNING):
                return False
            if self.state == RELEASED:
                return True
            if not self.worker_done:
                return False
            pending = list(self.held)
        if self.reclaimer is not None and self.reclaimer.is_alive():
            return False
        return all(held.confirm() for held in pending)

    def record(self):
        with self.lock:
            state = self.state
            resources = [held.report() for held in self.held]
        outstanding = [row for row in resources if row["state"] != CLOSED]
        return {"attempt": self.id, "state": state, "thread": self.thread.name,
                "worker_finished": self.worker_done,
                "reclaim_thread": self.reclaimer.name if self.reclaimer else None,
                "reclaim_thread_finished": self.reclaimer is None or not self.reclaimer.is_alive(),
                "closed": sum(1 for row in resources if row["state"] == CLOSED),
                "resources_still_held": len(outstanding),
                "resources": resources,
                "reclaimed": self.settled(),
                "reclaim_deadline_seconds": RECLAIM_SECONDS,
                "recovery": "this process still holds it; sweeping continues as later attempts "
                            "start, and it ends when the process ends. The compose stack is removed "
                            "by its own teardown regardless."}


class _Attempts:
    """Every attempt this process started, from before its worker exists until it owes nothing."""

    def __init__(self):
        self.lock = threading.Lock()
        self.slots = {}
        self.started = 0

    def start(self, work, name):
        with self.lock:
            self._collect()
            if len(self.slots) >= UNRECLAIMED_LIMIT:
                raise ContractError(
                    f"{len(self.slots)} attempts in this process are still owned "
                    f"({sorted(self.slots)}); refusing to start another. They end when this process "
                    f"ends; each compose stack is removed by its own teardown regardless.")
            self.started += 1
            attempt = _Attempt(f"a{self.started:04d}", name, work)
            self.slots[attempt.id] = attempt       # RESERVED: held before the worker exists
        try:
            attempt.thread.start()
        except BaseException:
            attempt.state = RELEASED               # the worker never existed; the slot goes back
            with self.lock:
                self.slots.pop(attempt.id, None)
            raise
        attempt.running()
        return attempt

    def finish(self, attempt):
        """The worker returned. Confirming is cheap; closing is not, so it is left to a reclaimer."""
        with self.lock:
            self._collect()

    def reclaim(self, attempt, seconds):
        """Wait, inside one window, for the cancelling, the closing and the worker together."""
        attempt.begin_reclaim(seconds).join(max(0.0, seconds))
        report = attempt.record()
        with self.lock:
            self._collect()
            report["owed_in_process"] = len(self.slots)
        return report

    def _collect(self):
        """Release what owes nothing, and keep taking back what still does. Call under the lock.

        Reserved and running attempts are left alone. They belong to whoever started them, and the
        only things that may move them are that caller's own deadline and the worker's own ending.
        Nothing here closes anything either: a close can block, and this runs on whichever thread
        happened to start the next attempt.
        """
        for identifier, attempt in list(self.slots.items()):
            if not attempt.reclaimable():
                continue                      # reserved or running: not this thread's business
            if attempt.settled():
                del self.slots[identifier]
                continue
            if attempt.reclaimer is None or not attempt.reclaimer.is_alive():
                attempt.begin_reclaim(RECLAIM_SECONDS)

    def sweep(self):
        with self.lock:
            self._collect()

    def outstanding(self):
        with self.lock:
            self._collect()
            return [attempt.record() for attempt in self.slots.values()]


ATTEMPTS = _Attempts()

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
        """Run one attempt, come back inside `seconds`, and leave nothing unowned behind.

        Coming back is not the same as letting go, and letting go is not the same as taking back.
        This reserves a slot from the process-wide owner, runs the attempt, and on a missed deadline
        hands it to that owner to reclaim inside a separate window. What cannot be reclaimed stays
        recorded there - with the ids, what was closed, and how it ends - and counts against every
        later attempt in this process, not just the ones this object makes.
        """
        attempt = ATTEMPTS.start(work, f"{self.project[-8:]}")
        finished = attempt.wait(max(0.0, seconds))
        if finished:
            # It came back on its own. What it opened is still closed and confirmed before the slot
            # is released, because a worker returning says nothing about its connection.
            try:
                return attempt.result()
            finally:
                ATTEMPTS.finish(attempt)
        report = ATTEMPTS.reclaim(attempt, RECLAIM_SECONDS)
        if not report["reclaimed"]:
            # Recorded where a reader will find it, on the failing path as well as the passing one.
            self.artifacts.put(canonical({"project": self.project, "status": "attempt_unreclaimed",
                                          **report}), "verification-unreclaimed")
        raise TimeoutError("the attempt did not finish within its share of the deadline")

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
        handle = _RedisHandle(client)
        register(handle)
        try:
            client.ping()
            return str(client.info("server").get("run_id"))
        finally:
            handle.close()

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
                "unreclaimed_attempts": ATTEMPTS.outstanding(),
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
