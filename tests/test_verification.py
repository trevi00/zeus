import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import (
    ATTEMPTS,
    VerificationServices,
    verification_environment,
)


@pytest.fixture(autouse=True)
def fresh_attempt_registry():
    """The owner is process-wide by design, so each check starts from a known state."""
    from codex_harness.adapters.verification import ATTEMPTS

    ATTEMPTS.slots.clear()
    yield
    ATTEMPTS.slots.clear()


@pytest.fixture(autouse=True)
def fake_endpoint_probe(request, monkeypatch):
    """Faked compose stacks publish ports nobody listens on; only the real disposable stack test probes them."""
    if not any(marker in request.node.name for marker in ('real_disposable', 'readiness', 'ready_')):
        monkeypatch.setattr(VerificationServices, '_await_service',
                            lambda self, service, port, deadline_seconds=30.0: {
                                "tcp_after": 0.0, "ready_after": 0.0, "identity": "fixture",
                                "refusals_during_startup": {}})


def test_verification_environment_cannot_inherit_production_endpoints():
    env = verification_environment({"database_url": "isolated-db", "redis_url": "isolated-redis"},
        {"ZEUS_DATABASE_URL": "production", "HARNESS_DATABASE_URL": "production",
         "ZEUS_REPOSITORY": "production-path", "PYTHONPATH": "production-python",
         "GH_TOKEN": "secret", "PATH": "executables", "SYSTEMROOT": "windows",
         "PYTHONIOENCODING": "cp949", "PYTHONUTF8": "0"})
    assert env["HARNESS_DATABASE_URL"] == "isolated-db"
    assert env["HARNESS_REDIS_URL"] == "isolated-redis"
    assert env["HARNESS_INTEGRATION"] == "1"
    assert env["PATH"] == "executables" and env["SYSTEMROOT"] == "windows"
    assert not any(k.startswith("ZEUS_") for k in env)
    assert not {"GH_TOKEN", "PYTHONPATH", "PYTHONUTF8"} & env.keys()
    # INV-ENCODING-001: the release pytest channel is bound regardless of the operator's locale.
    assert env["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.parametrize("failure", [None, "up", "port", "tests"])
def test_isolated_services_cleanup_on_every_exit(tmp_path, monkeypatch, failure):
    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    calls = []
    def command(*args):
        calls.append(args)
        assert services.password not in (services.directory / "compose.json").read_text("utf-8")
        if args[0] == failure:
            raise RuntimeError("fixture unavailable")
        return "127.0.0.1:45678" if args[0] == "port" else ""
    monkeypatch.setattr(services, "_command", command)
    def execute():
        with services as endpoints:
            assert "127.0.0.1:45678" in endpoints["database_url"]
            spec = json.loads((services.directory / "compose.json").read_text("utf-8"))
            assert spec["services"]["postgres"]["volumes"] == ["database:/var/lib/postgresql/data"]
            if failure == "tests":
                raise RuntimeError("fixture tests failed")
    if failure:
        with pytest.raises(RuntimeError):
            execute()
    else:
        execute()
    assert calls[-1] == ("down", "--volumes", "--remove-orphans", "--timeout", "10")
    assert not services.directory.exists()


def test_stale_cleanup_requires_unchanged_definition_and_leaves_fresh_stack(tmp_path, monkeypatch):
    artifacts = FileArtifacts(tmp_path / "artifacts")
    service = VerificationServices(tmp_path / "verification", artifacts)
    monkeypatch.setattr(VerificationServices, "_command", lambda *args: "127.0.0.1:45678")
    service.__enter__()
    assert VerificationServices.collect_stale(service.root, artifacts) == {"removed": []}
    manifest = service.directory / "manifest.json"
    metadata = json.loads(manifest.read_text("utf-8"))
    metadata["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    manifest.write_text(json.dumps(metadata), encoding="utf-8")
    definition = service.directory / "compose.json"
    original = definition.read_text("utf-8")
    definition.write_text('{}', encoding="utf-8")
    result = VerificationServices.collect_stale(service.root, artifacts)
    assert result["removed"] == [] and result["failures"][0]["status"] == "cleanup_blocked"
    assert service.directory.exists()
    definition.write_text(original, encoding="utf-8")
    assert VerificationServices.collect_stale(service.root, artifacts) == {"removed": [service.project]}
    assert not service.directory.exists()


def test_docker_command_uses_generated_project_and_filtered_environment(tmp_path, monkeypatch):
    service = VerificationServices(tmp_path, FileArtifacts(tmp_path / "artifacts"))
    monkeypatch.setenv("ZEUS_DATABASE_URL", "production")
    def run(argv, **kwargs):
        assert argv[3] == service.project
        assert kwargs["cwd"] == str(service.directory)
        assert "ZEUS_DATABASE_URL" not in kwargs["env"]
        assert kwargs["env"]["ZEUS_VERIFY_PASSWORD"] == service.password
        return SimpleNamespace(returncode=0, stdout="ok")
    monkeypatch.setattr("codex_harness.adapters.verification.run_process", run)
    assert service._command("up", "-d") == "ok"


def test_cleanup_failure_preserves_primary_error_and_is_retryable(tmp_path, monkeypatch):
    artifacts = FileArtifacts(tmp_path / "artifacts")
    service = VerificationServices(tmp_path / "verification", artifacts)
    def fail(*args):
        raise RuntimeError("primary startup error" if args[0] == "up" else "secondary cleanup error")
    monkeypatch.setattr(service, "_command", fail)
    with pytest.raises(RuntimeError, match="primary startup error"):
        service.__enter__()
    assert (service.directory / "manifest.json").exists()
    monkeypatch.setattr(VerificationServices, "_command", lambda *args: "")
    result = VerificationServices.collect_stale(service.root, artifacts, max_age=0)
    assert result["removed"] == [service.project]


def test_invalid_manifest_does_not_block_other_stack_cleanup(tmp_path, monkeypatch):
    artifacts = FileArtifacts(tmp_path / "artifacts")
    service = VerificationServices(tmp_path / "verification", artifacts)
    monkeypatch.setattr(VerificationServices, "_command", lambda *args: "127.0.0.1:45678")
    service.__enter__()
    invalid = service.root / ("zeus-verify-" + "0" * 32)
    invalid.mkdir()
    (invalid / "manifest.json").write_text("broken", encoding="utf-8")
    result = VerificationServices.collect_stale(service.root, artifacts, max_age=0)
    assert result["removed"] == [service.project] and len(result["failures"]) == 1
    assert invalid.exists() and not service.directory.exists()


@pytest.mark.skipif(os.environ.get("ZEUS_TEST_DOCKER") != "1", reason="Explicit disposable Docker validation required")
def test_real_disposable_database_and_redis_are_isolated_and_removed(tmp_path):
    import psycopg
    import redis

    from codex_harness.adapters.commands import run_process
    service = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    with service as endpoints:
        with psycopg.connect(endpoints["database_url"]) as connection:
            connection.execute("CREATE TABLE isolation_probe (value text)")
            connection.execute("INSERT INTO isolation_probe VALUES ('zeus')")
            assert connection.execute("SELECT value FROM isolation_probe").fetchone() == ("zeus",)
        client = redis.Redis.from_url(endpoints["redis_url"])
        try:
            assert client.dbsize() == 0
            client.set("isolation_probe", "zeus")
            assert client.get("isolation_probe") == b"zeus"
        finally:
            client.close()
    assert not service.directory.exists()
    result = run_process(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + service.project])
    assert result.returncode == 0 and not result.stdout.strip()
    result = run_process(["docker", "volume", "ls", "-q", "--filter", "label=com.docker.compose.project=" + service.project])
    assert result.returncode == 0 and not result.stdout.strip()


# ---- readiness: what "ready" is allowed to mean --------------------------------------------------
#
# Measured over 24 disposable stacks on two hosts (docs/zeus/evidence/readiness-004): every start has
# a window where the published port already accepts TCP and PostgreSQL still refuses the session -
# 43 refusals in 12 Windows starts, 144 in 12 WSL starts - and the refusals are the two symptoms CI
# recorded, `server closed the connection unexpectedly` and `FATAL: the database system is starting
# up`. On WSL the healthcheck was *observed* green before the first observed answer in 3 of 12
# starts; the probe polls health and then requests in turn, so that ordering is not evidence that
# the server could not have answered earlier. What the 24 starts do establish is that an open socket
# is not an answer, and that is the whole of what these checks rest on.


def listener(behaviour):
    """A real socket that accepts and then behaves as named, so the window can be reproduced here."""
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port = server.getsockname()[1]
    stop = threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                client, _ = server.accept()
            except OSError:
                continue
            if behaviour == "close_immediately":
                client.close()          # "server closed the connection unexpectedly"
            else:
                stop.wait(0.05)
                client.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, stop, thread


def test_readiness_refuses_a_port_that_accepts_and_cannot_answer(tmp_path):
    """The CI symptom, reproduced without Docker: the socket opens and the service never serves.

    Before this, readiness returned as soon as the connection was accepted, and the caller met the
    refusal instead - which is exactly what `test_host_interruption` met twice in CI.
    """
    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    try:
        with pytest.raises(ContractError, match="accepted a connection but did not answer"):
            services._await_service("postgres", port, deadline_seconds=1.0)
    finally:
        stop.set()
        thread.join(3)


def test_readiness_names_the_refusals_it_saw_without_quoting_them(tmp_path):
    """The two CI symptoms are told apart by name, and no credential travels with them."""
    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    assert services._refusal_kind(Exception("FATAL: the database system is starting up")) == "starting_up"
    assert services._refusal_kind(Exception("server closed the connection unexpectedly")) == "closed_unexpectedly"
    assert services._refusal_kind(ConnectionRefusedError("Connection refused")) == "refused"
    assert services._refusal_kind(TimeoutError("timed out")) == "timed_out"
    assert services._refusal_kind(Exception("something else")) == "other"

    from codex_harness.domain.model import ContractError

    port, stop, thread = listener("close_immediately")
    try:
        with pytest.raises(ContractError) as raised:
            # Long enough that the refusals are classified rather than the whole attempt being cut
            # short: the point here is the naming, not the bound.
            services._await_service("postgres", port, deadline_seconds=3.0)
    finally:
        stop.set()
        thread.join(3)
    message = str(raised.value)
    assert "closed_unexpectedly" in message, "the refusal is named"
    assert services.password not in message, "and the password is not in the refusal"


def test_readiness_still_refuses_a_port_that_never_accepts(tmp_path):
    """The WSL symptom is unchanged: nothing listening inside the bound is a bounded failure."""
    import socket

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    with pytest.raises(ContractError, match="never accepted a connection"):
        services._await_service("redis", port, deadline_seconds=0.5)


def test_readiness_waits_for_the_answer_rather_than_the_socket(tmp_path, monkeypatch):
    """Ready is reported when the service answers, not when the connection is accepted."""
    import time

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    answers_at = time.monotonic() + 0.5
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "our-service")

    def answer(self, service, port_, seconds=30, register=None):
        if time.monotonic() < answers_at:
            raise RuntimeError("FATAL: the database system is starting up")
        return "our-service"

    monkeypatch.setattr(VerificationServices, "_answer", answer)
    try:
        report = services._await_service("postgres", port, deadline_seconds=10)
    finally:
        stop.set()
        thread.join(3)

    assert report["ready_after"] >= 0.4, "ready waited for the answer, not the socket"
    assert report["tcp_after"] < report["ready_after"], "and the socket opened first, as it always does"
    assert report["refusals_during_startup"].get("starting_up"), "the window it waited through is recorded"
    assert report["identity"] == "our-service"


