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

The Docker opt-in (`ZEUS_TEST_DOCKER=1`) authorizes only `docker` itself, and only fixture images
with `--network none` for `run`/`create`. It never authorizes `claude` or `codex`.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

PROVIDERS = frozenset({"claude", "codex", "docker"})
FIXTURE_DIR_ENV = "ZEUS_TEST_PROVIDER_FIXTURES"
DOCKER_OPT_IN_ENV = "ZEUS_TEST_DOCKER"
DOCKER_IMAGES_ENV = "ZEUS_TEST_DOCKER_FIXTURE_IMAGES"
DEFAULT_FIXTURE_IMAGE_PREFIX = "zeus-test-fixture"
FAKE_EXIT = 97
SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "fish", "cmd", "powershell", "pwsh"})
# Docker subcommands that never start a workload; everything else needs the run/create policy.
DOCKER_INSPECTION = frozenset({"version", "info", "ps", "inspect", "logs", "wait", "stop", "kill",
                               "rm", "images", "image", "container", "volume", "network"})
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


def _docker_allowed(argv: list[str], env) -> bool:
    if ((env or {}).get(DOCKER_OPT_IN_ENV) or os.environ.get(DOCKER_OPT_IN_ENV)) != "1":
        return False
    rest = [a for a in argv[1:]]
    command = next((a for a in rest if not a.startswith("-")), None)
    if command in DOCKER_INSPECTION:
        return True
    if command not in {"run", "create", "build"}:
        return False
    prefixes = tuple(p for p in ((env or {}).get(DOCKER_IMAGES_ENV)
                                 or os.environ.get(DOCKER_IMAGES_ENV)
                                 or DEFAULT_FIXTURE_IMAGE_PREFIX).split(",") if p)
    if command == "build":
        tags = [rest[i + 1] for i, a in enumerate(rest[:-1]) if a in {"-t", "--tag"}]
        tags += [a.split("=", 1)[1] for a in rest if a.startswith("--tag=")]
        return bool(tags) and all(t.startswith(prefixes) for t in tags)
    network_none = any(a in {"--network=none", "--net=none"} for a in rest) or any(
        a in {"--network", "--net"} and rest[i + 1] == "none" for i, a in enumerate(rest[:-1]))
    images = [a for a in rest if a.startswith(prefixes)]
    return network_none and bool(images)


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
    return shutil.which("bwrap") is not None and sys.platform.startswith("linux")


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
