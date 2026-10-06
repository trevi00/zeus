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


# ---- fourth opt-in: OwnedContainer worker containers (S9 skip-closure DISPOSITION B17-20) -----------
WORKER_IMAGE_ID = "sha256:" + "a" * 64
CODEX_IMAGE_ID = "sha256:" + "b" * 64
RUN_ID = "0123456789abcdef0123456789abcdef"
CONTAINER_ID = "c" * 64
WORKER_NAME = "zeus-worker-" + RUN_ID


FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
[ "$1" = inspect ] || exit 3
for last; do :; done
[ -f "$FAKE_DOCKER_ANSWERS/$last" ] || exit 1
cat "$FAKE_DOCKER_ANSWERS/$last"
"""


@pytest.fixture
def worker(monkeypatch, tmp_path):
    """The four opt-ins plus a fake docker that records argv and answers only the guard's own inspect."""
    fake = tmp_path / "fake" / "docker"
    fake.parent.mkdir()
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(0o755)
    answers = tmp_path / "answers"
    answers.mkdir()
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.setenv(provider_guard.DOCKER_WORKER_ENV, "1")
    monkeypatch.setenv("ZEUS_TEST_WORKER_IMAGE", WORKER_IMAGE_ID)
    monkeypatch.setenv("ZEUS_TEST_CODEX_IMAGE", CODEX_IMAGE_ID)
    monkeypatch.setenv(provider_guard.DOCKER_BIND_ROOT_ENV, str(tmp_path / "bind"))
    (tmp_path / "bind").mkdir()
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(tmp_path / "log"))
    monkeypatch.setenv("FAKE_DOCKER_ANSWERS", str(answers))
    (tmp_path / "log").write_text("")

    class Fixture:
        docker = str(fake)
        bind = tmp_path / "bind"

        def answer(self, operand, labels=None, image=WORKER_IMAGE_ID):
            labels = {"zeus.isolated.run": RUN_ID} if labels is None else labels
            (answers / operand).write_text(json.dumps({"labels": labels, "image": image}), encoding="utf-8")

        def calls(self):
            return (tmp_path / "log").read_text().splitlines()

        def argv(self, *args):
            return [self.docker, *args]

    return Fixture()


def create_args(image=WORKER_IMAGE_ID, *, source=None, network="none", user="1000:1000", role="worker",
                run_id=RUN_ID, name=None):
    from codex_harness.execution.domain import container_spec as spec

    config = {"limits": spec.LIMITS, "image": image}
    return spec.container_args(config, name=name or f"zeus-{role}-{run_id}", run_id=run_id, role=role,
                               network=network, mounts=[(str(source), spec.WORKSPACE)] if source else [],
                               environment=spec.worker_environment(), pass_names=("CLAUDE_CODE_OAUTH_TOKEN",),
                               entry=["/opt/zeus/bin/python", "-c", "pass"], workdir="/", user=user)


def test_worker_create_admits_exactly_what_container_args_composes(worker):
    for image, role in ((WORKER_IMAGE_ID, "worker"), (CODEX_IMAGE_ID, "codex"), (WORKER_IMAGE_ID, "verifier")):
        provider_guard.check_spawn(None, worker.argv(*create_args(image, source=worker.bind / "ws", role=role)))
    provider_guard.check_spawn(None, worker.argv("container", *create_args(source=worker.bind)))
    assert worker.calls() == []  # create is judged on its argv alone: the guard never inspects for it


def test_worker_forms_are_refused_without_both_opt_ins(worker, monkeypatch):
    create = worker.argv(*create_args())
    worker.answer(CONTAINER_ID)
    forms = [create, worker.argv("start", "--attach", "--interactive", CONTAINER_ID), worker.argv("kill", CONTAINER_ID),
             worker.argv("rm", CONTAINER_ID), worker.argv("image", "inspect", WORKER_IMAGE_ID),
             worker.argv("ps", "-a", "--filter", "label=zeus.isolated.run=" + RUN_ID, "--format", "{{.ID}}")]
    for argv in forms:
        provider_guard.check_spawn(None, argv)
    monkeypatch.delenv(provider_guard.DOCKER_WORKER_ENV)
    assert all(refused(argv) for argv in forms)
    monkeypatch.setenv(provider_guard.DOCKER_WORKER_ENV, "1")
    monkeypatch.delenv(provider_guard.DOCKER_OPT_IN_ENV)
    assert all(refused(argv) for argv in forms)
    monkeypatch.setenv(provider_guard.DOCKER_WORKER_ENV, "0")
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    assert all(refused(argv) for argv in forms)


