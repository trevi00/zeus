"""S7 move-aheads (DESIGN-s7 adapters-move §7/§8): GitSource (host_os), read_blob/BacklogRefused (intake) and
settings (composition), moved verbatim ahead of their slices by A/evidence/rebuild/s7/move-aheads/transcribe.py.

The M7 comparison of GitSource executes M7's own class text, cut out of the SOURCE checkout named by
ZEUS_REBUILD_SOURCE_ROOT (never imported: the reference tree is not importable here, R-O). Without it only the
M7-documented shapes are asserted.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _layout import REPO

from codex_harness.composition import configuration
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.git_source import GitSource
from codex_harness.host_os.ports import GitBlobSource
from codex_harness.intake.adapters.backlog_blobs import REGULAR_BLOB, read_blob
from codex_harness.intake.domain.backlog import BacklogRefused
from codex_harness.kernel.errors import ContractError

sys.path.insert(0, str(REPO / "compare" / "drivers" / "common"))
from s7_host_targets import pinned_environment, pinned_git  # noqa: E402

M7_ROOT = os.environ.get("ZEUS_REBUILD_SOURCE_ROOT")


def m7_git_source():
    """M7's `GitSource` class, executed from its own text in the SOURCE checkout (None when it is not given)."""
    if not M7_ROOT:
        return None
    path = Path(M7_ROOT) / "src" / "codex_harness" / "adapters" / "operation_cli.py"
    text = path.read_text(encoding="utf-8")
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == "GitSource")
    scope = {"subprocess": subprocess, "no_console_kwargs": lambda: {}}
    exec(compile(ast.Module([node], []), str(path), "exec"), scope)  # noqa: S102
    return scope["GitSource"]


@pytest.fixture(scope="module")
def pinned(tmp_path_factory):
    base = tmp_path_factory.mktemp("move-aheads")
    env = pinned_environment(base)
    repo = base / "repo"
    repo.mkdir()
    pinned_git(repo, env, "init", "-q", "-b", "main")
    (repo / "plan.json").write_bytes(b'{"a": 1}\n')
    (repo / "dir").mkdir()
    (repo / "dir" / "inner.txt").write_bytes(b"x")
    pinned_git(repo, env, "add", "-A")
    pinned_git(repo, env, "commit", "-q", "-m", "one")
    return repo, pinned_git(repo, env, "rev-parse", "HEAD")


CASES = [("regular", "plan.json"), ("directory", "dir"), ("missing", "absent.txt")]


def test_git_source_is_a_git_blob_source_and_matches_the_documented_shapes(pinned):
    repo, rev = pinned
    source: GitBlobSource = GitSource(repo)
    assert source.commit_exists(rev) is True
    assert source.commit_exists("0" * 40) is False
    assert source.blob(rev, "plan.json") == ("100644", b'{"a": 1}\n')
    mode, listing = source.blob(rev, "dir")   # M7: a tree is shown as its listing, with mode 040000
    assert mode == "040000" and listing.startswith(b"tree ") and b"inner.txt" in listing
    assert source.blob(rev, "absent.txt") == (None, b"")
    assert source.blob("not-a-revision", "plan.json") == (None, b"")


def test_git_source_equals_m7_git_source_when_the_source_checkout_is_given(pinned):
    m7 = m7_git_source()
    if m7 is None:
        pytest.skip("ZEUS_REBUILD_SOURCE_ROOT not set: only the M7-documented shapes are asserted")
    repo, rev = pinned
    ours, theirs = GitSource(repo), m7(repo)
    for revision in (rev, "0" * 40, "not-a-revision"):
        assert ours.commit_exists(revision) == theirs.commit_exists(revision)
        for _, path in CASES:
            assert ours.blob(revision, path) == theirs.blob(revision, path)


