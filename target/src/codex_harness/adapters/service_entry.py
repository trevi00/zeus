"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.service_entry --journal PATH -- CLI_ARGS`.

Kept by the corrected S0 pinned-argv scan (`static.source.json` `shims.conditional`, keep_shim true; DESIGN-s11 §8 SH-a):
the contract-pinned argv of INV-SERVICE-DIAGNOSTICS-001 (`docs/contracts.md`). It only delegates.
"""
from codex_harness.entry.processes.service_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
