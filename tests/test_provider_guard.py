"""R-P negative controls: no real provider is reachable from target tests (S0 exit check 6).

Each layer has a control: (a) the in-process audit hook, extended to child Python interpreters by
`compare/guard/sitecustomize.py`; (b) the fail-loud fake executables and empty homes for any child;
(c) bwrap without network, checked only when the session runs under it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import provider_guard
import pytest


def fixture_binary(directory: Path, name: str, marker: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\necho fixture-{name}\ntouch '{marker}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_guard_is_installed_in_the_session():
    assert provider_guard.installed()


@pytest.mark.parametrize("argv", [["codex", "--version"], ["claude", "-p", "x"], ["docker", "ps"]])
def test_bare_provider_name_is_refused_in_process(argv):
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        subprocess.run(argv, capture_output=True, timeout=5)


def test_absolute_path_provider_is_refused_before_exec(tmp_path):
    marker = tmp_path / "ran"
    binary = fixture_binary(tmp_path / "bin", "claude", marker)
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        subprocess.run([str(binary)], capture_output=True, timeout=5)
    assert not marker.exists()


@pytest.mark.parametrize("command", ["docker ps", "echo hi && codex exec x", "/opt/x/claude -p y"])
def test_shell_strings_naming_a_provider_are_refused(command):
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        subprocess.run(command, shell=True, capture_output=True, timeout=5)


def test_os_level_spawns_are_refused(tmp_path):
    marker = tmp_path / "ran"
    binary = fixture_binary(tmp_path / "bin", "codex", marker)
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        os.posix_spawn(str(binary), [str(binary)], dict(os.environ))
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        os.system(f"{binary} --version")
    assert not marker.exists()


def test_configured_fixture_binary_is_the_only_admitted_provider(tmp_path, monkeypatch):
    marker = tmp_path / "ran"
    fixtures = tmp_path / "fixtures"
    binary = fixture_binary(fixtures, "codex", marker)
    monkeypatch.setenv(provider_guard.FIXTURE_DIR_ENV, str(fixtures))
    done = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
    assert done.stdout.strip() == "fixture-codex" and marker.exists()
    elsewhere = fixture_binary(tmp_path / "other", "codex", tmp_path / "other-ran")
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        subprocess.run([str(elsewhere)], capture_output=True, timeout=5)


FIXTURE_RUN = ["--rm", "--network", "none", "--label", "zeus.test.fixture=1",
               "--name", "zeus-test-fixture-worker", "zeus-test-fixture/worker:1", "true"]


def refused(argv) -> bool:
    try:
        provider_guard.check_spawn(None, argv)
    except provider_guard.ProviderSpawnRefused:
        return True
    return False


def test_docker_is_refused_without_the_opt_in(monkeypatch):
    monkeypatch.delenv(provider_guard.DOCKER_OPT_IN_ENV, raising=False)
    assert refused(["docker", "run", *FIXTURE_RUN]) and refused(["docker", "version"])


@pytest.mark.parametrize("argv", [
    # Codex S0 F1 discriminators: the alias launch and a fixture-looking name on a real image.
    ["docker", "container", "run", "ubuntu", "true"],
    ["docker", "run", "--network=none", "--name", "zeus-test-fixture-decoy", "ubuntu", "true"],
    ["docker", "run", "--network=none", "--label", "zeus.test.fixture=1", "--name",
     "zeus-test-fixture-decoy", "ubuntu", "true"],
    ["docker", "run", "--network", "none", "--label", "zeus.test.fixture=1", "--name",
     "zeus-test-fixture-x", "zeus-test-fixture-decoy/x", "true"],
    ["docker", "container", "run", "--network", "bridge", "--label", "zeus.test.fixture=1", "--name",
     "zeus-test-fixture-x", "zeus-test-fixture/worker:1"],
    ["docker", "run", "--network", "none", "--network", "host", "--label", "zeus.test.fixture=1",
     "--name", "zeus-test-fixture-x", "zeus-test-fixture/worker:1"],
    ["docker", "run", "--privileged", *FIXTURE_RUN],
    ["docker", "run", "-v", "/:/host", *FIXTURE_RUN],
    ["docker", "run", "--mount", "type=bind,src=/srv,dst=/x", *FIXTURE_RUN],
    ["docker", "-H", "tcp://127.0.0.1:2375", "run", *FIXTURE_RUN],
    ["docker", "--context", "remote", "container", "run", *FIXTURE_RUN],
    ["docker", "exec", "zeus-test-fixture-worker", "codex"],
    ["docker", "compose", "up"], ["docker", "pull", "ubuntu"], ["docker", "cp", "a", "b"],
    ["docker", "network", "rm", "bridge"], ["docker", "volume", "prune", "-f"],
    ["docker", "container", "prune", "-f"], ["docker", "image", "prune", "-a"],
    ["docker", "system", "prune"], ["docker", "rm", "-f", "zeus-prod-postgres"],
    ["docker", "container", "stop", "harness-ci-postgres-1"], ["docker", "rmi", "ubuntu"],
    ["docker", "image", "rm", "pgvector/pgvector:pg17"], ["docker", "kill", "0123abcd"],
    ["docker", "build", "-t", "ubuntu:evil", "--network", "none", "--label", "zeus.test.fixture=1", "."],
    ["docker", "build", "-t", "zeus-test-fixture/w:1", "--label", "zeus.test.fixture=1", "."],
    ["docker"], ["codex", "exec", "x"], ["claude", "-p", "x"],
])
def test_docker_opt_in_is_default_deny(monkeypatch, argv):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    assert refused(argv), argv


@pytest.mark.parametrize("argv", [
    ["docker", "run", *FIXTURE_RUN],
    ["docker", "container", "run", *FIXTURE_RUN],          # the alias is normalized, same check
    ["docker", "create", *FIXTURE_RUN[1:]],
    ["docker", "rm", "-f", "zeus-test-fixture-worker"],
    ["docker", "container", "stop", "-t", "5", "zeus-test-fixture-worker"],
    ["docker", "logs", "--tail", "20", "zeus-test-fixture-worker"],
    ["docker", "build", "-t", "zeus-test-fixture/worker:1", "--network", "none", "--label",
     "zeus.test.fixture=1", "fixture-context"],
    ["docker", "image", "inspect", "pgvector/pgvector:pg17"],
    ["docker", "version", "--format", "{{.Server.Version}}"],
])
def test_docker_opt_in_admits_owned_fixture_forms(monkeypatch, argv):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    provider_guard.check_spawn(None, argv)


def test_fixture_binds_are_limited_to_the_declared_root(monkeypatch, tmp_path):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    bind = ["--mount", f"type=bind,src={tmp_path / 'socket'},dst=/var/run/postgresql"]
    argv = ["docker", "run", *bind, "--network", "none", "--label", "zeus.test.fixture=1",
            "--name", "zeus-test-fixture-pg", "pgvector/pgvector:pg17"]
    assert refused(argv)
    monkeypatch.setenv(provider_guard.DOCKER_BIND_ROOT_ENV, str(tmp_path))
    provider_guard.check_spawn(None, argv)
    outside = ["docker", "run", "--mount", "type=bind,src=/home,dst=/h", *argv[3:]]
    assert refused(outside)


VERIFY_PROJECT = "zeus-verify-" + "0" * 32


def verify_stack(tmp_path, mutate=None):
    """The compose definition `host_os.adapters.verification.VerificationServices.__enter__` writes."""
    spec = {"services": {
        "postgres": {"image": "pgvector/pgvector:pg17",
                     "environment": {"POSTGRES_USER": "zeus", "POSTGRES_DB": "zeus",
                                     "POSTGRES_PASSWORD": "${ZEUS_VERIFY_PASSWORD}"},
                     "ports": ["127.0.0.1:15432:5432"], "volumes": ["database:/var/lib/postgresql/data"],
                     "mem_limit": "512m", "cpus": 1,
                     "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U zeus -d zeus"]}},
        "redis": {"image": "redis:7.4-alpine", "ports": ["127.0.0.1::6379"],
                  "command": ["redis-server", "--appendonly", "no"], "mem_limit": "128m", "cpus": 0.5,
                  "healthcheck": {"test": ["CMD", "redis-cli", "ping"]}}},
        "volumes": {"database": {}}}
    if mutate:
        mutate(spec)
    path = tmp_path / "stack" / "compose.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def compose(path, *args, project=VERIFY_PROJECT):
    return ["docker", "compose", "--project-name", project, "--file", str(path), *args]


LABEL_FILTER = "label=com.docker.compose.project=" + VERIFY_PROJECT


def test_the_verification_stack_forms_need_their_own_opt_in(monkeypatch, tmp_path):
    """SKIPPED-TEST-CLOSURE-20261004 B: the owner-run stack checks get a THIRD opt-in, never the fixture one alone."""
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.delenv(provider_guard.DOCKER_VERIFY_STACK_ENV, raising=False)
    path = verify_stack(tmp_path)
    assert refused(compose(path, "up", "-d", "--wait"))
    assert refused(["docker", "ps", "-aq", "--filter", LABEL_FILTER])
    monkeypatch.setenv(provider_guard.DOCKER_VERIFY_STACK_ENV, "1")
    provider_guard.check_spawn(None, compose(path, "up", "-d", "--wait"))
    monkeypatch.delenv(provider_guard.DOCKER_OPT_IN_ENV)
    assert refused(compose(path, "up", "-d", "--wait"))


@pytest.mark.parametrize("args", [
    ["up", "-d", "--wait"], ["up", "-d", "--no-recreate", "--wait", "postgres"], ["port", "postgres", "5432"],
    ["port", "redis", "6379"], ["ps", "--all", "--quiet", "postgres"], ["ps", "-q", "redis"], ["pause", "postgres"],
    ["unpause", "postgres"], ["stop", "--timeout", "5", "postgres"],
    ["down", "--volumes", "--remove-orphans", "--timeout", "10"],
    ["exec", "-T", "postgres", "psql", "-U", "zeus", "-d", "zeus", "-Atqc", "SELECT 1"],
    ["exec", "-T", "redis", "redis-cli", "info", "server"],
])
def test_the_verification_stack_admits_exactly_its_own_forms(monkeypatch, tmp_path, args):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.setenv(provider_guard.DOCKER_VERIFY_STACK_ENV, "1")
    provider_guard.check_spawn(None, compose(verify_stack(tmp_path), *args))


def test_the_verification_stack_removal_check_reads_only_its_project(monkeypatch):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.setenv(provider_guard.DOCKER_VERIFY_STACK_ENV, "1")
    provider_guard.check_spawn(None, ["docker", "ps", "-aq", "--filter", LABEL_FILTER])
    provider_guard.check_spawn(None, ["docker", "volume", "ls", "-q", "--filter", LABEL_FILTER])
    for argv in (["docker", "ps", "-aq"], ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=prod"],
                 ["docker", "volume", "ls", "-q"], ["docker", "volume", "rm", "x"], ["docker", "volume", "prune", "-f"],
                 ["docker", "ps", "-aq", "--filter", LABEL_FILTER, "extra"]):
        assert refused(argv), argv


@pytest.mark.parametrize("args,project,name", [
    (["up", "-d"], "zeus-prod", "compose.json"), (["up", "-d"], "zeus-verify-XYZ", "compose.json"),
    (["up", "-d"], VERIFY_PROJECT, "docker-compose.yml"), (["run", "postgres", "sh"], VERIFY_PROJECT, "compose.json"),
    (["cp", "postgres:/x", "/tmp"], VERIFY_PROJECT, "compose.json"), (["pull"], VERIFY_PROJECT, "compose.json"),
    (["config"], VERIFY_PROJECT, "compose.json"), (["up", "-d", "worker"], VERIFY_PROJECT, "compose.json"),
    (["port", "postgres", "6379"], VERIFY_PROJECT, "compose.json"), (["pause"], VERIFY_PROJECT, "compose.json"),
    (["exec", "-T", "postgres", "bash"], VERIFY_PROJECT, "compose.json"),
    (["exec", "postgres", "psql"], VERIFY_PROJECT, "compose.json"),
    (["down", "postgres"], VERIFY_PROJECT, "compose.json"), (["up", "--build"], VERIFY_PROJECT, "compose.json"),
])
def test_the_verification_stack_refuses_every_other_compose_form(monkeypatch, tmp_path, args, project, name):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.setenv(provider_guard.DOCKER_VERIFY_STACK_ENV, "1")
    path = verify_stack(tmp_path)
    renamed = path.with_name(name)
    path.rename(renamed)
    assert refused(compose(renamed, *args, project=project))
    assert refused(["docker", "compose", "--file", str(renamed), "--project-name", project, *args])
    assert refused(["docker", "compose", "--project-name", VERIFY_PROJECT, "--file", "stack/compose.json", "up", "-d"])


@pytest.mark.parametrize("mutate", [
    lambda s: s["services"]["postgres"].update(privileged=True),
    lambda s: s["services"]["redis"].update(network_mode="host"),
    lambda s: s["services"]["postgres"].update(cap_add=["SYS_ADMIN"]),
    lambda s: s["services"]["postgres"].update(image="ubuntu"),
    lambda s: s["services"]["postgres"].update(ports=["0.0.0.0:15432:5432"]),
    lambda s: s["services"]["redis"].update(ports=["6379:6379"]),
    lambda s: s["services"]["postgres"].update(ports=["127.0.0.1:15432:5432", "127.0.0.1:2375:2375"]),
    lambda s: s["services"]["postgres"].update(volumes=["/var/run/docker.sock:/var/run/docker.sock"]),
    lambda s: s["services"]["postgres"].update(volumes=["/srv:/var/lib/postgresql/data"]),
    lambda s: s["services"].update(extra={"image": "redis:7.4-alpine"}),
    lambda s: s["services"]["redis"].update(command=["sh", "-c", "id"]),
    lambda s: s["services"]["postgres"]["environment"].update(PGDATA="/x"),
    lambda s: s.update(networks={"default": {"external": True}}),
    lambda s: s["volumes"].update(other={"driver": "local"}),
])
def test_the_verification_stack_refuses_a_broader_definition(monkeypatch, tmp_path, mutate):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.setenv(provider_guard.DOCKER_VERIFY_STACK_ENV, "1")
    assert refused(compose(verify_stack(tmp_path, mutate), "up", "-d", "--wait"))


def test_docker_marker_does_not_admit_a_real_provider_spawn(monkeypatch):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    with pytest.raises(provider_guard.ProviderSpawnRefused):
        subprocess.run(["codex", "--version"], capture_output=True, timeout=5)


def test_child_interpreter_refuses_bare_and_absolute_provider_spawns(tmp_path, child_env):
    marker = tmp_path / "ran"
    binary = fixture_binary(tmp_path / "bin", "codex", marker)
    program = ("import subprocess, sys\n"
               "for argv in (['codex', '--version'], [sys.argv[1]]):\n"
               "    try:\n"
               "        subprocess.run(argv, capture_output=True, timeout=5)\n"
               "        print('SPAWNED', argv[0])\n"
               "    except PermissionError as exc:\n"
               "        print('REFUSED', type(exc).__name__)\n")
    done = subprocess.run([sys.executable, "-c", program, str(binary)], env=child_env,
                          capture_output=True, text=True, timeout=30)
    assert done.stdout.split("\n")[:2] == ["REFUSED ProviderSpawnRefused"] * 2, done.stderr
    assert not marker.exists()


def test_non_python_child_resolves_only_the_fail_loud_fake(tmp_path, child_env):
    script = tmp_path / "call.sh"
    script.write_text("codex --version\nclaude -p hi\n", encoding="utf-8")
    done = subprocess.run(["sh", str(script)], env=child_env, capture_output=True, text=True,
                          timeout=30)
    assert done.returncode == provider_guard.FAKE_EXIT
    assert "fail-loud fake 'claude'" in done.stderr or "fail-loud fake 'codex'" in done.stderr


def test_child_environment_has_empty_homes_and_no_credential_names(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-value-not-a-credential")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fixture-value-not-a-credential")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-value-not-a-credential")
    env = provider_guard.child_environment(tmp_path / "child")
    assert not {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN"} & set(env)
    for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        assert Path(env[name]).is_dir() and not any(Path(env[name]).iterdir())
    assert env["PATH"].split(os.pathsep)[0].endswith("fakebin")


@pytest.mark.skipif(os.environ.get("ZEUS_TEST_BWRAP") != "1",
                    reason="layer (c) is the local bwrap layer; this session is not under bwrap")
def test_bwrap_layer_has_no_network_and_empty_credential_dirs():
    interfaces = [line.split(":")[0].strip() for line in
                  Path("/proc/net/dev").read_text().splitlines()[2:]]
    assert interfaces == ["lo"]
    for raw in provider_guard.CREDENTIAL_DIRS:
        path = Path(os.path.expanduser(raw))
        if path.is_dir():
            assert not any(path.iterdir()), raw
