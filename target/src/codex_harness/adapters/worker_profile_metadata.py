"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.worker_profile_metadata`, no arguments.

The pinned argv of AGENTS.md, the worker-profile grant and the evidence-policy replay; it only delegates.
"""
from codex_harness.entry.processes.worker_profile_metadata import main

if __name__ == "__main__":
    raise SystemExit(main())