@pytest.mark.parametrize("extra", [
    ["--privileged"], ["--pid", "host"], ["--pid=host"], ["--ipc", "host"], ["--uts", "host"], ["--userns", "host"],
    ["--cap-add", "SYS_ADMIN"], ["--device", "/dev/kvm"], ["-v", "/:/host"], ["--volume", "/srv:/srv"],
    ["--network", "bridge"], ["--network", "host"], ["--net", "none"], ["--network", "none"],
    ["--security-opt", "seccomp=unconfined"], ["--cap-drop", "NET_RAW"], ["--publish", "80:80"], ["-p", "80:80"],
    ["--rm"], ["--group-add", "0"], ["--env-file", "/etc/passwd"], ["--volumes-from", "x"], ["--label", "extra=1"],
    ["--user", "0"], ["--add-host", "x:1.1.1.1"], ["--dns", "1.1.1.1"], ["--restart", "always"],
    ["--mount", "type=volume,source=v,target=/v"], ["--mount", "type=bind,source=/etc,target=/e"],
    ["--mount", "type=bind,source=%BIND%/x,target=/x,bind-propagation=rshared"],
    ["--mount", "type=bind,source=%BIND%/x,target=/x,readonly=false"],
    ["--mount", "type=bind,source=%BIND%/x,source=/etc,target=/x"],
    ["--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock"],
    ["--mount", "type=bind,source=%BIND%/docker.sock,target=/var/run/docker.sock"],
    ["--mount", "type=bind,source=%BIND%/../x,target=/x"], ["--mount", "type=tmpfs,target=/x"],
    ["--tmpfs", "/x:exec,suid"], ["-e", "1BAD=x"], ["--health-cmd", "x"],
])
def test_worker_create_refuses_every_option_container_args_never_composes(worker, extra):
    base = create_args()
    extra = [part.replace("%BIND%", str(worker.bind)) for part in extra]
    assert not refused(worker.argv(*base))
    assert refused(worker.argv(base[0], *extra, *base[1:])), extra


@pytest.mark.parametrize("network", ["bridge", "host", "container:x", "my-net", ""])
def test_worker_create_refuses_a_network_other_than_none(worker, network):
    assert refused(worker.argv(*create_args(network=network)))


def test_worker_create_refuses_a_security_option_other_than_no_new_privileges(worker):
    args = create_args()
    for option in ("seccomp=unconfined", "apparmor=unconfined", "no-new-privileges=false", "label=disable"):
        assert refused(worker.argv(*[option if a == "no-new-privileges" else a for a in args])), option
    assert not refused(worker.argv(*args))


@pytest.mark.parametrize("user", ["0", "root", "0:0", "0:1000", "root:root", ""])
def test_worker_create_refuses_a_root_user(worker, user):
    assert refused(worker.argv(*create_args(user=user)))


def drop(args, option, *, count=2):
    """`args` without every `option value` pair (or the lone flag when count is 1)."""
    out, i = [], 0
    while i < len(args):
        if args[i] == option:
            i += count
        else:
            out.append(args[i])
            i += 1
    return out


@pytest.mark.parametrize("option,count", [("--network", 2), ("--read-only", 1), ("--cap-drop", 2),
                                          ("--security-opt", 2), ("--user", 2), ("--name", 2), ("--memory", 2),
                                          ("--cpus", 2), ("--pids-limit", 2), ("-w", 2), ("--entrypoint", 2)])
def test_worker_create_refuses_a_missing_control(worker, option, count):
    assert refused(worker.argv(*drop(create_args(), option, count=count)))


def test_worker_create_refuses_a_missing_or_foreign_label(worker):
    args = create_args()
    run_label, role_label = f"zeus.isolated.run={RUN_ID}", "zeus.isolated.role=worker"
    for label in (run_label, role_label):
        index = args.index(label)
        assert refused(worker.argv(*args[:index - 1], *args[index + 1:])), label
    assert refused(worker.argv(*[a.replace(run_label, "zeus.isolated.run=" + "f" * 32) for a in args]))
    assert refused(worker.argv(*[a.replace(role_label, "zeus.isolated.role=verifier") for a in args]))
    assert refused(worker.argv(*[a.replace(run_label, "zeus.test.fixture=1") for a in args]))


