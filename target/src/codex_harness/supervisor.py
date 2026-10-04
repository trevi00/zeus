"""Permanent entry shim (§3.5): `python -m codex_harness.supervisor`; it only delegates."""
from codex_harness.entry.processes.supervisor import main

if __name__ == "__main__":
    raise SystemExit(main())
