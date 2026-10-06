import os
from pathlib import Path

import pytest

from codex_harness.adapters.configuration import (
    codex_auth,
    compose_environment,
    initialize,
    read_env,
    repository_root,
    runtime_dir,
)
from codex_harness.bootstrap import database_url, redis_url


def test_explicit_repository_resolves_config_from_another_directory(tmp_path, monkeypatch):
    root = tmp_path / "한글 path"
    root.mkdir()
    (root / ".env").write_text(
        'export HARNESS_DATABASE_URL="postgresql://user:pass@localhost/db" # local\n'
        "HARNESS_REDIS_URL='redis://localhost:123/1'\nHARNESS_RUNTIME_DIR=state\n",
        encoding="utf-8-sig")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_REPOSITORY", str(root))
    for name in ("HARNESS_DATABASE_URL", "HARNESS_REDIS_URL", "HARNESS_RUNTIME_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert repository_root() == root
    assert database_url() == "postgresql://user:pass@localhost/db"
    assert redis_url() == "redis://localhost:123/1"
    assert runtime_dir() == root / "state"
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://override/db")
    assert database_url() == "postgresql://override/db"
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", str(tmp_path / "isolated"))
    assert runtime_dir() == tmp_path / "isolated"


def test_auth_uses_codex_home_without_userprofile_and_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("HARNESS_CODEX_AUTH", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex 한글"))
    assert codex_auth() == tmp_path / "codex 한글/auth.json"
    monkeypatch.setenv("HARNESS_CODEX_AUTH", "secrets/auth.json")
    assert codex_auth() == tmp_path / "secrets/auth.json"
    assert compose_environment()["HARNESS_CODEX_AUTH"] == codex_auth().as_posix()


def test_setup_is_exclusive_and_does_not_rotate_password(tmp_path):
    assert initialize(tmp_path)["env_created"]
    original = (tmp_path / ".env").read_bytes()
    assert not initialize(tmp_path)["env_created"]
    assert (tmp_path / ".env").read_bytes() == original
    env = read_env(tmp_path)
    assert env["POSTGRES_PASSWORD"] in env["HARNESS_DATABASE_URL"]
    if os.name != "nt":
        assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_invalid_env_does_not_echo_credential(tmp_path):
    (tmp_path / ".env").write_text('SECRET="private-value', encoding="utf-8")
    with pytest.raises(ValueError, match="line 1") as error:
        read_env(tmp_path)
    assert "private-value" not in str(error.value)


def test_runtime_paths_resolve_at_call_time(tmp_path, monkeypatch):
    for name in ("first", "second"):
        monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path / name))
        monkeypatch.delenv("HARNESS_RUNTIME_DIR", raising=False)
        assert runtime_dir() == Path(tmp_path / name / ".runtime")
