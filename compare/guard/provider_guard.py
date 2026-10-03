"""No-real-provider guard for rebuild tests and comparison drivers (REBUILD-DESIGN-v2 §5.2 R-P).

Layer: harness (never shipped)
Owns: the refusal of `claude`/`codex`/`docker` process spawns in test and driver processes.

Three layers, each with a negative control in `target/tests/test_provider_guard.py`:
(a) `install()` adds a `sys.addaudithook` that refuses `subprocess.Popen`, `os.posix_spawn`,
    `os.exec*`, `os.spawn*` and `os.system` of a provider executable (bare name, absolute path or
    inside a shell command string) unless it resolves inside the configured fixture directory.
    `sitecustomize.py` in this directory installs the same hook in every child Python interpreter
    that runs with this directory on PYTHONPATH.
(b) `child_environment()` gives children a PATH that starts with fail-loud fake provider
    executables, empty HOME/CODEX_HOME/CLAUDE_CONFIG_DIR/XDG_CONFIG_HOME, and no credential-named
    variables (removed by NAME; values are never printed or recorded).
(c) `bwrap_prefix()` runs a local process without network and with tmpfs over the credential
    directories. CI has no provider credentials.

The Docker opt-in (`ZEUS_TEST_DOCKER=1`) never authorizes `claude` or `codex`, and it authorizes
`docker` only through `docker_policy`, which is default-deny: global options are refused, alias
forms (`container run`, `image build`, ...) are normalized and pass the same check, and only these
complete forms are admitted:
- `run`/`create`: every option is on the allow list, exactly one network option equal to `none`, the
  owned-fixture label, an owned `--name`, binds only under the declared fixture bind root, and the
  actual image operand is an allowed fixture image (never a prefix match on arbitrary tokens);
- `build`: fixture tags only, `--network none`, the fixture label;
- lifecycle `rm`/`stop`/`kill`/`inspect`/`logs`/`wait`: every operand is an owned fixture name;
- `rmi`/`image inspect`: fixture images only; `version`/`info`;
- `exec`, ONLY with the second opt-in `ZEUS_TEST_DOCKER_PGEXEC=1` (set by the harness for the
  `disposable-postgresql-pair` families alone, S7 restore design §2): no exec option at all, an owned fixture
  container, and exactly the M7 host-migration tool forms `pg_dump|pg_restore -U <ident> -h /var/run/postgresql
  ...` and `sha256sum /dump/<name>`, every path operand being `/var/run/postgresql` or `/dump/<name>`.
- `compose`, ONLY with the third opt-in `ZEUS_TEST_DOCKER_VERIFY_STACK=1` (set by the owner-run verification-stack
  command alone, SKIPPED-TEST-CLOSURE-20261004 B): exactly `compose --project-name zeus-verify-<32 hex> --file
  <absolute>/compose.json <subcommand>` over the disposable two-service stack `host_os.adapters.verification` writes
  (fixture images, loopback-only publications, one named volume, allow-listed service keys: nothing privileged, no
  network mode, no binds), with the stack's own subcommand forms, plus the project-scoped read-only `ps`/`volume ls`
  label filters its removal check uses.
Everything else (`cp`, `pull`, other `compose`, `network`, `volume`, `system`, other `exec` forms, ...) is refused.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path

PROVIDERS = frozenset({"claude", "codex", "docker"})
FIXTURE_DIR_ENV = "ZEUS_TEST_PROVIDER_FIXTURES"
DOCKER_OPT_IN_ENV = "ZEUS_TEST_DOCKER"
DOCKER_IMAGES_ENV = "ZEUS_TEST_DOCKER_FIXTURE_IMAGES"  # extra EXACT image refs, comma-separated
DOCKER_BIND_ROOT_ENV = "ZEUS_TEST_DOCKER_BIND_ROOT"
DOCKER_PGEXEC_ENV = "ZEUS_TEST_DOCKER_PGEXEC"  # second opt-in: the restore family's `docker exec` tool forms
DOCKER_VERIFY_STACK_ENV = "ZEUS_TEST_DOCKER_VERIFY_STACK"  # third opt-in: the owner-run VerificationServices stack
VERIFY_PROJECT = re.compile(r"^zeus-verify-[0-9a-f]{32}$")
VERIFY_SERVICES = {"postgres": "5432", "redis": "6379"}
VERIFY_SERVICE_KEYS = {"postgres": frozenset({"image", "environment", "ports", "volumes", "mem_limit", "cpus",
                                              "healthcheck"}),
                       "redis": frozenset({"image", "ports", "command", "mem_limit", "cpus", "healthcheck"})}
VERIFY_PROGRAMS = {"postgres": "psql", "redis": "redis-cli"}
PG_TOOLS = frozenset({"pg_dump", "pg_restore"})
PG_SOCKET_DIR = "/var/run/postgresql"
DUMP_PATH = re.compile(r"^/dump/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FIXTURE_LABEL = "zeus.test.fixture=1"
FIXTURE_NAME_PREFIX = "zeus-test-fixture-"
FIXTURE_IMAGE = re.compile(r"^zeus-test-fixture/[a-z0-9][a-z0-9._-]*(:[A-Za-z0-9._-]+)?$")
# Exact refs of disposable service images the repository itself uses (compose.yaml postgres, redis), and the
# digest-pinned refs compare/run.py starts its fixtures from (the goldens record those images' facts).
DEFAULT_FIXTURE_IMAGES = ("pgvector/pgvector:pg17", "redis:7.4-alpine",
                          "pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f",
                          "redis@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499")
FAKE_EXIT = 97
SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "fish", "cmd", "powershell", "pwsh"})
DOCKER_ALIASES = {("container", "run"): "run", ("container", "create"): "create",
                  ("container", "rm"): "rm", ("container", "stop"): "stop",
                  ("container", "kill"): "kill", ("container", "inspect"): "inspect",
                  ("container", "logs"): "logs", ("container", "wait"): "wait",
                  ("image", "build"): "build", ("image", "inspect"): "image-inspect",
                  ("image", "rm"): "rmi"}
DOCKER_TOP = frozenset({"run", "create", "build", "rm", "stop", "kill", "inspect", "logs", "wait",
                        "rmi", "image-inspect", "version", "info"})
RUN_VALUE_OPTIONS = frozenset({"--name", "--label", "-l", "--network", "--net", "--user", "-u",
                               "--workdir", "-w", "--env", "-e", "--memory", "-m", "--cpus",
                               "--pids-limit", "--entrypoint", "--tmpfs", "--mount", "--security-opt",
                               "--cap-drop", "--stop-timeout"})
RUN_FLAGS = frozenset({"--rm", "-i", "--interactive", "--read-only", "--init", "-d", "--detach"})
LIFECYCLE_OPTIONS = {"rm": ({"-f", "--force"}, set()), "stop": (set(), {"-t", "--time"}),
                     "kill": (set(), {"-s", "--signal"}), "inspect": (set(), {"-f", "--format"}),
                     "logs": (set(), {"--tail"}), "wait": (set(), set())}
SECRET_NAME_PARTS = ("TOKEN", "API_KEY", "APIKEY", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL",
                     "AUTH", "PRIVATE_KEY", "SESSION_KEY", "COOKIE")
SECRET_NAME_PREFIXES = ("ANTHROPIC_", "OPENAI_", "CLAUDE_CODE_", "CODEX_", "GH_", "GITHUB_",
                        "AWS_", "AZURE_", "GOOGLE_", "ZEUS_CLAUDE_", "ZEUS_CODEX_")
CREDENTIAL_DIRS = ("/srv/zeus/secrets", "~/.claude", "~/.codex", "~/.config/gh", "~/.ssh",
                   "~/.docker", "~/.config/claude")
CREDENTIAL_FILES = ("~/.claude.json", "~/.git-credentials", "~/.netrc")


class ProviderSpawnRefused(PermissionError):
    """Raised inside the audit hook: the spawn never reaches exec."""


def _stem(name: str) -> str:
    base = os.path.basename(str(name)).lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _fixture_dir(env) -> Path | None:
    value = (env or {}).get(FIXTURE_DIR_ENV) or os.environ.get(FIXTURE_DIR_ENV)
    return Path(value).resolve() if value else None


def _resolve(name: str, env) -> Path | None:
    if os.sep in name or (os.altsep and os.altsep in name):
        return Path(name).resolve()
    path = (env or {}).get("PATH") or os.environ.get("PATH", os.defpath)
    found = shutil.which(name, path=path)
    return Path(found).resolve() if found else None


class DockerRefused(ValueError):
    pass


def _fixture_images(env) -> set[str]:
    extra = (env or {}).get(DOCKER_IMAGES_ENV) or os.environ.get(DOCKER_IMAGES_ENV) or ""
    return set(DEFAULT_FIXTURE_IMAGES) | {i for i in extra.split(",") if i}


def _fixture_image(ref: str, env) -> bool:
    return bool(FIXTURE_IMAGE.match(ref)) or ref in _fixture_images(env)


def _options(args: list[str], values: set[str], flags: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Split leading options from operands; an unknown option is refused (default-deny)."""
    opts, i = [], 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        name, eq, value = args[i].partition("=")
        if name in flags and not eq:
            opts.append((name, ""))
            i += 1
        elif name in values:
            if not eq:
                if i + 1 >= len(args):
                    raise DockerRefused(f"option {name} lacks a value")
                value, i = args[i + 1], i + 1
            opts.append((name, value))
            i += 1
        else:
            raise DockerRefused(f"option {args[i]!r} is not on the allow list")
    return opts, args[i:]


