"""S1 synthetic controls for compare/run.py DisposableRedis (no Docker, no Redis).

The Redis fixture shares the PostgreSQL fixture's owner-label lifecycle (S0 SF-1): every docker argv
it issues passes the real default-deny guard, a started container is removed on exit and proven
absent, a same-name foreign container is never removed, and Docker 29's lowercase "no such object"
reads as absence (the S1 fix of the ownership lookup).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("s1_compare_run", ROOT / "compare" / "run.py")
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)
GUARD = RUN.provider_guard


class FakeDocker:
    def __init__(self, bind_root: Path, *, foreign=False, lowercase=True):
        self.env = {GUARD.DOCKER_OPT_IN_ENV: "1", GUARD.DOCKER_BIND_ROOT_ENV: str(bind_root)}
        self.by_name, self.calls, self.lowercase = {}, [], lowercase
        self.foreign = foreign

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        GUARD.docker_policy(["docker", *args], self.env)
        name = args[-1] if args[0] != "run" else args[args.index("--name") + 1]
        ok = lambda out="": subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        if self.foreign and name not in self.by_name:
            self.by_name[name] = "someone-else"
        if args[0] == "inspect":
            if name not in self.by_name:
                text = "Error: no such object: " if self.lowercase else "Error: No such object: "
                return subprocess.CompletedProcess(args, 1, "", text + name)
            return ok(self.by_name[name] + "\n")
        if args[0] == "run":
            labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            self.by_name[name] = next(lab.split("=", 1)[1] for lab in labels if lab.startswith(RUN.OWNER_KEY + "="))
            return ok("cid\n")
        if args[0] == "logs":
            return ok("* Ready to accept connections unix\n")
        if args[0] == "rm":
            self.by_name.pop(name, None)
            return ok()
        raise AssertionError(args)


@pytest.mark.parametrize("lowercase", [True, False])
def test_start_uses_guard_admitted_forms_and_exit_removes_the_owned_container(tmp_path, monkeypatch, lowercase):
    fixture = RUN.DisposableRedis(tmp_path)
    fake = FakeDocker(tmp_path, lowercase=lowercase)
    monkeypatch.setattr(fixture, "docker", fake)
    with fixture as started:
        assert started.url == f"unix://{tmp_path / 'redis-socket'}/redis.sock?db=0"
        run = next(c for c in fake.calls if c[0] == "run")
        assert run[run.index("--network") + 1] == "none" and RUN.REDIS_IMAGE in run
        assert "--save" in run and "--port" in run and run[run.index("--port") + 1] == "0"
    assert fixture.name not in fake.by_name
    assert [c[0] for c in fake.calls][-2:] == ["rm", "inspect"]


def test_a_foreign_container_with_the_name_is_refused_and_never_removed(tmp_path, monkeypatch):
    fixture = RUN.DisposableRedis(tmp_path)
    fake = FakeDocker(tmp_path, foreign=True)
    monkeypatch.setattr(fixture, "docker", fake)
    with pytest.raises(RuntimeError, match="taken or unverifiable"):
        with fixture:
            pass
    assert fake.by_name[fixture.name] == "someone-else"
    assert not any(c[0] == "rm" for c in fake.calls)


def test_the_redis_image_is_an_exact_default_fixture_image():
    assert RUN.REDIS_IMAGE in GUARD.DEFAULT_FIXTURE_IMAGES
    with pytest.raises(GUARD.DockerRefused):
        GUARD.docker_policy(["docker", "run", "--network", "none", "--label", GUARD.FIXTURE_LABEL, "--name",
                             GUARD.FIXTURE_NAME_PREFIX + "x", "redis:latest"], {GUARD.DOCKER_OPT_IN_ENV: "1"})
