"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.monitor_frontend_checks`, no arguments.

The pinned argv of the evidence policy, the worker-profile grant and the S0 scan; it only delegates.
"""
from codex_harness.entry.processes.monitor_frontend_checks import main

if __name__ == "__main__":
    raise SystemExit(main())
