import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.verification import VerificationServices, verification_environment


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
