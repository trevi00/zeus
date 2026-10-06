"""Host configuration shared by the CLI, supervisor and Compose launchers.

Resolve on each call: tests and separate host/container runtimes must not share
an import-time home or state directory. Environment overrides the repository file.
"""
from __future__ import annotations

import os
import re
import secrets
import tomllib
from pathlib import Path


def repository_root() -> Path:
    if value := os.environ.get("ZEUS_REPOSITORY") or os.environ.get("HARNESS_REPOSITORY"):
        return Path(value).expanduser().resolve()
    for candidate in (Path.cwd(), *Path.cwd().parents):
        project = candidate / "pyproject.toml"
        if project.is_file():
            try:
                name = tomllib.loads(project.read_text("utf-8"))["project"]["name"]
            except (tomllib.TOMLDecodeError, KeyError):
                continue
            if name in {"zeus-harness", "codex-self-harness"}:
                return candidate.resolve()
    source = Path(__file__).resolve().parents[3]
    if (source / "compose.yaml").is_file():
        return source
    return Path.cwd().resolve()


def read_env(root: Path | None = None) -> dict[str, str]:
    """Read literal dotenv values; never execute shell expansions or print secrets."""
    path = (root or repository_root()) / ".env"
    if not path.is_file():
        return {}
    values = {}
    for number, raw in enumerate(path.read_text("utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env assignment at line {number}")
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and
                           not value[end + 1:].lstrip().startswith("#")):
                raise ValueError(f"Invalid .env quoting at line {number}")
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def aliases(layer: dict[str, str]) -> dict[str, str]:
    """Normalize each precedence layer before merging; Zeus wins within one layer."""
    result = dict(layer)
    suffixes = {key.split("_", 1)[1] for key in layer if key.startswith(("ZEUS_", "HARNESS_"))}
    for suffix in suffixes:
        value = layer.get("ZEUS_" + suffix, layer.get("HARNESS_" + suffix))
        result["ZEUS_" + suffix] = result["HARNESS_" + suffix] = value
    return result


def settings() -> dict[str, str]:
    return {**aliases(read_env()), **aliases(dict(os.environ))}


def select_repository(root: Path) -> None:
    value = str(root.resolve())
    os.environ.update(ZEUS_REPOSITORY=value, HARNESS_REPOSITORY=value)


def runtime_dir() -> Path:
    root = repository_root()
    value = settings().get("HARNESS_RUNTIME_DIR")
    return (root / Path(value).expanduser()).resolve() if value else root / ".runtime"


def codex_auth() -> Path:
    config = settings()
    if value := config.get("HARNESS_CODEX_AUTH"):
        return (repository_root() / Path(value).expanduser()).resolve()
    home = Path(config.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    return (repository_root() / home / "auth.json").resolve()


def compose_environment() -> dict[str, str]:
    config = settings()
    config["HARNESS_CODEX_AUTH"] = codex_auth().as_posix()
    config["HARNESS_RUNTIME_DIR"] = runtime_dir().as_posix()
    config["ZEUS_CODEX_AUTH"] = config["HARNESS_CODEX_AUTH"]
    config["ZEUS_RUNTIME_DIR"] = config["HARNESS_RUNTIME_DIR"]
    return config


def initialize(root: Path | None = None) -> dict:
    """Create credentials exclusively; reruns never rotate an existing database password."""
    root = (root or repository_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".env"
    created = False
    password = secrets.token_hex(24)
    content = (f"POSTGRES_PASSWORD={password}\n"
               f"HARNESS_DATABASE_URL=postgresql://harness:{password}@127.0.0.1:55432/harness\n"
               "HARNESS_REDIS_URL=redis://127.0.0.1:56379/0\n"
               "COMPOSE_PROJECT_NAME=zeus\nZEUS_REDIS_NAMESPACE=zeus\n")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        created = True
    return {"repository": str(root), "env_created": created}