def _owned(name: str) -> bool:
    return name.startswith(FIXTURE_NAME_PREFIX) and len(name) > len(FIXTURE_NAME_PREFIX)


def _check_run(args: list[str], env) -> None:
    opts, operands = _options(args, RUN_VALUE_OPTIONS, RUN_FLAGS)
    networks = [v for k, v in opts if k in {"--network", "--net"}]
    if networks != ["none"]:
        raise DockerRefused("run/create needs exactly one network option equal to none")
    if FIXTURE_LABEL not in [v for k, v in opts if k in {"--label", "-l"}]:
        raise DockerRefused(f"run/create needs the owned-fixture label {FIXTURE_LABEL}")
    names = [v for k, v in opts if k == "--name"]
    if len(names) != 1 or not _owned(names[0]):
        raise DockerRefused(f"run/create needs one --name starting with {FIXTURE_NAME_PREFIX}")
    for k, v in opts:
        if k == "--security-opt" and v not in {"no-new-privileges", "no-new-privileges:true"}:
            raise DockerRefused(f"security option {v!r} is not allowed")
        if k == "--mount":
            fields = dict(part.partition("=")[::2] for part in v.split(","))
            kind = fields.get("type")
            if kind == "tmpfs":
                continue
            root = (env or {}).get(DOCKER_BIND_ROOT_ENV) or os.environ.get(DOCKER_BIND_ROOT_ENV)
            source = fields.get("source") or fields.get("src")
            if kind != "bind" or not root or not source or not Path(source).resolve().is_relative_to(
                    Path(root).resolve()):
                raise DockerRefused("only tmpfs mounts and binds under the fixture bind root")
    if not operands:
        raise DockerRefused("run/create names no image")
    if not _fixture_image(operands[0], env):
        raise DockerRefused(f"image operand {operands[0]!r} is not a fixture image")