def test_readiness_refuses_a_service_that_is_not_this_projects(tmp_path, monkeypatch):
    """Published ports are chosen by the daemon and reused. Answering is not enough; it must be ours."""
    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    monkeypatch.setattr(VerificationServices, "_answer",
                        lambda self, service, port_, seconds=30, register=None: "somebody-elses")
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "ours")
    try:
        with pytest.raises(ContractError, match="not this project's postgres"):
            services._await_service("postgres", port, deadline_seconds=5)
    finally:
        stop.set()
        thread.join(3)


def test_readiness_binds_the_receipt_to_what_answered(tmp_path, monkeypatch):
    """The stored receipt says how long each service took and which instance answered."""
    monkeypatch.setattr(VerificationServices, "_answer",
                        lambda self, service, port_, seconds=30, register=None: "identity-" + service)
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "identity-" + service)
    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    try:
        report = services._await_service("redis", port, deadline_seconds=5)
    finally:
        stop.set()
        thread.join(3)
    assert report["identity"] == "identity-redis"
    assert set(report) >= {"tcp_after", "ready_after", "identity", "refusals_during_startup", "note"}


# ---- second review: the deadline covers every stage, and nothing rides back on the exception -----

def test_readiness_refuses_an_answer_that_arrives_after_the_deadline(tmp_path, monkeypatch):
    """A late answer is not a ready that arrived late. Codex's counterexample, inverted.

    The check used to look at the clock only after a refusal, so an answer returning past the
    deadline broke out of the loop and was accepted.
    """
    import time

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")

    def slow_answer(self, service, port_, seconds=30, register=None):
        time.sleep(0.3)
        return "our-service"

    monkeypatch.setattr(VerificationServices, "_answer", slow_answer)
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "our-service")
    try:
        with pytest.raises(ContractError, match="did not answer within"):
            services._await_service("postgres", port, deadline_seconds=0.05)
    finally:
        stop.set()
        thread.join(3)


