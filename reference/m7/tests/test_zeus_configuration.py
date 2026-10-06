from pathlib import Path

import pytest

from codex_harness import cli
from codex_harness.adapters.configuration import (
    compose_environment,
    initialize,
    read_env,
    repository_root,
    select_repository,
    settings,
)


@pytest.mark.parametrize("file_prefix,env_prefix", [(a, b) for a in ("ZEUS", "HARNESS") for b in ("ZEUS", "HARNESS")])
def test_process_layer_wins_over_file_alias(tmp_path, monkeypatch, file_prefix, env_prefix):
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path))
    monkeypatch.delenv("ZEUS_REPOSITORY", raising=False)
    for prefix in ("ZEUS", "HARNESS"):
        monkeypatch.delenv(prefix + "_REDIS_URL", raising=False)
    (tmp_path / ".env").write_text(file_prefix + "_REDIS_URL=redis://file/0\n", encoding="utf-8")
    monkeypatch.setenv(env_prefix + "_REDIS_URL", "redis://process/0")
    config = settings()
    assert config["ZEUS_REDIS_URL"] == config["HARNESS_REDIS_URL"] == "redis://process/0"


def test_zeus_wins_within_layer_and_cli_override_wins_both(tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path / "zeus"))
    monkeypatch.setenv("HARNESS_REPOSITORY", str(tmp_path / "old"))
    assert repository_root() == tmp_path / "zeus"
    select_repository(tmp_path)
    assert repository_root() == tmp_path
    assert settings()["ZEUS_REPOSITORY"] == settings()["HARNESS_REPOSITORY"]
    monkeypatch.setenv("ZEUS_RUNTIME_DIR", "한글 state")
    monkeypatch.setenv("HARNESS_RUNTIME_DIR", "wrong")
    env = compose_environment()
    assert Path(env["ZEUS_RUNTIME_DIR"]) == tmp_path / "한글 state"
    assert env["ZEUS_RUNTIME_DIR"] == env["HARNESS_RUNTIME_DIR"]


@pytest.mark.parametrize("name", ["zeus-harness", "codex-self-harness"])
def test_root_discovery_accepts_both_distribution_names(tmp_path, monkeypatch, name):
    root = tmp_path / name
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = '" + name + "'\n", encoding="utf-8")
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.delenv("ZEUS_REPOSITORY", raising=False)
    monkeypatch.delenv("HARNESS_REPOSITORY", raising=False)
    assert repository_root() == root


def test_fresh_zeus_identity_and_existing_env_bytes_are_preserved(tmp_path):
    initialize(tmp_path)
    fresh = read_env(tmp_path)
    assert fresh["COMPOSE_PROJECT_NAME"] == fresh["ZEUS_REDIS_NAMESPACE"] == "zeus"
    old = b"POSTGRES_PASSWORD=existing\nHARNESS_REDIS_URL=redis://existing/0\n"
    (tmp_path / ".env").write_bytes(old)
    initialize(tmp_path)
    assert (tmp_path / ".env").read_bytes() == old


def test_paths_and_ticket_commands_are_available_without_renaming_legacy_imports():
    assert cli.parser().parse_args(["paths"]).command == "paths"
    assert cli.parser().parse_args(["ticket", "sync", "ZEUS-example", "--repo", "owner/repo", "--preview"]).preview