def _check_build(args: list[str], env) -> None:
    opts, operands = _options(args, {"-t", "--tag", "--label", "--network", "-f", "--file"},
                              {"--no-cache", "-q", "--quiet"})
    tags = [v for k, v in opts if k in {"-t", "--tag"}]
    if not tags or not all(FIXTURE_IMAGE.match(t) for t in tags):
        raise DockerRefused("build tags must all be zeus-test-fixture/ images")
    if [v for k, v in opts if k == "--network"] != ["none"]:
        raise DockerRefused("build needs --network none")
    if FIXTURE_LABEL not in [v for k, v in opts if k == "--label"]:
        raise DockerRefused(f"build needs the owned-fixture label {FIXTURE_LABEL}")
    if len(operands) != 1:
        raise DockerRefused("build needs exactly one context operand")


def _check_exec(args: list[str], env) -> None:
    """The restore family's tool forms only (M7 host_migration `_docker_pg`/`_archive_facts`)."""
    if ((env or {}).get(DOCKER_PGEXEC_ENV) or os.environ.get(DOCKER_PGEXEC_ENV)) != "1":
        raise DockerRefused(f"docker exec needs {DOCKER_PGEXEC_ENV}=1")
    if not args or args[0].startswith("-"):
        raise DockerRefused("docker exec takes no option")
    if not _owned(args[0]):
        raise DockerRefused("docker exec may name owned fixture containers only")
    program, rest = (args[1], args[2:]) if len(args) > 1 else (None, [])
    if program == "sha256sum":
        if len(rest) != 1 or not DUMP_PATH.match(rest[0]):
            raise DockerRefused("docker exec sha256sum takes exactly one /dump/<name> operand")
        return
    if program not in PG_TOOLS:
        raise DockerRefused(f"docker exec {program!r} is not a fixture tool form")
    if len(rest) < 4 or rest[0] != "-U" or not IDENT.match(rest[1]) or rest[2:4] != ["-h", PG_SOCKET_DIR]:
        raise DockerRefused("docker exec pg tool needs -U <ident> -h /var/run/postgresql first")
    for token in rest[4:]:
        value = token.partition("=")[2] if token.startswith("--") and "=" in token else token
        if value.startswith("/") and not DUMP_PATH.match(value):
            raise DockerRefused("docker exec pg tool paths must be /dump/<name>")
        if ".." in value:
            raise DockerRefused("docker exec pg tool arguments may not contain ..")