def test_readiness_refuses_a_success_that_completed_past_the_deadline(tmp_path, monkeypatch):
    """The other half of the same rule, reached deterministically.

    Above, the attempt is abandoned at its bound. Here it is allowed to return - the bound is
    removed - and it still must not be accepted, because it finished after the deadline.
    """
    import time

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    # No bound, and the attempt registers nothing: the point here is a late return, not reclamation.
    monkeypatch.setattr(VerificationServices, "_bounded",
                        lambda self, work, seconds: work(lambda resource: None))

    def slow_but_successful(self, service, port_, seconds=30, register=None):
        time.sleep(0.3)
        return "our-service"

    monkeypatch.setattr(VerificationServices, "_answer", slow_but_successful)
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "our-service")
    try:
        with pytest.raises(ContractError, match="answered after its"):
            services._await_service("postgres", port, deadline_seconds=0.05)
    finally:
        stop.set()
        thread.join(3)


def test_readiness_returns_even_when_the_service_stops_answering(tmp_path, monkeypatch):
    """Accepted, authenticated, and then silent: the call still comes back inside its bound."""
    import threading
    import time

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    released = threading.Event()

    def never_answers(self, service, port_, seconds=30, register=None):
        released.wait(30)          # a server that took the session and then went quiet
        return "our-service"

    monkeypatch.setattr(VerificationServices, "_answer", never_answers)
    started = time.monotonic()
    try:
        with pytest.raises(ContractError, match="did not answer within"):
            services._await_service("postgres", port, deadline_seconds=0.5)
    finally:
        released.set()
        stop.set()
        thread.join(3)
    assert time.monotonic() - started < 10, "the wait was bounded, not held by the other end"