@pytest.mark.parametrize("name", ["zeus-worker", "worker-" + RUN_ID, "zeus-test-fixture-worker", "zeus-prod-postgres",
                                  "zeus-worker-" + RUN_ID.upper(), "zeus-worker-" + RUN_ID + "-x"])
def test_worker_create_refuses_a_name_that_is_not_zeus_role_runid(worker, name):
    assert refused(worker.argv(*[name if a == WORKER_NAME else a for a in create_args()]))


@pytest.mark.parametrize("role,run_id", [("prod", "postgres"), ("test", "fixture"), ("worker", "x"),
                                         ("Worker", RUN_ID), ("worker", "0" * 33), ("a1", RUN_ID)])
def test_worker_create_refuses_a_name_outside_the_owned_container_rule_even_with_matching_labels(worker, role, run_id):
    assert refused(worker.argv(*create_args(role=role, run_id=run_id)))


def test_worker_create_refuses_a_bind_mount_that_is_not_type_bind_even_under_the_root(worker):
    args = create_args(source=worker.bind / "ws")
    bind = next(a for a in args if a.startswith("--mount") or a.startswith("type=bind"))
    for replacement in ("type=volume", "type=tmpfs", "type=npipe"):
        assert refused(worker.argv(*[a.replace("type=bind", replacement) for a in args])), replacement
    assert bind and not refused(worker.argv(*args))
    assert refused(worker.argv(*[a.replace("type=bind,", "") for a in args]))


def test_worker_create_image_must_be_exactly_an_admitted_immutable_id(worker, monkeypatch):
    for image in ("sha256:" + "d" * 64, WORKER_IMAGE_ID[:20], "ubuntu", "zeus-worker:latest", WORKER_IMAGE_ID + "x",
                  "pgvector/pgvector:pg17"):
        assert refused(worker.argv(*create_args(image))), image
    monkeypatch.setenv("ZEUS_TEST_WORKER_IMAGE", "zeus-worker:latest")  # a mutable tag is not an admitted value
    assert refused(worker.argv(*create_args("zeus-worker:latest")))
    monkeypatch.setenv("ZEUS_TEST_WORKER_IMAGE", "sha256:" + "A" * 64)
    assert refused(worker.argv(*create_args("sha256:" + "A" * 64)))
    monkeypatch.setenv("ZEUS_TEST_WORKER_IMAGE", "")
    monkeypatch.delenv("ZEUS_TEST_CODEX_IMAGE")
    assert refused(worker.argv(*create_args(WORKER_IMAGE_ID)))
    monkeypatch.setenv("ZEUS_TEST_CODEX_IMAGE", CODEX_IMAGE_ID)
    provider_guard.check_spawn(None, worker.argv(*create_args(CODEX_IMAGE_ID)))
    image_less = create_args()
    image_less.remove(WORKER_IMAGE_ID)
    assert refused(worker.argv(*image_less))


def test_worker_create_binds_stay_under_the_bind_root_and_never_name_a_socket(worker, monkeypatch, tmp_path):
    assert not refused(worker.argv(*create_args(source=worker.bind / "ws")))
    for source in (tmp_path / "elsewhere", Path("/"), Path("/var/run/docker.sock"), Path("/run/docker.sock"),
                   worker.bind / "docker.sock"):
        assert refused(worker.argv(*create_args(source=source))), source
    monkeypatch.delenv(provider_guard.DOCKER_BIND_ROOT_ENV)
    assert refused(worker.argv(*create_args(source=worker.bind / "ws")))
    link = worker.bind / "link"
    link.symlink_to("/var/run")  # a symlink out of the root resolves outside it
    assert refused(worker.argv(*create_args(source=link)))


def test_worker_run_is_never_admitted_only_create(worker):
    assert refused(worker.argv("run", *create_args()[1:]))
    assert refused(worker.argv("container", "run", *create_args()[1:]))


LIFECYCLES = [("start", "--attach", "--interactive"), ("start", "-a", "-i"), ("start",),
              ("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}"),
              ("inspect", "-f", "{{json .Mounts}}"), ("kill",), ("kill", "-s", "KILL"), ("rm",), ("stop", "-t", "5"),
              ("wait",)]


