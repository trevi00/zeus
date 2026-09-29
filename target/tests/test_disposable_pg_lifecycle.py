"""S0 SF-1 synthetic controls for compare/run.py DisposablePostgres (no Docker, no PostgreSQL).

Layer: rebuild guardrail tests. A fake `docker` models containers by id/name/labels, so each control
proves the fixture's owned-cleanup contract: cleanup on readiness timeout, on log-read failure and on
normal exit; an explicit error when removal fails; and no removal of a same-name container it did not
start. Primary errors are preserved; cleanup uncertainty is attached as a note.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("s0_compare_run", ROOT / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN = _load()


class FakeDocker:
    def __init__(self, *, ready=True, logs_raise=False, rm_fails=False, preexisting_name=None):
        self.containers = {}
        self.ready, self.logs_raise, self.rm_fails = ready, logs_raise, rm_fails
        self.calls = []
        if preexisting_name:
            self.containers["foreign"] = {"name": preexisting_name, "labels": set()}

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        ok = lambda out="": subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        if args[0] == "ps":
            flt = args[args.index("--filter") + 1]
            if flt.startswith("label="):
                ids = [cid for cid, c in self.containers.items() if flt[6:] in c["labels"]]
            else:
                name = flt[len("name=^/"):-1]
                ids = [cid for cid, c in self.containers.items() if c["name"] == name]
            return ok("\n".join(ids))
        if args[0] == "run":
            labels = {args[i + 1] for i, a in enumerate(args) if a == "--label"}
            name = args[args.index("--name") + 1]
            self.containers["cid-1"] = {"name": name, "labels": labels}
            return ok("cid-1\n")
        if args[0] == "logs":
            if self.logs_raise:
                raise OSError("log read failed")
            return ok("PostgreSQL init process complete\nready to accept connections\n" if self.ready else "")
        if args[0] == "rm":
            if self.rm_fails:
                return subprocess.CompletedProcess(args, 1, "", "daemon error")
            self.containers.pop(args[-1], None)
            return ok()
        raise AssertionError(f"unexpected docker call {args}")


def _fixture(fake, monkeypatch, tmp_path, clock=None):
    fx = RUN.DisposablePostgres.__new__(RUN.DisposablePostgres)
    fx.socket, fx.name, fx.container_id = tmp_path / "s", "zeus-w0-rebuild-s0-pg-1", ""
    fx.owner, fx.env, fx.dsn = "zeus.rebuild.owner=test-1", {}, ""
    fx.docker = fake
    if clock is not None:
        monkeypatch.setattr(RUN.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(RUN.time, "sleep", lambda s: None)
    return fx


def test_positive_start_ready_and_normal_exit_removes_owned_container(monkeypatch, tmp_path):
    fake = FakeDocker()
    with _fixture(fake, monkeypatch, tmp_path):
        assert "cid-1" in fake.containers
    assert fake.containers == {}


def test_readiness_timeout_cleans_up_and_preserves_primary_error(monkeypatch, tmp_path):
    fake = FakeDocker(ready=False)
    fx = _fixture(fake, monkeypatch, tmp_path, clock=iter([0, 121, 121, 121]))
    with pytest.raises(RuntimeError, match="did not become ready"):
        with fx:
            pass
    assert fake.containers == {}


def test_log_read_exception_cleans_up_and_preserves_primary_error(monkeypatch, tmp_path):
    fake = FakeDocker(logs_raise=True)
    with pytest.raises(OSError, match="log read failed"):
        with _fixture(fake, monkeypatch, tmp_path):
            pass
    assert fake.containers == {}


def test_removal_failure_on_normal_exit_is_explicit(monkeypatch, tmp_path):
    fake = FakeDocker(rm_fails=True)
    with pytest.raises(RUN.FixtureCleanupError):
        with _fixture(fake, monkeypatch, tmp_path):
            pass


def test_removal_failure_during_body_error_keeps_body_error_with_note(monkeypatch, tmp_path):
    fake = FakeDocker(rm_fails=True)
    with pytest.raises(ValueError) as info:
        with _fixture(fake, monkeypatch, tmp_path):
            raise ValueError("body")
    assert any("cleanup:" in note for note in getattr(info.value, "__notes__", []))


def test_removal_failure_during_startup_error_keeps_startup_error_with_note(monkeypatch, tmp_path):
    fake = FakeDocker(ready=False, rm_fails=True)
    fx = _fixture(fake, monkeypatch, tmp_path, clock=iter([0, 121, 121, 121]))
    with pytest.raises(RuntimeError, match="did not become ready") as info:
        with fx:
            pass
    assert any("cleanup:" in note for note in getattr(info.value, "__notes__", []))


def test_same_name_foreign_container_is_never_removed(monkeypatch, tmp_path):
    fake = FakeDocker(preexisting_name="zeus-w0-rebuild-s0-pg-1")
    with pytest.raises(RuntimeError, match="name is taken"):
        with _fixture(fake, monkeypatch, tmp_path):
            pass
    assert "foreign" in fake.containers
    assert not any(c[0] == "rm" and c[-1] == "foreign" for c in fake.calls)