def test_readiness_refuses_when_the_container_identity_cannot_be_read_in_time(tmp_path, monkeypatch):
    """The docker lookup spends the same deadline; it does not get a fresh one of its own."""
    import time

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    monkeypatch.setattr(VerificationServices, "_answer",
                        lambda self, service, port_, seconds=30, register=None: "our-service")

    def slow_lookup(self, service, seconds=30):
        time.sleep(5)
        return "our-service"

    monkeypatch.setattr(VerificationServices, "_container_identity", slow_lookup)
    started = time.monotonic()
    try:
        with pytest.raises(ContractError, match="container identity"):
            services._await_service("postgres", port, deadline_seconds=1.0)
    finally:
        stop.set()
        thread.join(3)
    from codex_harness.adapters.verification import RECLAIM_SECONDS

    # The readiness deadline and the reclaim window are separate bounds, and the call is held by
    # their sum at most - never by the lookup's own five seconds of sleeping.
    assert time.monotonic() - started < 1.0 + RECLAIM_SECONDS + 2


def test_readiness_failure_carries_nothing_back_on_the_exception_chain(tmp_path, monkeypatch):
    """A traceback prints the chain, so the chain must not hold the provider's own words."""
    import traceback

    from codex_harness.domain.model import ContractError

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    sentinel = "SENTINEL-ORIGINAL-ERROR-TEXT-b4f1"

    def refuse(self, service, port_, seconds=30, register=None):
        raise RuntimeError("connection failed: " + sentinel)

    monkeypatch.setattr(VerificationServices, "_answer", refuse)
    try:
        with pytest.raises(ContractError) as raised:
            services._await_service("postgres", port, deadline_seconds=0.3)
    finally:
        stop.set()
        thread.join(3)

    rendered = "".join(traceback.format_exception(type(raised.value), raised.value,
                                                  raised.value.__traceback__))
    assert sentinel not in rendered, "the original text reached the traceback"
    assert services.password not in rendered
    assert "refusals" in str(raised.value), "what is reported is the classification and its count"


