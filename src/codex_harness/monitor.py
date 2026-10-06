"""Permanent entry shim (§3.5): `zeus-monitor` and `python -m codex_harness.monitor`; it only delegates."""
from codex_harness.entry.processes.monitor import main

if __name__ == "__main__":
    main()
