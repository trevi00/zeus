"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.host_migration <command> …`.

Kept by the corrected S0 pinned-argv scan (`static.source.json` `shims.conditional`, keep_shim true; pinned by M7
`host_migration_evidence.py:5`). It only delegates to `entry.processes.host_migration`.
"""
from codex_harness.entry.processes.host_migration import main

if __name__ == "__main__":
    raise SystemExit(main())