# ---- third review: a deadline that returns must also take back what it opened --------------------

def silent_listener():
    """A real socket that accepts a connection and then never says anything again."""
    import socket
    import threading

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    port = server.getsockname()[1]
    accepted, stop = [], threading.Event()

    def serve():
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                client, _ = server.accept()
            except OSError:
                continue
            accepted.append(client)      # held open, answering nothing
        for client in accepted:
            try:
                client.close()
            except OSError:
                pass
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, accepted, stop, thread


def test_a_timed_out_attempt_takes_back_its_thread_and_its_socket(tmp_path):
    """Codex's counterexample: three timeouts used to leave three live workers and three sockets.

    Returning to the caller is not the same as letting go. The attempt registers the socket it
    opened, the deadline closes it, and closing is what actually ends the blocked recv - which is
    checked here on the worker itself, not inferred from the return value.
    """
    import socket
    import threading

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, accepted, stop, thread = silent_listener()
    sockets, before = [], threading.active_count()
    try:
        def blocking_work(register):
            client = socket.create_connection(("127.0.0.1", port), timeout=5)
            sockets.append(client)
            register(client)
            client.recv(1)               # the other end never answers
            return "unreachable"

        for _ in range(3):
            with pytest.raises(TimeoutError):
                services._bounded(blocking_work, 0.1)

        assert len(sockets) == 3, "three real attempts were made"
        for client in sockets:
            assert client.fileno() == -1, "the socket the attempt opened was closed, not abandoned"
        assert ATTEMPTS.outstanding() == [], "every worker was taken back inside the reclaim window"
        deadline = time.monotonic() + 5
        while threading.active_count() > before and time.monotonic() < deadline:
            time.sleep(0.05)
        assert threading.active_count() <= before, "no worker thread outlived its attempt"
    finally:
        stop.set()
        thread.join(3)


def test_an_attempt_that_cannot_be_taken_back_is_counted_and_then_refused(tmp_path):
    """What cannot be reclaimed is not forgotten, and it limits how many more may be started."""
    import threading

    from codex_harness.adapters.verification import UNRECLAIMED_LIMIT
    from codex_harness.domain.model import ContractError

    released = threading.Event()

    def unreclaimable(register):
        released.wait(30)                # ignores every close; nothing to register
        return "late"

    try:
        for index in range(UNRECLAIMED_LIMIT):
            # A new object every time, exactly as a run of stacks makes one per stack. The count
            # that matters is the process's, so it must not start over with each of them.
            services = VerificationServices(tmp_path / f"verification-{index}",
                                            FileArtifacts(tmp_path / "artifacts"))
            with pytest.raises(TimeoutError):
                services._bounded(unreclaimable, 0.05)
            assert len(ATTEMPTS.outstanding()) == index + 1, "what is still held is counted"

        assert ATTEMPTS.outstanding()[0]["recovery"], "and it says how it ends"
        fresh = VerificationServices(tmp_path / "verification-next",
                                     FileArtifacts(tmp_path / "artifacts"))
        with pytest.raises(ContractError, match="refusing to start another"):
            fresh._bounded(unreclaimable, 0.05)
    finally:
        released.set()


def test_readiness_receipt_separates_the_two_deadlines_and_names_what_is_held(tmp_path, monkeypatch):
    """One deadline decides ready. The other only bounds taking back an attempt that missed it."""
    from codex_harness.adapters.verification import RECLAIM_SECONDS

    monkeypatch.setattr(VerificationServices, "_answer",
                        lambda self, service, port_, seconds=30, register=None: "ours")
    monkeypatch.setattr(VerificationServices, "_container_identity",
                        lambda self, service, seconds=30: "ours")
    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    try:
        report = services._await_service("postgres", port, deadline_seconds=5)
    finally:
        stop.set()
        thread.join(3)

    assert report["readiness_deadline_seconds"] == 5
    assert report["reclaim_deadline_seconds"] == RECLAIM_SECONDS
    assert report["unreclaimed_attempts"] == []
    assert "reclaim deadline is separate" in report["note"]


