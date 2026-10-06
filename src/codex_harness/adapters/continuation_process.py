"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.continuation_process --launch <dir> --seconds <s> -- <command>`.

The guardian argv every guarded launch spawns (M7 ENTRY_ARGV, byte-identical, DESIGN-s6 §6); it only delegates.
"""
from codex_harness.entry.processes.guardian import main

if __name__ == "__main__":
    raise SystemExit(main())
