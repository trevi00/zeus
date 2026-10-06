"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.host_delivery service --state-dir DIR [--max-seconds N]`.

The launched delivery service's argv (M7 ProcessHostTarget, byte-identical, DESIGN-s7 adapters-move §9.2); it only delegates.
"""
from codex_harness.entry.processes.delivery_service import main

if __name__ == "__main__":
    raise SystemExit(main())
