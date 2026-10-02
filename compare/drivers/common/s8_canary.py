"""Shared S8 scenario steps for `review.canary`, characterized BEFORE pilot 99 moves M7 `adapters/canary.py` (DESIGN-s8 §13 V18 R-cn0/R-cn1).

M7 has no tests for the module, so the cases are authored from the one function `executable_canary(spec)`:

- hook specs (real `hook_apply`, never faked): an executable alias `codex.ps1` -> `codex.cmd` on windows (reproduction true), an alias that does not
  rewrite that command (reproduction false), an alias that also rewrites a normal command (normal_case false), a native hook (returns argv
  unchanged: reproduction false, normal true), an alias for another platform, and the refused specs (`hook_apply` raises before the probe runs);
- probe outcomes through a LABELLED fake probe (`FakeProbe`): passed, failed, a result without exit code, and raising OSError, SubprocessError,
  TimeoutExpired (a SubprocessError), ValueError (all -> {"passed": false, "version": "unavailable"}) and RuntimeError / KeyError-shaped results
  (propagate); the number of probe calls is recorded.

No real Codex binary runs: the probe is always the fake. Nothing in a result is drawn (no id, clock, pid or path), so no normalization is applied.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `run(spec, probe)` calls `executable_canary` with `probe` as the
Codex probe and returns its result."""

from __future__ import annotations

import subprocess

ALIAS = {"kind": "executable_alias", "match": "codex.ps1", "replacement": "codex.cmd", "platform": "windows"}
SPECS = {
    "alias_ps1_to_cmd": ALIAS,
    "alias_other_command": {"kind": "executable_alias", "match": "codex.sh", "replacement": "codex.cmd", "platform": "windows"},
    "alias_other_platform": {**ALIAS, "platform": "linux"},
    "alias_rewrites_git": {"kind": "executable_alias", "match": "git", "replacement": "git.exe", "platform": "windows"},
    "alias_rewrites_codex_on_linux": {"kind": "executable_alias", "match": "codex", "replacement": "codex.cmd", "platform": "linux"},
    "native_hook": {"kind": "native_hook", "event": "PreToolUse", "matcher": "Bash", "script_path": "hooks/pre.py", "script_sha256": "0" * 64},
}
REFUSED_SPECS = {
    "refused_empty_spec": {},
    "refused_unknown_kind": {"kind": "other"},
    "refused_alias_missing_field": {"kind": "executable_alias", "match": "codex.ps1", "replacement": "", "platform": "windows"},
    "refused_native_bad_event": {"kind": "native_hook", "event": "Nope", "matcher": "Bash", "script_path": "hooks/pre.py", "script_sha256": "0" * 64},
    "refused_native_absolute_script": {"kind": "native_hook", "event": "Stop", "matcher": "Bash", "script_path": "/etc/x", "script_sha256": "0" * 64},
}
PASSED = {"passed": True, "version": "codex-cli 0.0.0", "exit_code": 0}
FAILED = {"passed": False, "version": "", "exit_code": 1}
OUTCOMES = {
    "passed": PASSED,
    "failed": FAILED,
    "passed_without_exit_code": {"passed": True, "version": "v"},
    "oserror": OSError("no codex"),
    "subprocess_error": subprocess.SubprocessError("spawn failed"),
    "timeout_expired": subprocess.TimeoutExpired(["codex", "--version"], 20),
    "called_process_error": subprocess.CalledProcessError(3, ["codex", "--version"]),
    "valueerror": ValueError("bad version"),
    "runtimeerror_propagates": RuntimeError("unexpected"),
    "missing_passed_key_propagates": {"version": "v"},
}


class FakeProbe:
    """LABELLED fake of `CodexRuntime().probe()`: returns the scripted dict or raises the scripted exception; counts calls."""

    def __init__(self, outcome):
        self.outcome, self.calls = outcome, 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return dict(self.outcome)


def run(api, spec, outcome) -> dict:
    probe = FakeProbe(outcome)
    try:
        result = api.run(spec, probe)
    except Exception as exc:  # noqa: BLE001 - the exception type and message are the recorded behavior
        return {"raised": type(exc).__name__, "message": str(exc), "probe_calls": probe.calls}
    return {"result": result, "probe_calls": probe.calls}


def canary(api) -> dict:
    return {
        "specs": {name: run(api, spec, PASSED) for name, spec in SPECS.items()},
        "refused_specs": {name: run(api, spec, PASSED) for name, spec in REFUSED_SPECS.items()},
        "probes": {name: run(api, ALIAS, outcome) for name, outcome in OUTCOMES.items()},
        "probes_with_failing_hook": {name: run(api, SPECS["alias_rewrites_git"], outcome) for name, outcome in OUTCOMES.items()},
    }
