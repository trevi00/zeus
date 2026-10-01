"""Task-class registry and root-path validation.

Purpose: classify a task id into a bounded `task_class`, and validate configured roots on any platform.
Layer: tooling. Owns: the registry file format and DESIGN §3.11 task_class derivation, root validation.
Does-not-own: the registry file location in a deployment (W2) or any scan.
Implements: DESIGN §3.11, §5 (task_class <= 16 values); ACCEPTANCE A23, A24.

Registry format (TOML, location chosen by the operator; the design's `config/task-classes.toml` is outside this
work item's paths):

    [task_classes]
    routine_tooling = "^s7-"      # class name -> regex on the task id; first match in file order wins
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

from .vocab import FIXED_TASK_CLASSES, LABEL_RE, MAX_REGISTRY_CLASSES


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class TaskClassRegistry:
    rules: tuple[tuple[str, re.Pattern[str]], ...] = field(default_factory=tuple)

    def classify(self, task_id: str) -> str:
        for name, pattern in self.rules:
            if pattern.search(task_id):
                return name
        return "unclassified"


def parse_registry(text: str) -> TaskClassRegistry:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"task-class registry is not valid TOML: {exc}") from None
    table = data.get("task_classes", {})
    if not isinstance(table, dict):
        raise ConfigError("[task_classes] must be a table")
    if len(table) > MAX_REGISTRY_CLASSES:
        raise ConfigError(f"at most {MAX_REGISTRY_CLASSES} registry classes (label bound, DESIGN §5)")
    rules = []
    for name, expression in table.items():
        if not isinstance(expression, str) or not LABEL_RE.match(name) or name in FIXED_TASK_CLASSES:
            raise ConfigError("registry class names are bounded label values and not reserved")
        try:
            rules.append((name, re.compile(expression)))
        except re.error:
            raise ConfigError(f"registry class {name!r} has an invalid regex") from None
    return TaskClassRegistry(tuple(rules))


def load_registry(path: Path | None) -> TaskClassRegistry:
    if path is None:
        return TaskClassRegistry()
    return parse_registry(Path(path).read_text(encoding="utf-8"))


_WINDOWS_ROOT = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def validate_root(text: str) -> PurePath:
    """A23: a configured root is absolute. Windows-style roots (drive or UNC) validate with `PureWindowsPath`
    and everything else with `PurePosixPath`, on any host; runtime reading uses `pathlib.Path` only."""
    if not isinstance(text, str) or not text.strip():
        raise ConfigError("root must be a non-empty string")
    path: PurePath = PureWindowsPath(text) if _WINDOWS_ROOT.match(text) else PurePosixPath(text)
    if not path.is_absolute():
        raise ConfigError("root must be absolute")
    return path
