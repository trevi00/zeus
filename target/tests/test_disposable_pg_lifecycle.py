"""S0 SF-1 synthetic controls for compare/run.py DisposablePostgres (no Docker, no PostgreSQL).

Layer: rebuild guardrail tests. A fake `docker` models containers by name and owner label, so each
control proves the fixture's owned-cleanup contract: cleanup on readiness timeout, on log-read failure
and on normal exit; an explicit error when removal fails; no removal of a same-name container it did
not start. Every docker argv the fixture issues is also checked against the real default-deny guard
policy, so the fixture can only use guard-admitted forms (inspect/rm on the owned name, no ps/ids).
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
GUARD = RUN.provider_guard
NAME = f"{GUARD.FIXTURE_NAME_PREFIX}s0-pg-4242"


class FakeDocker:
    def __init__(self, *, ready=True, logs_raise=False, rm_fails=False, foreign=False):
        self.by_name = {}
        self.guard_env = {GUARD.DOCKER_OPT_IN_ENV: "1"}
        self.ready, self.logs_raise, self.rm_fails = ready, logs_raise, rm_fails
        self.calls = []
        if foreign:
            self.by_name[NAME] = "someone-else"

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        # Every form the fixture uses must pass the real default-deny guard policy.
        GUARD.docker_policy(["docker", *args], self.guard_env)
        done = lambda out="": subprocess.CompletedProcess(args, 0, out, "")  # noqa: E731
        name = args[-1]
        if args[0] == "inspect":
            if name not in self.by_name:
                return subprocess.CompletedProcess(args, 1, "", f"Error: No such object: {name}")
            return done(self.by_name[name] + "\n")
        if args[0] == "run":
            labels = [args[i + 1] for i, a in enumerate(args) if a == "--label"]
            owner = [lab.split("=", 1)[1] for lab in labels if lab.startswith(RUN.OWNER_KEY + "=")]
            self.by_name[args[args.index("--name") + 1]] = owner[0] if owner else ""
            return done("cid-1\n")
        if args[0] == "logs":
            if self.logs_raise:
                raise OSError("log read failed")
            return done("PostgreSQL init process complete\nready to accept connections\n" if self.ready else "")
        if args[0] == "rm":
            if self.rm_fails:
                return subprocess.CompletedProcess(args, 1, "", "daemon error")
            self.by_name.pop(name, None)
            return done()
        raise AssertionError(f"unexpected docker call {args}")


def _fixture(fake, monkeypatch, tmp_path, clock=None):
    fx = RUN.DisposablePostgres.__new__(RUN.DisposablePostgres)
    fx.socket, fx.name, fx.container_id = tmp_path / "s", NAME, ""
    fx.owner_value, fx.claimed, fx.env, fx.dsn = "test-1", False, {}, ""
    fx.docker = fake
    # The same guard environment the real fixture builds: opt-in plus the fixture bind root.
    fake.guard_env[GUARD.DOCKER_BIND_ROOT_ENV] = str(tmp_path)
    if clock is not None:
        monkeypatch.setattr(RUN.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(RUN.time, "sleep", lambda s: None)
    return fx


def test_positive_start_ready_and_normal_exit_removes_owned_container(monkeypatch, tmp_path):
    fake = FakeDocker()
    with _fixture(fake, monkeypatch, tmp_path):
        assert fake.by_name.get(NAME) == "test-1"
    assert fake.by_name == {}


def test_readiness_timeout_cleans_up_and_preserves_primary_error(monkeypatch, tmp_path):
    fake = FakeDocker(ready=False)
    fx = _fixture(fake, monkeypatch, tmp_path, clock=iter([0, 121, 121, 121]))
    with pytest.raises(RuntimeError, match="did not become ready"):
        with fx:
            pass
    assert fake.by_name == {}


def test_log_read_exception_cleans_up_and_preserves_primary_error(monkeypatch, tmp_path):
    fake = FakeDocker(logs_raise=True)
    with pytest.raises(OSError, match="log read failed"):
        with _fixture(fake, monkeypatch, tmp_path):
            pass
    assert fake.by_name == {}


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
    fake = FakeDocker(foreign=True)
    with pytest.raises(RuntimeError, match="name is taken"):
        with _fixture(fake, monkeypatch, tmp_path):
            pass
    assert fake.by_name.get(NAME) == "someone-else"
    assert not any(c[0] == "rm" for c in fake.calls)


def test_fixture_forms_are_guard_admitted_and_ps_is_not(monkeypatch):
    env = {GUARD.DOCKER_OPT_IN_ENV: "1"}
    assert GUARD.docker_policy(["docker", "inspect", "--format", "x", NAME], env) == "inspect"
    assert GUARD.docker_policy(["docker", "rm", "-f", NAME], env) == "rm"
    with pytest.raises(GUARD.DockerRefused):
        GUARD.docker_policy(["docker", "ps", "-aq", "--filter", "label=x"], env)
    with pytest.raises(GUARD.DockerRefused):
        GUARD.docker_policy(["docker", "rm", "-f", "cid-1"], env)


# ---- S7 restore design §2: the `disposable-postgresql-pair` fixture and the one narrow `docker exec` form ----
PAIR_ENV = {GUARD.DOCKER_OPT_IN_ENV: "1", GUARD.DOCKER_PGEXEC_ENV: "1"}
OWNED = f"{GUARD.FIXTURE_NAME_PREFIX}s0-pg-4242-source"
PG = ["-U", "zeus", "-h", "/var/run/postgresql"]


@pytest.mark.parametrize("argv", [
    [OWNED, "pg_dump", *PG, "-d", "zeus", "-Fc", "-f", "/dump/zeus-ab12cd34.dump"],
    [OWNED, "pg_restore", *PG, "-l", "/dump/zeus-ab12cd34.dump"],
    [OWNED, "pg_restore", *PG, "--exit-on-error", "--single-transaction", "--no-owner", "-d", "zeus_target",
     "/dump/zeus-ab12cd34.dump"],
    [OWNED, "sha256sum", "/dump/zeus-ab12cd34.dump"],
])
def test_the_m7_restore_tool_forms_are_admitted_under_the_second_opt_in(argv):
    assert GUARD.docker_policy(["docker", "exec", *argv], PAIR_ENV) == "exec"


@pytest.mark.parametrize("env, argv, why", [
    ({GUARD.DOCKER_OPT_IN_ENV: "1"}, [OWNED, "sha256sum", "/dump/x"], "needs ZEUS_TEST_DOCKER_PGEXEC"),
    (PAIR_ENV, ["-u", "root", OWNED, "pg_dump", *PG], "takes no option"),
    (PAIR_ENV, ["-i", OWNED, "pg_dump", *PG], "takes no option"),
    (PAIR_ENV, ["--privileged", OWNED, "pg_dump", *PG], "takes no option"),
    (PAIR_ENV, ["zeus-aibox-postgres", "pg_dump", *PG, "-d", "zeus"], "owned fixture containers only"),
    (PAIR_ENV, [OWNED, "psql", *PG, "-c", "select 1"], "not a fixture tool form"),
    (PAIR_ENV, [OWNED, "sh", "-c", "id"], "not a fixture tool form"),
    (PAIR_ENV, [OWNED], "not a fixture tool form"),
    (PAIR_ENV, [OWNED, "pg_dump", "-d", "zeus"], "-U <ident> -h /var/run/postgresql first"),
    (PAIR_ENV, [OWNED, "pg_dump", "-U", "zeus;id", "-h", "/var/run/postgresql"], "-h /var/run/postgresql"),
    (PAIR_ENV, [OWNED, "pg_dump", *PG, "-f", "/etc/passwd"], "paths must be /dump/<name>"),
    (PAIR_ENV, [OWNED, "pg_dump", *PG, "--file=/tmp/x"], "paths must be /dump/<name>"),
    (PAIR_ENV, [OWNED, "pg_restore", *PG, "-l", "/dump/../etc/passwd"], "/dump/<name>"),
    (PAIR_ENV, [OWNED, "pg_restore", *PG, "-d", "x..y"], "may not contain .."),
    (PAIR_ENV, [OWNED, "sha256sum", "/dump/a", "/dump/b"], "exactly one /dump/<name>"),
    (PAIR_ENV, [OWNED, "sha256sum", "/srv/zeus/secrets/zeus-aibox.env"], "exactly one /dump/<name>"),
])
def test_every_other_exec_form_is_refused(env, argv, why):
    with pytest.raises(GUARD.DockerRefused, match=why.replace("<", ".").replace(">", ".")):
        GUARD.docker_policy(["docker", "exec", *argv], env)


def test_a_pair_member_starts_with_its_user_and_dump_bind_through_admitted_forms_only(monkeypatch, tmp_path):
    fake = FakeDocker()
    dump = tmp_path / "dump"
    dump.mkdir()
    fx = _fixture(fake, monkeypatch, tmp_path)
    fx.user, fx.dump_dir = "zeus", dump
    with fx:
        pass
    run = next(c for c in fake.calls if c[0] == "run")
    assert "POSTGRES_USER=zeus" in run and f"type=bind,src={dump},dst=/dump" in run
    assert fake.by_name == {}


def test_the_single_fixture_keeps_its_s0_form(monkeypatch, tmp_path):
    fake = FakeDocker()
    with _fixture(fake, monkeypatch, tmp_path):
        pass
    run = next(c for c in fake.calls if c[0] == "run")
    assert not any(str(a).startswith("POSTGRES_USER=") or "dst=/dump" in str(a) for a in run)


def test_a_pair_whose_target_fails_to_start_removes_the_started_source(monkeypatch, tmp_path):
    started, removed = [], []

    class Member:
        def __init__(self, role, fail=False):
            self.role, self.fail = role, fail

        def __enter__(self):
            if self.fail:
                raise RuntimeError("target did not start")
            started.append(self.role)
            return self

        def __exit__(self, *exc):
            removed.append(self.role)
            return False

    pair = RUN.PostgresPair.__new__(RUN.PostgresPair)
    pair.source, pair.target = Member("source"), Member("target", fail=True)
    with pytest.raises(RuntimeError, match="target did not start"):
        with pair:
            pass
    assert started == ["source"] and removed == ["source"]
    pair.source, pair.target = Member("source"), Member("target")
    started.clear(), removed.clear()
    with pair:
        pass
    assert removed == ["target", "source"]  # both removed, the target first
