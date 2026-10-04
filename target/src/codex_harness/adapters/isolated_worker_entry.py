"""Permanent entry shim (§3.5): `/opt/zeus/bin/python -I -m codex_harness.adapters.isolated_worker_entry`.

The in-container entry argv the host launcher pins (`execution.domain.container_spec.ENTRY_MODULE`); it only delegates.
"""
from codex_harness.entry.processes.isolated_worker import main

if __name__ == "__main__":
    raise SystemExit(main())
