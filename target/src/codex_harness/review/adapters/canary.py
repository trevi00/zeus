"""Bootstrap command-hook canary: the observed Windows codex.ps1 -> codex.cmd incident as a fixed regression fixture.

Layer: adapters
Context: review
Owns: executable_canary (the bootstrap command-hook regression fixture: the codex.ps1 -> codex.cmd reproduction, the unchanged normal commands and the startup smoke probe)
Does not own: the declarative hook evaluator (research's `hook_apply`, injected as `hook_apply` by composition), the Codex CLI probe (execution's Codex runtime, injected as `probe`), release deployment canaries (delivery)
Entry points: executable_canary
Contracts: none

Moved from M7 `adapters/canary.py` (SOURCE e38aa722) through named rules (DESIGN-s8 §13 V18, A/evidence/rebuild/s8/canary-move/transcribe.py): R-cn0 (the Codex runtime and `hook_apply` imports are removed; `require` from kernel.errors), R-cn1 (`hook_apply` and `probe` are injected keyword-only into `executable_canary` and refused by one added `require` at its head); every other statement is M7's. M7's module had no docstring.
"""
from __future__ import annotations

import subprocess

from codex_harness.kernel.errors import require


def executable_canary(spec: dict, *, hook_apply=None, probe=None) -> dict:
    """Bootstrap fixture: the observed Windows codex.ps1 -> codex.cmd incident.

    This is a fixed independent regression fixture, not a test inferred from a candidate.
    cli_start is a startup smoke check, NOT a full agent task/candidate deployment test.
    """
    # V18 R-cn1: research's `hook_apply` and execution's Codex probe, wired by composition; refused before either runs.
    require(hook_apply is not None and probe is not None, "canary needs the hook rule and the Codex probe")
    reproduction = hook_apply(spec, ["codex.ps1", "--version"], "windows") == ["codex.cmd", "--version"]
    normal = all(hook_apply(spec, argv, platform) == argv for argv, platform in [
        (["git", "status"], "windows"), (["codex", "--version"], "linux"),
        (["codex.cmd", "--version"], "windows"),
    ])
    try:
        probe = probe()
    except (OSError, subprocess.SubprocessError, ValueError):
        probe = {"passed": False, "version": "unavailable"}
    return {"checks": {"reproduction": reproduction, "normal_case": normal,
                       "cli_start": probe["passed"]}, "probe": probe,
            "scope": "bootstrap-command-hook; not a release deployment canary"}
