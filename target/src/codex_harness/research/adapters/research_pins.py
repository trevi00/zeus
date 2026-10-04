"""The `uv.lock` version pins of research packages (GAP #20; DESIGN-s10 §14 G20-D5, D7).

Layer: adapters
Context: research
Owns: UvLockPins (the `ResearchPins` port: `current(pin_ref)`)
Does not own: the pin judgement (research.application.research_package_policy), the lock file's contents (the repository)
Entry points: UvLockPins.current
Contracts: INV-RESEARCH-001, INV-RESEARCH-004 (addendum A1 v2 RF-RT)

A declared target addition (no M7 counterpart). `uv.lock:<name>` answers the locked version of the package `<name>`,
read from the repository's `uv.lock` with stdlib `tomllib`. Any other kind, a missing package, an unreadable or
malformed lock answers None, which the policy turns into `blocked` `pin_unavailable` (CE-9: never an invented version).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

PREFIX = "uv.lock:"


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class UvLockPins:
    def __init__(self, repository_root):
        self.path = Path(repository_root) / "uv.lock"

    def current(self, pin_ref: str) -> str | None:
        if not isinstance(pin_ref, str) or not pin_ref.startswith(PREFIX) or not pin_ref[len(PREFIX):].strip():
            return None
        wanted = _canonical(pin_ref[len(PREFIX):].strip())
        try:
            document = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            return None
        for package in document.get("package", []):
            if isinstance(package, dict) and isinstance(package.get("name"), str) \
                    and _canonical(package["name"]) == wanted and isinstance(package.get("version"), str):
                return package["version"]
        return None