@pytest.mark.parametrize("form", LIFECYCLES, ids=[" ".join(f) for f in LIFECYCLES])
@pytest.mark.parametrize("operand", [CONTAINER_ID, WORKER_NAME])
def test_worker_lifecycle_is_admitted_after_the_guard_inspects_an_owned_container(worker, form, operand):
    worker.answer(operand)
    provider_guard.check_spawn(None, worker.argv(*form, operand))
    assert worker.calls() == [f"inspect --type container --format {provider_guard.WORKER_INSPECT_FORMAT} {operand}"]


@pytest.mark.parametrize("form", LIFECYCLES, ids=[" ".join(f) for f in LIFECYCLES])
def test_worker_lifecycle_refuses_unlabelled_foreign_or_uninspectable_containers(worker, form):
    argv = worker.argv(*form, CONTAINER_ID)
    assert refused(argv)  # the fake has no answer: the inspect fails
    worker.answer(CONTAINER_ID, labels={})
    assert refused(argv)
    worker.answer(CONTAINER_ID, labels={"zeus.test.fixture": "1"})
    assert refused(argv)
    worker.answer(CONTAINER_ID, labels=None, image="sha256:" + "d" * 64)
    assert refused(argv)
    worker.answer(CONTAINER_ID, labels=None, image="ubuntu")
    assert refused(argv)
    worker.answer(CONTAINER_ID, labels={"zeus.isolated.run": ""})
    assert refused(argv)
    (Path(os.environ["FAKE_DOCKER_ANSWERS"]) / CONTAINER_ID).write_text("not json")
    assert refused(argv)
    (Path(os.environ["FAKE_DOCKER_ANSWERS"]) / CONTAINER_ID).write_text("[]")
    assert refused(argv)
    worker.answer(CONTAINER_ID)
    provider_guard.check_spawn(None, argv)


def test_worker_lifecycle_inspects_every_operand_and_only_well_formed_ones(worker):
    other = "e" * 64
    worker.answer(CONTAINER_ID)
    assert refused(worker.argv("rm", CONTAINER_ID, other))  # the second has no answer
    worker.answer(other)
    provider_guard.check_spawn(None, worker.argv("rm", CONTAINER_ID, other))
    for operand in ("zeus-prod-postgres", "harness-ci-postgres-1", "abc123", "$(id)", "-f", "zeus-worker-x/../y"):
        if "/" not in operand:
            worker.answer(operand)  # even an owned-looking answer cannot admit a malformed operand
        assert refused(worker.argv("rm", operand)), operand
    assert refused(worker.argv("rm"))
    assert refused(worker.argv("start", "--attach", CONTAINER_ID, other))
    for option in ("--force", "-f", "--volumes", "--link", "--detach-keys=x", "--checkpoint", "-d"):
        assert refused(worker.argv("rm", option, CONTAINER_ID)), option


@pytest.mark.parametrize("argv", [["exec", CONTAINER_ID, "sh"], ["cp", CONTAINER_ID + ":/x", "/tmp"],
                                  ["logs", CONTAINER_ID], ["pause", CONTAINER_ID], ["restart", CONTAINER_ID],
                                  ["update", CONTAINER_ID], ["commit", CONTAINER_ID, "x"],
                                  ["attach", CONTAINER_ID], ["top", CONTAINER_ID], ["export", CONTAINER_ID],
                                  ["network", "connect", "bridge", CONTAINER_ID], ["pull", WORKER_IMAGE_ID],
                                  ["rmi", WORKER_IMAGE_ID], ["image", "rm", WORKER_IMAGE_ID],
                                  ["build", "-t", "zeus-worker:x", "."], ["save", WORKER_IMAGE_ID],
                                  ["container", "prune", "-f"], ["compose", "up"]])
def test_worker_opt_in_admits_no_other_docker_command(worker, argv):
    worker.answer(CONTAINER_ID)
    assert refused(worker.argv(*argv)), argv


