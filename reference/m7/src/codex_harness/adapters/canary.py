from __future__ import annotations

import subprocess

from codex_harness.adapters.codex import CodexRuntime
from codex_harness.domain.model import hook_apply


def executable_canary(spec: dict) -> dict:
    """Bootstrap fixture: the observed Windows codex.ps1 -> codex.cmd incident.

    This is a fixed independent regression fixture, not a test inferred from a candidate.
    cli_start is a startup smoke check, NOT a full agent task/candidate deployment test.
    """
    reproduction = hook_apply(spec, ["codex.ps1", "--version"], "windows") == ["codex.cmd", "--version"]
    normal = all(hook_apply(spec, argv, platform) == argv for argv, platform in [
        (["git", "status"], "windows"), (["codex", "--version"], "linux"),
        (["codex.cmd", "--version"], "windows"),
    ])
    try:
        probe = CodexRuntime().probe()
    except (OSError, subprocess.SubprocessError, ValueError):
        probe = {"passed": False, "version": "unavailable"}
    return {"checks": {"reproduction": reproduction, "normal_case": normal,
                       "cli_start": probe["passed"]}, "probe": probe,
            "scope": "bootstrap-command-hook; not a release deployment canary"}
