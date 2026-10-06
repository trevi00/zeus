"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.migrations precheck|apply …`.

Kept by the corrected S0 pinned-argv scan (`static.source.json` `shims.conditional`, keep_shim true; pinned by M7
`migrations.py:148`). It only delegates.
"""
from codex_harness.entry.processes.migrations import main

if __name__ == "__main__":
    raise SystemExit(main())
