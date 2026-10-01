"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.managed_runtime launch|entry|supervise --state-dir DIR ...`.

The launched managed Fleet processes' argv (M7 ManagedFleetTarget and the unit's ExecStart, byte-identical, DESIGN-s7
adapters-move §1); it only delegates, and re-exports the wired `supervise` for module-name imports.
"""
from codex_harness.entry.processes.managed_runtime import main, supervise

__all__ = ["main", "supervise"]

if __name__ == "__main__":
    raise SystemExit(main())