def test_the_guards_own_inspect_is_exact_and_admits_nothing_else(worker):
    worker.answer(CONTAINER_ID)
    provider_guard.check_spawn(None, worker.argv("kill", CONTAINER_ID))
    assert len(worker.calls()) == 1
    # after the inspect finished its exemption is gone: the same argv is no longer admitted by itself
    assert refused(worker.argv("inspect", "--type", "container", "--format", provider_guard.WORKER_INSPECT_FORMAT,
                               "f" * 64))
    assert provider_guard._GUARD_STATE.expected is None
    assert refused(worker.argv("--host", "tcp://x", "inspect", CONTAINER_ID))


RUN_FILTER = "label=zeus.isolated.run=" + RUN_ID


@pytest.mark.parametrize("args", [
    ["ps", "-a", "--filter", RUN_FILTER, "--format", "{{.ID}}"],
    ["ps", "--filter", RUN_FILTER, "--format", "{{.ID}}"],
    ["ps", "-a", "--no-trunc", "--filter", "name=^/" + WORKER_NAME + "$", "--filter", RUN_FILTER,
     "--format", "{{.ID}}"],
])
def test_worker_ps_admits_the_run_label_listing_forms(worker, args):
    provider_guard.check_spawn(None, worker.argv(*args))
    assert worker.calls() == []


@pytest.mark.parametrize("args", [
    ["ps", "-a"], ["ps", "-a", "--format", "{{.ID}}"], ["ps", "-a", "--filter", RUN_FILTER],
    ["ps", "-a", "--filter", RUN_FILTER, "--format", "{{.Names}}"],
    ["ps", "-a", "--filter", "label=zeus.isolated.run", "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", "label=other=" + RUN_ID, "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", "name=^/zeus-worker-" + RUN_ID + "$", "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", RUN_FILTER, "--filter", RUN_FILTER, "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", RUN_FILTER, "--filter", "name=zeus", "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", RUN_FILTER, "--format", "{{.ID}}", "x"], ["ps", "-aq", "--filter", RUN_FILTER],
    ["ps", "-a", "--filter", RUN_FILTER, "--format", "{{.ID}}", "--size"],
])
def test_worker_ps_refuses_every_other_listing(worker, args):
    assert refused(worker.argv(*args)), args


def test_worker_image_inspect_names_only_an_admitted_immutable_id(worker, monkeypatch):
    for form in (["image", "inspect", "--format", "{{.Id}}", WORKER_IMAGE_ID], ["image", "inspect", CODEX_IMAGE_ID],
                 ["version", "--format", "{{.Server.Version}}"]):
        provider_guard.check_spawn(None, worker.argv(*form))
    for form in (["image", "inspect", "--format", "{{.Id}}", "sha256:" + "d" * 64], ["image", "inspect", "ubuntu"],
                 ["image", "inspect", WORKER_IMAGE_ID, "ubuntu"], ["image", "inspect"],
                 ["image", "inspect", "--format", "{{.Id}}", WORKER_IMAGE_ID[:30]]):
        assert refused(worker.argv(*form)), form
    monkeypatch.setenv("ZEUS_TEST_WORKER_IMAGE", "zeus-worker:latest")
    monkeypatch.setenv("ZEUS_TEST_CODEX_IMAGE", "")
    assert refused(worker.argv("image", "inspect", "zeus-worker:latest"))


def test_worker_opt_in_leaves_the_fixture_and_other_opt_in_rules_unchanged(worker, monkeypatch):
    provider_guard.check_spawn(None, worker.argv("run", *FIXTURE_RUN))
    provider_guard.check_spawn(None, worker.argv("rm", "-f", "zeus-test-fixture-worker"))
    assert worker.calls() == []  # owned fixture names never need the worker inspect
    assert refused(worker.argv("exec", "zeus-test-fixture-worker", "codex"))
    assert refused(worker.argv("ps", "-aq", "--filter", LABEL_FILTER))
    assert refused(worker.argv("create", "--network", "none", "--name", "zeus-test-fixture-x", "ubuntu"))


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


# AMD-1 C.12/C.13 (cutover RH-1a): the rehearsal listing and `--memory-swap`. Expected results are the owner's
# ruling text: exactly `ps -a --filter label=zeus.rehearsal.run=<8 hex> [--filter label=zeus.test.fixture=1]
# --format {{.ID}}|{{.Names}}` under ZEUS_TEST_DOCKER=1, and `--memory-swap` as one more run value option.
REHEARSAL_RUN = "label=zeus.rehearsal.run=1a2b3c4d"
REHEARSAL_BOTH = ["ps", "-a", "--filter", REHEARSAL_RUN, "--filter", "label=zeus.test.fixture=1", "--format"]


