import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, verification_environment


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
# up`. On WSL the container healthcheck went green inside that window in 3 of 12 starts, so neither
# `up --wait` nor an open socket can stand in for the service being able to answer.


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
            services._await_service("postgres", port, deadline_seconds=0.6)
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
    monkeypatch.setattr(VerificationServices, "_container_identity", lambda self, service: "our-service")

    def answer(self, service, port_):
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
    monkeypatch.setattr(VerificationServices, "_answer", lambda self, service, port_: "somebody-elses")
    monkeypatch.setattr(VerificationServices, "_container_identity", lambda self, service: "ours")
    try:
        with pytest.raises(ContractError, match="not this project's postgres"):
            services._await_service("postgres", port, deadline_seconds=5)
    finally:
        stop.set()
        thread.join(3)


def test_readiness_binds_the_receipt_to_what_answered(tmp_path, monkeypatch):
    """The stored receipt says how long each service took and which instance answered."""
    monkeypatch.setattr(VerificationServices, "_answer", lambda self, service, port_: "identity-" + service)
    monkeypatch.setattr(VerificationServices, "_container_identity", lambda self, service: "identity-" + service)
    services = VerificationServices(tmp_path / "verification", FileArtifacts(tmp_path / "artifacts"))
    port, stop, thread = listener("close_immediately")
    try:
        report = services._await_service("redis", port, deadline_seconds=5)
    finally:
        stop.set()
        thread.join(3)
    assert report["identity"] == "identity-redis"
    assert set(report) >= {"tcp_after", "ready_after", "identity", "refusals_during_startup", "note"}