def test_git_source_spawns_only_through_the_chokepoint_run(pinned, monkeypatch):
    repo, rev = pinned
    calls = []
    real = process_groups.run

    def spy(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return real(argv, **kwargs)

    monkeypatch.setattr(process_groups, "run", spy)
    announced = []
    with process_groups.observe_spawns(announced.append):
        assert GitSource(repo).commit_exists(rev) is True
    # M7 `subprocess.run` never announced a pid and `process_groups.run` does not either: same observer shape.
    assert announced == []
    assert calls == [(["git", "-C", str(repo), "cat-file", "-e", rev + "^{commit}"],
                      {"capture_output": True, "timeout": 60, **process_groups.no_console_kwargs()})]


class Fake:
    def __init__(self, exists=True, mode="100644", data=b"0123456789"):
        self.exists, self.mode, self.data = exists, mode, data

    def commit_exists(self, revision):
        return self.exists

    def blob(self, revision, path):
        return self.mode, self.data


@pytest.mark.parametrize("fake,code", [
    (Fake(exists=False), "plan_revision_missing"),
    (Fake(mode=None, data=b""), "plan_missing_at_revision"),
    (Fake(mode="040000", data=b""), "plan_not_regular"),
    (Fake(data=b"x" * 20), "plan_too_large"),
])
def test_read_blob_refusals(fake, code):
    with pytest.raises(BacklogRefused) as raised:
        read_blob(fake, "r" * 40, "p", 10, "plan")
    assert raised.value.reason_code == code
    assert isinstance(raised.value, ContractError)
    assert str(raised.value) == "fleet backlog refused: " + code


def test_read_blob_pass_over_a_real_git_source(pinned):
    repo, rev = pinned
    assert REGULAR_BLOB == "100644"
    assert read_blob(GitSource(repo), rev, "plan.json", 10, "plan") == b'{"a": 1}\n'
    with pytest.raises(BacklogRefused, match="plan_too_large"):
        read_blob(GitSource(repo), rev, "plan.json", 3, "plan")
    with pytest.raises(BacklogRefused, match="plan_not_regular"):
        read_blob(GitSource(repo), rev, "dir", 10, "plan")


def test_backlog_refused_names_a_field_when_given():
    assert str(BacklogRefused("bad", "name")) == "fleet backlog refused: bad (name)"
    assert BacklogRefused("bad", "name").field == "name"


def test_settings_layers_the_environment_over_a_labelled_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "﻿# labelled move-aheads fixture\nexport HARNESS_ONLY=h\nZEUS_BOTH=file\nHARNESS_BOTH=other\n"
        "QUOTED=\"a # b\"\nPLAIN=v  # note\n", encoding="utf-8")
    for name in [k for k in os.environ if k.startswith(("ZEUS_", "HARNESS_"))]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("ZEUS_REPOSITORY", str(tmp_path))
    monkeypatch.setenv("HARNESS_ENV_ONLY", "env")
    monkeypatch.setenv("ZEUS_BOTH", "environment")
    assert configuration.repository_root() == tmp_path.resolve()
    assert configuration.read_env()["QUOTED"] == "a # b"
    assert configuration.read_env()["PLAIN"] == "v"
    merged = configuration.settings()
    assert merged["ZEUS_ONLY"] == merged["HARNESS_ONLY"] == "h"   # alias of the dotenv's HARNESS_ONLY
    assert merged["ZEUS_BOTH"] == merged["HARNESS_BOTH"] == "environment"
    assert merged["ZEUS_ENV_ONLY"] == merged["HARNESS_ENV_ONLY"] == "env"
    assert configuration.aliases({"ZEUS_X": "z", "HARNESS_X": "h"}) == {"ZEUS_X": "z", "HARNESS_X": "z"}


def test_read_env_refuses_an_invalid_assignment(tmp_path):
    (tmp_path / ".env").write_text("not an assignment\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 1"):
        configuration.read_env(tmp_path)
    assert configuration.read_env(tmp_path / "missing") == {}