# ---- fourth review: one owner, one window over the closing too, and no gap in registration -------

class Hanging:
    """A resource whose `close` stops, the way a client's close is a call like any other."""

    def __init__(self, released):
        self.released = released
        self.closed = False

    def close(self):
        self.released.wait(30)
        self.closed = True


class Recorded:
    """A resource that only records that it was closed."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_the_unreclaimed_limit_is_the_processs_and_does_not_reset_with_a_new_object(tmp_path):
    """A run makes one object per stack, so a count kept on the object would bound nothing."""
    import threading

    from codex_harness.adapters.verification import UNRECLAIMED_LIMIT
    from codex_harness.domain.model import ContractError

    released = threading.Event()

    def unreclaimable(register):
        released.wait(30)
        return "late"

    try:
        for index in range(UNRECLAIMED_LIMIT):
            services = VerificationServices(tmp_path / f"stack-{index}",
                                            FileArtifacts(tmp_path / "artifacts"))
            with pytest.raises(TimeoutError):
                services._bounded(unreclaimable, 0.05)
        assert len(ATTEMPTS.outstanding()) == UNRECLAIMED_LIMIT

        # A brand new object, as the next stack would make. The debt is still owed.
        nextstack = VerificationServices(tmp_path / "stack-next", FileArtifacts(tmp_path / "artifacts"))
        with pytest.raises(ContractError, match="refusing to start another"):
            nextstack._bounded(unreclaimable, 0.05)
    finally:
        released.set()


def test_a_close_that_hangs_does_not_hold_the_caller(tmp_path):
    """The reclaim window covers the closing, not only the waiting that follows it."""
    import threading
    import time

    from codex_harness.adapters.verification import RECLAIM_SECONDS

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    released = threading.Event()
    hanging = Hanging(released)
    done = threading.Event()

    def work(register):
        register(hanging)
        done.wait(30)
        return "late"

    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            services._bounded(work, 0.02)
        elapsed = time.monotonic() - started
        assert elapsed < RECLAIM_SECONDS + 3, "the caller came back; the stuck close did not hold it"
        assert not hanging.closed, "the close really was stuck, so the counterexample reached it"
        held = ATTEMPTS.outstanding()
        assert held and held[0]["reclaim_thread_finished"] is False, "the stuck reclaim is recorded too"
        assert held[0]["recovery"]
    finally:
        released.set()
        done.set()


def test_a_resource_registered_after_reclamation_began_is_still_closed(tmp_path):
    """Registration and cancellation share a lock, so there is no gap after the sweep to fall into."""
    import threading

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    swept, late = threading.Event(), Recorded()
    first = Recorded()

    def work(register):
        register(first)
        swept.wait(10)          # released once the first sweep has taken its snapshot
        register(late)          # arrives after it
        return "done"

    original = Recorded.close

    def close_and_release(self):
        original(self)
        if self is first:
            swept.set()

    Recorded.close = close_and_release
    try:
        with pytest.raises(TimeoutError):
            services._bounded(work, 0.05)
    finally:
        Recorded.close = original

    assert first.closed, "the resource present at the sweep was closed"
    assert late.closed, "and so was the one that arrived after it"
    assert ATTEMPTS.outstanding() == [], "nothing was left owed"


# ---- fifth review: the state transitions, from reservation to release ----------------------------

class Stubborn:
    """A resource whose close always fails. Calling close is not the same as being shut."""

    def __init__(self, pair):
        self.pair = pair          # a real socketpair half, so "not shut" is a real fact
        self.attempts = 0

    def close(self):
        self.attempts += 1
        raise OSError("this resource refuses to close")

    def shut_for_real(self):
        self.pair.close()


def test_a_running_attempt_occupies_its_slot_before_its_worker_starts(tmp_path):
    """The limit has to count work that is still running, not only work already given up on."""
    import threading

    from codex_harness.adapters.verification import UNRECLAIMED_LIMIT
    from codex_harness.domain.model import ContractError

    released = threading.Event()

    def never_ends(register):
        released.wait(30)
        return "late"

    try:
        for index in range(UNRECLAIMED_LIMIT):
            services = VerificationServices(tmp_path / f"stack-{index}",
                                            FileArtifacts(tmp_path / "artifacts"))
            with pytest.raises(TimeoutError):
                services._bounded(never_ends, 0.05)
        assert len(ATTEMPTS.outstanding()) == UNRECLAIMED_LIMIT

        nextstack = VerificationServices(tmp_path / "stack-next", FileArtifacts(tmp_path / "artifacts"))
        with pytest.raises(ContractError, match="refusing to start another"):
            nextstack._bounded(never_ends, 0.05)
        assert len(ATTEMPTS.outstanding()) == UNRECLAIMED_LIMIT, "the refusal started nothing"
    finally:
        released.set()


def test_starting_reserves_the_slot_so_running_work_counts_against_the_limit():
    """Codex's counterexample, driven at the owner: four starts, and the fourth must be refused.

    Going through `_bounded` hides this, because a timeout records the attempt on the way out. The
    fault is in `start` itself: it checked a count that only unreclaimed work had ever been added
    to, so work that was still running was not in the denominator.
    """
    import threading

    from codex_harness.adapters.verification import UNRECLAIMED_LIMIT
    from codex_harness.domain.model import ContractError

    released = threading.Event()

    def never_ends(register):
        released.wait(30)
        return "late"

    started = []
    try:
        for _ in range(UNRECLAIMED_LIMIT):
            started.append(ATTEMPTS.start(never_ends, "reserve"))
        assert all(attempt.thread.is_alive() for attempt in started), "all of them are running"

        with pytest.raises(ContractError, match="refusing to start another"):
            ATTEMPTS.start(never_ends, "reserve")
        assert len(ATTEMPTS.slots) == UNRECLAIMED_LIMIT, "and nothing extra was started"
    finally:
        released.set()
        for attempt in started:
            attempt.thread.join(5)


def test_a_resource_that_will_not_close_is_kept_and_the_attempt_stays_owed(tmp_path):
    """Codex's counterexample: a close that fails used to drop the resource and read as reclaimed."""
    import socket
    import threading
    import time

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    left, right = socket.socketpair()
    stubborn = Stubborn(left)
    hold = threading.Event()

    def work(register):
        register(stubborn)
        hold.wait(30)            # long enough to miss the deadline; the worker itself is fine
        return "done"

    try:
        with pytest.raises(TimeoutError):
            services._bounded(work, 0.05)
        hold.set()               # the worker ends; only the resource refuses to close

        deadline = time.monotonic() + 5
        while stubborn.attempts == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        held = ATTEMPTS.outstanding()
        assert held, "an attempt whose resource would not close is still owed"
        [record] = held
        assert record["reclaimed"] is False
        assert record["resources_still_held"] == 1, "the resource is kept, not dropped"
        assert record["resources"][0]["state"] != "closed", "closing failed, so it is not closed"
        assert record["resources"][0]["error"] == "OSError"
        assert record["resources"][0]["close_attempts"] >= 1, "closing was tried, and did not work"
        assert left.fileno() != -1, "and the socket really is still open"
    finally:
        hold.set()
        stubborn.shut_for_real()
        left.close()
        right.close()