def _verify_stack_definition(path: Path, env) -> None:
    """The file must be the disposable stack `VerificationServices.__enter__` writes, nothing broader."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DockerRefused(f"compose definition unreadable: {type(exc).__name__}") from None
    if not isinstance(spec, dict) or set(spec) != {"services", "volumes"} or spec["volumes"] != {"database": {}}:
        raise DockerRefused("compose definition is not the two-service verification stack")
    services = spec["services"]
    if not isinstance(services, dict) or set(services) != set(VERIFY_SERVICES):
        raise DockerRefused("compose services must be exactly postgres and redis")
    for name, service in services.items():
        if not isinstance(service, dict) or set(service) - VERIFY_SERVICE_KEYS[name]:
            raise DockerRefused(f"compose service {name} has a key outside the verification stack")
        if service.get("image") not in _fixture_images(env):
            raise DockerRefused(f"compose service {name} image is not a fixture image")
        ports = service.get("ports")
        if not (isinstance(ports, list) and len(ports) == 1 and isinstance(ports[0], str) and re.fullmatch(
                r"127\.0\.0\.1:([0-9]{1,5})?:" + VERIFY_SERVICES[name], ports[0])):
            raise DockerRefused(f"compose service {name} may publish its own port on 127.0.0.1 only")
    if services["postgres"].get("volumes") != ["database:/var/lib/postgresql/data"]:
        raise DockerRefused("compose postgres may mount only the named database volume")
    environment = services["postgres"].get("environment")
    if not isinstance(environment, dict) or set(environment) != {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"}:
        raise DockerRefused("compose postgres environment is not the verification stack's")
    if services["redis"].get("command") != ["redis-server", "--appendonly", "no"]:
        raise DockerRefused("compose redis command is not the verification stack's")


def _verify_filter(args: list[str], flags: set[str]) -> None:
    opts, operands = _options(args, {"--filter"}, flags)
    filters = [v for k, v in opts if k == "--filter"]
    if operands or len(filters) != 1 or not filters[0].startswith("label=com.docker.compose.project=") \
            or not VERIFY_PROJECT.match(filters[0].rsplit("=", 1)[1]):
        raise DockerRefused("only the verification project's label filter is admitted")


def _check_verify_stack(command: str, args: list[str], env) -> None:
    """The owner-run verification-stack forms (`host_os.adapters.verification._command` and its removal check)."""
    if ((env or {}).get(DOCKER_VERIFY_STACK_ENV) or os.environ.get(DOCKER_VERIFY_STACK_ENV)) != "1":
        raise DockerRefused(f"docker {command} needs {DOCKER_VERIFY_STACK_ENV}=1")
    if command == "ps":
        return _verify_filter(args, {"-a", "--all", "-q", "--quiet", "-aq", "-qa"})
    if command == "volume":
        if not args or args[0] != "ls":
            raise DockerRefused("docker volume ls only")
        return _verify_filter(args[1:], {"-q", "--quiet"})
    if len(args) < 5 or args[0] != "--project-name" or not VERIFY_PROJECT.match(args[1]) or args[2] != "--file":
        raise DockerRefused("compose needs --project-name zeus-verify-<32 hex> --file <path> first")
    path = Path(args[3])
    if not path.is_absolute() or path.name != "compose.json":
        raise DockerRefused("compose --file must be an absolute compose.json")
    _verify_stack_definition(path, env)
    sub, rest = args[4], args[5:]
    single = {"pause": (set(), set()), "unpause": (set(), set()), "stop": ({"-t", "--timeout"}, set())}
    if sub == "up":
        _, operands = _options(rest, set(), {"-d", "--detach", "--wait", "--no-recreate"})
        if len(operands) > 1 or not set(operands) <= set(VERIFY_SERVICES):
            raise DockerRefused("compose up names at most one stack service")
    elif sub == "port":
        if len(rest) != 2 or VERIFY_SERVICES.get(rest[0]) != rest[1]:
            raise DockerRefused("compose port <service> <its own port> only")
    elif sub == "ps":
        _, operands = _options(rest, set(), {"-a", "--all", "-q", "--quiet"})
        if len(operands) > 1 or not set(operands) <= set(VERIFY_SERVICES):
            raise DockerRefused("compose ps names at most one stack service")
    elif sub in single:
        _, operands = _options(rest, *single[sub])
        if len(operands) != 1 or operands[0] not in VERIFY_SERVICES:
            raise DockerRefused(f"compose {sub} names exactly one stack service")
    elif sub == "down":
        _, operands = _options(rest, {"-t", "--timeout"}, {"-v", "--volumes", "--remove-orphans"})
        if operands:
            raise DockerRefused("compose down takes no operand")
    elif sub == "exec":
        if len(rest) < 3 or rest[0] != "-T" or VERIFY_PROGRAMS.get(rest[1]) != rest[2]:
            raise DockerRefused("compose exec -T postgres psql | -T redis redis-cli only")
    else:
        raise DockerRefused(f"compose {sub} is not a verification-stack form")


def docker_policy(argv: list[str], env=None) -> str:
    """Return the normalized admitted subcommand, or raise DockerRefused (default-deny)."""
    if ((env or {}).get(DOCKER_OPT_IN_ENV) or os.environ.get(DOCKER_OPT_IN_ENV)) != "1":
        raise DockerRefused(f"{DOCKER_OPT_IN_ENV}=1 is not set")
    args = [os.fsdecode(a) for a in argv[1:]]
    if not args or args[0].startswith("-"):
        raise DockerRefused("global docker options and bare docker are refused")
    command, rest = args[0], args[1:]
    if (command, rest[0] if rest else None) in DOCKER_ALIASES:
        command, rest = DOCKER_ALIASES[command, rest[0]], rest[1:]
    if command == "exec":
        _check_exec(rest, env)
        return command
    if command in {"compose", "ps", "volume"}:
        _check_verify_stack(command, rest, env)
        return command
    if command not in DOCKER_TOP:
        raise DockerRefused(f"docker {command} is not a supported fixture form")
    if command in {"run", "create"}:
        _check_run(rest, env)
    elif command == "build":
        _check_build(rest, env)
    elif command in LIFECYCLE_OPTIONS:
        flags, values = LIFECYCLE_OPTIONS[command]
        _, operands = _options(rest, values, flags)
        if not operands or not all(_owned(o) for o in operands):
            raise DockerRefused(f"docker {command} may name owned fixture containers only")
    elif command in {"rmi", "image-inspect"}:
        _, operands = _options(rest, {"-f", "--format"} if command == "image-inspect" else set(),
                               {"-f", "--force"} if command == "rmi" else set())
        allowed = (lambda o: bool(FIXTURE_IMAGE.match(o))) if command == "rmi" \
            else (lambda o: _fixture_image(o, env))
        if not operands or not all(allowed(o) for o in operands):
            raise DockerRefused(f"docker {command} may name fixture images only")
    else:  # version, info
        _, operands = _options(rest, {"-f", "--format"}, set())
        if operands:
            raise DockerRefused(f"docker {command} takes no operand")
    return command


def _docker_allowed(argv: list[str], env) -> bool:
    try:
        docker_policy(argv, env)
    except DockerRefused:
        return False
    return True


def _candidates(executable, argv) -> list[str]:
    """Every token that names a program in this spawn, including inside a shell `-c` string."""
    if isinstance(argv, (str, bytes)):
        argv = [argv]
    argv = [os.fsdecode(a) for a in (argv or [])]
    names = [os.fsdecode(executable)] if executable else []
    names += argv[:1]
    if argv and _stem(argv[0]) in SHELLS:
        for a in argv[1:]:
            try:
                names += shlex.split(a)
            except ValueError:
                names += a.split()
    elif len(argv) == 1 and " " in argv[0]:
        try:
            names += shlex.split(argv[0])
        except ValueError:
            names += argv[0].split()
    return names


def check_spawn(executable, argv, env=None) -> None:
    """Refuse a spawn that names a provider unless it resolves into the fixture directory."""
    fixture = _fixture_dir(env)
    tokens = _candidates(executable, argv)
    argv_list = [os.fsdecode(a) for a in (argv if isinstance(argv, (list, tuple)) else [argv])] \
        if argv else []
    for token in tokens:
        stem = _stem(token)
        if stem not in PROVIDERS:
            continue
        resolved = _resolve(token, env)
        if fixture is not None and resolved is not None and resolved.is_relative_to(fixture):
            continue
        if stem == "docker" and argv_list and _stem(argv_list[0]) == "docker" \
                and _docker_allowed(argv_list, env):
            continue
        raise ProviderSpawnRefused(
            f"zeus-test R-P: spawning provider executable '{stem}' is refused in tests "
            f"(configure {FIXTURE_DIR_ENV} with a fixture binary)")


def _audit(event: str, args) -> None:
    if event == "subprocess.Popen":
        executable, argv, _cwd, env = args
        check_spawn(executable, argv, env)
    elif event == "os.posix_spawn":
        path, argv, env = args
        check_spawn(path, argv, env)
    elif event == "os.exec":
        path, argv, env = args
        check_spawn(path, argv, env)
    elif event == "os.spawn":
        _mode, path, argv, env = args
        check_spawn(path, argv, env)
    elif event == "os.system":
        check_spawn(None, ["sh", "-c", os.fsdecode(args[0])], None)


_INSTALLED = "_zeus_rebuild_provider_guard_installed"


def install() -> bool:
    """Install the audit hook once per interpreter. Audit hooks cannot be removed."""
    if getattr(sys, _INSTALLED, False):
        return False
    sys.addaudithook(_audit)
    setattr(sys, _INSTALLED, True)
    return True


def installed() -> bool:
    return bool(getattr(sys, _INSTALLED, False))


FAKE_SCRIPT = """#!/bin/sh
echo "zeus-test R-P: fail-loud fake '{name}' executed; a real provider is never reachable here" >&2
exit {code}
"""


def write_fake_bin(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in sorted(PROVIDERS):
        target = directory / name
        target.write_text(FAKE_SCRIPT.format(name=name, code=FAKE_EXIT), encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


def secret_name(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(SECRET_NAME_PREFIXES) or any(p in upper for p in SECRET_NAME_PARTS)


def child_environment(root: Path, *, base: dict | None = None, extra: dict | None = None) -> dict:
    """Environment for a child process: fake providers first on PATH, empty homes, no secrets."""
    source = dict(os.environ if base is None else base)
    env = {k: v for k, v in source.items() if not secret_name(k)}
    for name in ("DATABASE_URL", "REDIS_URL", "HARNESS_DATABASE_URL", "HARNESS_REDIS_URL",
                 "ZEUS_DATABASE_URL", "ZEUS_REDIS_URL", "PGPASSWORD", "PGHOST", "PGPORT"):
        env.pop(name, None)
    fake = write_fake_bin(root / "fakebin")
    homes = {}
    for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        path = root / "homes" / name.lower()
        path.mkdir(parents=True, exist_ok=True)
        homes[name] = str(path)
    env.update(homes)
    env["PATH"] = os.pathsep.join([str(fake), source.get("PATH", os.defpath)])
    guard_dir = str(Path(__file__).resolve().parent)
    env["PYTHONPATH"] = guard_dir
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["COLUMNS"] = "100"
    env["LC_ALL"] = "C.UTF-8"
    env["TZ"] = "UTC"
    env.pop("PYTHONSTARTUP", None)
    env.update(extra or {})
    return env


def bwrap_available() -> bool:
    """bwrap is installed AND can create the sandbox here (hosted runners may restrict userns)."""
    if shutil.which("bwrap") is None or not sys.platform.startswith("linux"):
        return False
    import subprocess

    probe = subprocess.run(bwrap_prefix([]) + ["true"], capture_output=True, timeout=30)
    return probe.returncode == 0


def bwrap_prefix(writable: list[Path]) -> list[str]:
    """Layer (c): no network, tmpfs over credential directories, only the given paths writable."""
    argv = ["bwrap", "--ro-bind", "/", "/", "--unshare-net", "--dev", "/dev", "--tmpfs", "/tmp"]
    for raw in CREDENTIAL_DIRS:
        path = Path(os.path.expanduser(raw))
        if path.is_dir():
            argv += ["--tmpfs", str(path)]
    for raw in CREDENTIAL_FILES:
        path = Path(os.path.expanduser(raw))
        if path.is_file():
            argv += ["--ro-bind", "/dev/null", str(path)]
    for path in writable:
        argv += ["--bind", str(path), str(path)]
    argv += ["--setenv", "ZEUS_TEST_BWRAP", "1", "--die-with-parent"]
    return argv