@pytest.mark.parametrize("args", [
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.Names}}"],
    [*REHEARSAL_BOTH, "{{.ID}}"], [*REHEARSAL_BOTH, "{{.Names}}"],
])
def test_rehearsal_ps_admits_exactly_the_run_label_listing(monkeypatch, args):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    provider_guard.check_spawn(None, ["docker", *args])


@pytest.mark.parametrize("args", [
    ["ps", "-a"], ["ps", "-a", "--format", "{{.ID}}"], ["ps", "-a", "--filter", REHEARSAL_RUN],
    ["ps", "-a", "--filter", "label=zeus.test.fixture=1", "--format", "{{.ID}}"],  # no rehearsal label
    ["ps", "-a", "--filter", "label=zeus.rehearsal.run", "--format", "{{.ID}}"],  # key without a value
    ["ps", "-a", "--filter", "label=zeus.rehearsal.other=1a2b3c4d", "--format", "{{.ID}}"],  # another label key
    ["ps", "-a", "--filter", "label=zeus.rehearsal.run=1A2B3C4D", "--format", "{{.ID}}"],  # not lower-case hex
    ["ps", "-a", "--filter", "label=zeus.rehearsal.run=1a2b3c4", "--format", "{{.ID}}"],  # 7 digits
    ["ps", "-a", "--filter", "label=zeus.rehearsal.run=1a2b3c4d5", "--format", "{{.ID}}"],  # 9 digits
    ["ps", "-a", "--filter", "label=zeus.rehearsal.run=1a2b3c4g", "--format", "{{.ID}}"],  # not hex
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--filter", "name=zeus", "--format", "{{.ID}}"],  # an extra filter
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--filter", "label=zeus.test.fixture=0", "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--filter", "label=zeus.test.fixture=1",
     "--filter", "label=zeus.test.fixture=1", "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}", "--no-trunc"],  # an extra option
    ["ps", "-a", "--no-trunc", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "-a", "--size", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "-aq", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.Image}}"],  # another format
    ["ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}", "x"],  # an operand
    ["ps", "-a", "--filter", "label=zeus.test.fixture=1", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"],
])
def test_rehearsal_ps_refuses_every_other_listing(monkeypatch, args):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.delenv(provider_guard.DOCKER_VERIFY_STACK_ENV, raising=False)
    assert refused(["docker", *args]), args


def test_rehearsal_ps_needs_the_docker_opt_in_and_opens_no_other_form(monkeypatch):
    monkeypatch.delenv(provider_guard.DOCKER_OPT_IN_ENV, raising=False)
    assert refused(["docker", "ps", "-a", "--filter", REHEARSAL_RUN, "--format", "{{.ID}}"])
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    monkeypatch.delenv(provider_guard.DOCKER_VERIFY_STACK_ENV, raising=False)
    for argv in (["docker", "ps"], ["docker", "ps", "-a"], ["docker", "ps", "-aq", "--filter", LABEL_FILTER],
                 ["docker", "volume", "ls", "-q", "--filter", REHEARSAL_RUN], ["docker", "images"]):
        assert refused(argv), argv


def test_memory_swap_is_one_more_run_value_option(monkeypatch):
    monkeypatch.setenv(provider_guard.DOCKER_OPT_IN_ENV, "1")
    run = ["docker", "run", "--network", "none", "--label", "zeus.test.fixture=1", "--name",
           "zeus-test-fixture-swap", "--memory", "4g", "--memory-swap", "4g", "zeus-test-fixture/worker:1"]
    provider_guard.check_spawn(None, run)
    provider_guard.check_spawn(None, [*run[:-1][:run.index("--memory-swap")], "--memory-swap=4g", run[-1]])
    assert "--memory-swap" in provider_guard.RUN_VALUE_OPTIONS
    # The addition widens nothing else: a swap option still needs its value, and its neighbours stay refused.
    assert refused(["docker", "run", "--network", "none", "--label", "zeus.test.fixture=1", "--name",
                    "zeus-test-fixture-swap", "--memory-swap"])
    for option in ("--memory-reservation", "--memory-swappiness", "--kernel-memory", "--oom-kill-disable"):
        assert refused([*run[:-1], option, "1", run[-1]]), option