def test_a_resource_registered_after_the_reclaim_window_is_still_taken_back(tmp_path):
    """The window bounds the caller's wait. It does not end ownership."""
    import threading
    import time

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    window_over, keep_running = threading.Event(), threading.Event()
    late = Recorded()

    def work(register):
        window_over.wait(30)     # registers only after the caller has given up waiting
        register(late)
        keep_running.wait(30)
        return "late"

    try:
        with pytest.raises(TimeoutError):
            services._bounded(work, 0.05)
        assert ATTEMPTS.outstanding(), "the attempt is still owned after the window"

        window_over.set()
        deadline = time.monotonic() + 10
        while not late.closed and time.monotonic() < deadline:
            ATTEMPTS.sweep()     # as a later attempt starting would
            time.sleep(0.05)
        assert late.closed, "a resource registered after the window was still taken back"
    finally:
        window_over.set()
        keep_running.set()


def test_a_slot_is_released_only_when_everything_it_owns_is_finished(tmp_path):
    """Normal completion: the worker ends, what it opened is shut, and the slot goes back."""
    import socket

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    left, right = socket.socketpair()

    def work(register):
        register(left)
        left.close()             # the ordinary path closes what it opened
        return "answered"

    try:
        assert services._bounded(work, 5) == "answered"
        assert ATTEMPTS.outstanding() == [], "the slot went back once nothing was owed"
        assert left.fileno() == -1
    finally:
        right.close()


