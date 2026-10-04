"""Permanent entry shim (§3.5): `python -m codex_harness.container_main ...`.

The role container ENTRYPOINT (M7 dotted path, byte-identical); it only delegates.
"""
from codex_harness.entry.processes.container_main import main

if __name__ == "__main__":
    main()
