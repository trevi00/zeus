"""Host settings: the dotenv layer merged under the environment (INV-HOST-DELIVERY-001).

Layer: composition
Owns: settings, repository_root, read_env and aliases (M7 `adapters/configuration.py` functions, moved ahead of S10); the rest of configuration.py stays S10
Does not own: the runtime directory, Codex auth and Compose environment helpers (S10)
Entry points: settings, repository_root, read_env, aliases
Contracts: INV-HOST-DELIVERY-001

Moved ahead of its slice from M7 `adapters/configuration.py` (SOURCE e38aa722) through named rules (DESIGN-s7 adapters-move, A/evidence/rebuild/s7/move-aheads/transcribe.py); the only changes are this header and the imports of the four functions; every body is otherwise M7's.
"""
from __future__ import annotations

import os
import re
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