# ---- sixth review: reserved is not finished, running is not reclaimable, unknown is not closed ----

class Unreadable:
    """A resource that refuses both to close and to say whether it is closed."""

    def __init__(self, pair):
        self.pair = pair
        self.asked = 0

    def fileno(self):
        self.asked += 1
        raise OSError("this resource will not say")

    def close(self):
        raise OSError("this resource will not close")

    def shut_for_real(self):
        self.pair.close()


def test_starting_one_attempt_does_not_reclaim_another_that_is_still_running(tmp_path):
    """Codex's counterexample: B's start used to cancel A and close A's resources.

    Collection ran on whichever thread started the next attempt and swept anything not yet settled -
    and a healthy, running attempt is not settled, it is simply not finished.
    """
    import threading

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    holding, finish = Recorded(), threading.Event()
    started = []

    def slow(register):
        register(holding)
        finish.wait(30)
        return "done"

    def quick(register):
        return "done"

    try:
        started.append(ATTEMPTS.start(slow, "A"))
        deadline = time.monotonic() + 5
        while not started[0].held and time.monotonic() < deadline:
            time.sleep(0.02)

        assert services._bounded(quick, 5) == "done", "B runs normally"

        assert not holding.closed, "A's resource was not closed by B starting"
        assert started[0].state == "running", "and A is still running, not cancelled"
    finally:
        finish.set()
        started[0].thread.join(5)
        ATTEMPTS.sweep()


def test_a_reservation_is_not_mistaken_for_a_finished_attempt(tmp_path):
    """A thread that has not started is not alive, and that is not the same as being done."""
    from codex_harness.adapters.verification import _Attempt

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    reserved = _Attempt("a-test", "reserve", lambda register: "done")
    try:
        assert reserved.state == "reserved"
        assert reserved.settled() is False, "a reservation is never collectable"
        assert reserved.reclaimable() is False, "and it is never swept"

        ATTEMPTS.slots[reserved.id] = reserved
        ATTEMPTS.sweep()
        assert reserved.id in ATTEMPTS.slots, "so collection cannot delete it"

        # And a run started beside it still works, with the reservation left alone.
        assert services._bounded(lambda register: "beside", 5) == "beside"
        assert reserved.id in ATTEMPTS.slots
    finally:
        ATTEMPTS.slots.pop(reserved.id, None)


def test_a_resource_that_cannot_say_whether_it_is_shut_is_not_called_closed(tmp_path):
    """Codex's counterexample: a failed `fileno` used to read as evidence of being closed."""
    import socket
    import threading

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    left, right = socket.socketpair()
    unreadable = Unreadable(left)
    hold = threading.Event()

    def work(register):
        register(unreadable)
        hold.wait(30)
        return "done"

    try:
        with pytest.raises(TimeoutError):
            services._bounded(work, 0.05)
        hold.set()

        deadline = time.monotonic() + 5
        while unreadable.asked == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        held = ATTEMPTS.outstanding()
        assert held, "an attempt whose resource cannot be read is still owed"
        [record] = held
        assert record["resources"][0]["state"] == "unknown", "not knowing is its own answer"
        assert record["reclaimed"] is False
        assert left.fileno() != -1, "and the socket really is still open"
    finally:
        hold.set()
        unreadable.shut_for_real()
        right.close()


def test_a_resource_with_a_readable_state_still_releases_its_slot(tmp_path):
    """The contrast: something that can say it is shut is believed, and the slot goes back."""
    import socket

    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    left, right = socket.socketpair()

    def work(register):
        register(left)
        left.close()
        return "answered"

    try:
        assert services._bounded(work, 5) == "answered"
        assert ATTEMPTS.outstanding() == []
    finally:
        right.close()
